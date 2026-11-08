# XRP Ledger anomaly detection

A local Python system that scores unusual XRP payments from validated Mainnet ledgers. XRPL provides public, ordered transaction history with exact integer amounts and a directed payment graph. This makes it possible to replay what the scorer could have known at each ledger and to measure how the models behave as activity changes over time.

```text
Read-only XRPL RPC → hash-checked ledger cache → normalized SQLite payments
  → chronological replay of 21 features → calibrated scorer → FastAPI
  → local request metrics and offline drift reports
```

The main engineering work is recovering from interrupted acquisition, preserving integer drops and ledger order, excluding same-ledger and future activity from features, and carrying the exact calibration rule into serving. The core uses Python and SQLite. Matplotlib renders the evaluation figures, MLflow tracks the frozen experiment locally, and the repository includes a pinned Docker build and a GitHub Actions workflow.

## Results

The robust statistical baseline is the operational reference. The full Isolation Forest comparison gained 0.00233 macro average precision on held-out synthetic interventions, and the advantage reversed when the last test block was excluded. Forest recall was lower under both evaluated alert policies. The original Mainnet payments are unlabeled, so the evaluation measures sensitivity to controlled changes. It supplies no real-fraud accuracy estimate.

Offline monitoring detected a large synthetic fee shift. Natural historical variation also frequently crossed the 0.20 empirical CDF distance guide, including forest scores in unchanged windows. The guide is descriptive. See the [technical audit](docs/phase5-audit.md) for the numerical results, figure provenance and verification boundaries.

## Try the offline demo

From the repository root in PowerShell, use x64 CPython 3.14.7 with pip. The install fetches hash-pinned wheels. The demo itself uses a deterministic synthetic test bundle and requires no ledger data or credentials.

```powershell
python -m venv .venv-demo
$python = './.venv-demo/Scripts/python.exe'
& $python -m pip install --only-binary=:all: --require-hashes -r requirements-service-py314.txt
& $python -m pip check
New-Item -ItemType Directory -Force artifacts | Out-Null
$env:PYTHONPATH = 'src;tests'
& $python -B -c "from pathlib import Path; from test_phase4b import service_fixture; from xrpl_anomaly.package_models import save; save(Path('artifacts/demo-model.json'), service_fixture()[0])"
$env:PYTHONPATH = 'src'
$env:XRPL_MODEL_PATH = 'artifacts/demo-model.json'
& $python -B -m uvicorn xrpl_anomaly.service:create_app --factory --host 127.0.0.1 --port 8000 --http h11 --no-proxy-headers --no-access-log
```

In another PowerShell window, check readiness, score a synthetic vector and read the worker's metrics.

```powershell
$uri = 'http://127.0.0.1:8000'
Invoke-RestMethod "$uri/health"
$model = Invoke-RestMethod "$uri/v1/model"
$body = @{
    feature_schema_version = $model.feature_schema_version
    feature_names = $model.feature_names
    values = @(0) * $model.feature_names.Count
} | ConvertTo-Json
Invoke-RestMethod "$uri/v1/score" -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod "$uri/v1/metrics"
```

The score response includes the bundle hash and schema version. The alert is null without a transaction ID. Keep the listener on loopback and use trusted local clients and model files. The service has no authentication or TLS.

## Develop and reproduce

The standard-library core declares CPython 3.12–3.14. The audit ran on Windows x64 CPython 3.14.7. The service lock targets conventional x64 CPython 3.14 on Windows and glibc Linux. Plotting and MLflow have separate Windows x64 locks.

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest discover -s tests -v
```

Use the actual interpreter path if a Windows Store alias takes precedence. The suite requires local loopback sockets. Service and plotting checks require their optional dependencies. Frozen-model and container checks are opt-in.

| Task | Guide |
| --- | --- |
| Data provenance, bounded acquisition and cache recovery | [XRPL specification](docs/specification.md), [pilot commands](docs/specification.md#reproduce-the-phase-2-pilot), [chronological sample](docs/phase3b3.md) |
| Feature definitions, leakage controls and experiment design | [Feature and evaluation contracts](docs/experiments.md), [architecture and roadmap](docs/roadmap.md) |
| Generate, verify or load the three frozen models from existing local experiment outputs | [Model packaging and MLflow](docs/phase4a.md) |
| API request contract, locked setup, Docker commands and CI | [Scoring API](docs/phase4b.md), [service and container guide](docs/phase4c.md) |
| Reproduce monitoring from local SQLite files and bundles | [Monitoring commands](docs/phase4d.md#reproduce-offline), [figure guide](docs/figures.md) |

The synthetic demo runs from a source checkout. Full historical replay requires the original caches or SQLite files and frozen outputs, which are kept locally. Docker runtime and hosted GitHub Actions execution remain unverified.
