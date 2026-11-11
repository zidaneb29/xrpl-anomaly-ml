# Phase B figure corrections

The independent audit at `418c6f7` identified four rendering problems. These corrections use the original frozen score tables, models and monitoring report. The public PNGs are listed in the [provenance manifest](../images/figure-provenance.json), which records their SHA-256 hashes, input hashes, renderer hashes and environment. The rendering source is identified by its working-tree digest because Phase A and B changes are awaiting review.

| Figure | Earlier rendering | Corrected rendering |
| --- | --- | --- |
| [Calibration](../images/calibration.png) | Descending ranks, midpoint steps and repeated score coordinates distorted empirical survival. | One right-continuous jump per distinct score gives P(score > x). Open circles at the axis base identify zero tails, which have no log coordinate. |
| [Fee override](../images/shift-recovery.png) | Only the scenario had score intervals. “Recovery” could imply state restoration. | Both series have capped p05–p95 intervals and median markers. The synthetic interval collapses to a labeled point at 69.98. The final stage is labeled “Original input restored.” |
| [Historical monitoring](../images/historical-monitoring.png) | Lines crossed unsampled multi-day gaps. The alert reference was unlabeled. | Lines stop at block boundaries, shaded gaps show their durations, and the axis states that gaps are compressed. Separate lines identify the block 7 rate and pooled calibration budget target. |
| [Development score pairs](../images/detector-scores.png) | Transparent points concealed the multiplicity of repeated score pairs. | Each exact coordinate pair appears once, with color giving its payment count on a shared logarithmic scale. |

The strict score tail excludes all observations tied at x. The actual frozen alert policy compares the complete score-and-digest key, so some cutoff ties can alert. For the baseline pooled calibration cutoff, 13 of 10,229 rows score strictly above the cutoff, 241 tie, and 89 of those ties alert. The actual calibration decision therefore selects 102 rows. The score-only survival curve and its vertical cutoff line must be read with the [calibration table](phase3b3.md#clean-calibration-and-operating-behavior).

The historical reference rate is 46/5,406 = 0.851%. The separate 1% line is the pooled calibration budget target. The achieved pooled calibration rate is 102/10,229 = 0.997%. The five unsampled intervals are 3 days 15 hours 30 minutes, 3 days 15 hours 30 minutes, 2 days 15 hours 30 minutes, 4 days 15 hours 30 minutes and 2 days 15 hours 30 minutes.

In the paired middle window, unchanged scores have p05 = 0.81, median = 12.36 and p95 = 48.37. The synthetic fee override has all three quantiles at 69.98. Its 2,030 rows include one whose original fee already equaled 100,000 drops, so 2,029 vectors change. The next window reuses original observations in a stateless scorer. This experiment describes an input perturbation and its removal.

Development block 5 contains 5,923 rows at 4,266 distinct score pairs, with a maximum multiplicity of 150. Block 6 contains 3,381 rows at 2,739 pairs, with a maximum of 147. Counts are aggregated only for identical pairs. Nearby distinct pairs can still overlap at finite image resolution, so the color scale describes exact-coordinate multiplicity.

## Reproduce the affected figures

Use the existing Windows plotting environment with Matplotlib 3.10.9 and the original local artifacts. Run from the repository root. The command creates a fresh directory and renders exactly the four affected experimental figures.

```powershell
$env:PYTHONPATH = 'src'
$env:MPLBACKEND = 'Agg'
$env:MPLCONFIGDIR = "$PWD/artifacts/mpl-config"
@'
import json
from pathlib import Path
from xrpl_anomaly.heldout_figures import render_calibration
from xrpl_anomaly.development_figures import render_detector_scores
from xrpl_anomaly.monitoring_figures import render
from xrpl_anomaly.monitoring_replay import sha256

root = Path('reports/generated/phase-b-figures-replay')
root.mkdir(exist_ok=False)
for name in ('heldout', 'development', 'monitoring'):
    (root / name).mkdir()
render_calibration(Path('reports/generated/phase3b3'), root / 'heldout')
render_detector_scores(Path('reports/generated/phase3b2'), root / 'development')
source = Path('reports/generated/phase4d-phase5-audit/monitoring.json')
render(json.loads(source.read_bytes()), root / 'monitoring', sha256(source))
'@ | .venv-phase2/Scripts/python.exe -B -
```

Each output directory contains figure metadata. The historical Phase 3B and Phase 4D directories and tracking copies retain their original outputs. Public copies under `docs/images/` use the four corrected renderings. The network and held-out AP bar PNGs retain their earlier hashes.

## Verification and review

Six regression tests in `tests/test_figure_semantics.py` check strict survival at and between tied scores, cutoff semantics, explicit zero-tail markers, preservation of exact score pairs and counts, line breaks at unsampled gaps, labeled alert references, both sets of score intervals, and coincident quantiles.

An independent calculation checked 34,848 empirical survival probabilities against the frozen calibration scores, including all observed scores, intervening midpoints and cutoffs. Direct counts separately checked each cutoff. Independent replay and sorted-score calculations matched all 18 window quantiles, 54 displayed ECDF distances and the synthetic score quantiles. Aggregated scatter coordinates and counts matched an independent identity join of the original score table.

The full offline suite ran 61 tests, with 59 passing and two Docker checks skipped because no local test image was configured. The four corrected PNGs were reviewed at full resolution and at 900 pixels wide as a README display approximation.

The focused review also covered the remaining pilot, training, development and held-out figures, including the two retained README PNGs. No additional clipping, legend occlusion or hidden graph structure requiring another rendering change was found. Development AP and recall charts retain their full 0–1 ranges, which compress small differences. The held-out ablation caption now states that forest subsample sizes differ between feature sets.

## Public reference changes

- `README.md` updates the monitoring captions, identifies both score intervals and restored input, clarifies forest ablation settings, and updates the image-directory description.
- `docs/figures.md` links the corrected calibration and development panels and describes current monitoring semantics.
- `docs/phases/phase5-audit.md` marks its byte-identical figure checks as historical and links this correction record.
- `docs/images/historical-monitoring.png` and `docs/images/shift-recovery.png` are replaced by corrected renderings.
- `docs/images/calibration.png`, `docs/images/detector-scores.png` and `docs/images/figure-provenance.json` are added for public inspection and provenance.

Phase A's six working-tree files retained their starting byte hashes. All 7,869 pre-existing files under `data/`, `reports/` and `artifacts/` retained their hashes. Original data, model packages, score tables, thresholds, experimental metrics and archived figures remain available for comparison. The local Phase B output directory contains the new renderings, metadata and independent-check summary.
