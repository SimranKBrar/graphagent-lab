"""Hidden criterion tests for task 'bugfix-single-item-validation'.

These tests are never present in an agent's workspace. They fail on the
original buggy repository (single-item orders bypass validation) and must
pass after a correct fix. An inventory-consistency check additionally catches
'fixes' that validate but drop stock reservation.
"""
import pytest

from orders.inventory import Inventory
from orders.models import OrderItem
from orders.repository import OrderRepository
from orders.service import create_order

SKUS = {"SKU-1": 10, "SKU-2": 10}


def _inv() -> Inventory:
    return Inventory(dict(SKUS))


def test_single_item_zero_quantity_rejected():
    with pytest.raises(ValueError):
        create_order("c-1", [OrderItem("SKU-1", 0, 5.0)],
                     repository=OrderRepository(), inventory=_inv())


def test_single_item_negative_quantity_rejected():
    with pytest.raises(ValueError):
        create_order("c-1", [OrderItem("SKU-1", -3, 5.0)],
                     repository=OrderRepository(), inventory=_inv())


def test_single_item_negative_price_rejected():
    with pytest.raises(ValueError):
        create_order("c-1", [OrderItem("SKU-1", 1, -0.01)],
                     repository=OrderRepository(), inventory=_inv())


def test_rejected_order_does_not_mutate_inventory():
    inv = _inv()
    with pytest.raises(ValueError):
        create_order("c-1", [OrderItem("SKU-1", -5, 5.0)],
                     repository=OrderRepository(), inventory=inv)
    assert inv.stock_for("SKU-1") == 10


def test_multi_item_any_invalid_rejected():
    items = [OrderItem("SKU-1", 1, 5.0), OrderItem("SKU-2", 0, 5.0)]
    with pytest.raises(ValueError):
        create_order("c-1", items, repository=OrderRepository(), inventory=_inv())


def test_valid_single_item_order_reserves_stock():
    inv = _inv()
    repo = OrderRepository()
    order = create_order("c-1", [OrderItem("SKU-1", 4, 5.0)],
                         repository=repo, inventory=inv)
    assert order.order_id is not None
    assert repo.count() == 1
    assert inv.stock_for("SKU-1") == 6


def test_rejected_multi_item_does_not_consume_stock():
    inv = _inv()
    items = [OrderItem("SKU-1", 2, 5.0), OrderItem("SKU-2", -1, 5.0)]
    with pytest.raises(ValueError):
        create_order("c-1", items, repository=OrderRepository(), inventory=inv)
    assert inv.stock_for("SKU-1") == 10
    assert inv.stock_for("SKU-2") == 10
