import pytest

from orders.inventory import Inventory
from orders.models import OrderItem
from orders.repository import OrderRepository
from orders.service import create_order
from orders.validation import ValidationError


class FailingRepository(OrderRepository):
    def save(self, order):
        raise RuntimeError("database unavailable")


def test_multi_item_invalid_rejected():
    inv = Inventory({"A": 5, "B": 5})
    repo = OrderRepository()
    items = [OrderItem("A", 1, 10.0), OrderItem("B", 0, 10.0)]
    with pytest.raises(ValueError):
        create_order("c-1", items, repository=repo, inventory=inv)
    assert repo.count() == 0


def test_single_valid_order_created():
    inv = Inventory({"A": 5})
    repo = OrderRepository()
    order = create_order("c-1", [OrderItem("A", 2, 10.0)],
                         repository=repo, inventory=inv)
    assert order.order_id is not None
    assert repo.count() == 1
    assert order.total > 0.0


def test_create_order_reserves_inventory():
    inv = Inventory({"A": 5, "B": 3})
    repo = OrderRepository()
    create_order("c-1", [OrderItem("A", 2, 10.0), OrderItem("B", 1, 4.0)],
                 repository=repo, inventory=inv)
    assert inv.stock_for("A") == 3
    assert inv.stock_for("B") == 2


def test_failed_save_releases_inventory():
    inv = Inventory({"A": 5})
    with pytest.raises(RuntimeError):
        create_order("c-1", [OrderItem("A", 2, 10.0)],
                     repository=FailingRepository(), inventory=inv)
    assert inv.stock_for("A") == 5


def test_empty_items_rejected():
    with pytest.raises(ValidationError):
        create_order("c-1", [], repository=OrderRepository(), inventory=Inventory())
