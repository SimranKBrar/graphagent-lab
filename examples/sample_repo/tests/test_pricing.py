from orders.models import OrderItem
from orders.pricing import (SHIPPING_PER_ORDER, compute_shipping, compute_subtotal,
                            compute_tax, compute_total)


def test_subtotal():
    items = [OrderItem("A", 2, 10.0), OrderItem("B", 1, 5.5)]
    assert compute_subtotal(items) == 25.5


def test_tax_and_shipping():
    items = [OrderItem("A", 1, 10.0)]
    subtotal = compute_subtotal(items)
    assert compute_tax(subtotal) == 0.8
    assert compute_shipping(subtotal) == SHIPPING_PER_ORDER


def test_free_shipping_above_threshold():
    items = [OrderItem("A", 1, 150.0)]
    assert compute_shipping(compute_subtotal(items)) == 0.0


def test_total():
    items = [OrderItem("A", 2, 10.0)]
    # 20.0 + 1.6 tax + 4.99 shipping
    assert compute_total(items) == 26.59
