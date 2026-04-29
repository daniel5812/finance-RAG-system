"""
Tests for financial_statement_extractor.py (Step 5C).

Covers:
- Full Hebrew sample extraction
- Partial extraction (some fields None)
- All fields missing → None returned
- Malformed amounts → field None, no raise
- Invalid dates → None
- Wrong doc_type → None
- Empty/whitespace text → None
- Account number formats
- Provider aliases (Hebrew + English transliterations)
- Line-based equity exposure matching
- Line-based FX exposure matching
- תשואה must NOT be parsed as investment_gains amount
- owner_id isolation is a DB concern — tested at crud level; extractor is stateless
"""

import pytest
from documents.financial_statement_extractor import (
    extract_financial_statement,
    FinancialStatementData,
    _parse_date,
    _parse_amount,
)


# ── Sample text fixtures ──────────────────────────────────────────────────────

FULL_HEBREW_SAMPLE = """
מגדל קופות גמל ופנסיה בע"מ
דוח שנתי לשנת 2024

קופת גמל
מספר חשבון העמית: 12345-678
תאריך הדוח: 31/12/2024

תקופת הדוח: 01/01/2024 - 31/12/2024

מסלול ההשקעה: מסלול מנייתי

יתרה לסוף התקופה: 285,000.00 ₪
הפקדות במהלך השנה: 24,000.00 ₪
רווחי השקעה: 18,500.00 ₪
דמי ניהול: 1,200.00 ₪

הרכב תיק ההשקעות:
מניות 65.50%
מט"ח 12.30%
אגרות חוב 22.20%
"""

PARTIAL_SAMPLE = """
הפניקס ביטוח בע"מ
קרן פנסיה

יתרה לסוף התקופה: 150,000 ₪
הפקדות במהלך השנה: 18,000 ₪
"""

NO_SIGNALS_SAMPLE = """
This document contains no financial keywords whatsoever.
Just some random plain text that should yield no extraction.
"""

TASHOA_TRAP_SAMPLE = """
מגדל קופות גמל

קופת גמל
מספר חשבון: 9999-111

תשואה: 8.50%
רווחים בניכוי הוצאות ניהול השקעות: 22,000.00 ₪
"""


# ── Full extraction ───────────────────────────────────────────────────────────

def test_full_extraction_provider():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.provider == "מגדל"


def test_full_extraction_account_type():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.account_type == "gemel"


def test_full_extraction_account_number():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.account_number == "12345-678"


def test_full_extraction_report_date():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.report_date == "2024-12-31"


def test_full_extraction_period():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.period_start == "2024-01-01"
    assert result.period_end == "2024-12-31"


def test_full_extraction_ending_balance():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.ending_balance == pytest.approx(285000.00)


def test_full_extraction_annual_deposits():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.annual_deposits == pytest.approx(24000.00)


def test_full_extraction_investment_gains():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.investment_gains == pytest.approx(18500.00)


def test_full_extraction_management_fees():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.management_fees == pytest.approx(1200.00)


def test_full_extraction_track_name():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.track_name is not None
    assert "מנייתי" in result.track_name


def test_full_extraction_equity_exposure():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.equity_exposure_pct == pytest.approx(65.50)


def test_full_extraction_fx_exposure():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "savings_statement")
    assert result is not None
    assert result.fx_exposure_pct == pytest.approx(12.30)


# ── Partial extraction ────────────────────────────────────────────────────────

def test_partial_extraction_returns_non_none():
    result = extract_financial_statement(PARTIAL_SAMPLE, "savings_statement")
    assert result is not None


def test_partial_extraction_has_found_fields():
    result = extract_financial_statement(PARTIAL_SAMPLE, "savings_statement")
    assert result.provider == "הפניקס"
    assert result.account_type == "pension"
    assert result.ending_balance == pytest.approx(150000.00)
    assert result.annual_deposits == pytest.approx(18000.00)


def test_partial_extraction_missing_fields_are_none():
    result = extract_financial_statement(PARTIAL_SAMPLE, "savings_statement")
    assert result.account_number is None
    assert result.report_date is None
    assert result.period_start is None
    assert result.period_end is None
    assert result.investment_gains is None
    assert result.management_fees is None
    assert result.track_name is None
    assert result.equity_exposure_pct is None
    assert result.fx_exposure_pct is None


# ── All missing → None ────────────────────────────────────────────────────────

def test_all_missing_returns_none():
    result = extract_financial_statement(NO_SIGNALS_SAMPLE, "savings_statement")
    assert result is None


# ── Wrong doc_type → None ─────────────────────────────────────────────────────

def test_wrong_doc_type_broker_returns_none():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "broker_statement")
    assert result is None


def test_wrong_doc_type_portfolio_returns_none():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "portfolio_statement")
    assert result is None


def test_wrong_doc_type_unknown_returns_none():
    result = extract_financial_statement(FULL_HEBREW_SAMPLE, "unknown")
    assert result is None


# ── Empty / whitespace text → None ───────────────────────────────────────────

def test_empty_string_returns_none():
    result = extract_financial_statement("", "savings_statement")
    assert result is None


def test_whitespace_only_returns_none():
    result = extract_financial_statement("   \n\n\t  ", "savings_statement")
    assert result is None


# ── Malformed amounts → field None, no raise ─────────────────────────────────

def test_malformed_amount_rejected():
    val = _parse_amount("abc")
    assert val is None


def test_malformed_amount_negative_rejected():
    val = _parse_amount("-500")
    assert val is None


def test_malformed_amount_zero_rejected():
    val = _parse_amount("0")
    assert val is None


def test_malformed_amount_too_large_rejected():
    val = _parse_amount("200,000,000")
    assert val is None


def test_malformed_amount_double_decimal_rejected():
    # e.g., "1.234.567" — float() will fail
    val = _parse_amount("1.234.567")
    assert val is None


def test_valid_amount_with_shekel_symbol():
    val = _parse_amount("50,000.00")
    assert val == pytest.approx(50000.00)


def test_valid_amount_no_symbol():
    val = _parse_amount("12345.67")
    assert val == pytest.approx(12345.67)


def test_extractor_does_not_raise_on_malformed_text():
    # Even with garbage text, extract_financial_statement must never raise
    garbage = "₪₪₪ 99999999999999999 !!! --- 00/00/0000"
    result = extract_financial_statement(garbage, "savings_statement")
    # Either None or a partial result — both valid; the key is no exception
    assert result is None or isinstance(result, FinancialStatementData)


# ── Invalid dates → None ─────────────────────────────────────────────────────

def test_invalid_date_impossible_day():
    result = _parse_date("32/01/2024")
    assert result is None


def test_invalid_date_impossible_month():
    result = _parse_date("01/13/2024")
    assert result is None


def test_valid_date_slash_format():
    result = _parse_date("31/12/2024")
    assert result == "2024-12-31"


def test_valid_date_dot_format():
    result = _parse_date("01.06.2023")
    assert result == "2023-06-01"


# ── Account number formats ────────────────────────────────────────────────────

def test_account_number_with_hebrew_label():
    text = "מספר חשבון העמית: 12345-678\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_number == "12345-678"


def test_account_number_with_english_label():
    text = "account number: 98765-4321\nסavings statement"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_number == "98765-4321"


def test_account_number_short_label():
    text = "מספר חשבון: 55555\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_number == "55555"


# ── Provider aliases ──────────────────────────────────────────────────────────

def test_provider_altschuler_shaham_hebrew():
    text = "אלטשולר שחם קופות גמל\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "אלטשולר שחם"


def test_provider_phoenix_hebrew():
    text = "הפניקס ביטוח\nקרן פנסיה"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "הפניקס"


def test_provider_menora_hebrew():
    text = "מנורה מבטחים\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "מנורה"


def test_provider_meitav_dash_hebrew():
    text = "מיטב דש קופות גמל\nקרן השתלמות"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "מיטב דש"


def test_provider_meitav_without_dash():
    text = "מיטב השקעות\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "מיטב"


def test_provider_harel_hebrew():
    text = "הראל ביטוח\nקרן פנסיה"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "הראל"


def test_provider_clal_hebrew():
    text = "כלל ביטוח\nקופת גמל"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.provider == "כלל"


# ── Line-based equity exposure ────────────────────────────────────────────────

def test_equity_exposure_extracted_from_correct_line():
    text = "קופת גמל\nמניות 72.00%\nאגרות חוב 28.00%"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.equity_exposure_pct == pytest.approx(72.00)


def test_equity_exposure_does_not_use_bond_line_percentage():
    # Bond line has its own percentage — equity must come from the מניות line
    text = "קופת גמל\nמניות 45.00%\nאגרות חוב 55.00%"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.equity_exposure_pct == pytest.approx(45.00)


def test_equity_exposure_none_when_line_absent():
    text = "קופת גמל\nאגרות חוב 100.00%"
    result = extract_financial_statement(text, "savings_statement")
    # May be None or partial; equity specifically must be None
    if result is not None:
        assert result.equity_exposure_pct is None


# ── Line-based FX exposure ────────────────────────────────────────────────────

def test_fx_exposure_extracted_from_correct_line():
    text = 'קופת גמל\nמט"ח 15.50%\nמניות 84.50%'
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.fx_exposure_pct == pytest.approx(15.50)


def test_fx_exposure_english_keyword():
    text = "savings statement\nforeign currency 8.25%\nequity 91.75%"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.fx_exposure_pct == pytest.approx(8.25)


def test_fx_exposure_none_when_line_absent():
    text = "קופת גמל\nמניות 100.00%"
    result = extract_financial_statement(text, "savings_statement")
    if result is not None:
        assert result.fx_exposure_pct is None


# ── תשואה must NOT be parsed as investment_gains amount ──────────────────────

def test_tashoa_not_parsed_as_investment_gains():
    """
    תשואה is a percentage return, not a monetary gain.
    It must never populate investment_gains.
    Only רווחי השקעה / רווחים בניכוי הוצאות ניהול השקעות / investment gains are valid anchors.
    """
    text = """
מגדל קופות גמל
קופת גמל

תשואה: 8.50%
"""
    result = extract_financial_statement(text, "savings_statement")
    # Either None (nothing else found) or investment_gains is None
    if result is not None:
        assert result.investment_gains is None


def test_tashoa_present_but_real_anchor_extracted():
    """
    When both תשואה and a valid gains anchor appear, only the valid anchor is used.
    """
    result = extract_financial_statement(TASHOA_TRAP_SAMPLE, "savings_statement")
    assert result is not None
    assert result.investment_gains == pytest.approx(22000.00)


# ── Account type variants ─────────────────────────────────────────────────────

def test_account_type_hishtalmut():
    text = "מגדל\nקרן השתלמות"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_type == "hishtalmut"


def test_account_type_gemel_lehashkaa():
    text = "כלל\nקופת גמל להשקעה"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_type == "gemel_lehashkaa"


def test_account_type_pension():
    text = "הראל\nקרן פנסיה"
    result = extract_financial_statement(text, "savings_statement")
    assert result is not None
    assert result.account_type == "pension"
