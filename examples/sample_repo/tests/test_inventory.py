import pytest

from orders.inventory import Inventory, OutOfStock
from orders.models import OrderItem


def test_reserve_decrements_stock():
    inv = Inventory({"A": 5})
    inv.reserve([OrderItem("A", 3, 1.0)])
    assert inv.stock_for("A") == 2


def test_reserve_insufficient_raises():
    inv = Inventory({"A": 1})
    with pytest.raises(OutOfStock):
        inv.reserve([OrderItem("A", 2, 1.0)])
    assert inv.stock_for("A") == 1


def test_release_restores_stock():
    inv = Inventory({"A": 5})
    item = OrderItem("A", 2, 1.0)
    inv.reserve([item])
    inv.release([item])
    assert inv.stock_for("A") == 5
