"""Local FastAPI service for scoring one prepared XRPL feature vector."""
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect

from .features import FEATURES, SCHEMA_VERSION, WINDOW
from .ledger import digest_id
from .model_artifact import FEATURE_TYPES, POLICY, VERSION, Score, load
from .monitoring import MetricsMiddleware, ServiceMetrics, inference_ms

DEFAULT_MODEL = Path("artifacts/phase4a/models/baseline-full.json")
MAX_REQUEST_BYTES = 8192
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def feature_value_schema(name, kind):
    schema = {"title": name, "type": kind, "minimum": 0}
    if kind == "integer":
        schema["maximum"] = WINDOW if name.endswith("_seconds") else 1
    elif name == "sender_out_concentration":
        schema["maximum"] = 1
    return schema


class ScoreRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    feature_schema_version: int = Field(json_schema_extra={"const": SCHEMA_VERSION})
    feature_names: list[str] = Field(
        min_length=len(FEATURES), max_length=len(FEATURES),
        json_schema_extra={"prefixItems": [{"const": name} for name in FEATURES], "items": False},
    )
    values: list[int | float] = Field(
        min_length=len(FEATURES), max_length=len(FEATURES),
        description="Finite, complete-history values in feature_names order. Integer positions require JSON integers.",
        json_schema_extra={"prefixItems": [feature_value_schema(name, kind)
                                          for name, kind in zip(FEATURES, FEATURE_TYPES, strict=True)],
                           "items": False},
    )
    transaction_id: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9A-Fa-f]{64}$",
        description="Optional transaction hash. Normalized to uppercase for the calibrated decision.",
    )


@dataclass(frozen=True)
class ScoreResponse(Score):
    alert: Annotated[bool | None, Field(description="Frozen anomaly decision, or null without a transaction hash.")]


class ScoreError(BaseModel):
    detail: str


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


async def read_score_request(request):
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "expected application/json")
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise HTTPException(413, "request body exceeds 8192 bytes")
            body.extend(chunk)
    except ClientDisconnect as exc:
        raise HTTPException(400, "incomplete request body") from exc
    try:
        decoded = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
        if isinstance(decoded, dict) and "xrpl.metrics" in request.scope:
            values = decoded.get("values")
            request.scope["xrpl.metrics"]["complete"] = (
                isinstance(values, list) and len(values) == len(FEATURES) and None not in values
            )
        return ScoreRequest.model_validate(decoded)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "invalid scoring request") from exc


def create_app(model_path=None):
    @asynccontextmanager
    async def lifespan(app):
        path = model_path if model_path is not None else os.getenv("XRPL_MODEL_PATH", str(DEFAULT_MODEL))
        app.state.detector = load(path)
        app.state.metrics = ServiceMetrics()
        try:
            yield
        finally:
            del app.state.detector
            del app.state.metrics

    app = FastAPI(title="XRPL anomaly scoring", version="1", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS, www_redirect=False)
    app.add_middleware(MetricsMiddleware)

    @app.get("/health")
    async def health():
        if not hasattr(app.state, "detector"):
            raise HTTPException(503, "model unavailable")
        return {"status": "ready"}

    @app.get("/v1/model")
    async def model():
        detector = app.state.detector
        return {"model_id": detector.model_id, "model_type": detector.model_type,
                "model_version": VERSION, "artifact_sha256": detector.artifact_sha256,
                "feature_schema_version": SCHEMA_VERSION, "feature_names": FEATURES,
                "feature_types": FEATURE_TYPES, "calibration_policy": POLICY}

    @app.get("/v1/metrics")
    async def metrics():
        if not hasattr(app.state, "metrics"):
            raise HTTPException(503, "model unavailable")
        detector = app.state.detector
        return {**app.state.metrics.snapshot(),
                "model": {"id": detector.model_id, "type": detector.model_type, "version": VERSION,
                          "artifact_sha256": detector.artifact_sha256, "feature_schema_version": SCHEMA_VERSION}}

    @app.post(
        "/v1/score",
        response_model=ScoreResponse,
        openapi_extra={"requestBody": {
            "required": True,
            "description": f"UTF-8 JSON with unique object keys, up to {MAX_REQUEST_BYTES} bytes.",
            "content": {"application/json": {"schema": ScoreRequest.model_json_schema()}},
        }},
        responses={
            400: {"description": "Invalid Host header or incomplete request body", "model": ScoreError,
                  "content": {"text/plain": {"schema": {"type": "string"}}}},
            413: {"description": "Body exceeds size limit", "model": ScoreError},
            415: {"description": "Unsupported media type", "model": ScoreError},
            422: {"description": "Invalid JSON, schema, feature values, or transaction hash", "model": ScoreError},
        },
    )
    async def score(request: Request):
        payload = await read_score_request(request)
        detector = app.state.detector
        observation = request.scope.get("xrpl.metrics", {})
        started = perf_counter_ns()
        try:
            result = detector.score(payload.values, feature_names=payload.feature_names,
                                    feature_schema_version=payload.feature_schema_version)
            alert = (detector.alerts(result, identity=digest_id(payload.transaction_id))
                     if payload.transaction_id is not None else None)
        except ValueError as exc:
            observation["scorer_rejected"] = True
            raise HTTPException(422, str(exc)) from exc
        observation.update(inference_ms=inference_ms(started), score=result.anomaly_score, alert=alert)
        return ScoreResponse(**asdict(result), alert=alert)

    return app
