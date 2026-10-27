"""Stock tracking with reservation semantics."""
from .models import OrderItem


class OutOfStock(ValueError):
    """Raised when an order cannot be fulfilled from available stock."""


class Inventory:
    def __init__(self, stock: dict[str, int] | None = None):
        self._stock: dict[str, int] = dict(stock or {})

    def stock_for(self, sku: str) -> int:
        return self._stock.get(sku, 0)

    def is_available(self, sku: str, quantity: int) -> bool:
        return self.stock_for(sku) >= quantity

    def reserve(self, items: list[OrderItem]) -> None:
        """Atomically reserve stock for every item or raise OutOfStock."""
        for item in items:
            if not self.is_available(item.sku, item.quantity):
                raise OutOfStock(
                    f"insufficient stock for {item.sku}: "
                    f"want {item.quantity}, have {self.stock_for(item.sku)}")
        for item in items:
            self._stock[item.sku] = self.stock_for(item.sku) - item.quantity

    def release(self, items: list[OrderItem]) -> None:
        """Return previously reserved stock (rollback path)."""
        for item in items:
            self._stock[item.sku] = self.stock_for(item.sku) + item.quantity
