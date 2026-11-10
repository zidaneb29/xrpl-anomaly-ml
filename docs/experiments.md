# Feature and evaluation contracts

The evaluation informs engineering decisions about which feature groups to compute, which scorer to serve, and how to set an alert budget. Compare detection of controlled perturbations, ranking stability across seeds and chronological blocks, and operating costs. Document the mathematical rationale for each scorer so the comparisons and failure modes can be interpreted.

## Feature rows

Use one row per eligible payment, ordered by ledger index and transaction index. Include the snapshot and feature schema versions plus row identity and coverage status as metadata. Model inputs exclude addresses, hashes, and ledger index.

For ledger close time `t`, start with a 10-minute lookback covering closes in `[t - 10 min, t)` from strictly earlier ledgers. Score every row from a ledger before updating history with any of that ledger's payments. Require observed coverage back to the lookback boundary and reset on gaps. In a complete window, zero prior eligible observations marks an account as unseen within that window. Encode missing recency with the window length and a separate indicator.

| Feature set | Inputs and rationale |
| --- | --- |
| Static | `log1p` of delivered amount and fee expressed numerically in drops. The log compresses heavy tails while preserving the rank order of individual values. |
| Temporal increment | Prior incoming and outgoing eligible counts and summed drops for both endpoints, plus time since each endpoint's last eligible observation in the window. Use log transforms for heavy-tailed counts and sums. |
| Graph increment | On the same window, construct a directed weighted edge for each sender and receiver pair, with weight equal to payment count. Use distinct incoming and outgoing counterparties for the endpoints, the prior sender-to-receiver count, and sender outgoing concentration `sum_j (count_ij / outgoing_count_i)^2`. Encode absent outgoing history with zero concentration and an explicit indicator. |

Use exact rolling sums before conversion to numerical model inputs. A graph state backed by edge counters and expiring observations permits incremental updates. Do not compute global centrality or mix histories across gaps. Future and same-ledger perturbation tests must preserve earlier feature rows exactly.

## Protocol

1. Freeze ranges and chronological warm-up, train, calibration, and test blocks before final scoring. Keep entire ledgers together. Fit transforms and model parameters on training data, select development settings without test access, and set model thresholds on calibration. Earlier observed events may seed the next contiguous split's history. Disjoint blocks require fresh warm-up.
2. Set a provisional 1% alert budget. On calibration, select a deterministic threshold with an explicit tie policy and report its achieved alert rate. Apply the threshold unchanged to each test period. For rank-based comparisons use a fixed budget on matched rows and report tie handling.
3. Replay separate synthetic test copies for conditional amount changes, plausible bursts, and counterparty concentration changes. Specify eligibility, seeds, placement, prevalence, and severity before scoring. For amount shifts use bounded additive offsets in log amount drawn from prespecified strengths, conditional on activity or amount strata and converted back to positive integer drops. For bursts move eligible events into nearer observed closes within the test block. For concentration redirect a bounded fraction of a sender's events to previously observed recipients while excluding self-payments. Preserve synthetic provenance and leave the original snapshot immutable. Track changed events and downstream feature spillover separately. Sample matched unmodified controls and label their experimental role rather than assuming verified normal behavior.
4. On synthetic copies report average precision, prevalence, and recall at the fixed alert budget by perturbation family and severity. Compare variants on the same rows and seeds. Report per-block effects and block-aware uncertainty when enough independent blocks exist. Otherwise report descriptive variation. On unmodified observations report score distributions, alert rates, top-k overlap, rank correlation on identical rows, and separate cold-start behavior. Real precision, recall, and false-positive rates require independently defensible labels.
5. Compare static, static plus temporal, and full inputs. Vary random seeds and a small prespecified hyperparameter set. Record training wall time, warm and cold latency, batch throughput, process peak memory, artifact bytes, and ingestion recovery metrics. Run timings under a fixed CPU thread budget and record hardware and workload size.

## Scorers

- **Robust deviation.** Score the maximum absolute median-centered deviation after scaling by `1.4826 * MAD` fitted on training. For zero MAD use `IQR / 1.349` if positive. Omit features with both scales zero and report them separately from training constants. Monitor new variation in constants. The legacy pilot used minimum training spacing for nonconstant zero-dispersion columns. See the [Phase 3A analysis](phases/phase3a.md) for results and the proposed block and injection protocol.
- **Isolation Forest.** Use tree paths to measure ease of isolation, orient scores with larger values meaning more unusual, and calibrate independently of training. With `T` trees and subsample size `m`, typical training work scales like `T * m * log(m)` and average per-row scoring like `T * log(m)`. Test a small range of subsample sizes and seeds. Low-frequency legitimate patterns may isolate easily.
- **Conditional CPU autoencoder.** Use a small fully connected bottleneck with a linear output, train on scaled features to minimize mean squared reconstruction error, and score by per-row mean squared error. Tune on development blocks and stop early. Training work scales with epochs, rows, and network weights. Require several usable temporal blocks, a clear unresolved comparison, and explicit approval before adding PyTorch. The model can reconstruct injected anomalies or penalize underrepresented legitimate behavior.
