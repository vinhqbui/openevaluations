"""Hidden test for refund-orders: Workflow.refund reverses the sale exactly as it was recorded."""

from datetime import date

import pytest

from tallyho import Customer, Money, Order, Product
from tallyho.errors import ValidationError
from tallyho.events import EventBus
from tallyho.ledger import Ledger
from tallyho.models import OrderStatus
from tallyho.pricing.coupons import Coupon, CouponBook
from tallyho.repository import Repository
from tallyho.store import MemoryStore
from tallyho.workflow import Workflow

MUG = Product("MUG-1", "Blue mug", Money.of("12.50"), "kitchen")
BOOK = Product("BOOK-7", "Field guide", Money.of("20.00"), "books")
ALICE = Customer("c1", "Alice", "alice@example.com", "US-CA")


def _order(oid="o1", codes=()):
    o = Order(oid, ALICE)
    o.add(MUG, 3)
    o.add(BOOK, 1)
    o.coupon_codes = list(codes)
    return o


def _balances(ledger):
    return {k: v.minor for k, v in ledger.balances().items()}


def _all_zero(ledger):
    return all(v == 0 for v in _balances(ledger).values())


def _paid(wf, order, placed=date(2026, 1, 1), paid=date(2026, 1, 10)):
    wf.place(order, placed)
    wf.pay(order, paid)
    return _balances(wf.ledger)


def test_refund_reverses_the_sale_and_publishes_the_event():
    bus = EventBus()
    wf = Workflow(Ledger(), bus)
    o = _order()
    sold = _paid(wf, o)
    assert sold["cash"] != 0
    before = len(wf.ledger.entries)
    wf.refund(o, date(2026, 2, 1))
    assert o.status is OrderStatus.REFUNDED and OrderStatus.REFUNDED.value == "refunded"
    assert bus.history[-1] == ("order.refunded", {"id": "o1"})
    new = wf.ledger.entries[before:]
    assert {e.memo for e in new} == {"refund o1"} and {e.on for e in new} == {date(2026, 2, 1)}
    assert sum(e.debit.minor for e in new) == sum(e.credit.minor for e in new) > 0
    by = {e.account: e for e in new}
    assert by["cash"].credit.minor == sold["cash"] and by["cash"].debit.minor == 0
    assert by["revenue"].debit.minor == -sold["revenue"]
    assert by["tax_payable"].debit.minor == -sold["tax_payable"]
    assert _all_zero(wf.ledger)
    assert wf.ledger.trial_balance_ok()


def test_refund_uses_the_amounts_charged_even_after_the_coupon_expired():
    book = CouponBook([Coupon("JAN10", "percent", "10", expires=date(2026, 1, 15))])
    wf = Workflow(Ledger(), coupons=book)
    o = _order(codes=["JAN10"])
    sold = _paid(wf, o)
    assert sold["revenue"] == -(5750 - 575)  # the coupon applied on the pay date
    wf.refund(o, date(2026, 3, 1))
    assert _all_zero(wf.ledger)


def test_refund_uses_the_pay_date_not_the_placing_date():
    book = CouponBook([Coupon("NEWYEAR", "fixed", "5.00", expires=date(2026, 1, 5))])
    wf = Workflow(Ledger(), coupons=book)
    o = _order(codes=["NEWYEAR"])
    sold = _paid(wf, o, placed=date(2026, 1, 1), paid=date(2026, 1, 10))
    assert sold["revenue"] == -5750  # expired when paid, so no discount was charged
    wf.refund(o, date(2026, 1, 20))
    assert _all_zero(wf.ledger)


def test_refund_after_the_coupon_book_changed():
    wf = Workflow(Ledger(), coupons=CouponBook([Coupon("SAVE5", "fixed", "5.00")]))
    o = _order(codes=["SAVE5"])
    _paid(wf, o)
    wf.coupons = CouponBook()
    wf.refund(o, date(2026, 1, 11))
    assert _all_zero(wf.ledger)


def test_refund_through_another_workflow_on_the_same_ledger():
    ledger = Ledger()
    first = Workflow(ledger, coupons=CouponBook([Coupon("SAVE5", "fixed", "5.00")]))
    o = _order(codes=["SAVE5"])
    _paid(first, o)
    Workflow(ledger).refund(o, date(2026, 1, 12))
    assert o.status is OrderStatus.REFUNDED
    assert _all_zero(ledger)


def test_only_the_refunded_order_is_reversed():
    wf = Workflow(Ledger())
    a, b = _order("o1"), _order("o2")
    a.add(MUG, 1)
    _paid(wf, a)
    after_a = _balances(wf.ledger)
    _paid(wf, b)
    wf.refund(b, date(2026, 2, 1))
    assert _balances(wf.ledger) == after_a


def test_shipped_orders_can_be_refunded():
    wf = Workflow(Ledger())
    o = _order()
    _paid(wf, o)
    wf.ship(o)
    wf.refund(o, date(2026, 2, 1))
    assert o.status is OrderStatus.REFUNDED and _all_zero(wf.ledger)


@pytest.mark.parametrize("state", ["draft", "placed", "cancelled", "refunded"])
def test_refunding_an_order_in_any_other_status_changes_nothing(state):
    bus = EventBus()
    wf = Workflow(Ledger(), bus)
    o = _order()
    if state == "placed":
        wf.place(o, date(2026, 1, 1))
    elif state == "cancelled":
        wf.cancel(o)
    elif state == "refunded":
        _paid(wf, o)
        wf.refund(o, date(2026, 2, 1))
    status, entries, events = o.status, list(wf.ledger.entries), list(bus.history)
    with pytest.raises(ValidationError):
        wf.refund(o, date(2026, 3, 1))
    assert o.status is status and wf.ledger.entries == entries and bus.history == events


def test_a_refunded_order_cannot_move_again():
    wf = Workflow(Ledger())
    o = _order()
    _paid(wf, o)
    wf.refund(o, date(2026, 2, 1))
    for move in (wf.ship, wf.cancel):
        with pytest.raises(ValidationError):
            move(o)
    with pytest.raises(ValidationError):
        wf.pay(o, date(2026, 2, 2))
    assert o.status is OrderStatus.REFUNDED


def test_refunded_orders_round_trip_through_the_repository():
    repo = Repository(MemoryStore())
    repo.save_product(MUG)
    repo.save_product(BOOK)
    repo.save_customer(ALICE)
    wf = Workflow(Ledger())
    o = _order()
    _paid(wf, o)
    wf.refund(o, date(2026, 2, 1))
    repo.save_order(o)
    assert repo.order("o1").status is OrderStatus.REFUNDED
    assert [x.id for x in repo.orders(OrderStatus.REFUNDED)] == ["o1"]
