from dataclasses import replace

from tallyho.models import Customer, Order, Product
from tallyho.money import Money
from tallyho.repository import Repository
from tallyho.store import MemoryStore


def _shop(price="10.00", currency="USD"):
    repo = Repository(MemoryStore())
    mug = Product("MUG-1", "Blue mug", Money.of(price, currency), "kitchen")
    alice = Customer("c1", "Alice", "alice@example.com", "US-CA")
    repo.save_product(mug)
    repo.save_customer(alice)
    order = Order("o1", alice)
    order.add(mug, 2)
    repo.save_order(order)
    return repo, mug


def test_reloaded_order_keeps_the_price_it_was_saved_with():
    repo, mug = _shop()
    repo.save_product(replace(mug, price=Money.of("12.50")))
    o = repo.order("o1")
    assert o.lines[0].product.price == Money.of("10.00")
    assert o.subtotal == Money.of("20.00")


def test_other_product_fields_come_from_the_current_record():
    repo, mug = _shop()
    repo.save_product(replace(mug, name="Large blue mug", price=Money.of("12.50"), category="gifts"))
    p = repo.order("o1").lines[0].product
    assert (p.name, p.category, p.price) == ("Large blue mug", "gifts", Money.of("10.00"))


def test_lines_record_their_currency():
    _, mug = _shop(currency="EUR")
    o = Order("o2", Customer("c2", "Bo", "bo@example.com", "DE"))
    o.add(mug, 1)
    (line,) = o.to_dict()["lines"]
    assert line["price"] == 1000 and line["currency"] == "EUR"


def test_saved_currency_survives_a_currency_change_of_the_product():
    repo, mug = _shop(currency="EUR")
    repo.save_product(replace(mug, price=Money.of("5.00", "USD")))
    o = repo.order("o1")
    assert o.lines[0].product.price == Money.of("10.00", "EUR")
    assert o.subtotal == Money.of("20.00", "EUR")


def test_records_saved_before_prices_were_kept_use_the_current_product():
    repo, mug = _shop()
    rec = repo.store.get("orders", "o1")
    for line in rec["lines"]:
        del line["price"]
        line.pop("currency", None)
    repo.store.put("orders", rec)
    repo.save_product(replace(mug, price=Money.of("12.50")))
    assert repo.order("o1").subtotal == Money.of("25.00")


def test_a_record_with_a_price_but_no_currency_uses_the_products_currency():
    repo, mug = _shop(currency="EUR")
    rec = repo.store.get("orders", "o1")
    for line in rec["lines"]:
        line.pop("currency", None)
    repo.store.put("orders", rec)
    repo.save_product(replace(mug, price=Money.of("12.50", "EUR")))
    assert repo.order("o1").lines[0].product.price == Money.of("10.00", "EUR")
