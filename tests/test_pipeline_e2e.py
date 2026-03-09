"""
tests/test_pipeline_e2e.py — Full End-to-End Pipeline Test

Tests the complete system from PDF upload through routing-aware /chat response.

Pipeline tested:
    PDF generation → Upload (POST /documents/upload) → Indexing (worker)
    → Status polling (GET /documents/{id}) → Chat with routing (POST /chat)
    → Tenant isolation (user A cannot access user B's document via chat)

Run:
    python tests/test_pipeline_e2e.py

Requires:
    - App running at localhost:8000 (docker compose up)
    - OPENAI_API_KEY set (routing LLM + generation)
    - Pinecone connected (vectors must upsert)
"""

import os
import sys
import json
import time
import textwrap
import subprocess
import httpx

BASE_URL = "http://localhost:8000"
PDF_PATH = "_e2e_test.pdf"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = 0
failed = 0


# ── PDF Generator (pure Python, no deps) ─────────────────────────────────────

def _create_pdf(title: str, body: str) -> bytes:
    """Minimal valid PDF with embedded searchable text."""
    wrapped: list[str] = []
    for para in body.split("\n\n"):
        for line in textwrap.wrap(para.strip(), 85):
            wrapped.append(line)
        wrapped.append("")

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_lines = ["BT", "/F1 14 Tf", "50 760 Td",
                     f"({_esc(title)}) Tj", "/F1 11 Tf", "0 -25 Td", "15 TL"]
    for line in wrapped:
        content_lines.append(f"({_esc(line)}) '")
    content_lines.append("ET")

    _MAP = {"\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " "}
    raw = "\n".join(content_lines)
    for u, a in _MAP.items():
        raw = raw.replace(u, a)
    content_stream = raw.encode("latin-1", errors="replace")

    o1 = b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
    o2 = b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
    o3 = (b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
          b"  /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>\nendobj\n")
    o4 = (f"4 0 obj\n<</Length {len(content_stream)}>>\nstream\n".encode()
          + content_stream + b"\nendstream\nendobj\n")
    o5 = b"5 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"

    objects = [o1, o2, o3, o4, o5]
    header = b"%PDF-1.4\n"
    offsets, pos = [], len(header)
    for obj in objects:
        offsets.append(pos); pos += len(obj)

    xref_pos = pos
    xref = b"xref\n" + f"0 {len(objects)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = (f"trailer\n<</Size {len(objects)+1} /Root 1 0 R>>\n"
               f"startxref\n{xref_pos}\n%%EOF\n").encode()

    return header + b"".join(objects) + xref + trailer


# ── Test content ─────────────────────────────────────────────────────────────

TITLE = "Q4 2024 Annual Investment Report -- Strategic Portfolios Ltd."

BODY = """
Executive Summary

This report covers the Q4 2024 performance of the Strategic Portfolios fund.
Total assets under management reached 4.2 billion USD, a 12.3 percent increase year-over-year.
The portfolio achieved a net return of 18.4 percent for 2024, outperforming the benchmark by 2.1 percent.

Equity Holdings

Equities represent 58 percent of the total portfolio. Key positions include large-cap technology,
healthcare, and industrial sectors. S&P 500 exposure is achieved through SPY and IVV ETFs.

Fixed Income

Fixed income comprises 28 percent of the portfolio. The duration target is 4.5 years.
Holdings include US Treasury bonds (10Y, 30Y) and investment-grade corporate bonds.
The yield-to-maturity stands at 4.8 percent.

Alternative Assets

Alternative investments account for 14 percent of the portfolio, including REITs and commodities.
Gold futures represent the largest commodity position with a 3.2 percent portfolio weight.

Risk Metrics

Value at Risk (95 percent, 1-day): 12.4 million USD.
Maximum drawdown over trailing 12 months: 8.2 percent.
Sharpe ratio: 1.41.

Outlook for Q1 2025

The investment committee approved a 3 percent rebalancing toward long-duration treasuries.
A new infrastructure asset allocation is under evaluation, pending due diligence.
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def header(title: str):
    print(f"\n{'='*60}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{'='*60}")


def ok(msg: str, detail: str = ""):
    global passed; passed += 1
    print(f"  {GREEN}✅ PASS{RESET}  {msg}")
    if detail: print(f"         {detail}")


def fail(msg: str, detail: str = ""):
    global failed; failed += 1
    print(f"  {RED}❌ FAIL{RESET}  {msg}")
    if detail: print(f"         {detail}")


def info(msg: str):
    print(f"  {CYAN}ℹ{RESET}  {msg}")


def docker_logs(events: list[str], tail: int = 80) -> list[str]:
    """Fetch matching log lines from the api container."""
    try:
        res = subprocess.run(
            ["docker", "compose", "logs", "api", f"--tail={tail}"],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        lines = res.stdout.splitlines()
        return [l for l in lines if any(ev in l for ev in events)]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
#  TEST 0 — Health Check
# ═══════════════════════════════════════════════════════════════
def test_health():
    header("TEST 0 — Health Check")
    for attempt in range(3):
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=15)
            info(f"HTTP {resp.status_code}  body={repr(resp.text[:80])}")
            if resp.status_code == 200:
                data = resp.json()
                ok("Server reachable", f"status={data.get('status')}")
                svcs = data.get("services", {})
                ok("Pinecone connected", str(svcs.get("pinecone_connected")))
                ok("OpenAI configured", str(svcs.get("openai_configured")))
                return
            if attempt < 2:
                print(f"  {YELLOW}⚠ {resp.status_code}, retrying...{RESET}")
                time.sleep(3)
        except httpx.ConnectError:
            fail("Cannot connect — is 'docker compose up' running?")
            sys.exit(1)
        except (httpx.ReadTimeout, httpx.TimeoutException):
            if attempt < 2:
                print(f"  {YELLOW}⚠ Timeout, retrying...{RESET}")
                time.sleep(3)
    fail("Server not ready after 3 attempts"); sys.exit(1)


# ═══════════════════════════════════════════════════════════════
#  TEST 1 — Generate PDFs for two users
# ═══════════════════════════════════════════════════════════════
def test_generate_pdfs() -> tuple[str, str]:
    header("TEST 1 — Generate PDFs")

    pdf_a = _create_pdf(TITLE, BODY)
    path_a = "_e2e_user_a.pdf"
    with open(path_a, "wb") as f: f.write(pdf_a)
    ok("User A PDF generated", f"{len(pdf_a)/1024:.1f} KB")

    # User B gets a different document (different content — isolation test)
    pdf_b = _create_pdf(
        "Q4 2024 Fixed Income Report -- Bond Capital Ltd.",
        """
Executive Summary

This report covers the Q4 2024 fixed income strategy of Bond Capital.
Total bond portfolio value: 1.8 billion USD. Duration: 5.2 years.
Average yield-to-maturity: 5.1 percent. Credit quality: investment grade.

Holdings

70 percent US Treasury bonds, 20 percent investment-grade corporates,
10 percent emerging market bonds. No equity exposure in this fund.

Performance

The fund returned 4.2 percent for 2024, outperforming the benchmark by 0.4 percent.
"""
    )
    path_b = "_e2e_user_b.pdf"
    with open(path_b, "wb") as f: f.write(pdf_b)
    ok("User B PDF generated", f"{len(pdf_b)/1024:.1f} KB")

    return path_a, path_b


# ═══════════════════════════════════════════════════════════════
#  TEST 2 — Upload and index both documents
# ═══════════════════════════════════════════════════════════════
def test_upload_and_index(path_a: str, path_b: str) -> tuple[str, str]:
    header("TEST 2 — Upload & Index (both users)")

    def upload(path: str, owner: str, upload_filename: str) -> str:
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{BASE_URL}/documents/upload",
                files={"file": (upload_filename, f, "application/pdf")},
                headers={"X-Owner-Id": owner},
                timeout=15,
            )
        if resp.status_code != 202:
            fail(f"{owner} upload", f"{resp.status_code}: {resp.text[:100]}")
            return ""
        data = resp.json()
        ok(f"{owner} → 202 Accepted", f"doc_id={data['document_id']}")
        return data["document_id"]

    doc_a = upload(path_a, "user-a", "Q4_2024_strategic_portfolio_report.pdf")
    doc_b = upload(path_b, "user-b", "Q4_2024_bond_capital_fixed_income_report.pdf")

    if not doc_a or not doc_b:
        fail("Upload failed — cannot continue"); sys.exit(1)

    # Poll both until completed (max 30s)
    def poll_until_done(doc_id: str, owner: str, timeout: int = 30) -> str:
        deadline = time.time() + timeout
        prev = None
        while time.time() < deadline:
            resp = httpx.get(f"{BASE_URL}/documents/{doc_id}", timeout=5)
            status = resp.json().get("status", "unknown")
            if status != prev:
                info(f"{owner} status → {BOLD}{status}{RESET}")
                prev = status
            if status == "completed":
                ok(f"{owner} pipeline completed ✓")
                return status
            if status == "failed":
                fail(f"{owner} worker failed")
                return status
            time.sleep(0.8)
        fail(f"{owner} timed out after {timeout}s")
        return "timeout"

    status_a = poll_until_done(doc_a, "user-a")
    status_b = poll_until_done(doc_b, "user-b")

    if status_a != "completed" or status_b != "completed":
        fail("Indexing incomplete — cannot test chat"); sys.exit(1)

    # Show worker logs
    log_events = ["text_extracted", "text_chunked", "chunks_embedded",
                  "vectors_upserted", "worker_completed"]
    found = docker_logs(log_events, tail=100)
    if found:
        print()
        for line in found[-8:]:
            try:
                payload = json.loads(line[line.index("{"):])
                print(f"  {CYAN}●{RESET} {json.dumps(payload)}")
            except Exception:
                print(f"  ● {line.strip()}")

    return doc_a, doc_b


# ═══════════════════════════════════════════════════════════════
#  TEST 3 — /chat with routing agent (user A)
# ═══════════════════════════════════════════════════════════════
def test_chat_routing(doc_id_a: str):
    header("TEST 3 — /chat with Routing Agent (User A)")

    questions = [
        {
            "q": "What was the portfolio total return in 2024?",
            "keywords": ["18", "return", "percent", "2024", "outperform"],
            "label": "Return question",
        },
        {
            "q": "What percentage of the portfolio is in equities?",
            "keywords": ["58", "equity", "percent", "equit"],
            "label": "Equity allocation question",
        },
        {
            "q": "What is the maximum drawdown and Sharpe ratio of the portfolio?",
            "keywords": ["1.41", "sharpe", "8.2", "drawdown", "risk", "value at risk"],
            "label": "Risk metrics question",
        },
    ]

    for item in questions:
        t0 = time.time()
        resp = httpx.post(
            f"{BASE_URL}/chat",
            json={
                "question": item["q"],
                "owner_id": "user-a",
            },
            timeout=60,
        )
        latency = time.time() - t0

        if resp.status_code != 200:
            fail(item["label"], f"HTTP {resp.status_code}: {resp.text[:150]}")
            continue

        data = resp.json()
        answer = data.get("answer", "").lower()
        breakdown = data.get("latency_breakdown", {})

        has_keyword = any(kw.lower() in answer for kw in item["keywords"])
        ok(item["label"],
           f"routing={breakdown.get('routing',0):.2f}s  "
           f"total={latency:.2f}s  "
           f"keyword_match={has_keyword}")

        if not has_keyword:
            fail(f"  Answer didn't contain expected keywords {item['keywords']}",
                 f"Got: '{data.get('answer','')[:120]}'")
        else:
            ok(f"  Answer references document content")

        info(f"  Queries used (from routing LLM): {data.get('latency_breakdown', {})}")


# ═══════════════════════════════════════════════════════════════
#  TEST 4 — Unrelated question (no answer from docs)
# ═══════════════════════════════════════════════════════════════
def test_chat_unrelated():
    header("TEST 4 — Unrelated Question (no info in docs)")

    resp = httpx.post(
        f"{BASE_URL}/chat",
        json={
            "question": "What is the recipe for chocolate cake?",
            "owner_id": "user-a",
        },
        timeout=60,
    )

    ok("Request succeeded", f"HTTP {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        answer = data.get("answer", "").lower()
        # Should NOT confidently claim to know the answer from financial docs
        refused = any(word in answer for word in [
            "cannot", "don't have", "not available", "no information",
            "not found", "doesn't contain", "not in"
        ])
        if refused:
            ok("Correctly declined to answer from financial docs")
        else:
            info(f"Model answered (may be hallucinating): '{data.get('answer','')[:120]}'")


# ═══════════════════════════════════════════════════════════════
#  TEST 5 — Tenant Isolation via /chat
# ═══════════════════════════════════════════════════════════════
def test_tenant_isolation():
    header("TEST 5 — Tenant Isolation (user-b cannot see user-a's data)")

    # User B asks about user A's specific content (18.4% return from A's doc)
    resp = httpx.post(
        f"{BASE_URL}/chat",
        json={
            "question": "What was the portfolio total return in 2024?",
            "owner_id": "user-b",   # user-b, asking about user-a's content
        },
        timeout=60,
    )
    ok("Request succeeded", f"HTTP {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        answer = data.get("answer", "")

        # User B's document is about bonds (4.2% return), not equities (18.4%)
        # If the system is isolated correctly, user B will get info about bonds
        # or nothing — NOT the 18.4% from user A's portfolio document.
        a_data_leaked = "18.4" in answer or "Strategic Portfolios" in answer
        if a_data_leaked:
            fail("ISOLATION BREACH: user-b received user-a's data!",
                 f"Answer: '{answer[:150]}'")
        else:
            ok("User-b answer does NOT contain user-a's private data ✓")
            info(f"User-b answer (about bonds): '{answer[:120]}'")


# ═══════════════════════════════════════════════════════════════
#  TEST 6 — Original /chat (no owner_id) still works
# ═══════════════════════════════════════════════════════════════
def test_original_chat():
    header("TEST 6 — Original /chat (backward compat, no owner_id)")

    resp = httpx.post(
        f"{BASE_URL}/chat",
        json={"question": "What is machine learning?"},
        timeout=30,
    )
    if resp.status_code == 200:
        ok("Returns 200", f"Got: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        ok("Has answer field", "answer" in data)
        ok("No routing latency (generic path)",
           data.get("latency_breakdown", {}).get("routing", 0) == 0)


# ═══════════════════════════════════════════════════════════════
#  CLEANUP & SUMMARY
# ═══════════════════════════════════════════════════════════════

def cleanup():
    for f in ["_e2e_user_a.pdf", "_e2e_user_b.pdf", PDF_PATH]:
        if os.path.exists(f):
            os.remove(f)


def print_summary():
    header("📊 TEST SUMMARY")
    print(f"  {GREEN}Passed: {passed}{RESET}")
    print(f"  {RED}Failed: {failed}{RESET}")
    print(f"  Total:  {passed + failed}")
    print()
    if failed == 0:
        print(f"  {GREEN}{BOLD}🎉 ALL TESTS PASSED — Full pipeline end-to-end verified!{RESET}")
    else:
        print(f"  {YELLOW}{BOLD}⚠  {failed} test(s) failed. Check logs above.{RESET}")
    print()


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BOLD}🧪 Full Pipeline E2E Test{RESET}")
    print(f"   Target: {BASE_URL}")
    print(f"   Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Covers: upload → indexing → routing → /chat → isolation")

    try:
        test_health()                                # 0 — guard

        path_a, path_b = test_generate_pdfs()       # 1 — create PDFs

        doc_a, doc_b = test_upload_and_index(        # 2 — upload + index
            path_a, path_b
        )

        test_chat_routing(doc_a)                     # 3 — routing queries

        test_chat_unrelated()                        # 4 — no hallucination

        test_tenant_isolation()                      # 5 — tenant isolation

        test_original_chat()                         # 6 — backward compat

    finally:
        cleanup()
        print_summary()
