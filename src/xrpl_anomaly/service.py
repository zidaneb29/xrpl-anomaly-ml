"""Local FastAPI service for scoring one prepared XRPL feature vector."""
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import ClientDisconnect

from .features import FEATURES, SCHEMA_VERSION
from .ledger import digest_id
from .model_artifact import FEATURE_TYPES, POLICY, VERSION, Score, load

DEFAULT_MODEL = Path("artifacts/phase4a/models/baseline-full.json")
MAX_REQUEST_BYTES = 8192


class ScoreRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    feature_schema_version: int
    feature_names: list[str] = Field(min_length=len(FEATURES), max_length=len(FEATURES))
    values: list[int | float] = Field(min_length=len(FEATURES), max_length=len(FEATURES))
    transaction_id: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{64}$")


@dataclass(frozen=True)
class ScoreResponse(Score):
    alert: bool | None


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
        return ScoreRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "invalid scoring request") from exc


def create_app(model_path=None):
    @asynccontextmanager
    async def lifespan(app):
        path = model_path if model_path is not None else os.getenv("XRPL_MODEL_PATH", str(DEFAULT_MODEL))
        app.state.detector = load(path)
        try:
            yield
        finally:
            del app.state.detector

    app = FastAPI(title="XRPL anomaly scoring", version="1", lifespan=lifespan, docs_url=None, redoc_url=None)

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

    @app.post("/v1/score", response_model=ScoreResponse, openapi_extra={
        "requestBody": {"required": True, "content": {
            "application/json": {"schema": ScoreRequest.model_json_schema()}}},
    }, responses={413: {"description": "Body exceeds size limit"},
                  415: {"description": "Unsupported media type"},
                  422: {"description": "Invalid JSON, schema, or feature values"}})
    async def score(request: Request):
        payload = await read_score_request(request)
        detector = app.state.detector
        try:
            result = detector.score(payload.values, feature_names=payload.feature_names,
                                    feature_schema_version=payload.feature_schema_version)
            alert = (detector.alerts(result, identity=digest_id(payload.transaction_id))
                     if payload.transaction_id is not None else None)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ScoreResponse(**asdict(result), alert=alert)

    return app
