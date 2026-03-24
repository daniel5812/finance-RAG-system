import os
import time
import textwrap
import pytest
import httpx
import json

BASE_URL = "http://localhost:8000"

# ── PDF Generator Helper ───────────────────────────────────────────────────

def create_simple_pdf(title: str, body: str) -> bytes:
    """Minimal valid PDF with embedded searchable text."""
    wrapped = []
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

    raw = "\n".join(content_lines)
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

# ── Test Cases ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    return httpx.Client(base_url=BASE_URL, timeout=30.0)

def test_0_health(client):
    """Verify system is up and connected."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy" or data["status"] == "degraded"
    # Note: degraded is okay if Pinecone index is empty but reachable

def test_1_full_workflow_user_a(client):
    """Scenario: User A uploads a doc and asks a question about it."""
    user_id = "user-a-unique-id"
    revenue_val = "12.5 million USD"
    
    # 1. Create PDF
    pdf_content = create_simple_pdf(
        "Quarterly Financial Report - User A",
        f"In Q4 2024, our total revenue reached {revenue_val}. This represents a strong growth."
    )
    
    # 2. Upload
    files = {"file": ("report_a.pdf", pdf_content, "application/pdf")}
    headers = {"X-Owner-Id": user_id}
    resp = client.post("/documents/upload", files=files, headers=headers)
    assert resp.status_code == 202
    doc_id = resp.json()["document_id"]
    
    # 3. Poll for completion
    completed = False
    for _ in range(30): # 30 attempts, 1s each
        poll = client.get(f"/documents/{doc_id}")
        if poll.json().get("status") == "completed":
            completed = True
            break
        time.sleep(1)
    
    assert completed, f"Document {doc_id} failed to process within timeout"
    
    # 4. Chat
    chat_payload = {
        "question": "What was the total revenue in Q4 2024 according to my report?",
        "owner_id": user_id
    }
    resp = client.post("/chat", json=chat_payload)
    assert resp.status_code == 200
    answer = resp.json().get("answer", "")
    assert "12.5" in answer
    assert "million" in answer.lower()

def test_2_tenant_isolation(client):
    """Scenario: User B cannot see User A's data."""
    user_a = "user-a-unique-id"
    user_b = "user-b-unique-id"
    
    # User B asks about A's data
    chat_payload = {
        "question": "What was the total revenue in Q4 2024?",
        "owner_id": user_b
    }
    resp = client.post("/chat", json=chat_payload)
    assert resp.status_code == 200
    answer = resp.json().get("answer", "").lower()
    
    # Isolation: User B's answer should NOT contain User A's 12.5M figure
    # since User B hasn't uploaded a document with that info.
    assert "12.5" not in answer, "ISOLATION BREACH: User B saw User A's data!"

def test_3_chat_stream(client):
    """Verify SSE streaming works."""
    user_id = "user-a-unique-id"
    chat_payload = {
        "question": "Tell me a short summary of the report.",
        "owner_id": user_id
    }
    
    with client.stream("POST", "/chat/stream", json=chat_payload) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        
        # Check first few events
        events_found = 0
        for line in response.iter_lines():
            if line.startswith("data:"):
                # SSE data: {"type": "token", "content": "..."}
                data = json.loads(line[5:])
                if data["type"] == "token":
                    events_found += 1
                if events_found > 3:
                    break
        assert events_found > 0, "No tokens received from stream"
