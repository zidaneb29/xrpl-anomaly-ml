# XRP Ledger Anomaly Detection and ML Systems Engineering

This project builds an end-to-end, local ML system for scoring statistically unusual XRP payments. The engineering work covers reliable XRPL ingestion, normalization and SQLite storage, reproducible feature generation, model training and evaluation, MLflow experiment tracking, local API serving, automated testing and CI, and monitoring.

The system focuses on successful, direct XRP payments in validated Mainnet ledgers. Model comparisons measure what earlier-ledger temporal and directed graph context adds to payment attributes and what it costs to compute and serve. Anomaly scores describe statistical atypicality relative to the sampled history and model. A high score alone cannot establish fraud.

Phase 2 implements the bounded Mainnet pilot, SQLite ingestion, chronological feature replay, and a robust statistical baseline. The core pipeline and offline tests use the Python standard library. Figure rendering has a separate, hash-pinned environment.

- [Technical specification and acquisition plan](docs/specification.md)
- [Feature and evaluation contracts](docs/experiments.md)
- [Architecture, reproduction, and phase gates](docs/roadmap.md)
- [Scientific figure plan](docs/figures.md)
- [Phase 3A baseline results and evaluation plan](docs/phase3a.md)
- [Phase 3B.1 alert budget and frozen acquisition plan](docs/phase3b1.md)
- [Phase 3B.2 training and development comparison](docs/phase3b2.md)
- [Phase 3B.3 held-out calibration and evaluation](docs/phase3b3.md)
- [Phase 4A model bundles, inference and local tracking](docs/phase4a.md)
- [Phase 4B local scoring API](docs/phase4b.md)
- [Phase 4C locked service setup, Docker, and CI](docs/phase4c.md)
- [Phase 4D local monitoring, replay, and recovery](docs/phase4d.md)

## Run the scoring API

Use the Phase 4C guide to install the hash-pinned service dependencies in an isolated CPython 3.14 environment or build the local Linux container. Both workflows load one approved bundle at startup. The guide includes the loopback binding, read-only model mount, and offline verification commands.

Use `GET /v1/metrics` for the worker's bounded request, latency and model statistics. The Phase 4D guide reproduces chronological drift comparisons and a synthetic shift followed by unchanged historical observations using the frozen model bundles.

## Offline checks

From the repository root in PowerShell, set `$python` to the path of a working CPython executable. Use the real interpreter path if a Windows Store alias takes precedence.

```powershell
$python = 'C:/path/to/python.exe'
& $python -I -B -c "import sys, unittest; sys.path.insert(0, 'src'); result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)"
```

This runs the standard-library smoke suite directly from source. It requires neither an install nor a network connection. The package metadata allows CPython 3.12 through 3.14, with Windows x64 CPython 3.14.7 used for Phase 1 verification.

## Phase 2 pilot

The approved pilot uses ledgers 108187347 through 108187602. To resume acquisition for that same snapshot, run the following from the repository root with a working CPython executable. The acquisition command makes read-only HTTPS requests for uncached ledgers. Use a single acquisition process per cache directory.

```powershell
$env:PYTHONPATH = 'src'
& $python -B -m xrpl_anomaly.pilot data/raw/pilot-108187602 108187602
```

Replay the Phase 2 cache offline with the revised Phase 3A baseline into separate SQLite and output paths.

```powershell
& $python -B -m xrpl_anomaly.analysis data/raw/pilot-108187602 data/processed/phase3a-pilot-108187602.sqlite reports/generated/phase3a-pilot-108187602
```

For PNG figures on Windows x64 CPython 3.14, install the optional wheels into a separate project environment. Run the same offline suite with this environment's interpreter to include the rendering check.

```powershell
& $python -m venv --without-pip .venv-phase2
$plotPython = '.venv-phase2/Scripts/python.exe'
& $python -m pip --python $plotPython install --only-binary=:all: --require-hashes -r requirements-phase2-plots-win-py314.txt
$env:MPLCONFIGDIR = "$PWD/artifacts/mpl-config"
& $plotPython -B -m xrpl_anomaly.analysis data/raw/pilot-108187602 data/processed/phase3a-pilot-108187602.sqlite reports/generated/phase3a-pilot-108187602 --figures
```

The raw manifest records checked hashes, exclusions, gaps, and acquisition budgets. The replay records source and snapshot digests, environment details, feature and score tables, and figure provenance. Replaying the same verified snapshot is idempotent. A digest or hash conflict requires review of the manifest and cache before continuing.

The default scorer uses features with positive training MAD or IQR. To reproduce the Phase 2 scoring policy, pass `--legacy-resolution` and use a separate output directory.

Historical features use observed activity in the previous 600 seconds and strictly earlier ledgers. Warm-up and gap-affected rows retain static values with historical columns blank. In complete windows an unseen account has zero prior counts and volumes, recency of 600 seconds, and an unseen indicator. The baseline fits the first half of the complete-history ledgers, calibrates on the next quarter, and applies that threshold to the final quarter. Scores exceeding the cutoff are statistical outliers under this local pilot baseline.
