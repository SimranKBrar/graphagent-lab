# flowgate

A small webhook delivery gateway: endpoints subscribe to topics, a router
selects targets, and a delivery queue drains pending events through the
dispatcher while an attempt ledger tracks how often each endpoint has been
called.

## Layout

- `app/` — runtime: endpoint model, attempt ledger, topic router, delivery
  queue, and the dispatcher that owns redelivery decisions and
  dead-lettering.
- `policies/` — retry budget policy and backoff schedules (scheduling
  only; the dispatch loop decides what to do with a spent budget).
- `reporting/` — read-only dashboard rollups over the attempt ledger.
- `tests/` — visible test suite (`python -m pytest -q`).

## Notes

Each endpoint carries a `max_attempts` ceiling. Once an endpoint has used
its allowance, further deliveries must be dead-lettered rather than
redelivered, so operators can inspect and re-drive them deliberately.
