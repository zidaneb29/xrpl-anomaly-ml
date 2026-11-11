# Phase 3B.2 training and development comparison

## Data and resource envelope

The local Phase 3B.1 checkpoint is `415f565600f54f7396894c85e9488421efb0f0d6`. The Stage 3B.2 CLI uses the recorded SHA-256 of the frozen plan and acquires only blocks 3 through 6. It checks independent header hashes at the start, middle and end of each block. The previous 1,235 ledgers used 1,242 requests, 437,339,687 decoded bytes, 94,278,773 gzip bytes and 1,908 seconds. Scaling by the 2,490 ledgers in the four new ranges gives approximately 0.82 GiB decoded, 181 MiB compressed and 64 minutes. The hard stage ceilings are 3,000 attempts, 2 GiB conservatively charged decoded bytes, 512 MiB raw-cache storage including manifests, and 7,200 seconds of cumulative acquisition time. The worker retains the 8 MiB response limit and 20-second parent deadline. Offline databases and outputs are separate from the raw-cache storage budget.

Training uses the complete scoring windows in blocks 1 through 4. Blocks 5 and 6 are development. Every block starts with its own warm-up. The reporting CLI verifies all six caches and ingests them into new SQLite files. Blocks with gaps, corrupt cache entries, broken ancestry, mismatched frozen boundaries, or missing independent checks cannot enter the comparison. Exact drop values and transaction positions remain in SQLite. The feature CSV includes all 21 features. Transaction identity and ledger metadata support joins and ranking only.

## Detectors and selection

Use static (2), static plus temporal (14), and full (21) columns. The robust baseline retains the Phase 3A MAD/IQR rules and reports omitted columns. Isolation Forest uses the existing log-transformed and count features directly in a single-threaded, standard-library implementation. It omits training constants and retains varying sparse columns. At each node it draws a varying feature uniformly and splits uniformly between observed extrema. It grows 64 depth-limited trees on distinct-row subsamples, with maximum depth `ceil(log2(m))`. The score is `2^(-mean adjusted path / c(m))`, where a leaf of size `n` contributes `c(n) = 2 H(n) - 2` for `n >= 1`. The isolated observation convention is `c(1) = 0`. [Liu, Ting and Zhou, Isolation Forest](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf)

Compare subsample sizes 128 and 256 under seeds 7 and 29, separately within each feature group. Select the size with the highest macro mean tie-grouped average precision over available development block, family, severity, and seed cells. Break exact ties in favor of the smaller size. Report both model seeds, which are repeated runs on the same observations. The development comparison supports model selection and is subject to selection optimism.

## Synthetic interventions

Draw from original prior-ledger context and use scoring-window payments only. Shuffle sorted eligible sender identities using seeds 17 and 43. Select up to one sender unit per 100 scoring rows (minimum one if any eligible sender exists). Choose events within those senders by the same seeded sampling at each severity. Each family and severity gets its own replay. The original stream stays immutable and supplies the same-identity matched controls.

- **Amount.** Multiply or integer-divide the delivered amount by 2 or 4. The original and both counterfactual amounts must fit within the pooled training scoring-window 1st to 99th empirical order statistics. Choose upward direction when feasible, otherwise downward. Keep sender, receiver, fee, ledger and position fixed. This tests sensitivity to a moderate log-amount shift within observed training support.
- **Burst.** For a sender with a prior outgoing payment 15 to 120 seconds earlier, shorten that gap toward half or a quarter. Round to the first observed ledger at or after the target time. Require distinct eligible target ledgers earlier than the original and within the scoring window. Append the moved payment to the target's eligible payment order. Preserve amount, fee, endpoints and identity. The feature history sees the move only after the target closes. The intervention compresses the local gap between two sender payments.
- **Concentration.** Require the original receiver in the prior 600-second outgoing history. Redirect one or three events from the same sender to a common alternative already seen at least twice and more frequently than the original receiver in each event's original prior window. Select the modal alternative deterministically, with a lexical tie-break. Require three candidate events at both levels so severity shares the sender and event selection.

Rebuild chronological features from the modified event stream and record modified identities and other identities whose feature vectors changed. Keep these downstream affected rows in the full-stream ranking and label them as non-intervened. Report this spillover separately. Report average precision, prevalence, recall at the fixed 1% ranking budget, bounds over cutoff ties, and matched score win rate and mean shift against the unmodified same-identity controls. Also report rank agreement, top-budget overlap, and median cold-start scores on unmodified development rows. The score tie-break is shared with Phase 3B.1. Calibration sets a deployment cutoff in a later approved phase.

The interventions approximate observation-level changes and omit ledger execution constraints such as sequence numbers, balance feasibility, and destination-specific obligations. Prior counts, a narrowed amount range, and sender recurrence affect eligibility and create a selected population. Moved events can alter other histories, and the higher concentration level changes label prevalence. Report prevalence with average precision and interpret differences across severity accordingly. The two development blocks support descriptive comparisons and have recurring accounts. Synthetic metrics measure sensitivity to these interventions. Real payment anomaly labels are unknown.

## Reproduction

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
& $python -B -m xrpl_anomaly.expansion acquire-next
$env:MPLCONFIGDIR = "$PWD/artifacts/mpl-config"
& $plotPython -B -m xrpl_anomaly.development --figures
```

Run the full offline suite with the README command and the existing pinned plotting environment. The local results are under `reports/generated/phase3b2`, with acquisition and block feasibility in `summary.json`, full detector and intervention results in `evaluation.json`, and figure inputs and output hashes in `figure-metadata.json`. Timings are recorded separately from deterministic metrics. The local output contains transaction identifiers.

## Observed acquisition and coverage

| Block | Role | Ledgers | Examined | Eligible with warm-up | Scored | Decoded bytes | Acquisition seconds |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Train | 622 | 63,010 | 8,174 | 5,036 | 185,361,734 | 826.36 |
| 2 | Train | 613 | 96,944 | 9,135 | 6,697 | 251,977,953 | 1,081.69 |
| 3 | Train | 625 | 50,930 | 7,749 | 6,802 | 153,773,694 | 753.95 |
| 4 | Train | 622 | 68,028 | 9,995 | 8,306 | 191,449,034 | 2,777.12 |
| 5 | Development | 620 | 62,904 | 7,641 | 5,923 | 185,460,681 | 790.58 |
| 6 | Development | 623 | 42,654 | 4,361 | 3,381 | 131,759,042 | 733.22 |

| Block | Other transaction type | Failed payment | Token payment | Routed or partial | Sender seen | Receiver seen | Prior edge | Repeated edges in block |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 32,906 | 8,822 | 12,651 | 457 | 87.3% | 58.0% | 19.0% | 502 |
| 2 | 49,396 | 17,216 | 20,567 | 630 | 89.9% | 84.2% | 38.9% | 903 |
| 3 | 28,564 | 5,272 | 8,784 | 561 | 89.8% | 58.6% | 25.3% | 507 |
| 4 | 38,230 | 2,863 | 16,686 | 254 | 93.4% | 65.7% | 32.7% | 791 |
| 5 | 39,319 | 3,212 | 12,494 | 238 | 88.4% | 77.1% | 28.4% | 829 |
| 6 | 26,620 | 1,568 | 9,016 | 1,089 | 86.3% | 77.2% | 27.3% | 514 |

All six blocks had zero gaps, malformed ledger arrays and invalid-account or invalid-amount exclusions. The six new SQLite files passed integrity and foreign-key checks. The four-block stage consumed 2,503 attempts, one retry, 662,442,451 observed decoded bytes, 670,831,059 charged bytes, 140,695,129 bytes of raw-cache storage including manifests, and 5,054.92 seconds. The six replay databases used 13,320,192 bytes. The evaluation and figures used about 28 MB. The first end-to-end offline evaluation took 97.31 seconds with the existing CPython 3.14 and Matplotlib environment.

Acquisition launch SHA-256 values were `4458a45d2f7da02c06868b44bea493c3e027473ee5aef0110841051b0b44141c` for `expansion.py`, `bb8881490c2e84ba3e8f0016d6ac74a2f998a0682f8db5208682037ac8f52eaf` for `pilot.py`, and `e363c276fbc7b5149040b1b3d92467c6d4d3b05cddcc91b8aeb3efe45565b5e0` for `http_worker.py`.

There were 26,841 training rows and 9,304 development rows. In development, 87.6% of senders and 77.2% of receivers had prior 600-second activity. At least one endpoint had no observed prior activity on 28.9% of rows. Directed edges had prior history on 29.8% of training rows and 28.0% of development rows. This coverage supports a directed-graph ablation, with most pairs still unseen in any given lookback. The two development blocks had 28 and 14 concentration-eligible senders, below the respective targets of 59 and 33. Results for this family are particularly sensitive to the choice of active senders and the downstream effects of redirects.

## Observed development results

| Feature set | Selected forest subsample | Baseline macro AP | Forest macro AP | Baseline recall at 1% | Forest recall at 1% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Static | 256 | 0.0134 | 0.0158 | 0.94% | 1.22% |
| Static + temporal | 128 | 0.0146 | 0.0164 | 0.94% | 1.43% |
| Full | 256 | 0.0162 | 0.0279 | 0.94% | 3.21% |

| Full feature set intervention | Mean prevalence | Baseline AP | Forest AP | Baseline recall at 1% | Forest recall at 1% |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amount ×/÷ 2 | 0.99% | 0.0206 | 0.0232 | 0.76% | 2.86% |
| Amount ×/÷ 4 | 0.99% | 0.0206 | 0.0232 | 0.76% | 2.65% |
| Burst gap ÷ 2 | 0.99% | 0.0190 | 0.0303 | 1.61% | 0.38% |
| Burst gap ÷ 4 | 0.99% | 0.0194 | 0.0734 | 1.61% | 12.03% |
| Concentration, one redirect | 0.44% | 0.0045 | 0.0047 | 0.00% | 0.45% |
| Concentration, three redirects | 1.33% | 0.0134 | 0.0126 | 0.89% | 0.89% |

The full forest's largest edited-stream AP advantage came from the stronger burst. Its matched score win statistic was 36.7%, with increases counted as one and ties as half. Ranking and score changes answer different questions because eligibility selects payments with particular histories and replay also changes the other ranked observations. Recipient redirects shifted matched forest scores upwards more often, while edited-stream AP and recall were low in those cells. At the higher level, 773 to 2,041 unmodified rows per block and seed had changed feature vectors. The [Phase C supplement](phase-c-interpretation.md#recipient-redirects-and-concentration) traces which history coordinates changed and explains the limits of attributing the response to sender concentration.

The robust model omitted five varying features whose fitted MAD and IQR were both zero. The forest retained all 21. On original development rows the full models' Spearman correlations ranged from 0.672 to 0.763. Their top-ranked sets shared 1 to 4 of 59 rows in the first development block and 3 to 5 of 33 in the second. The full robust model's median scores were about 21 to 22 on rows with an unseen endpoint and 3 to 4 on the remaining rows. Full forest scoring took about 0.61 seconds for 9,304 rows, versus 0.09 seconds for the full robust baseline in the first run.

The seven figures cover block volumes, feature distributions, sparsity, recurrence, score agreement, synthetic severity and ablations. The figure metadata records their names and hashes. Two offline runs reproduced all 11 checked artifact hashes, including the feature and score tables, evaluation JSON, figure metadata and seven PNGs. All 28 offline tests passed, including loopback deadline recovery and fixture-based multi-block ingestion. The historical checks verified 1,491 cached bodies, four SQLite databases and 12 figures against their recorded hashes where available.

Keep the selected classical configurations and protocol fixed for the next approved milestone. Acquire calibration and final-test data within a fresh resource envelope. Set the 1% empirical cutoff on calibration and evaluate it unchanged on the final blocks, with per-block results and cold-start and tie summaries. Revisit the concentration intervention and neural modeling only in a separately approved experiment. Current results come from synthetic development labels and cannot estimate real fraud detection performance.
