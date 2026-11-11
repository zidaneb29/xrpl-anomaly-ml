# Phase C scientific interpretation supplement

This post hoc analysis of the frozen Phase 3B.3 comparison uses the working tree based on `418c6f7`. It reproduces the existing edits on copies of the held-out streams and scores them with the existing fits. The [original evaluation tables](phase3b3.md#synthetic-test-comparison) retain their original metrics, alert policies and weighting.

## Matched original and edited rankings

For each of the 48 block, intervention type, severity and intervention seed combinations, label the same directly edited payment identities in both streams. The original stream contains their unmodified scores. The edited stream contains their edited scores, the scores of other rows whose features changed through replay, and the remaining original scores. Both rankings use the full block population, so prevalence is identical within a pair. “Original” means unmodified. The selected identities and the rest of the population have no verified fraud labels.

AP groups equal scores at one threshold. Independently, for each positive identity with score s, compute the fraction of positives among all rows scoring at least s and average these fractions over the positives. This gives the same AP with ties included together. The paired score win statistic averages 1 for increases, 0.5 for ties and 0 for decreases. A row's rank percentile is the fraction scoring below it plus half the fraction tied with it. Rank change is the edited minus original percentile in percentage points. Positive change means a higher relative position within the full stream. Raw score changes have different units for the robust and forest models.

Each table gives equal weight to blocks. Within a block, each available intervention type and severity and its two seeds receive equal weight. Each forest fit is shown separately. The original forest comparison averages seeds 7 and 29. Repeated identities, intervention seeds and forest fits do not increase the number of independent blocks.

| Fit | Original AP | Edited AP | Change in AP | Score win | Mean score change | Mean rank change (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline static | 0.009952 | 0.010018 | +0.000066 | 57.33% | +0.035210 | +0.335 |
| Baseline temporal | 0.011210 | 0.011208 | −0.000002 | 45.91% | +0.074971 | +0.176 |
| Baseline full | 0.013545 | 0.013536 | −0.000009 | 53.73% | +0.205639 | +0.602 |
| Forest static, seed 7 | 0.012584 | 0.013181 | +0.000597 | 54.15% | +0.001971 | +0.814 |
| Forest static, seed 29 | 0.012686 | 0.013174 | +0.000489 | 50.40% | +0.001083 | +0.312 |
| Forest temporal, seed 7 | 0.014994 | 0.014365 | −0.000628 | 50.49% | +0.000641 | +0.536 |
| Forest temporal, seed 29 | 0.015463 | 0.014861 | −0.000602 | 47.73% | −0.000673 | −0.001 |
| Forest full, seed 7 | 0.015131 | 0.014184 | −0.000947 | 53.04% | +0.004400 | +1.815 |
| Forest full, seed 29 | 0.016651 | 0.017553 | +0.000903 | 54.36% | +0.004336 | +1.838 |

The full forest averaged 0.015891 original AP and 0.015869 edited AP. The forest-minus-baseline gap was **+0.002346 on original streams** and **+0.002333 on edited streams**, a difference of −0.000013. The gap was already present for the selected identities before editing. This comparison of two aggregate gaps is descriptive. Seed 7 lost AP and seed 29 gained AP, while both raised the mean rank percentile of selected rows. AP weights positions near the top differently from mean rank, and spillover changes the competing scores as well. The two gaps therefore capture only one aspect of the response to the edits.

| Test block | Baseline full AP, original → edited | Forest full seed 7 | Forest full seed 29 | Forest mean minus baseline, original → edited |
| --- | ---: | ---: | ---: | ---: |
| 9 | 0.009670 → 0.009584 | 0.008118 → 0.008174 | 0.009043 → 0.009424 | −0.001090 → −0.000784 |
| 10 | 0.017163 → 0.017169 | 0.014925 → 0.015105 | 0.016030 → 0.016420 | −0.001686 → −0.001406 |
| 11 | 0.008488 → 0.008498 | 0.007219 → 0.007250 | 0.008047 → 0.008066 | −0.000856 → −0.000840 |
| 12 | 0.018857 → 0.018893 | 0.030262 → 0.026208 | 0.033484 → 0.036304 | +0.013016 → +0.012363 |

Block 12 accounts for the mean forest advantage both before and after editing. The baseline retains higher published recall at both the fixed rank budget and the frozen calibration cutoff. These operating comparisons, together with the measured scoring cost, support its role as the reference for the study.

| Intervention | Baseline full AP, original → edited | Forest full seed 7 | Forest full seed 29 |
| --- | ---: | ---: | ---: |
| Amount ×/÷ 2 | 0.017159 → 0.017159 | 0.021311 → 0.021444 | 0.023761 → 0.028646 |
| Amount ×/÷ 4 | 0.017159 → 0.017159 | 0.021311 → 0.021851 | 0.023761 → 0.029624 |
| Burst gap ÷ 2 | 0.017157 → 0.017089 | 0.019960 → 0.016108 | 0.021457 → 0.017835 |
| Burst gap ÷ 4 | 0.017157 → 0.016900 | 0.019960 → 0.015622 | 0.021457 → 0.017421 |
| One recipient redirect | 0.002917 → 0.002986 | 0.002221 → 0.002690 | 0.002581 → 0.003343 |
| Three recipient redirects | 0.009719 → 0.009921 | 0.006024 → 0.007391 | 0.006888 → 0.008450 |

| Intervention | Baseline full win / rank change | Forest full seed 7 win / rank change | Forest full seed 29 win / rank change |
| --- | ---: | ---: | ---: |
| Amount ×/÷ 2 | 50.85% / +0.003 pp | 63.12% / +0.316 pp | 58.14% / +0.176 pp |
| Amount ×/÷ 4 | 50.85% / +0.006 pp | 70.68% / +0.642 pp | 63.56% / +0.392 pp |
| Burst gap ÷ 2 | 48.52% / +0.230 pp | 25.14% / −1.302 pp | 23.39% / −1.246 pp |
| Burst gap ÷ 4 | 48.04% / −0.042 pp | 20.95% / −2.196 pp | 23.87% / −1.833 pp |
| One recipient redirect | 62.40% / +1.932 pp | 62.59% / +6.942 pp | 81.54% / +7.419 pp |
| Three recipient redirects | 61.69% / +1.485 pp | 75.75% / +6.490 pp | 75.63% / +6.119 pp |

In these averages, both full forests gained AP on the matched amount and recipient edits and lost AP on the matched burst edits. These comparisons use each intervention's own original identities. Severity comparisons for redirects involve different positive counts. The values describe ranking changes for these four held-out blocks, with dependencies between accounts and scenarios.

## Feature configurations and graph inputs

The held-out forests used 64 trees per fit and the same two seeds, with development-selected subsample sizes of **256 static, 128 temporal, and 256 full**. The temporal-to-full comparison changes the graph inputs and subsample size. The size change also changes the depth limit from 7 to 8 and the path-length normalization. The static and full configurations use the same size, but differ in both temporal and graph inputs. The published held-out comparisons therefore establish how those selected configurations performed on the frozen ranking task.

The frozen development evaluation includes temporal and full forests at both sizes. Re-averaging its original edited-stream AP records at each fixed size gives the following narrower development result. Each cell averages the same 48 records across two blocks, two model seeds, six intervention settings and two intervention seeds.

| Subsample size | Temporal forest AP | Full forest AP | Full minus temporal |
| ---: | ---: | ---: | ---: |
| 128 | 0.016352 | 0.017845 | +0.001492 |
| 256 | 0.014970 | 0.027915 | +0.012945 |

The full set had higher mean edited-stream AP at each fixed size in development. Those blocks also supported model selection, so the result is descriptive development evidence. A held-out estimate of the graph increment for a fixed forest size is unavailable.

The robust baseline provides a different comparison. The same fitted scale and center are retained for every shared active feature. It uses 2 static, 11 static-plus-temporal, and 16 full active columns after dispersion filtering. Five active graph coordinates join the temporal score in the full fit. The published edited-stream AP increases across those nested configurations, while recall under both reported alert rules stays the same. The full baseline's matched AP change is −0.000009. Thus the higher raw AP with graph features does not establish increased sensitivity to the intervention effects.

## Recipient redirects and concentration

The edit changes only the recipient of selected payments, with amount, fee, sender, close time and position preserved. For the edited row, receiver features query a different account's earlier history, and prior directed-edge count queries the sender's earlier edge to that recipient. The sender's outgoing concentration is computed from strictly earlier ledgers. The row's own redirect cannot change that feature on the same row. Earlier redirects can change it for a later edited row or an unedited payment. Redirects can also change the earlier incoming history of accounts that appear as senders or receivers later.

Across the eight block and seed combinations per severity, every directly edited row had higher prior-edge count and changed receiver incoming drops. At the one-redirect level, receiver incoming count changed for 67 of 68 edited occurrences and receiver recency changed for 64. At the three-redirect level the corresponding counts were 199 and 183 of 204. Sender outgoing count and amount remained the same. The counts below are row occurrences across scenarios and include repeated identities.

| Redirects per selected sender | Cohort | Occurrences | Sender concentration increased | Decreased | Equal |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | Direct edit | 68 | 0 | 0 | 68 |
| 1 | Unedited with feature spillover | 2,027 | 1,031 | 191 | 805 |
| 3 | Direct edit | 204 | 111 | 0 | 93 |
| 3 | Unedited with feature spillover | 3,150 | 1,630 | 116 | 1,404 |

Independent scans of the raw normalized event sequences checked sender concentration, prior-edge count and receiver incoming drops against the replay for all 5,449 occurrences. Spillover begins after an edited ledger, and a subsequent window can contain a different mix of edges as observations expire.

The forest scores and ranks generally responded upward for the redirected identities, even at the level where the sender concentration coordinate never changed for a directly edited row. The published forest recall for both redirect levels is zero under both alert policies. These results establish a response to a composite recipient and history edit under the selected scenarios. They leave the contribution of the concentration coordinate and the sensitivity to concentration changes in isolation unresolved.

## Prepared fee override and historical crossings

The block 8 comparison sets the prepared fee coordinate to `log1p(100000)` on 2,030 vectors, with 2,029 values actually changing. All other features and identities are held fixed. The same original rows are the paired comparison. This is a controlled prepared-feature shift with the existing scorer and cutoff.

| Fit | Middle-window score distance, original → override | Middle-window frozen alerts, original → override | Score distance ≥0.20 on original block 8 windows | Score distance ≥0.20 on original final-test windows |
| --- | ---: | ---: | ---: | ---: |
| Baseline full | 0.190 → 1.000 | 16 → 2,030 | 0/3 | 10/12 |
| Forest full, seed 7 | 0.220 → 0.278 | 4 → 29 | 3/3 | 10/12 |
| Forest full, seed 29 | 0.256 → 0.242 | 6 → 19 | 3/3 | 11/12 |

For seed 29, the override increased the number of transaction alerts while score distance to block 7 fell. These statistics measure different properties. Distance describes a distribution relative to a reference, while frozen alerts count individual transactions selected by the score-and-digest rule. The original final-test window alert rates ranged from 0.66% to 5.43% for the baseline, 0.04% to 1.31% for forest seed 7 and 0.13% to 7.28% for seed 29. At least one baseline feature crossed the guide in all 12 original final-test windows. The guide describes these sampled windows, whose incident status is unknown.

The final stage directly supplies the next original window to a stateless scorer. Its measurements describe that subsequent window. The paired comparison within the middle window isolates the effect of overriding the fee coordinate. Automated recovery, incident response performance and real-fraud detection require separate evidence. [Original monitoring report](phase4d.md#historical-behavior-and-controlled-shift)

## Reproduce and verify the supplement

Run the [supplement module](../../src/xrpl_anomaly/audit_supplement.py) from the repository root. The audit used CPython 3.14.7. Its JSON contains all 432 per-fit scenario comparisons, counts by concentration feature and cohort, and frozen input and snapshot hashes. It checks the archived intervention identities, edited AP, matched score changes and win statistics. It opens the four held-out databases read-only and uses the archived fitted parameters.

```powershell
$env:PYTHONPATH = 'src'
$out = 'reports/generated/phase-c-audit-replay'
New-Item -ItemType Directory $out -ErrorAction Stop | Out-Null
& .venv-phase4c/Scripts/python.exe -B -m xrpl_anomaly.audit_supplement |
    Set-Content -Encoding utf8 "$out/supplement.json"
```

An independent per-positive AP and rank calculation matched all 432 paired records. The development table uses 192 original AP records from `phase3b2/evaluation.json`. Independent ECDF and alert-key calculations matched 54 original fit-window pairs and the three overridden middle windows in `phase4d-phase5-audit`, `phase4d-phase5-forest7` and `phase4d-phase5-forest29`. The tables round only for display.

The full offline suite ran 63 tests. It passed 61, including the paired AP and block-weighting tests and frozen bundle parity. Two Docker checks were skipped because no local test image was configured.

The 7,869 archived data, report and artifact file hashes matched the recorded inventory. The six Phase A file hashes and the Phase B renderer and PNG hashes matched their earlier records. The protocol and frozen evaluation sources match `418c6f7`.

An untouched held-out comparison at a shared forest size would be needed to estimate a graph-only increment. Isolating sensitivity to concentration would need interventions that control other context changes and evaluate the realized concentration at a prespecified unit, such as a sender window. Estimating fraud detection or operational recovery would need defensible labels or separately designed incident exercises. The current supplement uses the existing frozen experiments and is descriptive.

## Files changed in Phase C

- Public summary and captions: [README.md](../../README.md) and [docs/figures.md](../figures.md).
- Interpretations in the phase reports: [phase3b2.md](phase3b2.md), [phase3b3.md](phase3b3.md), [phase4a.md](phase4a.md), [phase4d.md](phase4d.md) and [phase5-audit.md](phase5-audit.md).
- Supplement: `docs/phases/phase-c-interpretation.md`, [src/xrpl_anomaly/audit_supplement.py](../../src/xrpl_anomaly/audit_supplement.py) and [tests/test_audit_supplement.py](../../tests/test_audit_supplement.py).
- Local output: `reports/generated/phase-c-audit/supplement.json`.
