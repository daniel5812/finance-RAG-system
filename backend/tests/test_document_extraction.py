"""
Tests for deterministic holdings extraction (Step 5B).

Pure-unit — no DB, no network, no file I/O.
All tests call extract_holdings() directly.
"""

import pytest
from documents.extractor import extract_holdings, CandidateHolding


# ── Eligible doc types ────────────────────────────────────────────────────────

def test_broker_statement_extraction_runs():
    holdings = extract_holdings("AAPL 100 185.32", "broker_statement")
    assert len(holdings) == 1
    assert holdings[0].ticker == "AAPL"


def test_portfolio_statement_extraction_runs():
    holdings = extract_holdings("MSFT 50 415.20", "portfolio_statement")
    assert len(holdings) == 1
    assert holdings[0].ticker == "MSFT"


def test_bank_statement_returns_empty():
    holdings = extract_holdings("AAPL 100 185.32", "bank_statement")
    assert holdings == []


def test_financial_report_returns_empty():
    holdings = extract_holdings("AAPL 100 185.32", "financial_report")
    assert holdings == []


def test_unknown_doc_type_returns_empty():
    holdings = extract_holdings("AAPL 100 185.32", "unknown")
    assert holdings == []


def test_generic_financial_doc_returns_empty():
    holdings = extract_holdings("AAPL 100 185.32", "generic_financial_doc")
    assert holdings == []


# ── Valid extraction ──────────────────────────────────────────────────────────

def test_ticker_and_quantity_extracted_high_confidence():
    holdings = extract_holdings("AAPL 100 185.32 18532.00", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity == 100.0
    assert holdings[0].confidence == "high"


def test_quantity_with_commas_parsed():
    holdings = extract_holdings("MSFT 1,000 415.20", "broker_statement")
    assert holdings[0].quantity == 1000.0
    assert holdings[0].confidence == "high"


def test_quantity_with_dollar_sign_parsed():
    holdings = extract_holdings("TSLA $50 250.00", "broker_statement")
    # $50 stripped → 50.0
    assert holdings[0].quantity == 50.0


def test_fractional_quantity_parsed():
    holdings = extract_holdings("BRK 0.5 600000.00", "broker_statement")
    assert holdings[0].quantity == 0.5
    assert holdings[0].confidence == "high"


def test_source_line_stored():
    """source_line must record the raw line for audit purposes."""
    holdings = extract_holdings("AAPL 100 185.32", "broker_statement")
    assert holdings[0].source_line == "AAPL 100 185.32"


def test_ticker_after_company_name():
    """Common format: 'Apple Inc. AAPL 100 185.32'."""
    holdings = extract_holdings("Apple Inc. AAPL 100 185.32", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity == 100.0


# ── Missing quantity → low confidence ────────────────────────────────────────

def test_missing_quantity_confidence_low():
    holdings = extract_holdings("AAPL no numeric tokens here", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity is None
    assert holdings[0].confidence == "low"


def test_ticker_only_line_low_confidence():
    holdings = extract_holdings("GOOGL", "broker_statement")
    # Line too short (< 8 chars) — should be rejected
    assert holdings == []


def test_ticker_with_only_noise_after_it():
    holdings = extract_holdings("AMZN Total Balance Sheet", "broker_statement")
    # 'Total', 'Balance', 'Sheet' are not valid quantities
    assert holdings[0].ticker == "AMZN"
    assert holdings[0].quantity is None
    assert holdings[0].confidence == "low"


# ── Ticker formats: plain, parenthesized, class shares ────────────────────────

def test_parenthesized_ticker_extracted():
    """Tickers in parentheses: (AAPL) 100."""
    holdings = extract_holdings("Apple Inc (AAPL) 100 185.32", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity == 100.0


def test_class_share_dot_notation():
    """Class shares with dot: BRK.B 2."""
    holdings = extract_holdings("Berkshire Hathaway BRK.B 2 600000.00", "broker_statement")
    assert holdings[0].ticker == "BRK.B"
    assert holdings[0].quantity == 2.0


def test_class_share_dash_notation_normalized():
    """Class shares with dash: BRK-B → normalized to BRK.B."""
    holdings = extract_holdings("Berkshire Hathaway BRK-B 2 600000.00", "broker_statement")
    assert holdings[0].ticker == "BRK.B"
    assert holdings[0].quantity == 2.0


def test_parenthesized_class_share():
    """Parenthesized class share: (BRK.B)."""
    holdings = extract_holdings("Berkshire (BRK.B) 2 600000", "broker_statement")
    assert holdings[0].ticker == "BRK.B"
    assert holdings[0].quantity == 2.0


# ── Ticker validation ─────────────────────────────────────────────────────────

def test_ticker_too_long_rejected():
    holdings = extract_holdings("TOOLONG 100 50.00", "broker_statement")
    assert not any(h.ticker == "TOOLONG" for h in holdings)


def test_lowercase_ticker_not_extracted():
    holdings = extract_holdings("aapl 100 185.32", "broker_statement")
    assert holdings == []


def test_mixed_case_ticker_not_extracted():
    holdings = extract_holdings("Aapl 100 185.32", "broker_statement")
    assert holdings == []


def test_noise_ticker_TOTAL_rejected():
    holdings = extract_holdings("TOTAL 5000 100000.00", "broker_statement")
    assert not any(h.ticker == "TOTAL" for h in holdings)


def test_noise_ticker_CASH_rejected():
    holdings = extract_holdings("CASH 10000 1.00", "broker_statement")
    assert not any(h.ticker == "CASH" for h in holdings)


def test_noise_ticker_FUND_rejected():
    holdings = extract_holdings("FUND 200 50.00", "broker_statement")
    assert not any(h.ticker == "FUND" for h in holdings)


def test_noise_ticker_ETF_rejected():
    holdings = extract_holdings("ETF 300 25.00", "broker_statement")
    assert not any(h.ticker == "ETF" for h in holdings)


def test_noise_ticker_NULL_rejected():
    holdings = extract_holdings("NULL 100 50.00", "broker_statement")
    assert not any(h.ticker == "NULL" for h in holdings)


# ── Quantity validation ───────────────────────────────────────────────────────

def test_zero_quantity_yields_low_confidence():
    holdings = extract_holdings("AAPL 0 185.32", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity is None
    assert holdings[0].confidence == "low"


def test_negative_quantity_skipped():
    """Negative token is not a valid share quantity."""
    holdings = extract_holdings("AAPL -50 185.00", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity is None


def test_quantity_too_large_skipped():
    """Implausibly large share count → quantity rejected, ticker kept."""
    holdings = extract_holdings("AAPL 9999999 185.00", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].quantity is None
    assert holdings[0].confidence == "low"


def test_percentage_quantity_rejected():
    """Percentage tokens must not be parsed as share quantity."""
    holdings = extract_holdings("AAPL 5% 185.00", "broker_statement")
    assert holdings[0].ticker == "AAPL"
    # 5% rejected → first valid qty is 185.00 or None
    # 185.00 is valid → quantity should be 185.00
    assert holdings[0].quantity == 185.00


# ── Noisy line rejection ──────────────────────────────────────────────────────

def test_line_too_short_rejected():
    """Lines under 8 chars → skipped."""
    holdings = extract_holdings("AB 10", "broker_statement")
    assert holdings == []


def test_total_line_rejected():
    holdings = extract_holdings("Total portfolio value 100000.00", "broker_statement")
    assert holdings == []


def test_subtotal_line_rejected():
    holdings = extract_holdings("Subtotal 50000.00", "broker_statement")
    assert holdings == []


def test_page_line_rejected():
    holdings = extract_holdings("Page 2 of 10", "broker_statement")
    assert holdings == []


def test_date_line_rejected():
    holdings = extract_holdings("Date 2024-01-01 statement", "broker_statement")
    assert holdings == []


def test_balance_line_rejected():
    holdings = extract_holdings("Balance 150000.00 current", "broker_statement")
    assert holdings == []


def test_cash_line_rejected():
    holdings = extract_holdings("Cash and equivalents 5000.00", "broker_statement")
    assert holdings == []


# ── Multi-line and edge cases ─────────────────────────────────────────────────

def test_multiple_holdings_extracted():
    text = "\n".join([
        "AAPL 100 185.32 18532.00",
        "MSFT 50 415.20 20760.00",
        "GOOGL 25 175.00 4375.00",
    ])
    holdings = extract_holdings(text, "broker_statement")
    tickers = [h.ticker for h in holdings]
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert "GOOGL" in tickers
    assert len(holdings) == 3


def test_duplicate_tickers_both_stored():
    """Duplicates are allowed — deduplication is a consumer concern."""
    text = "AAPL 100 185.32\nAAPL 200 186.00"
    holdings = extract_holdings(text, "broker_statement")
    aapl_holdings = [h for h in holdings if h.ticker == "AAPL"]
    assert len(aapl_holdings) == 2


def test_noisy_lines_mixed_with_valid():
    """Noisy lines are skipped; valid lines are extracted."""
    text = "\n".join([
        "Total portfolio 250000.00",
        "AAPL 100 185.32",
        "Page 1 of 5",
        "MSFT 50 415.20",
        "Balance 250000.00 USD",
    ])
    holdings = extract_holdings(text, "broker_statement")
    tickers = [h.ticker for h in holdings]
    assert tickers == ["AAPL", "MSFT"]


def test_empty_text_returns_empty():
    assert extract_holdings("", "broker_statement") == []


def test_whitespace_only_text_returns_empty():
    assert extract_holdings("   \n\n  ", "broker_statement") == []


def test_no_valid_lines_returns_empty():
    text = "Total 100000\nPage 1 of 5\nDate 2024-01-01 period end"
    assert extract_holdings(text, "broker_statement") == []


# ── Return type integrity ────────────────────────────────────────────────────

def test_returns_list_of_candidate_holdings():
    holdings = extract_holdings("AAPL 100 185.32", "broker_statement")
    assert isinstance(holdings, list)
    assert isinstance(holdings[0], CandidateHolding)


def test_confidence_only_high_or_low():
    text = "AAPL 100 185.32\nMSFT no qty here bla bla"
    holdings = extract_holdings(text, "broker_statement")
    for h in holdings:
        assert h.confidence in ("high", "low")
