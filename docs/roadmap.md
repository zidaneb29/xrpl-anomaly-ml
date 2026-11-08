# Architecture, reproduction, and phase gates

## Local architecture

Read-only RPC → immutable compressed cache and manifest → schema and payment validation → SQLite → chronological feature replay → training and evaluation → versioned model bundle → local FastAPI and monitoring.

Use SQLite foreign keys, unique ledger and transaction keys, and atomic per-ledger writes. Keep the feature calculation shared across training and batch inference. Serve versioned feature vectors initially and return score, threshold decision, and model version. Validate the schema and reject mismatches. Use local MLflow for experiment tracking and store the exact preprocessing and calibration policy with the model. Load only trusted local model bundles.

Record coverage gaps, exclusion counts, cold starts, feature and score distributions, alert rates, throughput, and latency. A monitoring demonstration can use chronological replay and a separate documented synthetic distribution shift. Changes in input or score distributions have observable meanings even when outcome labels are absent.

## Environment and reproduction

Phase 1 uses standard-library tests on Windows x64 CPython 3.14.7. The shell's Windows Store aliases were inaccessible, while an alternate interpreter worked. SQLite 3.50.4 was available in that interpreter. NumPy 2.5.3 and pandas 3.0.5 were present in the base interpreter and are outside the Phase 1 environment.

For the eventual ML environment, retain 3.14 as a candidate. Published releases have Windows x64 CPython 3.14 wheels for scikit-learn and PyArrow, and PyTorch documents Windows support for 3.14. MLflow's Python minimum and platform-independent wheel alone establish little about its transitive dependency set. Before choosing a full environment, resolve the exact approved dependencies with binary wheels for Windows x64 and the planned CI platform, then test imports and a small fit, serialization, and reload. Recommend CPython 3.12 as the compatibility fallback if the chosen stack fails that check. Select a separate CPU-only neural environment if the autoencoder is approved. [scikit-learn files](https://pypi.org/project/scikit-learn/#files), [PyArrow files](https://pypi.org/project/pyarrow/#files), [pandas release notes](https://pandas.pydata.org/docs/whatsnew/index.html), [PyTorch installation](https://pytorch.org/get-started/locally/), [MLflow setup](https://mlflow.org/docs/latest/genai/getting-started/connect-environment/)

Phase 1 has an empty runtime dependency set. The source tests run in a fresh pip-free virtual environment. Packaging metadata names a build backend for future wheel builds. Lock the build tooling and test wheel installation when the project first needs a built distribution. Add and verify a transitive lock with artifact hashes when introducing third-party runtime or test dependencies. Prefer offline fixtures and a small test workload. Split tests into unit, local integration, and opt-in live or experimental runs as those entry points appear.

Keep inputs and outputs in separate local paths such as `data/raw/`, `data/processed/`, `artifacts/`, and `reports/generated/`. Each run records the snapshot and configuration digests, schema versions, ledger bounds, code revision, interpreter and package lock, OS and CPU/thread configuration, seeds, split boundaries, run ID, model ID, and commands. Preserve exact inputs for replay where permitted. Specify which outputs are deterministic and use documented tolerances for platform-sensitive model scores and timings.

## Phases

| Phase | Deliverables and acceptance |
| --- | --- |
| 1. Foundation | Technical scope, source and sampling plan, feature and evaluation contracts, architecture, dependency decision, and scientific figure plan. Save a minimal scaffold and local ignored instructions. Run the source checks in a fresh environment without third-party dependencies. |
| 2. Ingestion and baseline | Approved bounded live pilot, validated cache, SQLite store, exact normalized values, deterministic feature replay, and robust baseline report. Test fixtures cover malformed amounts, API parsing, throttling, gaps, duplicate handling, interrupted writes, graph counts, and temporal leakage. Report pilot feasibility before increasing the download budget. |
| 3. Models and evaluation | Isolation Forest and optionally an approved CPU autoencoder, frozen chronological experiments, synthetic benchmark, ablations, and MLflow tracking. Reproduce selected comparisons from versioned inputs and reload artifacts to verify scoring parity. |
| 4. Local inference and monitoring | FastAPI service, CI, Docker, local monitoring, and operational guide. Verify offline/API parity, bad-input handling, and drift and recovery demonstrations. |
| 5. Audit and publication preparation | Reproduce reference results, audit claims and figures, review data and dependency terms, and prepare a concise technical evaluation report, reproducible figures, and public README. Cover ingestion reliability, feature and model trade-offs, serving and monitoring behavior, limitations, and reproduction commands. Publication and hosting require separate authorization. |

At each boundary record changed files, executed checks, any experimental results and generated figures, limitations, open decisions, and the next phase. Wait for approval before advancing.
