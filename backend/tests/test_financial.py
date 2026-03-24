"""
tests/test_financial.py — Financial ingestion routes test suite.

Tests all active financial endpoints (prices, fx, macro, filings, holdings, portfolio-stub).
Run with:
    python tests/test_financial.py

Requires: app running at localhost:8000, valid API keys in .env.
Note: Most tests use incremental=True (default) — will return "empty" or "up_to_date" if already current.
"""

import sys
import time
import httpx

BASE_URL = "http://localhost:8000"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = 0
failed = 0

VALID_STATUSES = ("success", "empty", "up_to_date")


def header(title: str):
    print(f"\n{'='*60}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{'='*60}")


def result(test_name: str, success: bool, details: str = ""):
    global passed, failed
    if success:
        passed += 1
        icon = f"{GREEN}✅ PASS{RESET}"
    else:
        failed += 1
        icon = f"{RED}❌ FAIL{RESET}"
    print(f"  {icon}  {test_name}")
    if details:
        print(f"         {details}")


# ═══════════════════════════════════════════════════════════════
#  TEST 0 — Health Check (guard)
# ═══════════════════════════════════════════════════════════════
def test_health():
    header("TEST 0 — Health Check")
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5)
        result("Server reachable", resp.status_code == 200)
    except httpx.ConnectError:
        result("Server reachable", False, "Cannot connect — is the app running?")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
#  TEST 1 — Prices (Stooq)
# ═══════════════════════════════════════════════════════════════
def test_prices():
    header("TEST 1 — POST /financial/ingest/prices (Stooq)")

    # ── Happy path ──
    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/prices",
        json={"symbol": "SPY", "incremental": True},
        timeout=30,
    )
    result("Returns 200", resp.status_code == 200, f"Got: {resp.status_code}")
    data = resp.json()
    result("provider = 'stooq'", data.get("provider") == "stooq",
           f"Got: '{data.get('provider')}'")
    result("status is valid", data.get("status") in VALID_STATUSES,
           f"Got: '{data.get('status')}'")
    result("rows_ingested present", "rows_ingested" in data,
           f"rows_ingested = {data.get('rows_ingested')}")
    result("symbol echoed", data.get("symbol") == "SPY",
           f"Got: '{data.get('symbol')}'")

    # ── Invalid symbol ──
    # Stooq returns an empty CSV (no data), not an HTTP error → 200 with empty/up_to_date
    resp2 = httpx.post(
        f"{BASE_URL}/financial/ingest/prices",
        json={"symbol": "XXXXINVALID"},
        timeout=30,
    )
    result("Invalid symbol → 200 or 502 (no 500)",
           resp2.status_code in (200, 502),
           f"Got: {resp2.status_code}")

    # ── Missing required field → 422 ──
    resp_bad = httpx.post(f"{BASE_URL}/financial/ingest/prices", json={}, timeout=10)
    result("Missing symbol → 422", resp_bad.status_code == 422)


# ═══════════════════════════════════════════════════════════════
#  TEST 2 — FX Rates (Bank of Israel)
# ═══════════════════════════════════════════════════════════════
def test_fx():
    header("TEST 2 — POST /financial/ingest/fx (Bank of Israel)")

    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/fx",
        json={"incremental": True},
        timeout=30,
    )
    result("Returns 200", resp.status_code == 200, f"Got: {resp.status_code}")
    data = resp.json()
    result("provider = 'boi'", data.get("provider") == "boi",
           f"Got: '{data.get('provider')}'")
    result("status is valid", data.get("status") in VALID_STATUSES,
           f"Got: '{data.get('status')}'")
    result("rows_ingested present", "rows_ingested" in data,
           f"rows_ingested = {data.get('rows_ingested')}")


# ═══════════════════════════════════════════════════════════════
#  TEST 3 — Macro (FRED)
# ═══════════════════════════════════════════════════════════════
def test_macro():
    header("TEST 3 — POST /financial/ingest/macro (FRED)")

    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/macro",
        json={"series_id": "FEDFUNDS", "incremental": True},
        timeout=30,
    )
    result("Returns 200", resp.status_code == 200, f"Got: {resp.status_code}")
    data = resp.json()
    result("provider = 'fred'", data.get("provider") == "fred",
           f"Got: '{data.get('provider')}'")
    result("series_id echoed", data.get("series_id") == "FEDFUNDS",
           f"Got: '{data.get('series_id')}'")
    result("status is valid", data.get("status") in VALID_STATUSES,
           f"Got: '{data.get('status')}'")
    result("rows_ingested present", "rows_ingested" in data,
           f"rows_ingested = {data.get('rows_ingested')}")

    # ── Missing series_id → 422 ──
    resp_bad = httpx.post(f"{BASE_URL}/financial/ingest/macro", json={}, timeout=10)
    result("Missing series_id → 422", resp_bad.status_code == 422)


# ═══════════════════════════════════════════════════════════════
#  TEST 4 — Filings (SEC EDGAR)
# ═══════════════════════════════════════════════════════════════
def test_filings():
    header("TEST 4 — POST /financial/ingest/filings (SEC EDGAR)")

    # ── Happy path ──
    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/filings",
        json={"ticker": "AAPL"},
        timeout=60,
    )
    result("Returns 200", resp.status_code == 200, f"Got: {resp.status_code}")
    data = resp.json()
    result("ticker echoed", data.get("ticker") == "AAPL",
           f"Got: '{data.get('ticker')}'")
    result("status is valid", data.get("status") in VALID_STATUSES,
           f"Got: '{data.get('status')}'")

    # ── Unknown ticker → 404 (ValueError from EDGAR CIK lookup) ──
    # Must be ≤10 chars (Pydantic max_length) but not exist in SEC's CIK database
    resp_unknown = httpx.post(
        f"{BASE_URL}/financial/ingest/filings",
        json={"ticker": "ZZZZZ"},
        timeout=30,
    )
    result("Unknown ticker → 404", resp_unknown.status_code == 404,
           f"Got: {resp_unknown.status_code}")

    # ── Missing ticker → 422 ──
    resp_bad = httpx.post(f"{BASE_URL}/financial/ingest/filings", json={}, timeout=10)
    result("Missing ticker → 422", resp_bad.status_code == 422)


# ═══════════════════════════════════════════════════════════════
#  TEST 5 — Holdings (yahooquery, background task → 202)
# ═══════════════════════════════════════════════════════════════
def test_holdings():
    header("TEST 5 — POST /financial/ingest/holdings (Background Task)")

    # ── Specific ETF ──
    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/holdings",
        json={"etf_symbols": ["SPY"]},
        timeout=15,
    )
    result("Returns 202 Accepted", resp.status_code == 202,
           f"Got: {resp.status_code}")
    data = resp.json()
    result("status = 'accepted'", data.get("status") == "accepted",
           f"Got: '{data.get('status')}'")
    result("message present", "message" in data)
    result("etf_symbols echoed", data.get("etf_symbols") == ["SPY"],
           f"Got: {data.get('etf_symbols')}")

    # ── No ETF list (all active) ──
    # When etf_symbols is None → route returns "all active" (a string, not a list)
    resp_all = httpx.post(
        f"{BASE_URL}/financial/ingest/holdings",
        json={},
        timeout=10,
    )
    result("Empty body → 202", resp_all.status_code == 202)
    data_all = resp_all.json()
    result("etf_symbols is 'all active' string",
           data_all.get("etf_symbols") == "all active",
           f"Got: {data_all.get('etf_symbols')}")


# ═══════════════════════════════════════════════════════════════
#  TEST 6 — Deprecated Portfolio Upload (410 Gone)
# ═══════════════════════════════════════════════════════════════
def test_portfolio_deprecated():
    header("TEST 6 — POST /financial/ingest/portfolio-upload (410 Gone)")

    resp = httpx.post(
        f"{BASE_URL}/financial/ingest/portfolio-upload",
        timeout=10,
    )
    result("Returns 410 Gone", resp.status_code == 410,
           f"Got: {resp.status_code}")
    data = resp.json()
    result("Has 'detail' field", "detail" in data,
           f"detail = '{data.get('detail')}'")
    result("Has 'reason' field", "reason" in data,
           f"reason = '{data.get('reason')}'")


# ═══════════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════════
def print_summary():
    total = passed + failed
    header("📊 TEST SUMMARY")
    print(f"  {GREEN}Passed: {passed}{RESET}")
    print(f"  {RED}Failed: {failed}{RESET}")
    print(f"  Total:  {total}")
    print()
    if failed == 0:
        print(f"  {GREEN}{BOLD}🎉 ALL TESTS PASSED!{RESET}")
    else:
        print(f"  {YELLOW}{BOLD}⚠️  {failed} test(s) failed. Check logs above.{RESET}")
    print()


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{BOLD}🧪 Financial Routes — Test Suite{RESET}")
    print(f"   Target: {BASE_URL}")
    print(f"   Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")

    test_health()               # 0 — guard
    test_prices()               # 1 — Stooq
    test_fx()                   # 2 — BOI
    test_macro()                # 3 — FRED
    test_filings()              # 4 — EDGAR
    test_holdings()             # 5 — yahooquery (background)
    test_portfolio_deprecated() # 6 — 410 stub

    print_summary()
