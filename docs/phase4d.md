# Phase 4D local monitoring and recovery

## API metrics

Start the local service using the [Phase 4C commands](phase4c.md#local-api-on-windows). From a second PowerShell session:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/metrics | ConvertTo-Json -Depth 8
```

Each worker keeps the most recent 1,024 HTTP request completions in memory. The endpoint excludes its own GET requests from the window and uses the existing Host validation. The response includes the retained count, capacity, process startup time and first and last completion times in UTC, along with the loaded model ID, type, bundle version, digest and feature schema version.

- **Service operations.** HTTP status counts cover the retained requests. Scoring rejection rate divides POST scoring responses with status 400, 413, 415 or 422 by all retained POST scoring attempts. This includes Host and request transport or format rejections. The endpoint separately counts 422 responses, reports their rate among POST scoring attempts and counts validation failures from the frozen scorer. It counts a decoded object as structurally complete when its values array has all 21 positions and contains no null. Invalid types, values, version or feature order can still make a structurally complete request fail validation. Bodies that could not be decoded to an object are counted separately.
- **Inference latency.** The service times validation in the frozen scorer, scoring and the optional frozen alert decision for successful responses. It reports milliseconds, sample count, p50 for nonempty samples and p95 at 20 samples or more. The measurement excludes body reading, JSON and Pydantic parsing, middleware, response serialization and network time. Quantiles use the nearest rank, including the lower of the middle two observations for p50 with even sample sizes.
- **Model statistics.** Successful scores contribute to p05, p50, p95 and zero rate. The frozen alert rate divides the number of true decisions by the number of known decisions. Requests without a transaction hash contribute a score and an unknown decision. Each request contributes separately, including retries and repeats.

The window retains statuses, completeness and scorer rejection flags, timestamps, latency, scores and alert decisions. It retains no feature vectors, transaction IDs, account addresses, headers or request bodies. Keep the endpoint local. Small windows can expose individual scores through quantiles. Worker restarts reset all metrics. Multiple workers report separate windows, and polling through a load balancer can mix snapshots from different workers. The bounded window can turn over quickly under load. The endpoint gives an in-process summary. Drift comparisons and plots run offline.

## Reference and drift calculations

Block 7 supplies 5,406 clean complete-history reference vectors. It was the first of the two original calibration blocks. The frozen alert cutoff still uses the original pooled calibration keys from blocks 7 and 8. Blocks 1–4 fitted the models, blocks 5–6 supported development selection, block 8 provides the subsequent calibration comparisons and controlled scenario, and blocks 9–12 retain their final-test role. The block 7 subwindows overlap their reference and serve as descriptive checks. The reference comes entirely from earlier observations for all later comparisons.

For each feature and the selected model's anomaly score, the report gives observed and missing counts, zero fractions, nearest-rank p05, p50 and p95, and the maximum absolute difference between the two empirical cumulative distribution functions. For sorted reference values X and comparison values Y, each ECDF at t is the count of observations at or below t divided by its sample size. The distance D is the maximum of the absolute ECDF difference at distinct pooled observed values. Tied values are evaluated together. D ranges from 0 to 1 and does not require bins, density estimation or division by a variance. A constant column compared with the same constant gives 0. Two different constants give 1. Zero remains an observed value. Missing values are counted and omitted from the ECDF, and nonfinite or nonnumeric inputs raise an error.

A comparison reports D and a descriptive flag when each sample has at least 100 observed values. The flag marks D at or above 0.20, a difference of at least 20 percentage points in cumulative mass somewhere in the distribution. Below the sample floor the distance and flag are null. The sample floor and guide are fixed operating choices for this demonstration. Dependence between payments, overlapping histories, sparse rare tails and simultaneous checks across 21 features limit interpretation. The distance measures marginal change and can miss changes in feature relationships or small tail populations. It carries no p-value, false-positive guarantee or inference about accuracy. The frozen alert rate can vary above or below the original calibration budget. Anomaly scores describe statistical atypicality, and the available data do not establish fraud probabilities or real-fraud accuracy.

## Reproduce offline

Use the existing plotting interpreter and the existing Phase 3B.3 SQLite and Phase 4A bundle files. Run from the repository root. Omit `--figures` to use a standard-library Python environment. Each run reserves a new directory under `reports/generated/`. If a run is interrupted, choose a fresh name and inspect the previous directory for partial output.

```powershell
$plotPython = './.venv-phase2/Scripts/python.exe'
$env:PYTHONPATH = 'src'
$env:MPLBACKEND = 'Agg'
$env:MPLCONFIGDIR = "$PWD/artifacts/phase4d/mpl"
& $plotPython -B -m xrpl_anomaly.monitoring_replay --figures --run-name phase4d-local
& $plotPython -B -m xrpl_anomaly.monitoring_replay --figures --run-name phase4d-local-repeat
& $plotPython -B -m xrpl_anomaly.monitoring_replay --model isolation-full-7 --run-name phase4d-local-forest7
& $plotPython -B -m xrpl_anomaly.monitoring_replay --model isolation-full-29 --run-name phase4d-local-forest29
& $plotPython -B -m xrpl_anomaly.verify_packaged
```

The replay opens the six SQLite files in immutable read-only mode. It reuses the earlier-ledger feature pipeline, the frozen scoring interval and the loaded detector. Each block gets fresh warm-up history. Three half-open, ten-minute windows per block preserve ledger and transaction order and keep each ledger together. The replay retains the reference and works on one subsequent block at a time on one Python thread. UTC Unix window bounds and sample sizes are recorded per window. The monitoring report records the bundle and SQLite hashes, frozen protocol, revision and source hashes, runtime versions, window settings and intervention configuration. Figure metadata ties each PNG to the monitoring JSON by SHA-256. Comparisons across different Git revisions should account for provenance fields even when the statistics are identical.

## Historical behavior and controlled shift

The run covered 23,677 unchanged rows in 18 windows across blocks 7–12. Baseline alert rates in the 12 final-test windows ranged from 0.66% to 5.43%. Fee and score distance each crossed the guide in 10 of those windows. At least one feature crossed the guide in all 12 final-test windows and 3 of 6 calibration windows. These unmodified observations establish the background rate of guide crossings. Ground truth for operational incidents is unavailable.

The scenario uses block 8's first window unchanged, sets the prepared `log_fee_drops` coordinate to `log1p(100000)` in the second, and uses the third window unchanged. The fixed window and fee require no random seed. The second window contains 2,030 vectors, of which 2,029 changed because one already had that fee. Original row identities, order and all other coordinates are preserved. The unchanged second window provides a same-row control. The intervention acts on prepared vectors and leaves historical storage and feature state intact. It models a large fee-input shift and does not simulate ledger execution or provide verified fraud labels.

| Baseline segment | n | Fee D | Score D | Median score | Frozen alerts |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference block 7 | 5,406 | — | — | 9.53 | 46 (0.85%) |
| Normal | 1,452 | 0.126 | 0.131 | 5.69 | 25 (1.72%) |
| Middle window, unchanged | 2,030 | 0.192 | 0.190 | 12.36 | 16 (0.79%) |
| Middle window, synthetic | 2,030 | 1.000 | 1.000 | 69.98 | 2,030 (100%) |
| Recovery | 1,341 | 0.128 | 0.194 | 4.34 | 15 (1.12%) |

Both baseline distances fell below the 0.20 guide in recovery. Score distance remained higher than in the normal window. Among the forest comparisons, score D reached 0.278 for seed 7 and 0.242 for seed 29 under intervention. It fell to 0.212 and 0.234 in recovery, respectively. All three clean block 8 windows already exceeded the score guide for both forests, so the guide could not separate the synthetic segment from normal variation for those scores. The seed 29 response was especially weak in the recovery comparison. These findings describe sensitivity to one large, deliberately localized perturbation.

## Verification boundary

The full frozen verifier matched 71,031 scores and all 18 operating alert counts across the three bundles. Two baseline monitoring runs produced byte-identical JSON, figure metadata and both PNGs. The separate forest runs used the same six read-only databases and reporting procedure. The local offline suite passed 48 checks, including FastAPI, plotting, loopback deadline recovery and frozen-bundle parity. Two Docker checks were skipped. The 7,778 pre-existing files under the data, artifacts and reports directories matched their starting SHA-256 hashes. Docker runtime verification and GitHub Actions execution remain outstanding from Phase 4C. Phase 5 would consolidate the technical evaluation and its audited figure set, with a decision on the monitoring guide's intended use before treating it as an operational policy.

To run the same Windows test scope with the existing separate service and plotting environments, keep the plotting variables from above and run this in a shell that permits local loopback sockets.

```powershell
$env:PYTHONPATH = 'src;.venv-phase2/Lib/site-packages'
$env:XRPL_TEST_FROZEN_MODELS = 'artifacts/phase4a/models'
Remove-Item Env:XRPL_TEST_IMAGE -ErrorAction SilentlyContinue
& ./.venv-phase4c/Scripts/python.exe -B -m unittest discover -s tests -v
Remove-Item Env:XRPL_TEST_FROZEN_MODELS
$env:PYTHONPATH = 'src'
```
