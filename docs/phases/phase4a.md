# Phase 4A model packaging and experiment tracking

The full robust baseline is the operational reference. The two full Isolation Forest fits remain optional comparison detectors with their original seeds, subsample size, tree count and separate cutoffs. Phase 4A imports fitted state from Phase 3B.3. Historical synthetic metrics describe ranking and alert selection for intervention-selected identities on edited streams. The [matched evaluation](phase-c-interpretation.md#matched-original-and-edited-rankings) measures how those rankings changed relative to the original streams. The original Mainnet payments are unlabeled.

## Model bundle v1

Each `xrpl-anomaly-model` bundle is a single UTF-8 JSON file with deterministic key ordering. The model ID identifies the fit and the SHA-256 identifies its canonical bundle bytes. Version 1 supports the three full fits only.

| Section | Contents |
| --- | --- |
| Identity | Format and model implementation version, model type, fit ID |
| Feature schema | Schema v1, 21 ordered feature names and types, 600-second lookback, prepared inputs without imputation |
| Training | Blocks 1–4, 1,800-second scoring windows, robust scale rules or forest seed, subsample size and tree count |
| Fitted state | Robust medians and scales with their MAD or IQR method, or forest split trees, leaf path corrections and normalizer. Both list omitted features. |
| Calibration | Blocks 7–8, target divisor 100, and the exact cutoff tuple and tie policy |
| Provenance | Historical experiment ID, recorded Git HEAD, Phase 3B.3 checkpoint, source and protocol hashes, source output hashes, all 12 snapshot hashes and original runtime |

The original evaluation recorded Git HEAD `20946b589cdc59e7660adcbf28ff59311a49a7b0` while Phase 3B.3 changes were in the working tree. The local checkpoint `893e8f6149c4804a145bc504065842edc313f60a` captures those changes. The bundle preserves both identifiers and the hashes of the source used by the evaluation.

The loader validates JSON structure, size, versions, feature order and types, fitted state and the cutoff digest before constructing either standard-library scorer. It uses no pickle, estimator framework or MLflow dependency. Provenance fields carry digests for external verification. JSON validation alone cannot establish artifact authenticity, so compare the bundle digest with a trusted record when exchanging bundles.

## Package and verify locally

From the repository root, using the existing plotting environment or another supported CPython interpreter:

```powershell
$env:PYTHONPATH = 'src'
$python = '.venv-phase2/Scripts/python.exe'
& $python -B -m xrpl_anomaly.package_models
& $python -B -m xrpl_anomaly.package_models --output artifacts/phase4a/repeat-models
& $python -B -m xrpl_anomaly.verify_packaged
```

The packaging command reads the original `reports/generated/phase3b3` outputs and checks their frozen protocol, scorer source and recorded hashes. It writes the three bundles under `artifacts/phase4a/models`. It accepts an identical existing bundle and refuses a conflicting file. The verification command opens the six existing calibration and test SQLite databases in immutable read-only mode, replays features and checks exact score equality against the historical clean table. It also checks the operating alert counts. It needs the completed Phase 3B.3 local outputs and never fits a detector.

## Prepared-feature inference

```python
from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION
from xrpl_anomaly.model_artifact import load

detector = load("artifacts/phase4a/models/baseline-full.json")
score = detector.score(
    prepared_values,
    feature_names=FEATURES,
    feature_schema_version=SCHEMA_VERSION,
)
alert = detector.alerts(score, identity=transaction_id)
```

Supply complete-history vectors from the existing chronological replay. Values must be finite, nonnegative Python integers or floats. Recency and indicator columns require integers within their schema bounds, and concentration is in [0, 1]. Supply the producer's actual ordered schema and preserve the original transaction identity exactly for a calibrated decision. The scorer uses only the vector. The decision compares `(score, SHA-256 tie digest, identity)` strictly above the persisted cutoff, using the original tie domain and ordering. The return value identifies the model, bundle digest and feature version. The alert describes statistical atypicality under the frozen policy.

## Local experiment tracking

The optional Windows x64 CPython 3.14.7 environment uses MLflow Skinny 3.16.1 with SQLAlchemy and Alembic. The hash-pinned lock records the wheel set from the verified install. It is separate from both the scoring runtime and the plotting environment.

```powershell
# Set $basePython to the actual CPython 3.14.7 executable with pip.
& $basePython -m venv --without-pip .venv-phase4a
$trackingPython = '.venv-phase4a/Scripts/python.exe'
& $basePython -m pip --python $trackingPython install --only-binary=:all: --require-hashes -r requirements-phase4a-tracking-win-py314.txt
$env:PYTHONPATH = 'src'
& $trackingPython -B -m xrpl_anomaly.track_history
```

The importer uses an explicit SQLite tracking store and local artifact directory in `artifacts/phase4a/tracking`. Run one importer at a time. It marks the run as a historical import, records the original synthetic aggregate and clean alert rates, and stores runtime benchmarks, bundles, calibration summaries, all five original figures and figure metadata. The import manifest links bundle and figure hashes to the source outputs. The forest aggregate retains the original two-seed comparison. The benchmark is the original prepared-row run with its original timing variation. Importing does not measure current runtime or launch a tracking server.

A repeated import checks logged artifact bytes and returns the existing finished run ID. A failed attempt remains visible and can be retried. The original score table and identity-level intervention records stay in their historical directories. The SQLite database, file artifacts and environment remain ignored by Git.

## Local verification

- Two packaging passes produced byte-identical JSON for all three fits. Read-only feature replay matched 71,031 historical scores exactly across calibration and test and reproduced all 18 block-level operating alert counts.
- The full offline suite passed 36 tests on CPython 3.14.7 with the existing plotting environment and local loopback access. This includes fresh-process loading, malformed artifact and feature rejection, and comparisons against both existing scorers.
- The finished local MLflow run `771058a4095d4838bce105287aa34f82` contains 35 metrics and 13 verified files. Reimport returned the same run ID. The earlier failed import remains in the local database.
- The pre- and post-phase SHA-256 inventories of all 7,750 files under `data` and `reports/generated` matched.

## Phase boundary

Phase 4B can wrap the prepared-feature interface in a local FastAPI service. Keep request validation, model loading and calibrated decision semantics aligned with this contract, and add service-level tests and latency measurements under a separately approved phase.
