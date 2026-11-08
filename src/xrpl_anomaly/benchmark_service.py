"""Measure single-client loopback HTTP scoring with synthetic prepared vectors."""
import argparse
import http.client
import json
import platform
from contextlib import closing
from dataclasses import asdict
from statistics import median
from time import perf_counter_ns

from .features import FEATURES, SCHEMA_VERSION
from .model_artifact import load
from .service import DEFAULT_MODEL


def benchmark(port, model_path, count):
    detector = load(model_path)
    cases = []
    for index in range(32):
        values = [0] * len(FEATURES)
        values[0] = index / 2
        values[1] = 2.5
        identity = f"{index:064X}"
        score = detector.score(values, feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION)
        request = dict(feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION,
                       values=values, transaction_id=identity)
        cases.append((json.dumps(request).encode(), dict(asdict(score), alert=detector.alerts(score, identity=identity))))
    samples = []
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        for index in range(100 + count):
            body, expected = cases[index % len(cases)]
            started = perf_counter_ns()
            client.request("POST", "/v1/score", body, {"Content-Type": "application/json"})
            response = client.getresponse()
            raw = response.read()
            elapsed = perf_counter_ns() - started
            if response.status != 200 or json.loads(raw) != expected:
                raise RuntimeError(f"HTTP response differs from offline inference (status {response.status})")
            if index >= 100:
                samples.append(elapsed / 1000)
    samples.sort()
    return dict(model_id=detector.model_id, artifact_sha256=detector.artifact_sha256,
                requests=count, warmup=100, python=platform.python_version(), platform=platform.platform(),
                median_us=median(samples), p95_us=samples[(95 * len(samples) + 99) // 100 - 1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--requests", type=int, default=1000)
    args = parser.parse_args()
    if args.requests <= 0:
        parser.error("--requests must be positive")
    print(json.dumps(benchmark(args.port, args.model, args.requests), indent=2))
