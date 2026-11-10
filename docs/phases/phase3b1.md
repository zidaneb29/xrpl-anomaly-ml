# Phase 3B.1 acquisition and alert budgets

## Alert budget

Use the Phase 3A training-only robust scorer unchanged. Distinct observations can receive the same maximum standardized deviation, for example when the same discrete fee level drives their scores. The pilot's six calibration rows at the maximum were all fee-driven. The strict score rule alerted on zero of 423 calibration rows. Including every tied row would alert on six, above the target of four.

For each detector, orient finite scores with larger values more unusual. Order observations by descending `(score, SHA-256(domain || identity), identity)`, where the domain is the UTF-8 prefix `xrpl-alert-budget-v1` followed by a zero byte. Use the canonical transaction hash for original observations and retain the original identity for synthetic copies. The identity is a secondary ordering key and remains outside the model inputs. The last key gives a total order even if the digests collide.

For `n` calibration observations, set `k = floor(n / 100)` and save the key at descending zero-based position `k`. Alert on keys strictly greater than it. Unique identities guarantee exactly `k` calibration alerts, including when `k = 0`. Freeze the entire key before scoring the final blocks. The pilot illustration uses only the 423 historical calibration rows and selects four of the six cutoff ties. Digest ordering assigns no anomaly meaning to differences within a tied score. The calibration rate is empirical and the same cutoff can yield higher or lower rates on later, dependent observations.

Report each block's eligible count, alert count and fraction, strictly above-score count, score-tie count and fraction, and alerted ties. Use the same frozen calibration rule for operating comparisons and separately rank each detector on the same evaluation rows at `floor(n / 100)` for fixed-budget metrics. Use the same digest order for all detectors and report a sensitivity interval for labeled recall when a tie straddles the ranking budget. No new detector or test-dependent tuning enters this phase.

## Frozen sample

Use the six latest full UTC Monday-to-Sunday weeks preceding the pilot, from September 21 through November 1, 2026. Apply the Wednesday and Saturday UTC-hour rotation in [Phase 3A](phase3a.md) without looking at transaction composition. The ledger ranges are inclusive and the UTC scoring window is half-open, starting at the listed time and ending 30 minutes later. The first range index is the last validated close at or before the start minus 600 seconds. Start each replay with empty history at that anchor. Score only the listed scoring interval, using strictly earlier ledgers. A gap disqualifies the block for the primary evaluation.

| Block | Role | UTC scoring start | Warm-up anchor | First scored ledger | Last scored ledger |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | Train | 2026-09-23 00:00 | 107169483 | 107169638 | 107170104 |
| 2 | Train | 2026-09-26 16:00 | 107251397 | 107251550 | 107252009 |
| 3 | Train | 2026-09-30 08:00 | 107332790 | 107332947 | 107333414 |
| 4 | Train | 2026-10-03 00:00 | 107392255 | 107392411 | 107392876 |
| 5 | Development | 2026-10-07 16:00 | 107497270 | 107497426 | 107497889 |
| 6 | Development | 2026-10-10 08:00 | 107556893 | 107557050 | 107557515 |
| 7 | Calibration | 2026-10-14 00:00 | 107638745 | 107638899 | 107639358 |
| 8 | Calibration | 2026-10-17 16:00 | 107720359 | 107720516 | 107720978 |
| 9 | Test | 2026-10-21 08:00 | 107801237 | 107801389 | 107801846 |
| 10 | Test | 2026-10-24 00:00 | 107859611 | 107859766 | 107860224 |
| 11 | Test | 2026-10-28 16:00 | 107961334 | 107961483 | 107961934 |
| 12 | Test | 2026-10-31 08:00 | 108018907 | 108019049 | 108019515 |

[The frozen manifest](../protocols/phase3b-blocks.json) records advertised history on both operators and the validated headers bracketing each boundary. Ripple's Clio time lookup supplied candidate indexes. Adjacent numeric ledger requests verified the official close-time boundaries. Freeze completed at 2026-11-08 03:37:06 UTC in 110 attempts, 82,143 decoded bytes and 110.24 seconds, after two exploratory coverage probes. Each acquired block separately checks its first, middle and last hashes with InFTF. [XRPL history](https://xrpl.org/docs/concepts/networks-and-servers/ledger-history), [Clio time lookup](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/clio-methods/ledger_index), [ledger close times](https://xrpl.org/docs/concepts/ledgers/ledger-close-times)

Frozen manifest SHA-256 is `9f483936a72cb36fa4fe08cf61b694aaea7ae417af6fa607be65e766bfa44e24`.

The first two blocks contain 1,235 ledgers and cost at least 1,241 acquisition attempts including cross-checks. All blocks contain 7,393 ledgers, implying at least 7,429 acquisition attempts. At the pilot's per-ledger averages, the first stage would use about 0.62 GiB decoded, 0.14 GiB compressed and 35 minutes. The complete plan would use about 3.70 GiB decoded, 0.85 GiB compressed and 3.5 hours before retries. These estimates depend on the transaction mix and endpoint load.

Fit only on the training weeks, make model choices in development, set operating cutoffs in calibration, and preserve the final two weeks for evaluation. Recurring accounts or directed edges can cross these calendar boundaries and induce dependence. Keep identifiers in the local metadata and report overlap as a descriptive stratum. Fixed calendar slots may alias scheduled traffic and miss other days and market conditions. The calendar and frozen ledger ranges stay fixed when later results are observed.

## Acquisition and recovery

Run from the repository root with the project CPython. The expansion CLI stages only blocks 1 and 2.

```powershell
$env:PYTHONPATH = 'src'
& $python -B -m xrpl_anomaly.expansion acquire
$env:MPLCONFIGDIR = "$PWD/artifacts/mpl-config"
& $plotPython -B -m xrpl_anomaly.expansion_report --figures
```

Each attempt runs in a disposable child process with a monotonic deadline in the parent. The parent terminates and reaps a stalled child, then applies the retry policy. The deadline covers opening the response and reading the body. OS process creation and termination can add small scheduling overhead. The child has an 8 MiB decoded-response limit with identity encoding. The parent reserves the full remaining allowance before dispatch, settles successful byte reports, and keeps the reservation when completion or byte counts are uncertain. Network and worker failures can therefore consume budget without committing any data.

The acquisition ran from an unborn Git branch. Launch source hashes were `c68e6d5245d247aa84a1f66b9aa20aba919e65e4f8d0e6e5ef0fc989e7d33f90` for `expansion.py`, `2901ea7ca8bc3395d03bb8d23a0439238e87f85a651db2c061a43b2e35347ae5` for `pilot.py`, and `e363c276fbc7b5149040b1b3d92467c6d4d3b05cddcc91b8aeb3efe45565b5e0` for `http_worker.py`. Future runs create temporary files in ignored `artifacts/http-spool` instead of the repository root.

A Windows file lock serializes the stage. The stage checkpoint persists the attempt count, conservative byte charge and time budget across both blocks and resumes. An unclean stop retains the pending reservation and charges downtime past the reserved deadline conservatively. The stage caps are 1,500 attempts, 1 GiB charged and one hour. Incomplete, corrupt, unvalidated or conflicting records cannot enter the verified manifest. Resume verifies cached body digests and skips the previously committed prefix. SQLite and feature replay run offline into separate Phase 3B paths.

## Initial training results

| Block | Attempts | Acquisition seconds | Decoded bytes | Gzip cache bytes | Validated ledgers | Eligible payments including warm-up | Complete scoring-window feature rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 625 | 826.36 | 185,361,734 | 38,653,254 | 622 | 8,174 | 5,036 |
| 2 | 617 | 1,081.69 | 251,977,953 | 55,625,519 | 613 | 9,135 | 6,697 |
| Stage | 1,242 | 1,908.08 | 437,339,687 | 94,278,773 | 1,235 | 17,309 | 11,733 |

The stage used one retry and charged 445,728,295 bytes, including an 8 MiB reserve for the failed attempt. All six secondary hashes matched. Coverage had zero gaps. All adjacent parents and strictly increasing close times matched, all transaction arrays passed hash and position validation, and the eligible rows and exclusion counts reconciled to 159,954 observed transactions. Both SQLite databases passed integrity and foreign-key checks and retained integer drops. The checks validate the returned transaction arrays and independently compare selected header hashes. The transaction-set root was not recomputed.

| Scoring-window recurrence | Block 1 | Block 2 |
| --- | ---: | ---: |
| Distinct accounts | 2,645 | 2,002 |
| Repeat senders | 247 | 382 |
| Repeat receivers | 722 | 1,035 |
| Distinct directed edges | 4,008 | 4,152 |
| Directed edges repeated within block | 502 | 903 |
| Sender seen in the preceding 10 minutes | 87.3% | 89.9% |
| Receiver seen in the preceding 10 minutes | 58.0% | 84.2% |
| Directed edge seen in the preceding 10 minutes | 19.0% | 38.9% |

The two scoring windows shared 476 accounts and 372 directed edges. Cross-block overlap is descriptive. Each replay used only its own warm-up and prior ledgers. On the second offline pass, cache verification and idempotent SQLite ingestion took 4.30 and 5.60 seconds, and block feature replays took about 0.42 seconds each. The two passes reproduced both feature digests and both PNGs. The original 256-ledger cache matched its recorded snapshot hash. The five original and five Phase 3A PNGs matched their recorded hashes.

The local outputs are under `reports/generated/phase3b-training`. The summary records block digests, validation checks, run costs, environment and recurrence. The figures show pilot sparsity and calibration ties, and account and edge recurrence in the two new blocks. All 22 offline tests passed using the README command on CPython 3.14.7 with the existing plotting environment and local loopback access.

At the measured rate, the remaining 6,158 ledgers would require at least 6,188 requests, about 2.0 GiB decoded and 2.6 hours serialized. Later blocks can differ in transaction volume, endpoint load and response size, so retain budget and coverage checks. Two training periods also provide limited evidence about account dependence and seasonal variation. For Phase 3B.2, authorize the two remaining training and two development blocks first, verify perturbation eligibility on development, and freeze the comparison protocol before acquiring calibration and final test data.
