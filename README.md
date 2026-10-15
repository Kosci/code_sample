# SIS Enrollment Reconciliation

A small integration tool that pulls enrollment data from a Student Information
System (SIS) REST API and reconciles it against a downstream system's roster, 
reporting anything out of sync.

All data is fictional. Requires Python 3.9+.

## Run it

    python main.py                 # demo: starts a local mock SIS API automatically
    python -m unittest -v          # run the test suite (9 tests)

The demo deliberately fails one API page with a 503 so you can see the retry
logic working. 

It writes `discrepancy_report.csv`.

## Layout

| File | Purpose |
|------|---------|
| `sis_client.py` | REST client: pagination, retry with exponential backoff, fail-fast on 4xx |
| `reconcile.py` | Pure business logic: validation, normalization, reconciliation rules |
| `mock_sis_server.py` | Fake SIS API (stdlib `http.server`) for demos and integration tests |
| `main.py` | CLI that wires the pieces together |
| `test_sync.py` | Unit tests plus integration tests against the mock API |

## Business assumptions & rules

1. A student enrolled in the SIS must appear on the downstream roster.
2. Anyone on the roster who is not enrolled in the SIS (dropped, waitlisted,
   or no record) is flagged as stale.
3. Records with a missing student ID, missing course, or unknown status are
   rejected.
4. Rejected records are reported, never silently dropped.   
5. Formatting differences (`" cse 115 "` vs `CSE115`) are normalized so they
   don't produce false mismatches.

## Design decisions

- **Logic separated from I/O.** `reconcile.py` never touches the network, so
  the rules are trivially unit-testable.
- **Retry only what is retryable.** Timeouts, 429s, and 5xx are retried with
  backoff; 4xx (like a bad token) fail immediately.
- **Generator-based pagination** keeps memory flat for large terms.
- **Injectable `sleep`** keeps retry tests fast and deterministic.

## What I'd add with more time

- Config via environment variables instead of CLI flags
- Cover more potential formatting differences in course names
- Structured logging and metrics for monitoring purposes
