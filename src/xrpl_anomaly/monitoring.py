"""Bounded operational metrics and descriptive empirical distribution comparisons."""
from bisect import bisect_right
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from time import perf_counter_ns

from .model_artifact import number

MIN_DRIFT_N = 100
DRIFT_GUIDE = 0.20
SERVICE_WINDOW = 1024


def ordered(values):
    result = []
    for value in values:
        if value is None:
            continue
        if not number(value):
            raise ValueError("expected a finite numeric observation or None")
        result.append(value)
    return sorted(result)


def quantile(values, probability):
    return values[max(0, ceil(len(values) * probability) - 1)] if values else None


def distribution(values):
    sample = ordered(values)
    return {"n": len(sample), "missing": len(values) - len(sample),
            "zero_rate": sample.count(0) / len(sample) if sample else None,
            "p05": quantile(sample, .05), "p50": quantile(sample, .50),
            "p95": quantile(sample, .95)}


def drift(reference, current):
    left, right = ordered(reference), ordered(current)
    distance = None
    if min(len(left), len(right)) >= MIN_DRIFT_N:
        # Evaluate both right-continuous ECDFs at every distinct pooled value.
        distance = max(abs(bisect_right(left, x) / len(left) - bisect_right(right, x) / len(right))
                       for x in set(left).union(right))
    return {"reference_n": len(left), "reference_missing": len(reference) - len(left),
            "comparison": distribution(current), "ks_distance": distance,
            "flag": distance >= DRIFT_GUIDE if distance is not None else None}


def alert_summary(decisions):
    known = sum(value is not None for value in decisions)
    alerts = sum(value is True for value in decisions)
    return {"alerts": alerts, "decisions": known, "unknown": len(decisions) - known,
            "rate": alerts / known if known else None}


def utc_now():
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class RequestEvent:
    completed_at: str
    status: int | None
    is_score: bool
    complete: bool | None
    inference_ms: float | None
    score: float | None
    scorer_rejected: bool
    alert: bool | None


class ServiceMetrics:
    def __init__(self):
        self.started_at = utc_now()
        self.events = deque(maxlen=SERVICE_WINDOW)

    def snapshot(self):
        events = tuple(self.events)
        counts = Counter(event.status for event in events if event.status is not None)
        scoring = [event for event in events if event.is_score]
        checked = [event.complete for event in scoring if event.complete is not None]
        successful = [event for event in scoring if event.status == 200 and event.score is not None]
        latency = ordered(event.inference_ms for event in successful)
        failures = sum(event.status in (400, 413, 415, 422) for event in scoring)
        invalid = sum(event.status == 422 for event in scoring)
        return {
            "window": {"capacity": SERVICE_WINDOW, "n": len(events), "process_started_at": self.started_at,
                       "first_completed_at": events[0].completed_at if events else None,
                       "last_completed_at": events[-1].completed_at if events else None},
            "operations": {
                "requests": len(events), "status_codes": dict(sorted(counts.items())),
                "without_status": len(events) - sum(counts.values()),
                "score_requests": len(scoring), "score_request_rejections": failures,
                "score_request_rejection_rate": failures / len(scoring) if scoring else None,
                "feature_vectors_inspected": len(checked),
                "feature_vectors_uninspected": len(scoring) - len(checked),
                "feature_vectors_complete": sum(checked),
                "complete_vector_rate": sum(checked) / len(checked) if checked else None,
                "scorer_validation_failures": sum(event.scorer_rejected for event in scoring),
                "score_422_responses": invalid,
                "score_validation_failure_rate": invalid / len(scoring) if scoring else None,
                "inference_ms": {"n": len(latency), "p50": quantile(latency, .50),
                                 "p95": quantile(latency, .95) if len(latency) >= 20 else None},
            },
            "model_statistics": {"scores": distribution([event.score for event in successful]),
                                 "frozen_alerts": alert_summary([event.alert for event in successful])},
        }


class MetricsMiddleware:
    """Observe HTTP status outside Host validation without buffering requests or responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] == "GET" and scope["path"] == "/v1/metrics"
                or not hasattr(scope["app"].state, "metrics")):
            await self.app(scope, receive, send)
            return

        metrics = scope["app"].state.metrics
        is_score = scope["method"] == "POST" and scope["path"] == "/v1/score"
        status = None
        observation = {}
        if is_score:
            scope["xrpl.metrics"] = observation

        async def observe(message):
            nonlocal status
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]

        try:
            await self.app(scope, receive, observe)
        except Exception:
            if status is None:
                status = 500  # The outer Starlette error middleware handles unhandled exceptions.
            raise
        finally:
            metrics.events.append(RequestEvent(
                utc_now(), status, is_score, observation.get("complete"), observation.get("inference_ms"),
                observation.get("score"), observation.get("scorer_rejected", False), observation.get("alert"),
            ))


def inference_ms(start):
    return (perf_counter_ns() - start) / 1_000_000
