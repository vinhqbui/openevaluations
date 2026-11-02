from decimal import Decimal

import pytest

from tallyho.config import load_config
from tallyho.errors import ConfigError


def _cfg(tmp_path, text):
    p = tmp_path / "shop.ini"
    p.write_text(text, encoding="utf-8")
    return p


def test_percent_signs_are_literal(tmp_path):
    cfg = load_config(_cfg(tmp_path, "[shop]\nname = Half % Off\nstore_dir = data/%(user)s\n"))
    assert cfg.shop_name == "Half % Off"
    assert str(cfg.store_dir).replace("\\", "/") == "data/%(user)s"


def test_known_currency_is_upper_cased(tmp_path):
    assert load_config(_cfg(tmp_path, "[shop]\ncurrency = eur\n")).currency == "EUR"


@pytest.mark.parametrize("value", ["XYZ", "dollars", ""])
def test_unknown_currency_is_a_config_error(tmp_path, value):
    with pytest.raises(ConfigError, match="(?i)currency"):
        load_config(_cfg(tmp_path, f"[shop]\ncurrency = {value}\n"))


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5"])
def test_page_size_must_be_a_positive_integer(tmp_path, value):
    with pytest.raises(ConfigError, match="page_size"):
        load_config(_cfg(tmp_path, f"[shop]\npage_size = {value}\n"))


def test_valid_page_size(tmp_path):
    assert load_config(_cfg(tmp_path, "[shop]\npage_size = 25\n")).page_size == 25


@pytest.mark.parametrize("value", ["0", "6.5", "100"])
def test_tax_rates_from_0_to_100_are_kept(tmp_path, value):
    cfg = load_config(_cfg(tmp_path, f"[tax]\nus-wa = {value}\n"))
    assert cfg.taxes.rates["US-WA"] == Decimal(value)


@pytest.mark.parametrize("value", ["-1", "100.5", "nan", "inf", "seven"])
def test_bad_tax_rate_is_a_config_error_naming_the_region(tmp_path, value):
    with pytest.raises(ConfigError) as e:
        load_config(_cfg(tmp_path, f"[tax]\nus-wa = {value}\n"))
    assert "us-wa" in str(e.value).lower()


def test_unreadable_file_is_still_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.ini")
