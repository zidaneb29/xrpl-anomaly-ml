# Phase 4B local scoring API

For the dedicated service lock, Docker setup and CI checks, see the [Phase 4C guide](phase4c.md).

Run the service from the repository root with the [Phase 4A tracking environment](phase4a.md#local-experiment-tracking). Its existing lock includes FastAPI 0.162.2, Pydantic 2.14.3, Starlette 1.10.0, and Uvicorn 0.54.0. Serving imports the standard-library scorer and the HTTP stack. It opens the selected bundle at startup and keeps one validated detector per process. Missing or malformed bundles fail startup. Correct the path or restore a verified bundle, then restart the process.

```powershell
$env:PYTHONPATH = 'src'
$python = '.venv-phase4a/Scripts/python.exe'
& $python -B -m uvicorn xrpl_anomaly.service:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The default artifact is `artifacts/phase4a/models/baseline-full.json`. Package it first using the Phase 4A commands if needed. To serve an alternate frozen model, set `XRPL_MODEL_PATH` to its local bundle before starting the process.

Keep the Uvicorn bind address at `127.0.0.1` for local use. The service accepts `Host` values of `127.0.0.1`, `localhost`, and `[::1]`, with optional ports. The default listener uses IPv4. Host validation alone cannot prevent network exposure because clients can set the header themselves. The service relies on a loopback listener, trusted local clients, and a trusted local bundle.

## HTTP contract

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Reports readiness after startup validation |
| `GET /v1/model` | Returns model ID, version, bundle hash, feature names and types, and calibration policy |
| `POST /v1/score` | Scores one prepared feature vector and optionally returns a calibrated alert |
| `GET /openapi.json` | Returns the machine-readable HTTP contract |

For a synthetic smoke request in a second PowerShell window:

```powershell
$uri = 'http://127.0.0.1:8000'
$model = Invoke-RestMethod "$uri/v1/model"
$body = @{
    feature_schema_version = $model.feature_schema_version
    feature_names = $model.feature_names
    values = @(0) * $model.feature_names.Count
} | ConvertTo-Json
Invoke-RestMethod "$uri/v1/score" -Method Post -ContentType 'application/json' -Body $body
```

For real observations, send the producer's actual schema version and ordered feature names with its complete-history prepared vector. The producer must use strictly earlier ledgers. The API cannot infer history coverage or check temporal provenance from a vector alone.

Include a 64-character hexadecimal `transaction_id` to request a calibrated decision. The service normalizes the hash to uppercase using the ingestion rule. The hash participates only in the persisted tie policy. Without it, `alert` is null and the anomaly score is identical. The response includes model metadata and omits transaction identity and the calibration boundary's transaction hash. A true alert describes statistical atypicality.

Bodies require UTF-8 `application/json`, unique JSON object keys, and at most 8 KiB. The API returns 400 for a missing or disallowed Host or an incomplete body, 413 for oversized bodies, 415 for unsupported media types, and 422 for malformed JSON, duplicate keys, incompatible schemas, invalid vectors, or invalid identities. Request bodies are not logged by the service.

The OpenAPI contract specifies all 21 feature positions, numeric bounds where applicable, the optional transaction hash, and the score and error response types. Integer positions require JSON integer literals. The live scorer validates the supplied feature schema version and names before scoring.

## Local verification

Run the service tests with the optional serving environment. They cover allowed Hosts, duplicate JSON keys, bounded request parsing, OpenAPI structure, offline/API parity, tied cutoff decisions, and startup failure and recovery.

```powershell
& $python -I -B -c "import sys, unittest; sys.path.insert(0, 'src'); r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests', pattern='test_phase4b.py')); sys.exit(not r.wasSuccessful())"
```

With the service running, measure serial loopback requests over one HTTP connection. Pass `--model` if the server uses an alternate bundle. The client checks every response against direct inference.

```powershell
$env:PYTHONPATH = 'src'
& $python -B -m xrpl_anomaly.benchmark_service --requests 1000
```

The benchmark cycles through 32 synthetic prepared vectors, warms up with 100 requests, and times sending each pre-encoded request through reading its response. It measures local single-client latency, including HTTP, validation, scoring, and response serialization. It excludes feature replay, client-side JSON decoding, and concurrent load.

| Model | Timed requests | Median | p95 |
| --- | ---: | ---: | ---: |
| Robust baseline | 1,000 | 1.06 ms | 1.37 ms |
| Isolation Forest, seed 7 | 1,000 | 1.16 ms | 1.33 ms |
| Isolation Forest, seed 29 | 1,000 | 1.14 ms | 1.55 ms |

All 3,300 responses, including warm-up, matched direct inference exactly. These measurements come from one local Windows x64 CPython 3.14.7 run with separate client and server processes. The ignored `artifacts/phase4b/loopback-benchmark.json` records the timings and bundle hashes.
