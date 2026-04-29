"""
Tests for deterministic document classification (Step 5A).

Classification is content-only: extracted text only, filename ignored.
All tests are pure-unit — no DB, no network, no file I/O.
"""

import pytest
from documents.classifier import classify_document


# ── Broker statement ──────────────────────────────────────────────────────────

def test_broker_multiple_signals_high_confidence():
    """2+ keywords from same type → high confidence."""
    doc_type, confidence = classify_document(
        filename="misleading_name.pdf",  # Ignored
        text_snippet="Account statement and trade confirmation. Brokerage transaction history attached.",
    )
    assert doc_type == "broker_statement"
    assert confidence == "high"


def test_broker_single_signal_medium_confidence():
    """1 keyword from type → medium confidence."""
    doc_type, confidence = classify_document(
        filename="document.pdf",
        text_snippet="Your brokerage account summary for this quarter.",
    )
    assert doc_type == "broker_statement"
    assert confidence == "medium"


def test_broker_another_single_signal():
    """Another single-keyword test."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Your transaction history for this month.",
    )
    assert doc_type == "broker_statement"
    assert confidence == "medium"


# ── Portfolio statement ───────────────────────────────────────────────────────

def test_portfolio_multiple_signals_high_confidence():
    """2+ keywords from same type → high confidence."""
    doc_type, confidence = classify_document(
        filename="bank_statement.pdf",  # Misleading — should be ignored
        text_snippet="Portfolio statement showing your holdings and asset allocation across positions.",
    )
    assert doc_type == "portfolio_statement"
    assert confidence == "high"


def test_portfolio_single_signal_medium_confidence():
    """1 keyword from type → medium confidence."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Your investment summary for today.",
    )
    assert doc_type == "portfolio_statement"
    assert confidence == "medium"


def test_portfolio_holdings_keyword_single_signal():
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Current holdings in your account summary.",
    )
    assert doc_type == "portfolio_statement"
    assert confidence == "medium"


# ── Bank statement ────────────────────────────────────────────────────────────

def test_bank_multiple_signals_high_confidence():
    """2+ keywords from same type → high confidence."""
    doc_type, confidence = classify_document(
        filename="quarterly_earnings.pdf",  # Misleading — should be ignored
        text_snippet="Bank of America checking account statement. Deposits and withdrawals listed below.",
    )
    assert doc_type == "bank_statement"
    assert confidence == "high"


def test_bank_single_signal_medium_confidence():
    """1 keyword from type → medium confidence."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Your withdrawals and transfers for this month.",
    )
    assert doc_type == "bank_statement"
    assert confidence == "medium"


def test_bank_deposits_keyword_single_signal():
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Recent deposits and account activity summary.",
    )
    assert doc_type == "bank_statement"
    assert confidence == "medium"


# ── Financial report ─────────────────────────────────────────────────────────

def test_financial_report_multiple_signals_high_confidence():
    """2+ keywords from same type → high confidence."""
    doc_type, confidence = classify_document(
        filename="bank_statement.pdf",  # Misleading — ignored
        text_snippet="Annual report for fiscal year 2023. Earnings and balance sheet included.",
    )
    assert doc_type == "financial_report"
    assert confidence == "high"


def test_financial_report_single_signal_medium_confidence():
    """1 keyword from type → medium confidence."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="The quarterly report for Q3 2024.",
    )
    assert doc_type == "financial_report"
    assert confidence == "medium"


def test_financial_report_10k_keyword():
    """Single keyword from financial_report."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="SEC 10-Q filing.",
    )
    assert doc_type == "financial_report"
    assert confidence == "medium"


# ── Generic financial doc ─────────────────────────────────────────────────────

def test_generic_financial_2plus_weak_keywords():
    """No specific type + 2+ generic financial keywords → generic_financial_doc/medium."""
    doc_type, confidence = classify_document(
        filename="document.pdf",
        text_snippet="Your account balance and investment return are shown here.",
    )
    assert doc_type == "generic_financial_doc"
    assert confidence == "medium"


def test_generic_financial_multiple_weak_signals():
    doc_type, confidence = classify_document(
        filename="upload.pdf",
        text_snippet="Financial capital fund equity dividend statement.",
    )
    assert doc_type == "generic_financial_doc"
    assert confidence == "medium"


def test_generic_financial_less_than_2_keywords_is_unknown():
    """Only 1 generic keyword + no specific type → unknown/low."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Your balance this month.",
    )
    assert doc_type == "unknown"
    assert confidence == "low"


# ── Unknown / low confidence ─────────────────────────────────────────────────

def test_no_signals_returns_unknown():
    """No keywords at all → unknown/low."""
    doc_type, confidence = classify_document(
        filename="document.pdf",
        text_snippet="This is completely unrelated text with no financial content whatsoever.",
    )
    assert doc_type == "unknown"
    assert confidence == "low"


def test_empty_text_returns_unknown():
    """Empty text snippet → unknown/low."""
    doc_type, confidence = classify_document(
        filename="",
        text_snippet="",
    )
    assert doc_type == "unknown"
    assert confidence == "low"


def test_misleading_filename_alone_ignored():
    """
    Misleading filename without matching text content must NOT classify.
    This is the core invariant: filename is ignored.
    """
    doc_type, confidence = classify_document(
        filename="broker_statement.pdf",  # Strong broker signal
        text_snippet="",  # Empty — no text signal
    )
    assert doc_type == "unknown"
    assert confidence == "low"


def test_filename_broker_text_financial_report():
    """
    Filename says broker, text says financial report.
    Text wins (filename ignored), result is financial_report.
    """
    doc_type, confidence = classify_document(
        filename="brokerage_account_statement.pdf",  # "broker", "account statement"
        text_snippet="Quarterly earnings report and balance sheet.",
    )
    assert doc_type == "financial_report"
    assert confidence == "medium"


# ── Conflicting signals ──────────────────────────────────────────────────────

def test_conflicting_signals_returns_unknown():
    """Text has keywords from 2 different specific types → conflict → unknown/low."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Account statement and trade confirmation from our brokerage. Balance sheet and earnings.",
    )
    # Text matches both "broker_statement" (broker, account statement, trade) and "financial_report" (balance sheet, earnings)
    assert doc_type == "unknown"
    assert confidence == "low"


def test_conflicting_portfolio_vs_bank():
    """Portfolio keywords + bank keywords = conflict → unknown/low."""
    doc_type, confidence = classify_document(
        filename="doc.pdf",
        text_snippet="Holdings and asset allocation for your savings account and checking account.",
    )
    # "portfolio" signals (holdings, asset allocation) + "bank" signals (savings account, checking account)
    assert doc_type == "unknown"
    assert confidence == "low"


# ── Invariant: low confidence always yields unknown ──────────────────────────

def test_low_confidence_always_unknown():
    """The invariant: if confidence=low, then doc_type=unknown."""
    test_cases = [
        ("", ""),
        ("abc.pdf", "unrelated text"),
        ("misleading.pdf", ""),
        ("doc.pdf", "only one weak keyword like balance"),
    ]
    for filename, text in test_cases:
        doc_type, confidence = classify_document(filename, text)
        if confidence == "low":
            assert doc_type == "unknown", (
                f"Failed invariant: confidence=low but doc_type={doc_type} "
                f"(filename={filename}, text={text})"
            )


# ── Text snippet truncation (500 chars) ───────────────────────────────────────

def test_only_first_500_chars_used():
    """
    Keywords beyond 500 chars must not influence classification.
    Only the first 500 chars of text_snippet are examined.
    """
    padding = "x" * 510
    doc_type, confidence = classify_document(
        filename="document.pdf",
        text_snippet=padding + "Account statement and trade confirmation from brokerage.",
    )
    # The broker keywords are beyond 500 chars — should not be detected
    assert doc_type != "broker_statement" or doc_type == "unknown"
