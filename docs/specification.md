# Technical specification and acquisition

## System objective and scope

Build a reliable, reproducible path from public XRPL records to locally served anomaly scores. The system should recover from ingestion failures, preserve ledger and payment semantics in SQLite, replay features deterministically, track model runs and artifacts, and expose data quality and scoring behavior through monitoring. Automated tests and CI verify the contracts between stages.

The observation is one validated, successful, direct XRP payment on Mainnet. The [evaluation protocol](experiments.md) supports decisions about feature sets, scorers, and operating costs. The real sample has unknown anomaly status. Use addresses as pseudonymous account identifiers, without identity inference or attribution of intent.

Account windows are a possible extension if there is enough repeated activity. A graph-level detector would require a separate sampling and labeling design. Network-wide time bins support descriptive analysis, while transaction scores let an operator trace an alert to a specific payment. The sample represents the eligible payment subset in the captured periods. Other transaction types and off-ledger activity fall outside that scope.

## Sources

| Option | Practical trade-off |
| --- | --- |
| Expanded ledger over public JSON-RPC | Preferred historical path. Fetch transactions and metadata by index without downloading state. Test Ripple's `s2` and InFTF's `xrplcluster.com` independently. Free access can be throttled and available ranges can differ. |
| WebSocket requests and subscriptions | Historical availability still depends on the server. A later live replay would need durable checkpoints and historical backfill after disconnects. |
| Account history | Useful for spot checks. Fix ledger bounds, pass the opaque marker unchanged, cap pages, and restart the bounded query if a marker expires. Account selection biases network coverage and a transaction may appear in multiple histories. |
| Provider extracts | Bitquery documents Parquet exports. Coverage, finality, field fidelity, cost, and redistribution terms require separate review. Consider an export only if it fits a bounded local slice and has clear rights and provenance. |

[Public servers](https://xrpl.org/docs/tutorials/public-servers), [ledger API](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/ledger-methods/ledger), [ledger history](https://xrpl.org/docs/concepts/networks-and-servers/ledger-history), [subscriptions](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/subscription-methods/subscribe), [account history](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/account-methods/account_tx), [markers](https://xrpl.org/docs/references/http-websocket-apis/api-conventions/markers-and-pagination), [provider exports](https://docs.bitquery.io/docs/cloud/ripple/), [provider terms](https://www.bitquery.io/datastore/legal/terms)

## Proposed Phase 2 pilot

1. Query advertised history and a validated Mainnet tip. Freeze 256 consecutive indexes ending at that tip before examining payment composition. Pin JSON-RPC API v2 and use numeric ledger indexes, expanded transactions and metadata, and no full ledger state. Check network identity where reported and compare the first, middle, and last ledger hashes against a second operator.
2. Start with concurrency one and at least one second between request starts. Allow at most 320 total HTTP attempts including probes, retries, and cross-checks, 8 MiB per decoded response, and 256 MiB of decoded response data across the run. Use a 20-second request deadline and at most three attempts per request. Honor retry hints, use bounded exponential backoff with jitter for transient errors, slow down on load warnings, and stop at the run budget or persistent throttling. Treat an unavailable historical index separately from overload.
3. Verify validation status, expected index, explicit transaction array, required fields, unique transaction hashes and indexes, and parent-hash continuity. An empty confirmed ledger contributes observed zero activity. A missing ledger or structurally invalid response is a gap. Record gaps and block affected feature rows until a full lookback is available. Quarantine conflicting hashes or inconsistent responses for review.
4. Measure bytes, latency, retry counts, eligible payments, coverage, and repeat counterparties. Size a subsequent evaluation snapshot before scoring results. Prefer contiguous ranges. If cost requires sampling, predeclare nonoverlapping contiguous UTC blocks across different days or times and warm up independently in each block. If recurrence or temporal coverage is weak, narrow the evaluation before adding models.

Full-history access has historical limits and endpoint coverage can have holes. Ledger 32570 is the earliest available Mainnet ledger. The pilot budgets above are local client limits, subject to tighter operator limits. [Server coverage](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/server-info-methods/server_info), [rate limits](https://xrpl.org/docs/references/http-websocket-apis/api-conventions/rate-limiting), [full history](https://xrpl.org/docs/infrastructure/configuration/data-retention/configure-full-history)

## Normalization and snapshot contract

- Require a validated ledger and `Payment` with `tesSUCCESS`, distinct classic source and destination addresses, native XRP `DeliverMax` (v2) or `Amount` (v1 fixtures), no routing or send-limit fields, and no partial-payment flag. Require positive integer-string `meta.delivered_amount` and a valid nonnegative integer-string fee. Token payments, failed transactions, unsupported types, and malformed or unavailable amounts get separate counts. Never substitute requested amounts for missing delivery metadata.
- Store the transaction hash, ledger index and hash, metadata `TransactionIndex`, close time, source, destination, amount drops, and fee drops. Use integer drops and exact sums, including an overflow-safe strategy for aggregates beyond SQLite's signed integer range. Convert from the Ripple epoch to UTC. Close time describes a ledger, with coarser resolution than a per-payment arrival timestamp.
- Cache immutable response bodies and store a manifest with schema version, endpoint, API version, request settings, acquisition time, requested and observed ranges, per-ledger identity and content digests, errors, gaps, exclusions, and input configuration digest. Deduplicate by hash, reject conflicting duplicates, and commit each complete ledger and its rows atomically. Retry from verified cached data or fetch the missing ledger again.
- Keep raw responses local. Publish manifests and permitted aggregates only after reviewing source terms. Use synthetic fixtures in Git by default. The application uses read-only methods and has no wallet or signing workflow.

[Payment protocol](https://xrpl.org/docs/references/protocol/transactions/types/payment), [metadata](https://xrpl.org/docs/references/protocol/transactions/metadata), [units and time](https://xrpl.org/docs/references/protocol/data-types/basic-data-types), [close time resolution](https://xrpl.org/docs/concepts/ledgers/ledger-close-times)
