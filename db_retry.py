"""Bounded retries for replay-safe collector persistence requests only."""
import random
import time

import httpx
from postgrest.exceptions import APIError


MAX_ATTEMPTS = 4
TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
TRANSIENT_CODES = {str(status) for status in TRANSIENT_STATUSES} | {
    "40001",  # serialization failure
    "40P01",  # deadlock
    "55P03",  # lock unavailable
    "57014",  # statement timeout / query cancelled
    "PGRST000", "PGRST001", "PGRST002", "PGRST003",  # connection/pool
}


def is_transient(error):
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError,
                          httpx.RemoteProtocolError)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in TRANSIENT_STATUSES
    return isinstance(error, APIError) and str(error.code) in TRANSIENT_CODES


def execute_with_retry(request_factory, *, table, operation, batch_number, row_count):
    """Rebuild each request; callers must capture identical payloads/filters.

    A timeout may occur after commit. Use only conflict-key upserts, fixed-value
    updates and deletes whose replay has the same intended database state.
    Never swallow a final failure: reconciliation must not follow failed writes.
    """
    started = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_started = time.monotonic()
        context = (f"DB table={table} operation={operation} batch={batch_number} "
                   f"rows={row_count} attempt={attempt}/{MAX_ATTEMPTS}")
        try:
            result = request_factory().execute()
        except Exception as error:
            retry = attempt < MAX_ATTEMPTS and is_transient(error)
            # Do not log server messages, payloads, URLs or credentials.
            print(f"{context} elapsed={time.monotonic() - started:.3f}s "
                  f"attempt_elapsed={time.monotonic() - attempt_started:.3f}s "
                  f"result={'retry' if retry else 'failed'} "
                  f"error={type(error).__name__}", flush=True)
            if not retry:
                raise
            delay = 2 ** (attempt - 1) + random.uniform(0, 1)
            print(f"{context} retry_delay={delay:.3f}s", flush=True)
            time.sleep(delay)
        else:
            print(f"{context} elapsed={time.monotonic() - started:.3f}s "
                  f"attempt_elapsed={time.monotonic() - attempt_started:.3f}s "
                  "result=success", flush=True)
            return result
