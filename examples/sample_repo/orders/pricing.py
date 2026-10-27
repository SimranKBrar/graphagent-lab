"""Pricing rules: subtotal, tax and shipping."""
from .models import OrderItem

TAX_RATE = 0.08
SHIPPING_PER_ORDER = 4.99
FREE_SHIPPING_THRESHOLD = 100.0


def compute_subtotal(items: list[OrderItem]) -> float:
    return round(sum(item.subtotal for item in items), 2)


def compute_tax(subtotal: float) -> float:
    return round(subtotal * TAX_RATE, 2)


def compute_shipping(subtotal: float) -> float:
    return 0.0 if subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_PER_ORDER


def compute_total(items: list[OrderItem]) -> float:
    subtotal = compute_subtotal(items)
    return round(subtotal + compute_tax(subtotal) + compute_shipping(subtotal), 2)
