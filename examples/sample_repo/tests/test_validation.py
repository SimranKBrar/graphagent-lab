import pytest

from orders.models import OrderItem
from orders.validation import ValidationError, validate_customer_id, validate_item


def test_valid_item_passes():
    validate_item(OrderItem(sku="SKU-1", quantity=2, unit_price=9.99))


def test_zero_quantity_rejected():
    with pytest.raises(ValueError):
        validate_item(OrderItem(sku="SKU-1", quantity=0, unit_price=9.99))


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        validate_item(OrderItem(sku="SKU-1", quantity=-2, unit_price=9.99))


def test_negative_price_rejected():
    with pytest.raises(ValueError):
        validate_item(OrderItem(sku="SKU-1", quantity=1, unit_price=-1.0))


def test_empty_customer_rejected():
    with pytest.raises(ValidationError):
        validate_customer_id("   ")
