# XRP Ledger Anomaly Detection — End-to-End ML Systems

End-to-end ML system for XRP Ledger transaction anomaly detection, featuring temporal and graph-based features, reproducible model evaluation, FastAPI inference, Docker, CI, and drift monitoring.

A local Python system that scores unusual XRP payments from validated Mainnet ledgers. XRPL provides public, ordered transaction history with exact integer amounts and a directed payment graph. This makes it possible to replay what the scorer could have known at each ledger and to measure how the models behave as activity changes over time.

```text
Read-only XRPL RPC → hash-checked ledger cache → normalized SQLite payments
  → chronological replay of 21 features → calibrated scorer → FastAPI
  → local request metrics and offline drift reports
```

The main engineering work is recovering from interrupted acquisition, preserving integer drops and ledger order, excluding same-ledger and future activity from features, and carrying the exact calibration rule into serving. The core uses Python and SQLite. Matplotlib renders the evaluation figures, MLflow tracks the frozen experiment locally, and the repository includes a pinned Docker build and a GitHub Actions workflow.

[Technical audit](docs/phases/phase5-audit.md) · [Figure gallery](#figure-gallery) · [Offline demo](#try-the-offline-demo) · [Documentation guide](#documentation-guide)

## Results

The robust statistical baseline is the operational reference. On the edited held-out streams, the full Isolation Forest averaged 0.00233 higher macro average precision (AP), and the advantage reversed when the last test block was excluded. The same selected payments already gave the forest a 0.00235 AP advantage on the original streams. One full forest fit gained AP after editing and the other lost AP. Forest recall was lower under both evaluated alert policies. These results describe ranking and alert behavior under a controlled selection and editing procedure. The original Mainnet payments are unlabeled. [Matched evaluation](docs/phases/phase-c-interpretation.md#matched-original-and-edited-rankings)

In offline replay, overriding one prepared fee coordinate moved baseline score distance from 0.190 to 1.000 on the same rows. Unchanged historical windows also frequently crossed the descriptive 0.20 distance guide. The final stage uses the next unchanged input window with a stateless scorer. The replay provides evidence about distribution shift for this intervention. Fraud detection and operational incident response remain unevaluated. [Monitoring interpretation](docs/phases/phase-c-interpretation.md#prepared-fee-override-and-historical-crossings)

## Figure gallery

![Unlabeled directed payment graph for the 256-ledger Mainnet pilot](docs/images/directed-network.png)

**Payment network.** The November 8, 2026 UTC pilot contained 3,873 eligible payments. The graph shows 19 directed edges among the 16 accounts with the most incident payments in that slice. Node area and edge width encode payment counts. See the [pilot specification](docs/specification.md#reproduce-the-phase-2-pilot).

![Synthetic held-out average precision by feature set and test block](docs/images/ablation-and-blocks.png)

**Held-out synthetic evaluation.** Macro average precision compares the robust baseline with Isolation Forest on synthetic interventions in blocks 9–12. The panels use different vertical scales. Forest ablations also use different development-selected subsample sizes. Block 12 accounts for the forest's mean advantage with the full feature set. See the [held-out comparison](docs/phases/phase3b3.md#synthetic-test-comparison).

The bars rank intervention-selected payment identities on the edited streams. See the [matched original-stream AP and configuration comparison](docs/phases/phase-c-interpretation.md#matched-original-and-edited-rankings) for how much of the ranking was already present before the edits.

![Distribution distances and alert rates across unchanged Mainnet windows](docs/images/historical-monitoring.png)

**Historical monitoring.** Eighteen unchanged ten-minute Mainnet windows contain 23,677 observations. Lines connect windows within each block. Shaded, compressed gaps identify unsampled days. The upper panel compares distributions against block 7, which overlaps its own reference. The lower panel labels the block 7 alert rate (0.851%) and the pooled calibration budget target (1%) separately. The 0.20 distance guide is descriptive.

![Synthetic fee override and restored original input alongside the same unchanged Mainnet rows](docs/images/shift-recovery.png)

**Synthetic fee override and restored input.** In the shaded block 8 window, the fee feature represents a fixed 100,000 drops for all 2,030 rows. Orange crosses show the same rows with their original fees. Both score series show medians and capped 5th–95th percentile intervals. All three quantiles coincide at 69.98 for the overridden window. The final stage reuses the next unchanged window in a stateless scorer. See the [monitoring results](docs/phases/phase4d.md#historical-behavior-and-controlled-shift) and [figure corrections](docs/phases/phase-b-figures.md).

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

## Repository structure

| Path | Contents |
| --- | --- |
| [`src/xrpl_anomaly/`](src/xrpl_anomaly/) | Ledger ingestion, feature replay, model evaluation, scoring API, and monitoring |
| [`tests/`](tests/) | Offline tests for ingestion through serving and monitoring |
| [`docs/`](docs/) | Data specification, feature and evaluation contracts, roadmap, and figure guide |
| [`docs/phases/`](docs/phases/) | Historical phase reports and the final technical audit |
| [`docs/protocols/`](docs/protocols/) | Frozen ledger manifest and machine-readable held-out protocol |
| [`docs/images/`](docs/images/) | Public figures used in the gallery and figure guide |
| [`Dockerfile`](Dockerfile), [`.github/workflows/offline.yml`](.github/workflows/offline.yml) | Container build and hosted offline checks |

## Documentation guide

| Task | Guide |
| --- | --- |
| Data provenance, bounded acquisition and cache recovery | [XRPL specification](docs/specification.md), [pilot commands](docs/specification.md#reproduce-the-phase-2-pilot), [chronological sample](docs/phases/phase3b3.md) |
| Feature definitions, leakage controls and experiment design | [Feature and evaluation contracts](docs/experiments.md), [architecture and roadmap](docs/roadmap.md) |
| Follow the modeling work from pilot to held-out results | [Baseline analysis](docs/phases/phase3a.md), [training sample](docs/phases/phase3b1.md), [development comparison](docs/phases/phase3b2.md), [held-out evaluation](docs/phases/phase3b3.md) |
| Inspect the frozen experiment inputs | [Ledger manifest](docs/protocols/phase3b-blocks.json), [held-out protocol](docs/protocols/phase3b3-protocol.json) |
| Generate, verify or load the three frozen models from existing local experiment outputs | [Model packaging and MLflow](docs/phases/phase4a.md) |
| API request contract, locked setup, Docker commands and CI | [Scoring API](docs/phases/phase4b.md), [service and container guide](docs/phases/phase4c.md) |
| Reproduce monitoring from local SQLite files and bundles | [Monitoring commands](docs/phases/phase4d.md#reproduce-offline), [figure guide](docs/figures.md) |

The synthetic demo runs from a source checkout. Full historical replay requires the original caches or SQLite files and frozen outputs, which are kept locally. The earlier revision [`418c6f7`](https://github.com/zidaneb29/xrpl-anomaly-ml/commit/418c6f78a02ec10c587cbf9e732446b65b94e741) passed the hosted Windows and Ubuntu offline jobs, including the synthetic Docker smoke checks on Ubuntu. The [Phase 5 audit](docs/phases/phase5-audit.md) records the earlier local verification scope.

## License

Project code and documentation are available under the [MIT License](LICENSE) where the project holds the rights to license them. Third-party dependencies, XRP Ledger data, and external services remain subject to their respective terms.
