# Collector write reliability

`flush_job_batches()` retries each replay-safe request at most four times.
Each retry rebuilds the request with the same upsert values or cleanup filters.
The three waits are 1–2, 2–3 and 4–5 seconds (exponential backoff plus jitter).
Batch size remains 200; upserts retain the `source,source_job_id` conflict key
and request `return=minimal` because no returned rows are consumed.

Retryable failures are HTTPX timeouts, network errors and remote protocol
errors; HTTP 408/429/500/502/503/504; and PostgREST codes for those statuses,
connection/pool failures, serialization failure, deadlock, unavailable locks
and statement cancellation/timeout. Other errors stop immediately. The final
exception propagates, so later batches, cleanup and expiration reconciliation
do not continue after an exhausted request.

Logs include table, operation, batch number, row count, attempt, attempt and
total elapsed time, result and retry delay. They omit request bodies and server
error messages. Cleanup batch numbering runs across source groups per table.

## Verification

Run `python -m unittest -v` after installing the existing requirements.
Tests use in-memory stores and HTTPX MockTransport; no credentials, collectors
or live database are needed. They cover timeout recovery, commit-before-timeout
replay, exhausted retries, permanent failures, request headers and payloads,
deduplication, 200-row batches, source scoping, reference retention and the
write/reconciliation boundary. The existing retention tests remain included.

Supabase's documented `returning="minimal"` option is used:
https://supabase.com/docs/reference/python/upsert

## Risks and limits

- Retries add up to 10 seconds of backoff per failing request, plus up to four
  existing request timeout periods. They do not resolve database load or IO pressure.
- A lost response may follow a committed write. Conflict-key upserts and fixed
  cleanup operations converge on the same row state, but database triggers may
  execute again. This is not an exactly-once or atomic multi-table transaction.
- Earlier successful batches can remain committed after a later failure;
  reconciliation is skipped rather than expiring listings from a partial run.
- No production database or workflow run is used for validation. Local transport
  tests cannot reproduce production lock contention or trigger side effects.

## Rollback

Before merge, close the PR to discard the proposal. If merged later, revert the
reliability commit through a reviewed PR. No schema/settings/data rollback is
needed. The old behavior will again fail immediately on transient write errors.
Do not manually rerun production collection as part of rollback verification.
