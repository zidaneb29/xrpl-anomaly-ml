# Phase 3B.3 held-out classical evaluation

## Protocol frozen before acquisition

The [machine-readable protocol](../protocols/phase3b3-protocol.json) pins the [ledger manifest](../protocols/phase3b-blocks.json), feature definitions, scorer and intervention source digests, development-selected configurations and acquisition ceilings. Use blocks 1–4 for fitting, 5–6 only as the source of the previous model selection, 7–8 for clean calibration, and 9–12 for final testing. Each block has its own warm-up and all replay uses only earlier ledgers in the 600-second window. Convert exact integer drops through the existing log transforms. Neither detector adds scaling or imputation to the Phase 3B.2 input pipeline.

The primary comparison is the full robust baseline against the full forest, averaging both prespecified forest seeds within each block and intervention cell. Reuse the [Phase 3B.2 interventions](phase3b2.md) exactly, including training-only amount support, prior-history eligibility, sender sampling, severity and seeded replay. On each synthetic copy, use full-stream tie-grouped average precision and report prevalence. Use the original same-payment scores as paired controls. Separate the directly changed, feature-affected and unchanged observations and report their alert rates. Keep empty intervention cells visible and exclude them from detection averages. Prespecified secondary analyses cover all family and severity cells, static and temporal ablations, and clean-score rank agreement, overlap and concentration by block. The forest ablations use their own development-selected subsample sizes, so they combine a feature-set change with the established configuration for that set.

For each fitted detector, pool clean calibration keys and freeze the descending key at zero-based position `n // 100`. Alert strictly above this key on every original or synthetic test stream. Report the score component, score ties, alerted ties and actual alert rates. Separately select the first `n // 100` test keys per block as a ranking diagnostic and report tie counts and synthetic recall bounds. Do not combine the two alert policies. Report macro averages with equal block weight and paired block ranges and leave-one-block-out sensitivity for the full comparison. Seeds and related transactions are dependent. Use no transaction-level confidence intervals. Historical case studies, if any, are exploratory and cannot establish fraud.

## Acquisition envelope

The 3,668 planned ledgers require at least 3,686 requests including the independent start, middle and end checks. Scaling the four-block Phase 3B.2 stage (2,490 ledgers, 662 MB decoded, 141 MB cache, 5,055 seconds) projects roughly 976 MB decoded, 207 MB cache and 124 minutes. Cap this stage at 4,500 requests, 3 GiB conservatively charged, 768 MiB of raw cache and three cumulative acquisition hours. Retain the 20-second parent deadline, bounded retries and 8 MiB per-response limit. Stop on an integrity or persistent transport failure and preserve the verified prefix for a bounded resume. Use separate Phase 3B.3 paths for all new outputs.

| Block | Role | Warm-up anchor through final scored ledger |
| --- | --- | --- |
| 7 | Calibration | 107638745–107639358 |
| 8 | Calibration | 107720359–107720978 |
| 9 | Test | 107801237–107801846 |
| 10 | Test | 107859611–107860224 |
| 11 | Test | 107961334–107961934 |
| 12 | Test | 108018907–108019515 |

## Local reproduction

```powershell
$env:PYTHONPATH = 'src'
$env:MPLCONFIGDIR = "$PWD/artifacts/mpl-config"
& $python -B -m xrpl_anomaly.heldout_protocol
& $plotPython -B -m xrpl_anomaly.heldout --figures
& $plotPython -B -m xrpl_anomaly.heldout --figures --output reports/generated/phase3b3-repeat
```

Acquisition resumes the verified prefix and retains cumulative budget charges. The evaluation runs offline. It verifies all twelve caches, uses separate Phase 3B.3 SQLite files and writes model parameters and cutoffs before scoring the final test blocks. Compare the model, score, evaluation and figure file hashes across runs. Acquisition and timing summaries contain wall-clock measurements. Benchmark latency measures scorer calls on prepared vectors. The traced allocation peak covers scoring only, excluding the fitted model, input vectors and process overhead. Compact JSON bytes measure serialized model size. The local artifacts contain transaction identifiers.

## Verified acquisition

| Block | Ledgers | Examined transactions | Eligible with warm-up | Scored | Decoded ledger bytes | Gzip body bytes | Seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 614 | 75,978 | 6,648 | 5,406 | 220,925,129 | 47,030,337 | 915 |
| 8 | 620 | 69,755 | 6,455 | 4,823 | 204,501,100 | 43,501,473 | 899 |
| 9 | 610 | 76,977 | 2,290 | 1,684 | 243,151,929 | 50,198,157 | 931 |
| 10 | 614 | 92,395 | 4,768 | 4,205 | 262,093,969 | 56,841,931 | 1,107 |
| 11 | 601 | 116,428 | 3,600 | 2,779 | 308,892,779 | 67,037,191 | 1,324 |
| 12 | 609 | 70,289 | 6,109 | 4,780 | 187,890,592 | 40,146,361 | 938 |

All 3,668 ledgers matched the frozen boundaries and formed six gap-free validated parent chains. All 18 independent header hashes matched. Acquisition used 3,686 attempts, zero retries, 1,427,469,178 decoded and charged bytes including cross-check responses, 306,989,262 raw-cache bytes including manifests, and 6,113.42 seconds. All twelve replay databases passed SQLite integrity, foreign-key and integer-drop checks and used 22,216,704 bytes. The earlier 4,040 files matched their starting hashes. The preceding local checkpoint is `20946b589cdc59e7660adcbf28ff59311a49a7b0`.

## Clean calibration and operating behavior

Each detector alerted on 102 of 10,229 pooled calibration observations (0.997%). Below, pairs in the ties column count all rows at the calibration score boundary and the subset alerted by the frozen key. The full cutoff tuples and per-block empirical quantiles are in `models.json` and `evaluation.json`.

| Detector | Score component | Ties / alerted ties | Calibration rates 7 / 8 | Test rates 9 / 10 / 11 / 12 |
| --- | ---: | ---: | --- | --- |
| Full baseline | 52.134681 | 241 / 89 | 0.851% / 1.161% | 3.444% / 2.045% / 3.131% / 1.632% |
| Full forest, seed 7 | 0.625145 | 1 / 0 | 1.424% / 0.518% | 0.891% / 0.452% / 0.720% / 0.146% |
| Full forest, seed 29 | 0.622824 | 27 / 8 | 1.387% / 0.560% | 1.010% / 0.523% / 0.684% / 2.510% |

Median scores fell from block 7 to block 8 for all three full models, from 9.53 to 6.34 for the baseline, 0.521 to 0.479 for seed 7 and 0.521 to 0.481 for seed 29.

The separate test ranking budget selects 16, 42, 27 and 47 clean observations per block. Full-baseline rank-boundary tie counts were 140, 167, 1 and 133, with 2, 19, 1 and 23 alerted ties. Forest seeds 7 and 29 had tie counts of 1–15 and 1–37 respectively. The unchanged operating key produced 54 alerted score ties out of 140 in block 11 for the baseline. The full forest operating cutoff had zero test ties for either seed. Seed 29 sent 90% of its block 12 operating alerts to one recipient, compared with 29% for the most frequent recipient under seed 7. These are alert concentrations in unlabeled historical observations.

## Synthetic test comparison

The four test blocks contain 13,448 original scoring rows. Macro figures below weight the four chronological blocks equally, then available family and severity cells and their prespecified repetitions. All six intervention cells were available in each block.

| Feature set and detector | Macro AP | Recall at rank budget | Recall at calibration cutoff |
| --- | ---: | ---: | ---: |
| Static baseline | 0.01002 | 0.898% | 1.743% |
| Static forest | 0.01318 | 0.495% | 0.215% |
| Static + temporal baseline | 0.01121 | 0.898% | 1.743% |
| Static + temporal forest | 0.01461 | 0.448% | 0.663% |
| Full baseline | 0.01354 | 0.898% | 1.743% |
| Full forest | 0.01587 | 0.783% | 0.781% |

| Intervention | Mean prevalence | AP baseline / forest | Rank recall baseline / forest | Cutoff recall baseline / forest |
| --- | ---: | --- | --- | --- |
| Amount ×/÷ 2 | 0.976% | 0.01716 / 0.02505 | 0.00% / 2.36% | 0.73% / 1.88% |
| Amount ×/÷ 4 | 0.976% | 0.01716 / 0.02574 | 0.00% / 2.34% | 0.73% / 1.88% |
| Burst gap ÷ 2 | 0.976% | 0.01709 / 0.01697 | 2.15% / 0.00% | 3.72% / 0.93% |
| Burst gap ÷ 4 | 0.976% | 0.01690 / 0.01652 | 2.15% / 0.00% | 3.72% / 0.00% |
| One redirect | 0.241% | 0.00299 / 0.00302 | 0.00% / 0.00% | 0.00% / 0.00% |
| Three redirects | 0.723% | 0.00992 / 0.00792 | 1.08% / 0.00% | 1.57% / 0.00% |

Full-forest macro AP exceeded the baseline by 0.00233. The paired block differences were −0.00078, −0.00141, −0.00084 and +0.01236 in order. Leaving block 12 out reverses the difference to −0.00101. The full forest's stronger-burst gain from development did not recur. Although both detectors gained macro AP with the full inputs, the forest ablations also use different selected subsample sizes and the baseline alert recall was unchanged across groups. The baseline–forest Spearman correlations ranged from 0.201 to 0.523, with zero to five shared alerts under the fixed rank budget. Forest seed pairs had Spearman correlations of 0.908–0.961 and shared 6 to 20 alerts. In block 12, the two seeds agreed on only 6 of their 47 top alerts.

The synthetic evaluation reports matched score changes for the same payments, recall for the original counterpart scores, and separate direct, spillover and unchanged alert counts. AP includes the full synthetic stream and uses only directly changed identities as positives. Eligibility depends on the original activity histories, and concentration changes affect downstream feature vectors. Test observations can share accounts both within and across blocks. These four blocks support descriptive comparisons and do not establish precision or recall for real fraud. Lower operating alert rates for the forest affect its cutoff recall relative to the baseline.

Across the two forest fits, the matched score win statistic was 61–67% for amount, 23–24% for burst and 69–79% for concentration. The statistic assigns one to an increase, half to a tie and zero to a decrease. The largest affected cohorts per copy were 541 for amount, 270 for burst and 818 for concentration. Higher matched concentration scores coexisted with zero forest recall under either alert policy.

The [Phase C matched comparison](phase-c-interpretation.md) gives the selected identities the same labels on the original and edited streams. The full forest AP gap was +0.002346 on the original streams and +0.002333 on the edited streams. The forest fits' individual AP changes have opposite signs. The supplement reports both fits separately, separates the graph feature increment from subsample selection, and traces recipient redirects through earlier-ledger features.

## Operational costs and figures

| Full detector | Scoring throughput | Block p95 latency | Scoring allocation peak | Compact model |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 128,824 rows/s | 7.4–8.3 µs | 848 B | 2,405 B |
| Forest, seed 7 | 15,362 rows/s | 94.7–97.2 µs | 24 B | 284,957 B |
| Forest, seed 29 | 15,157 rows/s | 90.0–101.0 µs | 24 B | 288,410 B |

The single-thread benchmarks cover prepared feature vectors on the local CPU. The allocation peak measures transient Python allocations during scorer calls and excludes retained model memory. The serialized model size includes the calibration key.

The local figure set contains `calibration.png`, `synthetic-families.png`, `ablation-and-blocks.png`, `alerts-and-stability.png` and `performance-and-cost.png`. Figure metadata records captions, input hashes and figure hashes. The first output directory occupies 28,136,817 bytes.

## Verification

The full offline suite passed 32 tests on CPython 3.14 in the existing plotting environment, including loopback deadline recovery and deterministic fixture regeneration. Two full offline evaluations produced nine byte-identical files, including all five PNGs, model parameters and cutoffs, clean scores, metrics and figure metadata. All summary fields matched after excluding ingest and replay times. The separate benchmark records retain measured timing variation. The protocol SHA-256 is `f36b02932764c304ee93252e1e64486e5553723deb288f48f1dbae19cd6743fe`.

## Phase boundary

The results establish a classical reference with reproducible operating thresholds. The baseline's higher edited-stream recall under both alert rules and lower scoring cost support its use as the operational reference for this study. The small aggregate forest AP gap was already present for the selected identities on the original streams, so it supplies weak evidence for prioritizing that forest as an alerting system. A separate neural experiment would test a distinct modeling hypothesis on a new untouched evaluation split.
