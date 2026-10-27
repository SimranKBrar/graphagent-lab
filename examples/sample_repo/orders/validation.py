"""Validation rules for order items and customers."""
from .models import OrderItem


class ValidationError(ValueError):
    """Raised when order input fails a validation rule."""


def validate_item(item: OrderItem) -> None:
    """Raise ValidationError when an item is not orderable."""
    if not isinstance(item, OrderItem):
        raise ValidationError("item must be an OrderItem")
    if item.quantity < 1:
        raise ValidationError("quantity must be at least 1")
    if item.unit_price < 0:
        raise ValidationError("unit price cannot be negative")


def validate_customer_id(customer_id: str) -> None:
    if not customer_id or not str(customer_id).strip():
        raise ValidationError("customer_id is required")
