"""A shopping cart."""
from shop.pricing import apply_tax


class Cart:
    def __init__(self):
        self.items = []  # (name, unit_price, quantity)

    def add(self, name: str, unit_price: float, quantity: int = 1) -> None:
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        self.items.append((name, unit_price, quantity))

    def subtotal(self) -> float:
        return sum(price for _, price, qty in self.items)

    def total(self, discount_percent: float = 0) -> float:
        discounted = self.subtotal() * (1 - discount_percent / 100)
        return round(apply_tax(discounted), 2)
