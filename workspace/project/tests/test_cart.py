from shop.cart import Cart


def test_subtotal_counts_quantity():
    cart = Cart()
    cart.add("pen", 2.0, quantity=3)
    assert cart.subtotal() == 6.0


def test_total_with_discount():
    cart = Cart()
    cart.add("book", 10.0)
    assert cart.total(discount_percent=10) == 9.72
