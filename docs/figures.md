# Scientific figure plan

Use Matplotlib for report figures and NetworkX for directed graph construction and layout. Use Plotly only if interactivity answers a specific analytical question. This plan specifies future figures and their inputs.

| Phase | Figure and data source | Interpretation |
| --- | --- | --- |
| 1 | Define figure IDs, input tables, units, and caption requirements. | Planning deliverable. |
| 2 | Plot payment counts and delivered XRP volume by UTC interval from normalized payments and coverage manifest. Show gaps distinctly from observed zero. Include selected account bursts or rolling activity summaries if the snapshot supports them. | Descriptive activity within the captured eligible subset. |
| 2 | Plot amount and fee distributions, temporal counts, and selected feature associations from the feature table. Label units, log transforms, and sample sizes. | Describe heavy tails, sparsity, and redundancy. |
| 2 | Draw a directed payment subgraph from a prespecified UTC slice and bounded deterministic node selection. Size nodes by eligible incident count and scale edge width by transfer count. Save the selection and layout seed. | Illustrates topology in a documented subset. Address labels can be omitted. |
| 3 | Plot synthetic average precision and recall at budget by perturbation family, strength, and feature ablation. Show prevalence and block-based intervals when the data support them. | Measures detection under the injection design. Any precision-recall curve uses explicit synthetic or independently verified labels. |
| 3 | Plot real score distributions and alert rates across temporal blocks, plus same-row rank agreement or top-k overlap across models and seeds. Include controlled noise and hyperparameter sensitivity if run. | Shows ranking and threshold stability without real-label performance claims. |
| 3 | Plot training time, memory, and inference cost against synthetic detection metrics. If neural modeling proceeds, plot training and development reconstruction losses. Add a small directed case illustration if the selected structure helps explain a graph feature. | Documents operational trade-offs and convergence. |
| 4 | Plot coverage, exclusions, cold starts, processing time, feature and score shifts, and alert or latency changes over replay time. Use real reference windows and clearly labeled synthetic drift scenarios. | Shows measurable changes in pipeline or score behavior. |
| 5 | Regenerate selected figures from audited artifacts and link them from the README and report. | Connects each claim to a traceable run. |

Generate figures through a version-controlled script with explicit input manifest or run ID, parameters, and output path. Save figure metadata with the input digests, command, code revision, plot library versions, bins or layout parameters, and applicable seeds. Record the exact invocation once each plot entry point exists. Write outputs under `reports/generated/` and select figures for inclusion after review.

Captions identify the source, date range, coverage, aggregation, units, sample size, and what the visualization supports. Distinguish observed and synthetic data in labels as well as captions. Test plotting-data preparation for boundary times, missing intervals, counts, and units. Use a small offline rendering smoke test once plotting is implemented.

## Phase 4D figures

The [Phase 4D reproduction commands](phase4d.md#reproduce-offline) write these PNGs and `figure-metadata.json` to the ignored run directory.

| Figure | Source and interpretation |
| --- | --- |
| `historical-monitoring.png` | Eighteen clean ten-minute windows from blocks 7–12. Fee, prior-edge count and score distances use block 7 as the reference. The lower panel shows frozen alert rates. |
| `shift-recovery.png` | Three block 8 windows, with the intervention shaded and its same-row historical counterpart shown separately. The panels show fee drift, score quantiles and frozen alert rates. |
