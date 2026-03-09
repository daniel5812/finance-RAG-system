"""
tests/test_real_pdf.py — End-to-end pipeline test with a REAL PDF.

This script:
  1. Generates a valid PDF with real embedded text (no external library needed)
  2. Uploads it to POST /documents/upload
  3. Polls GET /documents/{id} until status = "completed"
  4. Prints the full pipeline trace from Docker logs

Run:
    python tests/test_real_pdf.py

Requires: app running at localhost:8000 (docker compose up --build)
"""

import os
import sys
import time
import json
import textwrap
import subprocess
import httpx

BASE_URL   = "http://localhost:8000"
UPLOAD_URL = f"{BASE_URL}/documents/upload"
STATUS_URL = f"{BASE_URL}/documents"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Minimal PDF generator (no external deps) ─────────────────────────────────

def _create_pdf_bytes(title: str, body: str) -> bytes:
    """
    Generate a minimal but fully valid PDF with embedded searchable text.

    No external libraries (reportlab, fpdf2) needed.
    Uses PDF Type1/Helvetica (always available, no font embedding required).
    The ' operator moves to the next line AND shows the string — compact content stream.
    """
    # Wrap body into ~85-char lines
    wrapped_lines: list[str] = []
    for para in body.split("\n\n"):
        for line in textwrap.wrap(para.strip(), 85):
            wrapped_lines.append(line)
        wrapped_lines.append("")   # blank line between paragraphs

    def _pdf_str(s: str) -> str:
        """Escape a string for use inside a PDF string literal ( ... )"""
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    # Build content stream
    # BT ... ET  = Begin/End Text block
    # /F1 11 Tf  = use font F1 (Helvetica) at 11pt
    # 15 TL      = text leading 15pt
    # 50 740 Td  = position cursor
    # ' operator = move to next line AND show text
    content_lines = [
        "BT",
        "/F1 14 Tf",
        f"50 760 Td",
        f"({_pdf_str(title)}) Tj",   # title line
        "/F1 11 Tf",
        "0 -25 Td",                  # drop below title
        "15 TL",                     # set leading
    ]
    for line in wrapped_lines:
        content_lines.append(f"({_pdf_str(line)}) '")
    content_lines.append("ET")

    # Sanitize: PDF content streams must be latin-1 encodable.
    # Replace common Unicode punctuation with ASCII equivalents.
    _UNICODE_MAP = {
        "\u2014": "--",   # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",    # non-breaking space
    }
    joined = "\n".join(content_lines)
    for uni, asc in _UNICODE_MAP.items():
        joined = joined.replace(uni, asc)
    # Drop anything still outside latin-1
    content_stream = joined.encode("latin-1", errors="replace")
    stream_len = len(content_stream)

    # ── Build object bodies ──
    obj1 = b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"  /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>\nendobj\n"
    )
    obj4 = (
        f"4 0 obj\n<</Length {stream_len}>>\nstream\n".encode()
        + content_stream
        + b"\nendstream\nendobj\n"
    )
    obj5 = b"5 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"

    objects = [obj1, obj2, obj3, obj4, obj5]

    # ── Compute byte offsets for xref table ──
    header = b"%PDF-1.4\n"
    offsets: list[int] = []
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)

    xref_pos = pos
    xref = b"xref\n"
    xref += f"0 {len(objects) + 1}\n".encode()
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<</Size {len(objects) + 1} /Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    return header + b"".join(objects) + xref + trailer


# ── Test document content ─────────────────────────────────────────────────────

TITLE = "Q4 2024 Portfolio Summary — Strategic Investments Ltd."

BODY = """
Executive Summary

This report summarizes the investment portfolio performance for Q4 2024. The total assets under management reached 4.2 billion USD, representing a 12.3% year-over-year growth. The portfolio maintained a diversification strategy across equities, fixed income, and alternative assets.

Equity Holdings

The equity portion represents 58% of the portfolio. Notable positions include large-cap technology, healthcare, and industrial sectors. The S&P 500 exposure is primarily achieved through SPY and IVV ETFs. The equity book generated a return of 18.4% for the full year 2024, outperforming the benchmark by 2.1%.

Fixed Income

Fixed income comprises 28% of the total portfolio. The duration target is 4.5 years. Holdings include US Treasury bonds (10Y, 30Y), investment-grade corporate bonds, and a small allocation to emerging market debt. The yield-to-maturity of the fixed income book stands at 4.8%.

Alternative Assets

Alternative investments account for the remaining 14%. This includes real estate investment trusts (REITs), commodities (gold and oil futures), and a small allocation to private equity funds with an expected 7-year lock-up period.

Risk Metrics

Value at Risk (95%, 1-day): 12.4M USD. Maximum drawdown over the trailing 12 months: 8.2%. Sharpe ratio: 1.41. The portfolio remains within all regulatory risk limits as per the investment policy statement.

Outlook for Q1 2025

The investment committee has approved a 3% rebalancing toward long-duration treasuries given the expected rate cut cycle. Equity exposure will remain neutral. A new position in infrastructure assets is under evaluation, pending due diligence completion.
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def header(title: str):
    print(f"\n{'='*60}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{'='*60}")


def ok(msg: str, detail: str = ""):
    print(f"  {GREEN}✅ PASS{RESET}  {msg}")
    if detail:
        print(f"         {detail}")


def fail(msg: str, detail: str = ""):
    print(f"  {RED}❌ FAIL{RESET}  {msg}")
    if detail:
        print(f"         {detail}")


def info(msg: str):
    print(f"  {CYAN}ℹ{RESET}  {msg}")


# ── Test steps ────────────────────────────────────────────────────────────────

def step0_health():
    header("STEP 0 — Health Check")
    for attempt in range(3):
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=15)
            info(f"HTTP {resp.status_code}  body={repr(resp.text[:120])}")
            if resp.status_code != 200:
                if attempt < 2:
                    print(f"  {YELLOW}⚠ Got {resp.status_code}, retrying in 3s...{RESET}")
                    time.sleep(3)
                    continue
                else:
                    fail(f"Health returned {resp.status_code}")
                    sys.exit(1)
            try:
                status = resp.json().get("status", "unknown")
            except Exception:
                status = f"(non-JSON: {resp.text[:60]})"
            ok("Server reachable", f"status={status}")
            return
        except httpx.ConnectError:
            fail("Cannot connect — is 'docker compose up --build' running?")
            sys.exit(1)
        except (httpx.ReadTimeout, httpx.TimeoutException):
            if attempt < 2:
                print(f"  {YELLOW}⚠ Timeout, retrying in 3s...{RESET}")
                time.sleep(3)
            else:
                fail("Timed out after 3 attempts")
                sys.exit(1)


def step1_generate_pdf(path: str):
    header("STEP 1 — Generate Real PDF")
    pdf_bytes = _create_pdf_bytes(TITLE, BODY)
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    size_kb = len(pdf_bytes) / 1024
    ok("PDF generated", f"{size_kb:.1f} KB — '{TITLE[:50]}'")
    info(f"Saved to: {path}")


def step2_upload(path: str) -> str:
    header("STEP 2 — Upload PDF")
    t0 = time.time()
    with open(path, "rb") as f:
        resp = httpx.post(
            UPLOAD_URL,
            files={"file": ("portfolio_q4_2024.pdf", f, "application/pdf")},
            headers={"X-Owner-Id": "user-investor-001"},
            timeout=15,
        )
    latency = time.time() - t0

    if resp.status_code != 202:
        fail(f"Upload failed → {resp.status_code}", resp.text[:200])
        sys.exit(1)

    data = resp.json()
    doc_id = data["document_id"]
    ok("202 Accepted", f"latency={latency:.2f}s")
    ok(f"document_id = {doc_id}")
    ok(f"original_filename = {data.get('original_filename')}")
    return doc_id


def step3_poll(doc_id: str, timeout: int = 15):
    header("STEP 3 — Poll Status Until Completed")
    deadline = time.time() + timeout
    prev_status = None

    while time.time() < deadline:
        resp = httpx.get(f"{STATUS_URL}/{doc_id}", timeout=5)
        if resp.status_code != 200:
            fail(f"Poll returned {resp.status_code}")
            break

        data = resp.json()
        status = data["status"]

        if status != prev_status:
            info(f"status → {BOLD}{status}{RESET}")
            prev_status = status

        if status == "completed":
            ok("Pipeline completed ✓")
            return data
        elif status == "failed":
            fail("Worker set status = 'failed'")
            info("Check docker compose logs for the error.")
            return data

        time.sleep(0.5)

    fail(f"Timed out after {timeout}s — last status: {prev_status}")
    return {}


def step4_show_logs():
    header("STEP 4 — Worker Log Events (from Docker)")
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "api", "--tail=60"],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        lines = result.stdout.splitlines()

        events = [
            "worker_started", "text_extracted", "text_chunked",
            "chunks_embedded", "vectors_upserted", "worker_completed",
            "worker_failed", "page_extraction_skip",
        ]
        found = [l for l in lines if any(ev in l for ev in events)]

        if found:
            print()
            for line in found:
                # Pretty-print the JSON payload inside the log line
                try:
                    # Log lines look like: "api-1 | {...json...}"
                    json_start = line.index("{")
                    payload = json.loads(line[json_start:])
                    event = payload.get("event", "")
                    color = GREEN if "completed" in event else CYAN
                    print(f"  {color}●{RESET} {json.dumps(payload)}")
                except Exception:
                    print(f"  ● {line.strip()}")
        else:
            info("No worker events found in recent logs — worker may still be running.")
            info("Run: docker compose logs api --tail=40 | grep worker")
    except Exception as e:
        info(f"Could not fetch docker logs: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PDF_PATH = "test_real.pdf"

    print(f"\n{BOLD}🧪 Real PDF Pipeline Test{RESET}")
    print(f"   Target: {BASE_URL}")
    print(f"   Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")

    step0_health()
    step1_generate_pdf(PDF_PATH)
    doc_id = step2_upload(PDF_PATH)
    final  = step3_poll(doc_id, timeout=15)
    step4_show_logs()

    # Cleanup
    if os.path.exists(PDF_PATH):
        os.remove(PDF_PATH)

    status = final.get("status", "unknown")
    print(f"\n{'='*60}")
    if status == "completed":
        print(f"  {GREEN}{BOLD}🎉 PIPELINE END-TO-END: PASSED{RESET}")
        print(f"     Upload → Worker → Extraction → Chunking → Embedding → completed")
    else:
        print(f"  {RED}{BOLD}⚠  PIPELINE STATUS: {status.upper()}{RESET}")
    print(f"{'='*60}\n")
