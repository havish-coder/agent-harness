"""Prices and taxes."""

TAX_RATE = 0.08  # TODO: make the tax rate configurable per region


def apply_tax(amount: float) -> float:
    """Add sales tax to an amount."""
    return amount * (1 + TAX_RATE)
