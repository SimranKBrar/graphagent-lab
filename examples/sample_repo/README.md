# orders-service

A small order management service used as the GraphAgent Lab benchmark subject.

## Layout
- `orders/models.py` — `OrderItem` and `Order` dataclasses
- `orders/validation.py` — item / customer validation rules
- `orders/pricing.py` — subtotal, tax, shipping, total computation
- `orders/inventory.py` — stock reservation and release
- `orders/repository.py` — order persistence
- `orders/service.py` — `create_order` orchestration
- `tests/` — unit tests (run with `python -m pytest -q`)

## Known issue (benchmark task)
Order validation is skipped for single-item orders: `create_order` only
validates items when the order contains more than one item, so invalid
quantities or negative prices slip through. See the benchmark task
"Fix validation skipped for single-item orders".
