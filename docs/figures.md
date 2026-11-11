# Scientific figure plan

Use Matplotlib for report figures and NetworkX for directed graph construction and layout. Use Plotly only if interactivity answers a specific analytical question. This plan specifies future figures and their inputs.

| Phase | Figure and data source | Interpretation |
| --- | --- | --- |
| 1 | Define figure IDs, input tables, units, and caption requirements. | Planning deliverable. |
| 2 | Plot payment counts and delivered XRP volume by UTC interval from normalized payments and coverage manifest. Show gaps distinctly from observed zero. Include selected account bursts or rolling activity summaries if the snapshot supports them. | Descriptive activity within the captured eligible subset. |
| 2 | Plot amount and fee distributions, temporal counts, and selected feature associations from the feature table. Label units, log transforms, and sample sizes. | Describe heavy tails, sparsity, and redundancy. |
| 2 | Draw a directed payment subgraph from a prespecified UTC slice and bounded deterministic node selection. Size nodes by eligible incident count and scale edge width by transfer count. Save the selection and layout seed. | Illustrates topology in a documented subset. Address labels can be omitted. |
| 3 | Plot synthetic average precision and recall at budget by perturbation family, strength, and feature ablation. Show prevalence and block-based intervals when the data support them. | Measures ranking and alert selection under the injection design. A matched original stream shows how those identities ranked before the edits. |
| 3 | Plot real score distributions and alert rates across temporal blocks, plus same-row rank agreement or top-k overlap across models and seeds. Include controlled noise and hyperparameter sensitivity if run. | Shows ranking and threshold stability without real-label performance claims. |
| 3 | Plot training time, memory, and inference cost against synthetic detection metrics. If neural modeling proceeds, plot training and development reconstruction losses. Add a small directed case illustration if the selected structure helps explain a graph feature. | Documents operational trade-offs and convergence. |
| 4 | Plot coverage, exclusions, cold starts, processing time, feature and score shifts, and alert or latency changes over replay time. Use real reference windows and clearly labeled synthetic drift scenarios. | Shows measurable changes in pipeline or score behavior. |
| 5 | Regenerate selected figures from audited artifacts and link them from the README and report. | Connects each claim to a traceable run. |

Generate figures through a version-controlled script with explicit input manifest or run ID, parameters, and output path. Save figure metadata with the input digests, command, code revision, plot library versions, bins or layout parameters, and applicable seeds. Record the exact invocation once each plot entry point exists. Write outputs under `reports/generated/` and select figures for inclusion after review.

Captions identify the source, date range, coverage, aggregation, units, sample size, and what the visualization supports. Distinguish observed and synthetic data in labels as well as captions. Test plotting-data preparation for boundary times, missing intervals, counts, and units. Use a small offline rendering smoke test once plotting is implemented.

## Phase 4D figures

The [Phase 4D reproduction commands](phases/phase4d.md#reproduce-offline) write these PNGs and `figure-metadata.json` to the ignored run directory.

| Figure | Source and interpretation |
| --- | --- |
| `historical-monitoring.png` | Eighteen clean ten-minute windows from blocks 7–12. Fee, prior-edge count and score distances use block 7 as the reference. The lower panel shows frozen alert rates. |
| `shift-recovery.png` | Three block 8 windows, with the intervention shaded and its same-row historical counterpart shown separately. The panels show fee drift, score quantiles and frozen alert rates. |


## Phase 5 reproduction and interpretation

The [Phase 5 audit commands](phases/phase5-audit.md#figure-audit) record the historical rendering checks. The [Phase B corrections and commands](phases/phase-b-figures.md) reproduce the four corrected figures from the same frozen tables and monitoring report in a fresh directory. The PNGs use aggregated observations and their metadata identifies the inputs.

| Output | How to read it |
| --- | --- |
| `ablation-and-blocks.png` | Point summaries of synthetic AP for feature ablations and four held-out blocks. The two panels have different vertical ranges. Block 12 dominates the forest's mean advantage. Use the [recall and paired-block results](phases/phase3b3.md#synthetic-test-comparison) alongside AP. |
| [`calibration.png`](images/calibration.png) | Strict empirical P(score > x) on a log scale, with tied scores jumping together and zero tails explicitly marked at the axis base. The line marks the score component only. The [calibration table](phases/phase3b3.md#clean-calibration-and-operating-behavior) gives exact tie and alert counts. |
| `historical-monitoring.png` | Lines connect unchanged windows within blocks. Shaded gaps give the unsampled duration in days and are compressed. Block 7 overlaps its reference. The block 7 alert rate and pooled 1% target have separate labeled lines. The 0.20 ECDF guide is descriptive. |
| `shift-recovery.png` | Both series show score medians and capped p05–p95 ranges; coincident quantiles are annotated. The shaded middle window uses a synthetic fee coordinate. The final stage restores original input from the next unchanged window. The alert panel includes the 100% response. Read the [numeric table](phases/phase4d.md#historical-behavior-and-controlled-shift) for low alert rates. |
| [`detector-scores.png`](images/detector-scores.png) | Exact development score pairs retain their coordinates. A shared logarithmic color scale encodes the number of payments at each pair. The panels identify both row counts and distinct pair counts. |

The AP figures show the original comparisons on edited streams. The [Phase C supplement](phases/phase-c-interpretation.md) compares AP on the same identities before editing and explains why the selected forest configurations do not isolate a graph-feature effect. The monitoring panels show empirical distance and transaction alert rates from a prepared-feature replay. The final unchanged window describes restored input to a stateless scorer.

## Existing figure inventory

The table groups distinct PNG filenames by generation stage. Audit repeats and tracking copies reuse the same filenames. The README gallery uses the original held-out AP bars, the revised pilot network and two monitoring figures corrected in Phase B. Corrected calibration and development score panels are linked above.

| Figure | Purpose | Generation source |
| --- | --- | --- |
| `payment-counts.png`, `xrp-volume.png` | Eligible payment counts and delivered XRP by UTC minute | Phase 2 pilot coverage and normalized payments via [`analysis.py`](../src/xrpl_anomaly/analysis.py) and [`plots.py`](../src/xrpl_anomaly/plots.py). Phase 3A also replayed the pilot. |
| `amount-fee.png`, `history-features.png` | Amount and fee distributions and eligible prior activity | Same Phase 2 and 3A plotting path |
| [`directed-network.png`](images/directed-network.png) | Unlabeled directed pilot subgraph | Original Phase 2 pilot, ledgers 108187347–108187602, snapshot prefix `a90ec409114ee`. The fixed layout in [`plots.py`](../src/xrpl_anomaly/plots.py) separates the two senders with five shared recipients. The two isolates appear at lower right. |
| `pilot-sparsity-and-ties.png`, `training-recurrence.png` | Pilot sparsity and score ties, plus training-block graph recurrence | [Phase 3B.1 training and pilot summaries](phases/phase3b1.md) |
| `block-comparison.png`, `detector-scores.png`, `feature-ablation.png`, `feature-distributions.png`, `graph-recurrence.png`, `sparse-features.png`, `synthetic-severity.png` | Training and development comparisons, observed feature and score behavior, and controlled changes | [Phase 3B.2 development results](phases/phase3b2.md) via [`development_figures.py`](../src/xrpl_anomaly/development_figures.py) |
| [`ablation-and-blocks.png`](images/ablation-and-blocks.png), `synthetic-families.png` | Synthetic average precision by feature set, test block, or perturbation family and strength | Frozen Phase 3B.3 evaluation, clean scores and model metadata via [`heldout_figures.py`](../src/xrpl_anomaly/heldout_figures.py). The gallery uses the [Phase 5 audited copy](phases/phase5-audit.md#figure-audit). |
| `alerts-and-stability.png`, `calibration.png`, `performance-and-cost.png` | Historical alert and ranking behavior, calibration survival curves, and synthetic average precision versus model size | Same frozen Phase 3B.3 inputs and renderer |
| [`historical-monitoring.png`](images/historical-monitoring.png), [`shift-recovery.png`](images/shift-recovery.png) | Unchanged Mainnet window behavior and a separate paired synthetic intervention | Phase 4D baseline replay report via [`monitoring_figures.py`](../src/xrpl_anomaly/monitoring_figures.py). The gallery uses the [Phase B corrected renderings](phases/phase-b-figures.md). |
