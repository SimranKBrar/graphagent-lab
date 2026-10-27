"""Order creation orchestration.

Flow: validate input -> price the order -> persist.
"""
from .inventory import Inventory
from .models import Order, OrderItem
from .pricing import compute_total
from .repository import OrderRepository
from .validation import ValidationError, validate_customer_id, validate_item


def create_order(customer_id: str, items: list[OrderItem], *,
                 repository: OrderRepository, inventory: Inventory) -> Order:
    """Create, price and persist an order.

    Every item is validated up front so invalid quantities or negative
    prices can never enter an order.
    """
    for item in items:
        validate_item(item)
    validate_customer_id(customer_id)
    if not items:
        raise ValidationError("order must contain at least one item")

    total = compute_total(items)
    order = Order(customer_id=customer_id, items=list(items), total=total)
    repository.save(order)
    return order
