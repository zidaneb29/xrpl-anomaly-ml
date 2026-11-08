# Phase 3A baseline stabilization and evaluation design

## Pilot diagnosis

The frozen cache covers 256 validated ledgers, 108187347–108187602, from 2026-11-08 02:47:21 to 03:04:30 UTC. There are 3,873 eligible payments and 1,342 complete-history rows, split chronologically into 628 training, 423 calibration, and 291 test rows. The training diagnosis uses only complete rows from ledgers 108187494–108187547 in the original `features.csv`. Take inclusive quartiles, count zero and distinct values, and sort unique transformed values to find the smallest adjacent difference.

| Training distribution of `sender_log_in_drops` | Value |
| --- | --- |
| Zero rows | 558 of 628 (88.85%) |
| Positive rows and distinct transformed levels | 70 rows, 38 distinct positive levels |
| Median, MAD, Q1 and Q3 including zeros | 0 for each |
| Positive minimum, Q1, median, Q3, maximum | 2.3979, 3.9766, 17.5592, 18.3900, 25.6145 |
| Closest distinct levels | 18.1819252200 and 18.1819259818, corresponding to 78,760,740 and 78,760,800 drops |
| Legacy fallback scale | 0.0000007618005675 |

Zero denotes no observed eligible incoming XRP payment for the sender in the preceding 600 seconds. The zero mass covers both quartile positions and the median absolute deviation. For positive totals `a` and `b`, the transformed spacing is `log((1 + b) / (1 + a))`. A difference of 60 drops at those totals produces a tiny denominator. Even the smallest positive training value yields a standardized deviation above three million. A single close pair can make the denominator arbitrarily small relative to the spread of a column and dominate the maximum across features.

| Remedy | Training-based assessment |
| --- | --- |
| Minimum scale | A floor would bound amplification but would need a defensible unit and magnitude for log drops, log counts, and indicators. There is no common scale floor supported by the pilot. |
| Transform or rank the whole column | A strictly increasing transform preserves the dominant tie. Rank or empirical tail scores require a new tie and rarity policy, and a small dependent sample gives coarse tail estimates. |
| Separate zero occurrence and positive magnitude | A two-part scorer could model contextual occurrence and conditional magnitude separately. The 70 positive rows have scaled MAD 3.986. Dependence, stratum size, and calibration of the combined score need independent blocks. |
| Exclude undefined scales from the maximum | A median-centered standardized deviation requires a positive dispersion estimate. Require positive scaled MAD or IQR and record omissions. This makes the score independent of spacing in any omitted feature. |

The final row is the Phase 3A policy. Its rule applies to all features using training only. This retains 15 of 21 inputs and omits sender incoming count, volume and distinct counterparties, both unseen indicators, and sender no-outgoing. All six are nonconstant. The feature table retains them for monitoring and later model comparisons. The policy loses direct sensitivity to rare occurrence on these axes and does not establish that remaining positive scales are stable across time.

| Same pilot, same strict calibration rule | Phase 2 | Phase 3A |
| --- | ---: | ---: |
| Cutoff | 31,857,696.16 | 113.3488 |
| Calibration alerts | 4 / 423 (0.95%) | 0 / 423 |
| Test alerts | 7 / 291 (2.41%) | 0 / 291 |
| Calibration median score | 4.6668 | 4.4813 |
| Test median score | 2.4794 | 2.4084 |

All 11 original alerts were driven by sender incoming volume. Under the corrected policy the maximum equals the cutoff in both splits. Six calibration rows and three test rows share that maximum, all driven by log fee. The strict greater-than rule excludes cutoff ties and can underspend the 1% budget. These figures describe a replay of an already studied pilot and give no estimate of detection quality. Keep the threshold rule for future observed alert rates and use a separate fixed-budget ranking metric for model comparisons.

Original artifacts are under `reports/generated/pilot-108187602`. The revised run and its five regenerated figures are under `reports/generated/phase3a-pilot-108187602`. The snapshot SHA-256 is `a90ec409114ee4043b5b0f9b66583900ec159a645a634afa1633e38b26e36ce4`. The revised summary and figure metadata contain commands, environment, inputs, and source hashes. The repository has no Git commit at this phase.

The README offline suite passed 17 of 17 tests before and after the change using the existing figure environment. The legacy replay reproduced the original feature and score CSVs byte for byte. The revised feature CSV also matched the original. Two identical revised CLI invocations each took about seven seconds with figures and produced nine byte-identical files. Both SQLite databases passed integrity and foreign-key checks and contained 3,873 integer amounts totaling 1,062,637,068,514 drops. The original cache, database, and report files matched their pre-change hashes.

## Proposed acquisition and chronological splits

Seventeen minutes of observations support pipeline and failure-mode checks. The complete rows share rolling windows and recurring accounts, leaving little independent variation. Use 12 disjoint 30-minute scoring blocks over six consecutive full UTC weeks with two blocks per week. Freeze an approved six-week interval that excludes the pilot and lies in verified provider coverage. For week indices 0–5, schedule Wednesday starts at 00:00, 08:00, 16:00 UTC in rotation and Saturday starts at 16:00, 00:00, 08:00 in rotation. This spans weekday and weekend UTC hours and separates blocks by days. Fixed slots can still alias recurring automated activity and miss other weekdays or exceptional conditions. Distinct time blocks can share accounts and regimes.

- Assign weeks 0–1 to training, week 2 to development, week 3 to calibration, and weeks 4–5 to final testing. Freeze timestamps, roles, ledger indexes and hashes, plus any approved replacement schedule, before looking at transaction composition or model scores.
- For start time `T`, include the last validated close at or before `T - 600s` as the warm-up anchor and all subsequent ledgers with close below `T + 1800s`. Score only closes in `[T, T + 1800s)`. Use bounded header lookup to map UTC boundaries. Verify chain continuity and three independent endpoint hash checks per block. Start fresh history per block. An unresolved gap invalidates the block for the primary comparison. Report missing blocks and the loss of coverage before applying any replacement.
- For each block report row counts, fractions of seen accounts and prior edges within the lookback, repeat sender and receiver counts, distinct directed edges, degree and concentration distributions, and overlap of account and edge sets with earlier blocks. Use recurrence and overlap as reporting strata. Addresses remain metadata. Report insufficient graph or burst eligibility and effective sample counts rather than weakening selection to fill quotas.
- The pilot averaged 4.04 seconds per ledger interval, about 0.512 MiB decoded and 0.118 MiB cached per ledger, and 1.70 seconds per ledger including acquisition overhead. Extrapolate to about 595 ledgers per block and 7,150 total, roughly 3.6 GiB decoded, 0.83 GiB compressed, and 3.4 hours serialized before probes, retries or throttling. At pilot density expect about 108,000 eligible rows including warm-up and 81,000 scored rows. Size and density can vary substantially.
- Stage the first two training blocks with a proposed combined ceiling of 1,500 HTTP attempts, 1 GiB decoded and one hour elapsed. Require a second review of measured costs before continuing. Proposed full-run caps including that stage are 9,000 attempts, 6 GiB decoded and six elapsed acquisition hours, with 3 GiB free local disk, concurrency one and at least one second between starts. Preserve the 8 MiB per-response cap and respect tighter endpoint limits. Persist cumulative budgets across resumes. Time acquisition, replay and feature extraction separately. Start with one CPU worker, replay one block at a time, and measure peak RSS against a provisional 1 GiB budget on the training stage.

## Controlled anomaly protocol

Freeze the injection manifest, rules and candidate severity grid before test access. Use development blocks to check eligibility and feasibility and calibrate thresholds on clean calibration blocks. Run families separately on copies of test observations with a clean replay for comparison. Record source snapshot and block, seed, selected IDs, clean and changed values, origin and target ledgers, attempted and achieved prevalence, and skipped candidates with reasons. These are feature-space interventions on normalized ledger observations. They do not model protocol execution, funding constraints, or fraud outcomes.

| Family | Proposed intervention and label |
| --- | --- |
| Conditional amount | Sample eligible events across train-defined log-amount and sender activity strata. Multiply positive delivered drops by 1.5 or 2.5, or their reciprocals, with deterministic integer rounding. Require a changed positive value inside the training amount range for the primary analysis. Label the modified event. |
| Burst | For recurrent senders, compress a sequence of 3 or 5 events occurring over several minutes into distinct observed closes within a 60- or 30-second interval respectively. Keep chronological order and constrain the schedule to the scored block and the selected sender's adjacent untouched events. Reassign deterministic unique ledger positions in the overlay. Label moved events and report event and burst detection separately. |
| Counterparty concentration | For senders with at least three prior outgoing counterparties, redirect approximately 10% or 25% of selected outgoing events over a prespecified five-minute episode to a different recipient already seen for that sender before the episode. Require a realized increase in episode concentration, exclude self-payments and retain amounts and closes. Label redirected events and report episode detection as well. |

Use seeds 11, 23, 47, 83 and 101, and target about 1% changed events per family, strength and block subject to eligibility. Prefer at most one episode per sender per copy. Select controls from comparable eligible rows within each block using clean pre-intervention activity and amount strata. Exclude affected downstream rows from primary matched controls, report their scores separately, and report realized evaluation prevalence alongside AP. Use full-copy rankings to measure competition for alerts. Candidate selection and controls must never depend on model scores.

Warm-up remains clean. Apply every intervention to the event stream before replay. Score all events in a ledger using earlier-ledger history, then update history with that ledger's altered events. An amount change updates future volume sums. A move removes the original event and adds it at the new close. Redirection changes both the old and new recipient histories. Track unmodified rows with changed features as spillover, including changes from removed events until they would have expired. Keep stable analysis identities separate from ledger positions. History changes can first affect feature rows after the earliest edited ledger and are confined to the test copy. Verify these invariants with deterministic fixtures, including an expiry boundary case.

Report synthetic average precision, prevalence, recall at top `floor(0.01 * n)` on full copies, and recall at the frozen clean calibration cutoff. For top-k, use a stable hash of the original event identity as an independent tie order and report a sensitivity range for ties straddling the budget. Also show matched original-to-altered score and rank changes, episode recall and time to first alert for bursts, and spillover alert rates. For observed blocks report realized alert rates, fraction tied at cutoff, score quantiles, cold-start strata, top-k overlap and Spearman rank agreement on identical rows. Report paired per-block comparisons by family, severity, ablation and seed. With four test blocks report descriptive ranges and leave-one-block-out sensitivity. For later expanded designs resample whole blocks for paired intervals, and test sensitivity to shared accounts and adjacent weeks. Repeated seeds measure injection sensitivity and do not add independent blocks. Observed payments lack verified labels for real precision, recall and false-positive rates.

## HTTP deadline and verification gate

The monotonic checks surround `read1` calls. A blocking read, including response framing or a slowly dripped body, can cross the deadline before control returns. Opening the response can also block across multiple stages. Before expanding acquisition, use a prestarted disposable worker for one HTTP attempt at a time. The parent enforces a monotonic deadline from dispatch, kills and reaps a stalled worker, and starts a replacement before retrying. Bound the response inside the worker and make budget accounting conservative after termination, such as reserving the response allowance at dispatch and settling it only after a complete byte report. Keep retries, accounting, validation and atomic publication in the parent. Startup and teardown need separate supervision and measured tolerance. [Python subprocess timeout behavior](https://docs.python.org/3.14/library/subprocess.html)

Use offline loopback fixtures for delayed headers, stalled and slowly dripped bodies, oversized responses, throttling and interrupted worker cleanup. Assert bounded termination, no partial cache publication, and verified resume at the first missing ledger. Verify SQLite integrity, integer drops, identical feature replay, and provenance before acquiring the first two training blocks.

## Figure additions

1. Show the training point mass at zero separately from the conditional positive ECDF, with quartiles and sample counts.
2. Plot training score contributions under candidate scales on a log axis and annotate the legacy closest pair. Use development blocks for any further scale sensitivity decisions.
3. Compare per-block coverage, payment counts, cold starts, repeated accounts and edges, and degree and concentration quantiles.
4. Show observed score quantiles and cutoff ties by block, paired score shifts for altered rows, and same-row rank and top-k agreement.
5. In later model phases, show paired synthetic AP and recall at budget by family and strength, with prevalence, per-block points and CPU and memory costs.

## Phase 3B proposal

Approve the six-week sampling frame, acquisition ceilings and staged go/no-go criteria. Implement and verify the bounded transport and frozen multi-block manifests with offline fixtures. Resolve and freeze all block ranges, then acquire and replay only the first two training blocks under the staged cap. Review coverage, recurrence, graph and injection eligibility, cost and recovery evidence before authorizing the remaining blocks. Freeze the perturbation implementation and comparison settings on development data before final test access. Keep model additions under their later approval gate.
