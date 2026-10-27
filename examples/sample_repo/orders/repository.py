"""Persistence for orders (in-memory store with id assignment)."""
from .models import Order


class OrderRepository:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._sequence = 0

    def save(self, order: Order) -> str:
        self._sequence += 1
        order.order_id = f"ord-{self._sequence:05d}"
        self._orders[order.order_id] = order
        return order.order_id

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def count(self) -> int:
        return len(self._orders)
