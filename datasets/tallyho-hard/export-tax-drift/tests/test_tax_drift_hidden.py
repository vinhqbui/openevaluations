"""Hidden test for export-tax-drift: every tax table is independent of the others."""

from datetime import date
from decimal import Decimal

import pytest

from tallyho import Customer, Money, Order, Product
from tallyho.config import Config, load_config
from tallyho.pricing import default_tax_table, quote_order
from tallyho.report import orders_to_csv

DAY = date(2026, 1, 1)


@pytest.fixture
def order():
    o = Order("o1", Customer("c1", "Alice", "alice@example.com", "US-CA"))
    o.add(Product("MUG-1", "Blue mug", Money.of("12.50"), "kitchen"), 2)
    o.add(Product("BOOK-7", "Field guide", Money.of("20.00"), "books"), 1)
    return o


@pytest.fixture
def shops(tmp_path):
    a = tmp_path / "a.ini"
    a.write_text("[shop]\nname = Shop A\n\n[tax]\nus-ca = 10\nxx = 5\n", encoding="utf-8")
    b = tmp_path / "b.ini"
    b.write_text("[shop]\nname = Shop B\n", encoding="utf-8")
    return a, b


def test_a_config_quotes_with_its_own_rates(order, shops):
    a = load_config(shops[0])
    assert quote_order(order, taxes=a.taxes, today=DAY).tax.minor == 250  # 25.00 at 10 %


def test_a_later_config_does_not_get_an_earlier_configs_rates(shops):
    a = load_config(shops[0])
    b = load_config(shops[1])
    assert b.taxes.rate("US-CA") == Decimal("7.25")
    assert b.taxes.rate("XX") == Decimal(0)
    assert a.taxes.rate("US-CA") == Decimal(10) and a.taxes.rate("XX") == Decimal(5)


def test_quotes_without_a_table_keep_the_shipped_rates_after_a_config_is_loaded(order, shops):
    load_config(shops[0])
    assert quote_order(order, today=DAY).tax.minor == 181  # 25.00 at 7.25 %
    assert default_tax_table().rate("US-CA") == Decimal("7.25")
    assert default_tax_table().rate("XX") == Decimal(0)


def test_the_csv_export_keeps_the_shipped_rates_after_a_config_is_loaded(order, shops):
    load_config(shops[0])
    load_config(shops[1])
    assert orders_to_csv([order]).splitlines()[1] == "o1,Alice,draft,3,45.00,46.81,USD"


def test_changing_a_default_configs_rates_changes_no_other_table(order):
    Config().taxes.rates["US-CA"] = Decimal(1)
    assert Config().taxes.rate("US-CA") == Decimal("7.25")
    assert default_tax_table().rate("US-CA") == Decimal("7.25")
    assert quote_order(order, today=DAY).tax.minor == 181


def test_changing_a_default_table_changes_no_other_table(order, shops):
    t = default_tax_table()
    t.rates["US-CA"] = Decimal(50)
    t.rates["GB"] = Decimal(0)
    assert default_tax_table().rate("GB") == Decimal(20)
    assert Config().taxes.rate("US-CA") == Decimal("7.25")
    assert load_config(shops[1]).taxes.rate("US-CA") == Decimal("7.25")
    assert quote_order(order, today=DAY).tax.minor == 181
