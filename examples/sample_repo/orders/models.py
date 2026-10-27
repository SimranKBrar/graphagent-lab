"""Domain models for orders and order items."""
from dataclasses import dataclass, field


@dataclass
class OrderItem:
    sku: str
    quantity: int
    unit_price: float

    @property
    def subtotal(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Order:
    customer_id: str
    items: list[OrderItem] = field(default_factory=list)
    total: float = 0.0
    order_id: str | None = None
