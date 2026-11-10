# Phase 5 technical audit

## Readiness

**PASS for a local checkpoint. PARTIAL for public release.** The Windows offline integration checks, frozen replay and figure reproduction passed. Docker and hosted CI remain unverified. Before public release, confirm the visibility of commit metadata. The service is a local research tool for prepared features.

## Architecture and checks

| Component | Status | Evidence |
| --- | --- | --- |
| Acquisition and storage | PASS offline | Reviewed the bounded read-only RPC client, body deadlines, retry and resume paths, validated ledger and parent checks, body digests and atomic per-ledger SQLite writes. Fixtures exercise gaps, duplicates, malformed responses, interruption and rollback. Fresh verification used cached artifacts. Earlier phases verified the sampled chains and independent header checks. |
| Feature replay | PASS | Successful direct native XRP payments retain integer drops and ledger/transaction order. The frozen schema contains 21 static, temporal and directed-graph features. The 600-second lookback uses strictly earlier ledgers and restarts after gaps or at block boundaries. Fixtures check same-ledger isolation and expiry. Account identifiers index history outside the model vector. Read-only replay matched historical scores exactly. |
| Frozen fits and calibration | PASS | Repackaging matched the existing robust fit and both full Isolation Forest bundles, seeds 7 and 29, byte for byte. Scoring matched 71,031 saved scores and all 18 per-model operating alert counts. Tests cover score ties using the persisted ordering key of score, SHA-256 of the observation ID and the observation ID itself. The strict comparison excludes the boundary key. |
| Chronological evaluation | PASS for recorded evidence | Blocks 1–4 fit, 5–6 supported selection, 7–8 calibrated and 9–12 tested. The recorded evaluation, score table and fitted-state hashes were verified. Synthetic intervention fixtures cover replay, ties and matched changes. Phase 5 regenerated figures from frozen inputs without fitting or reacquiring. |
| Experiment tracking | PASS | The MLflow importer returned the same finished local run after verifying the 13 logged files against the source evidence. The historical provenance links protocol, code revision and artifact digests. |
| API and local security | PASS locally | Frozen direct/ASGI parity for all three bundles, cutoff behavior, startup failure and recovery, Host allowlist, bounded UTF-8 JSON, duplicate-key rejection, schema validation and metrics passed. A synthetic HTTP smoke through Uvicorn exercised readiness, metadata, scoring and metrics on IPv4 loopback. The API depends on the caller for correct temporal feature provenance. |
| Operational monitoring | PASS locally | Fixtures cover rolling request counts, completeness, unknown alert decisions, nearest-rank quantiles, tied ECDF values and reset behavior. Historical reports and baseline PNGs were reproduced from six read-only databases. The in-memory window is per worker and resets on restart. |
| Platform and dependency compatibility | PARTIAL | The three existing Windows x64 CPython 3.14.7 environments passed pip dependency checks. The core declares 3.12–3.14. Fresh wheel downloads, other minors and Linux installation were outside the local verification. Matplotlib emitted a NumPy timedelta deprecation warning during the fixture render. |
| Docker and GitHub Actions | NOT VERIFIED at runtime | Reviewed the digest pin, amd64 target, hashed wheel install and pip check, allowlisted build context, nonroot user, health probe and loopback-only host publication. Parsed workflow YAML and verified triggers, read-only permissions and the OS matrix. Docker was absent from PATH and no hosted run exists. |

Bundle SHA-256 values from both packaging passes:

| Bundle | SHA-256 |
| --- | --- |
| baseline-full | `9e7d670c87dfdbfbdcf7330afd1af1f4a1c58140c93941fe638831f5db72043b` |
| isolation-full-7 | `6561fac94edd469943cfe0dc7f325e6c3950262b5f4ca1f33f18af81f9e438d5` |
| isolation-full-29 | `2f1548dcef3e1822a075b9538c83a9864977aca68601d6b3eeecfc8c44eb90d8` |

## Scientific evaluation

**Historical observations.** The final four blocks contain 13,448 original scoring rows. These and the calibration transactions are unlabeled. Each full fit flagged 102 of 10,229 pooled calibration rows. The test alert rates varied by block and by detector. Differences in scores, alert rates and rank agreement describe behavior on the captured payment subset.

**Synthetic interventions.** Amount changes, compressed bursts and recipient redirects create labels for directly modified payments. Replaying the modified sequence also changes some unmodified payments' histories. The held-out evaluation separates direct changes from spillover. The macro comparison weights chronological blocks equally and aggregates over the prespecified available intervention cells and repetitions. The forest result aggregates two fits.

| Full detector | Macro average precision | Recall at per-block rank budget | Recall at frozen calibration cutoff |
| --- | ---: | ---: | ---: |
| Robust baseline | 0.01354 | 0.898% | 1.743% |
| Isolation Forest | 0.01587 | 0.783% | 0.781% |

The forest gained 0.00233 macro AP. Excluding block 12 changes the difference to −0.00101. The forest had lower recall under both alert policies. This supports keeping the robust baseline as the operational reference. The four test blocks can share accounts, so the block comparisons are descriptive. [Held-out protocol and results](phase3b3.md)

**Engineering benchmarks carried forward.** Prepared-vector throughput was 128,824 rows/s for the baseline and about 15,000 rows/s for each forest on one local CPU thread. The separate serial loopback benchmark reported p95 of 1.37 ms for the baseline and 1.33–1.55 ms for the forests. These measurements exclude feature replay and characterize their original run conditions. Phase 5 ran a functional HTTP smoke. [Prepared-vector benchmark](phase3b3.md#operational-costs-and-figures), [loopback benchmark](phase4b.md#local-verification)

**Descriptive monitoring.** The baseline replay covered 23,677 unmodified rows in 18 windows across blocks 7–12. Fee and baseline score distances each crossed 0.20 in 10 of 12 final-test windows. Some feature crossed it in every final-test window. In the controlled block 8 middle window, changing the fee feature to represent 100,000 drops moved both fee and baseline score distances to 1.000, versus 0.192 and 0.190 on the same unchanged rows. The next unchanged window gave 0.128 and 0.194. Both forests already crossed the score guide in all three clean block 8 windows and remained above it in recovery. The guide measures the largest marginal ECDF difference with at least 100 observed values per sample. Its production false-alarm rate and incident sensitivity are unknown. [Monitoring calculations and results](phase4d.md)

**Unverified production assumptions.** Real fraud prevalence, sensitivity, precision, serving under concurrent load, ongoing data availability and persistent multiworker monitoring have no validation in this audit.

## Reproduction record

Commands were run from the repository root. The historical runs below used the Phase 4D checkpoint as their Git HEAD. The offline suite required loopback socket access. An initial sandboxed run encountered socket restrictions. With that access, 48 tests passed and two Docker tests were skipped out of 50.

```powershell
$service = './.venv-phase4c/Scripts/python.exe'
$plot = './.venv-phase2/Scripts/python.exe'
$tracking = './.venv-phase4a/Scripts/python.exe'
$env:PYTHONPATH = 'src;.venv-phase2/Lib/site-packages'
$env:XRPL_TEST_FROZEN_MODELS = 'artifacts/phase4a/models'
Remove-Item Env:XRPL_TEST_IMAGE -ErrorAction SilentlyContinue
$env:MPLBACKEND = 'Agg'
$env:MPLCONFIGDIR = "$PWD/artifacts/phase5-mpl"
& $service -B -m unittest discover -s tests -v

$env:PYTHONPATH = 'src'
& $service -B -m xrpl_anomaly.verify_packaged
& $service -B -m xrpl_anomaly.package_models --output artifacts/phase5-model-check
& $tracking -B -m xrpl_anomaly.track_history
& $plot -B -m xrpl_anomaly.monitoring_replay --figures --run-name phase4d-phase5-audit
& $service -B -m xrpl_anomaly.monitoring_replay --model isolation-full-7 --run-name phase4d-phase5-forest7
& $service -B -m xrpl_anomaly.monitoring_replay --model isolation-full-29 --run-name phase4d-phase5-forest29

$base = & $service -B -c "import sys; print(sys._base_executable)"
foreach ($target in $service, $plot, $tracking) { & $base -B -m pip --python $target check }

$inventory = Get-Content artifacts/phase4d/after.json -Raw | ConvertFrom-Json
foreach ($row in $inventory) {
    if ((Get-FileHash -LiteralPath $row.Path -ErrorAction Stop).Hash -cne $row.Hash) {
        throw "Historical hash mismatch"
    }
}
```

All 7,778 paths listed in the Phase 4D inventory matched their recorded SHA-256. The inventory contains local paths and remains private. For the HTTP smoke, the [README demo](../../README.md#try-the-offline-demo) used the existing service interpreter and port 18755. A fresh environment install was outside that check.

### Figure audit

The five held-out PNGs and their metadata regenerated byte for byte from `evaluation.json`, `clean-scores.csv` and `models.json` copied into a fresh ignored output directory. Both baseline monitoring PNGs matched the frozen originals. The baseline replay JSON matched its Phase 4D counterpart except for `provenance.git_head`. Both forest replays matched their saved reports outside provenance, where the recorded revision and source digest map differ. Figure metadata binds the two PNGs to the fresh JSON digest. These checks are reproducible with Matplotlib 3.10.9 in the locked Windows plotting environment.

```powershell
$out = 'reports/generated/phase5-heldout-figures'
New-Item -ItemType Directory $out -ErrorAction Stop | Out-Null
foreach ($name in 'evaluation.json', 'clean-scores.csv', 'models.json') {
    Copy-Item "reports/generated/phase3b3/$name" $out
}
& $plot -B -c "from pathlib import Path; from xrpl_anomaly.heldout_figures import render; render(Path('reports/generated/phase5-heldout-figures'))"
```

The held-out calibration panels use an empirical survival scale and show the score component of the boundary. Read them with the tie-count table. The ablation and block panels use separate zero-based AP scales and show point summaries from synthetic data. The model-size axis is logarithmic in KiB. The historical plots report alert percentages on unchanged payments. The shift plot shades the synthetic window and shows its same-row control. The p05–p95 bars describe score spread within windows. They are neither confidence intervals nor error bounds. The [figure guide](../figures.md) gives context for using these outputs without implying incident detection.

## Privacy, dependencies and release gates

- **Tracked content and history.** Reviewed the path inventory for the eight commits reachable at the start of the audit, commit authors and current ignores. The local instructions are ignored and absent from reachable history. Raw ledger bodies, SQLite files, generated reports and models, tracking stores and virtual environments stay ignored. A targeted history scan covered credential patterns, private-key headers, local Windows paths and XRPL address-like strings. Its hits were the Base58 alphabet and public-address test fixtures. This was a heuristic review. Git history carries a personal display name and GitHub noreply identity as well as earlier automation identities. Confirm that this metadata is suitable for public release. No history rewrite was undertaken.
- **Data provenance.** The tracked block definitions and reports describe the public Mainnet sample. Treat account and transaction identifiers as pseudonymous and keep identity-bearing inputs and artifacts local. Verify provider access and redistribution terms before sharing any new derived files. Use the acquisition budgets and honor operator load warnings, throttling and availability constraints. [XRPL public servers](https://xrpl.org/docs/tutorials/public-servers), [XRPL rate limits](https://xrpl.org/docs/references/http-websocket-apis/api-conventions/rate-limiting)
- **Dependency notices.** The 14 installed service packages declare MIT, BSD-3-Clause, Apache-2.0 or PSF-2.0 in wheel metadata. Reviewed wheel metadata for the 12 plotting and 48 tracking packages as well. The plotting stack includes Matplotlib and bundled-library terms. The tracking stack includes LGPL and MPL declarations. Optional environments install separately from their own locks. The project code and documentation are covered by the [MIT License](../../LICENSE) where the project holds the rights to license them. Before distributing a binary or image, inventory the actual base image and the exact dependencies being shipped and retain the applicable license texts and notices. [GitHub repository licensing](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- **Service exposure.** The host listener and Docker publish examples bind IPv4 loopback. The container's internal listener is reachable by trusted peers on its Docker network. Host validation is input hardening. The trust boundary relies on local access and a verified bundle. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)

After publication is authorized, run the pinned workflow on the published commit. Review both Windows and Linux logs for locked installation, `pip check`, import and test results. On Linux, confirm the pinned image builds and that the synthetic fixture verifies health, missing-bundle startup failure, Host handling and exact score parity. Separately run the documented hardened local container with each trusted frozen bundle on a native amd64 Docker Engine 28+ host and record the image ID, engine version, health status and exact HTTP parity. Keep private bundles out of hosted CI. [Docker and CI commands](phase4c.md)
