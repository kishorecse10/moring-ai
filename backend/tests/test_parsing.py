from datetime import date
from decimal import Decimal

import pytest

from ledgerline.parsing import parse_amount, parse_date


def test_parse_amount_indian_grouping():
    assert parse_amount("1,23,456.00") == Decimal("123456.00")


def test_parse_amount_rupee_symbol():
    assert parse_amount("₹ 2,480.00") == Decimal("2480.00")


def test_parse_amount_numbers_become_exact_decimals():
    # Was: returned the float 1789.2. Policy section 1: never binary floating point.
    assert parse_amount(1789.2) == Decimal("1789.20")
    assert isinstance(parse_amount("1,789.20"), Decimal)


def test_parse_amount_empty_is_none():
    assert parse_amount("") is None


def test_parse_amount_lakh_and_crore():
    # dev_005 prints "₹1.2 lakh"; the starter raised ValueError and the batch silently dropped the invoice.
    assert parse_amount("₹1.2 lakh") == Decimal("120000.00")
    assert parse_amount("2 crore") == Decimal("20000000.00")


def test_parse_amount_rs_prefix_and_slash_dash_suffix():
    assert parse_amount("Rs. 66,375/-") == Decimal("66375.00")
    assert parse_amount("INR 5,00,000.00") == Decimal("500000.00")


def test_parse_amount_negative_round_off():
    assert parse_amount("-0.40") == Decimal("-0.40")


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_amount("see attached")


def test_sums_are_exact():
    # 0.1 + 0.2 != 0.3 in floats; totals checks must not depend on that.
    assert parse_amount("0.10") + parse_amount("0.20") == parse_amount("0.30")


def test_parse_date_iso():
    assert parse_date("2026-04-25") == date(2026, 4, 25)


def test_parse_date_with_slashes_is_day_first():
    # Was: asserted 2026-03-04 (dateutil's month-first guess). Policy section 1: Indian vendors print day first.
    # dev_002 is dated 03/04/2026, which is 3 April 2026 (FY 2026-27), not 4 March (FY 2025-26).
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_parse_date_dashes_and_dots():
    assert parse_date("11-04-2026") == date(2026, 4, 11)
    assert parse_date("05.04.2026") == date(2026, 4, 5)


def test_parse_date_month_first_for_us_vendors():
    # dev_014 (CloudNimbus, US) prints 04/03/2026 for 3 April 2026.
    assert parse_date("04/03/2026", month_first=True) == date(2026, 4, 3)


def test_parse_date_day_first_when_unambiguous():
    assert parse_date("25/04/2026") == date(2026, 4, 25)


def test_parse_date_with_month_name():
    assert parse_date("6 Apr 2026") == date(2026, 4, 6)


def test_parse_date_rejects_impossible_dates():
    with pytest.raises(ValueError):
        parse_date("25/13/2026")
