"""Order creation orchestration.

Flow: validate input -> price the order -> reserve stock -> persist.
"""
from .inventory import Inventory
from .models import Order, OrderItem
from .pricing import compute_total
from .repository import OrderRepository
from .validation import ValidationError, validate_customer_id, validate_item


def create_order(customer_id: str, items: list[OrderItem], *,
                 repository: OrderRepository, inventory: Inventory) -> Order:
    """Create, price, reserve and persist an order.

    Every item is validated up front (before any side effect), including
    single-item orders. Raises ValidationError for invalid input and
    OutOfStock when stock cannot be reserved. If persistence fails, any
    reserved stock is released before the error propagates.
    """
    for item in items:
        validate_item(item)
    validate_customer_id(customer_id)
    if not items:
        raise ValidationError("order must contain at least one item")

    total = compute_total(items)
    inventory.reserve(items)
    order = Order(customer_id=customer_id, items=list(items), total=total)
    try:
        repository.save(order)
    except Exception:
        inventory.release(items)
        raise
    return order
