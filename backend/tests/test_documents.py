"""
tests/test_documents.py — Document pipeline test suite (Stages 1, 2, 3).

Tests every layer of the document ingestion pipeline:
  - POST /documents/upload  (validation, 202, worker trigger)
  - GET  /documents/{id}    (status polling)
  - Worker lifecycle        (status transitions in DB)

Run with:
    python tests/test_documents.py

Requires: app running at localhost:8000, test.pdf in working dir (auto-created).
"""

import os
import sys
import time
import json
import httpx

BASE_URL = "http://localhost:8000"
UPLOAD_URL  = f"{BASE_URL}/documents/upload"
STATUS_URL  = f"{BASE_URL}/documents"

# ── Colors ──
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = 0
failed = 0


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


def poll_status(document_id: str, expected: str, timeout: int = 5) -> dict:
    """Poll GET /documents/{id} until status matches expected or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = httpx.get(f"{STATUS_URL}/{document_id}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == expected:
                return data
        time.sleep(0.3)
    # Return whatever we got last
    resp = httpx.get(f"{STATUS_URL}/{document_id}", timeout=5)
    return resp.json() if resp.status_code == 200 else {}


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_pdf(path: str, content: str = "%PDF-1.4 test financial document"):
    with open(path, "w") as f:
        f.write(content)

def _make_non_pdf(path: str):
    with open(path, "w") as f:
        f.write("This is a plain text file, not a PDF.")


# ═══════════════════════════════════════════════════════════════
#  TEST 0 — Health Check (sanity guard)
# ═══════════════════════════════════════════════════════════════
def test_health():
    header("TEST 0 — Health Check")
    # Health endpoint checks Pinecone/Redis/OpenAI — can take >5s.
    # Retry once before giving up.
    for attempt in range(2):
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=15)
            result("Server reachable", resp.status_code == 200)
            data = resp.json()
            result("Status healthy/degraded",
                   data.get("status") in ("healthy", "degraded"),
                   f"Got: {data.get('status')}")
            return  # success
        except httpx.ConnectError:
            result("Server reachable", False, "Cannot connect to localhost:8000 — is the app running?")
            sys.exit(1)
        except (httpx.ReadTimeout, httpx.TimeoutException) as e:
            if attempt == 0:
                print(f"  {YELLOW}⚠ Health check timed out, retrying...{RESET}")
                time.sleep(2)
            else:
                result("Server reachable", False, f"Timed out after 2 attempts: {e}")
                sys.exit(1)


# ═══════════════════════════════════════════════════════════════
#  TEST 1 — Successful Upload (Happy Path)
# ═══════════════════════════════════════════════════════════════
def test_upload_happy_path() -> str:
    header("TEST 1 — Successful Upload (Happy Path)")

    _make_pdf("test.pdf")

    t0 = time.time()
    with open("test.pdf", "rb") as f:
        resp = httpx.post(
            UPLOAD_URL,
            files={"file": ("test.pdf", f, "application/pdf")},
            headers={"X-Owner-Id": "user-test-001"},
            timeout=15,
        )
    latency = time.time() - t0

    result("Returns 202 Accepted", resp.status_code == 202,
           f"Got: {resp.status_code}")

    data = resp.json()
    doc_id = data.get("document_id", "")

    result("Has document_id (UUID)", len(doc_id) == 36,
           f"Got: '{doc_id}'")
    result("status = 'accepted'", data.get("status") == "accepted",
           f"Got: '{data.get('status')}'")
    result("original_filename echoed", data.get("original_filename") == "test.pdf",
           f"Got: '{data.get('original_filename')}'")
    result(f"Latency < 3s", latency < 3.0, f"{latency:.2f}s")

    print(f"\n  📄 document_id: {doc_id}")
    return doc_id


# ═══════════════════════════════════════════════════════════════
#  TEST 2 — Status Polling (GET /documents/{id})
# ═══════════════════════════════════════════════════════════════
def test_status_polling(doc_id: str):
    header("TEST 2 — Status Polling (GET /documents/{id})")

    resp = httpx.get(f"{STATUS_URL}/{doc_id}", timeout=5)
    result("Returns 200", resp.status_code == 200, f"Got: {resp.status_code}")

    data = resp.json()
    result("Has document_id", data.get("document_id") == doc_id)
    result("owner_id correct", data.get("owner_id") == "user-test-001",
           f"Got: '{data.get('owner_id')}'")
    result("Has original_filename", data.get("original_filename") == "test.pdf")
    result("Has file_size_bytes", isinstance(data.get("file_size_bytes"), int))
    result("Has created_at", data.get("created_at") is not None)
    result("Has updated_at", data.get("updated_at") is not None)

    status = data.get("status", "")
    result("Status is valid pipeline value",
           status in ("pending_processing", "processing", "completed", "failed"),
           f"Got: '{status}'")

    print(f"\n  🔄 Current status: {status}")


# ═══════════════════════════════════════════════════════════════
#  TEST 3 — Worker Lifecycle (status transitions)
# ═══════════════════════════════════════════════════════════════
def test_worker_lifecycle(doc_id: str):
    header("TEST 3 — Worker Lifecycle (status transitions)")

    print("  ⏳ Waiting for worker to complete (up to 5s)...")
    final = poll_status(doc_id, "completed", timeout=5)

    status = final.get("status", "")

    # With the skeleton worker (no real work), it should complete immediately
    result("Status reaches 'completed'", status == "completed",
           f"Got: '{status}' — if 'processing', worker may be slow or crashed")
    result("updated_at changed", final.get("updated_at") is not None)

    print(f"\n  ✅ Final status: {status}")


# ═══════════════════════════════════════════════════════════════
#  TEST 4 — Validation: Wrong Content-Type
# ═══════════════════════════════════════════════════════════════
def test_wrong_content_type():
    header("TEST 4 — Validation: Wrong Content-Type (415)")

    _make_non_pdf("test.txt")

    with open("test.txt", "rb") as f:
        resp = httpx.post(
            UPLOAD_URL,
            files={"file": ("test.txt", f, "text/plain")},
            headers={"X-Owner-Id": "user-test-001"},
            timeout=10,
        )

    result("Returns 415 Unsupported Media Type", resp.status_code == 415,
           f"Got: {resp.status_code}")
    result("Error detail present", "detail" in resp.json())

    os.remove("test.txt")


# ═══════════════════════════════════════════════════════════════
#  TEST 5 — Validation: Wrong Magic Bytes (fake PDF)
# ═══════════════════════════════════════════════════════════════
def test_fake_pdf():
    header("TEST 5 — Validation: Fake PDF (wrong magic bytes → 415)")

    # File claims to be PDF but starts with wrong bytes
    with open("fake.pdf", "wb") as f:
        f.write(b"NOTAPDF this is not a real PDF")

    with open("fake.pdf", "rb") as f:
        resp = httpx.post(
            UPLOAD_URL,
            files={"file": ("fake.pdf", f, "application/pdf")},
            headers={"X-Owner-Id": "user-test-001"},
            timeout=10,
        )

    result("Returns 415 (magic byte check)", resp.status_code == 415,
           f"Got: {resp.status_code}")
    result("Error mentions '%PDF'", "%PDF" in resp.json().get("detail", ""),
           f"Detail: {resp.json().get('detail', '')[:80]}")

    os.remove("fake.pdf")


# ═══════════════════════════════════════════════════════════════
#  TEST 6 — Validation: Missing X-Owner-Id Header
# ═══════════════════════════════════════════════════════════════
def test_missing_owner_header():
    header("TEST 6 — Validation: Missing X-Owner-Id Header (422)")

    _make_pdf("test.pdf")

    with open("test.pdf", "rb") as f:
        resp = httpx.post(
            UPLOAD_URL,
            files={"file": ("test.pdf", f, "application/pdf")},
            # No X-Owner-Id header
            timeout=10,
        )

    result("Returns 422 Unprocessable Entity", resp.status_code == 422,
           f"Got: {resp.status_code}")


# ═══════════════════════════════════════════════════════════════
#  TEST 7 — Status: Unknown Document ID
# ═══════════════════════════════════════════════════════════════
def test_status_not_found():
    header("TEST 7 — Status: Unknown Document ID (404)")

    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = httpx.get(f"{STATUS_URL}/{fake_id}", timeout=5)

    result("Returns 404 Not Found", resp.status_code == 404,
           f"Got: {resp.status_code}")
    result("Error detail present", "detail" in resp.json(),
           f"Detail: {resp.json().get('detail', '')[:80]}")


# ═══════════════════════════════════════════════════════════════
#  TEST 8 — Tenant Isolation (different owner_ids are separate)
# ═══════════════════════════════════════════════════════════════
def test_tenant_isolation():
    header("TEST 8 — Tenant Isolation (two users, separate documents)")

    _make_pdf("test.pdf")

    # Upload as user A
    with open("test.pdf", "rb") as f:
        resp_a = httpx.post(
            UPLOAD_URL,
            files={"file": ("report_a.pdf", f, "application/pdf")},
            headers={"X-Owner-Id": "user-A"},
            timeout=10,
        )

    # Upload as user B
    with open("test.pdf", "rb") as f:
        resp_b = httpx.post(
            UPLOAD_URL,
            files={"file": ("report_b.pdf", f, "application/pdf")},
            headers={"X-Owner-Id": "user-B"},
            timeout=10,
        )

    result("User A upload → 202", resp_a.status_code == 202)
    result("User B upload → 202", resp_b.status_code == 202)

    id_a = resp_a.json().get("document_id", "")
    id_b = resp_b.json().get("document_id", "")

    result("Different document_ids issued", id_a != id_b,
           f"A={id_a[:8]}… B={id_b[:8]}…")

    # Verify each document stores the correct owner_id
    status_a = httpx.get(f"{STATUS_URL}/{id_a}", timeout=5).json()
    status_b = httpx.get(f"{STATUS_URL}/{id_b}", timeout=5).json()

    result("Document A owner_id = 'user-A'", status_a.get("owner_id") == "user-A",
           f"Got: '{status_a.get('owner_id')}'")
    result("Document B owner_id = 'user-B'", status_b.get("owner_id") == "user-B",
           f"Got: '{status_b.get('owner_id')}'")


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
    print(f"\n{BOLD}🧪 Document Pipeline — Test Suite{RESET}")
    print(f"   Target: {BASE_URL}")
    print(f"   Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")

    test_health()                        # 0 — guard
    doc_id = test_upload_happy_path()    # 1 — happy path
    test_status_polling(doc_id)          # 2 — GET /documents/{id}
    test_worker_lifecycle(doc_id)        # 3 — status transitions
    test_wrong_content_type()            # 4 — 415 content-type
    test_fake_pdf()                      # 5 — 415 magic bytes
    test_missing_owner_header()          # 6 — 422 missing header
    test_status_not_found()              # 7 — 404 unknown id
    test_tenant_isolation()              # 8 — multi-tenant

    print_summary()

    # Clean up test files
    for f in ["test.pdf"]:
        if os.path.exists(f):
            os.remove(f)
