"""Hidden test for line-tax-allocation: the discount is spread over the lines exactly, tax is per line."""

import random
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

import pytest

from tallyho import Customer, Money, Order, Product
from tallyho.pricing import TaxTable, apply_discounts, default_tax_table, quote_order
from tallyho.pricing.coupons import Coupon, CouponBook

DAY = date(2026, 1, 1)


def _customer(region="US-CA"):
    return Customer("c1", "Alice", "alice@example.com", region)


def _order(*lines, codes=(), region="US-CA"):
    o = Order("o1", _customer(region))
    for i, (cents, qty, category, taxable) in enumerate(lines):
        o.add(Product(f"P-{i}", f"product {i}", Money(cents), category, taxable), qty)
    o.coupon_codes = list(codes)
    return o


def _reference(order, book, taxes):
    """The spec, written out independently of tallyho's quote code."""
    subtotal = order.subtotal
    discounts = book.discounts_for(order.coupon_codes, subtotal, order.customer.tier, DAY)
    discounted, _ = apply_discounts(subtotal, discounts)
    off = subtotal.minor - discounted.minor
    subs = [l.subtotal.minor for l in order.lines]
    if subtotal.minor:
        exact = [Fraction(off * s, subtotal.minor) for s in subs]
    else:
        exact = [Fraction(0) for _ in subs]
    shares = [int(x) for x in exact]  # floor: the values are non-negative
    left = off - sum(shares)
    by_remainder = sorted(range(len(subs)), key=lambda i: (-(exact[i] - shares[i]), i))
    for i in by_remainder[:left]:
        shares[i] += 1
    assert sum(shares) == off
    rate = taxes.rate(order.customer.region)
    out = []
    for line, sub, share in zip(order.lines, subs, shares):
        p = line.product
        if p.taxable and p.category not in taxes.exempt_categories:
            tax = int((Decimal(sub - share) * rate / 100).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
        else:
            tax = 0
        out.append((p.sku, tax))
    return discounted.minor, out


def _check(order, book=None, taxes=None):
    book = book or CouponBook()
    taxes = taxes or default_tax_table()
    q = quote_order(order, book, taxes, today=DAY)
    discounted, expected = _reference(order, book, taxes)
    assert [(sku, m.minor) for sku, m in q.line_taxes] == expected
    assert all(isinstance(m, Money) and m.currency == order.currency for _, m in q.line_taxes)
    assert q.tax.minor == sum(t for _, t in expected)
    assert q.discounted.minor == discounted
    assert q.total.minor == discounted + q.tax.minor
    return q


def test_the_shipped_example_still_quotes_the_same():
    q = _check(_order((1250, 2, "kitchen", True), (2000, 1, "books", True)))
    assert [(sku, m.minor) for sku, m in q.line_taxes] == [("P-0", 181), ("P-1", 0)]
    assert q.tax.minor == 181 and q.total.minor == 4681


def test_left_over_cents_go_to_the_largest_remainders_then_the_earlier_line():
    # 1.00 off three equal lines: shares 34, 33, 33; at 50 % that is 483 + 484 + 484
    taxes = TaxTable(rates={"US-CA": Decimal(50)})
    book = CouponBook([Coupon("ONE", "fixed", "1.00")])
    q = _check(_order((1000, 1, "general", True), (1000, 1, "general", True), (1000, 1, "general", True),
                      codes=["ONE"]), book, taxes)
    assert [m.minor for _, m in q.line_taxes] == [483, 484, 484]
    assert q.tax.minor == 1451


def test_largest_remainder_wins_over_position():
    # 10 % off 9.99 + 0.01 + 5.00: exact shares 99.9, 0.1, 50 -> 100, 0, 50
    q = _check(_order((999, 1, "general", True), (1, 1, "general", True), (500, 1, "books", True),
                      codes=["TEN"]), CouponBook([Coupon("TEN", "percent", "10")]))
    assert [m.minor for _, m in q.line_taxes] == [65, 0, 0]


def test_untaxable_products_and_exempt_categories_pay_no_tax():
    taxes = TaxTable(rates={"US-CA": Decimal(10)}, exempt_categories=frozenset({"food"}))
    q = _check(_order((1000, 1, "food", True), (1000, 1, "general", False), (1000, 1, "books", True)), None, taxes)
    assert [m.minor for _, m in q.line_taxes] == [0, 0, 100]


def test_a_free_order_and_an_empty_order():
    q = _check(_order((0, 3, "general", True)))
    assert [m.minor for _, m in q.line_taxes] == [0] and q.tax.minor == 0
    q = quote_order(Order("o2", _customer()), today=DAY)
    assert q.line_taxes == [] and q.tax.minor == 0


def test_a_discount_bigger_than_the_order():
    book = CouponBook([Coupon("BIG", "fixed", "500.00")])
    q = _check(_order((1999, 2, "general", True), (1, 1, "general", True), codes=["BIG"]), book)
    assert q.discounted.minor == 0 and q.tax.minor == 0


@pytest.mark.parametrize("seed", range(40))
def test_random_orders_follow_the_spec(seed):
    rng = random.Random(seed)
    lines = [(rng.choice([0, 1, 7, 99, 333, 1250, 1999, 4567]), rng.randint(1, 4),
              rng.choice(["general", "kitchen", "books", "food"]), rng.random() < 0.8)
             for _ in range(rng.randint(1, 6))]
    book = CouponBook([Coupon("P", "percent", rng.choice(["5", "12.5", "33", "50"])),
                       Coupon("F", "fixed", rng.choice(["0.01", "1.00", "3.33", "17.00"]))])
    codes = rng.choice([[], ["P"], ["F"], ["P", "F"]])
    region = rng.choice(["US-CA", "US-NY", "US-TX", "GB", "DE"])
    _check(_order(*lines, codes=codes, region=region), book)
