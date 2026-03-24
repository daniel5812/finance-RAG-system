import pytest
import httpx
import re

API_URL = "http://localhost:8000"

@pytest.fixture
def client():
    with httpx.Client(base_url=API_URL, timeout=40.0) as client:
        yield client

def test_financial_advisor_structure(client):
    """Verifies the response follows the mandated Answer/Explanation/Insight structure."""
    question = "מה הסטטוס של שער ה-USD/ILS ומה זה אומר על ההשקעות שלי?"
    
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    answer_text = data.get("answer", "")
    
    # Check for structural headers (case-insensitive or exact based on prompt)
    assert "Answer:" in answer_text
    assert "Explanation:" in answer_text
    assert "Insight:" in answer_text
    
    # Verify citations are present (tags like [S1] or [D1])
    assert re.search(r"\[[SD]\d+\]", answer_text)

def test_advisor_routing_triggers_vector(client):
    """Verifies that advisory queries trigger vector search for qualitative context."""
    # This query should trigger both SQL (for rates) and Vector (for interpretation/impact)
    question = "Give me some insights and risks about the current exchange rate environment."
    
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    
    # Check sources to see if we have both SQL and Vector
    sources = data.get("sources", [])
    has_sql = any(s.get("document_id") == "sql_query" for s in sources)
    # Vector sources have UUID-like IDs or at least not "sql_query"
    has_vector = any(s.get("document_id") != "sql_query" for s in sources)
    
    # The router prompt now forces vector search for "insights" or "risks"
    assert has_vector, "Query for 'insights/risks' did not trigger qualitative vector retrieval."

def test_anti_hallucination_on_advisory(client):
    """Ensures the advisor doesn't make up numbers even when providing 'Insights'."""
    question = "What is the projected 2030 exchange rate of Bitcoin based on my documents?"
    
    # Assuming the documents don't have this specific forecast
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    answer_text = data.get("answer", "")
    
    # If the info isn't there, it should state it doesn't have enough info
    # instead of guessing a number in the "Insight" section.
    if "I don't have enough information" in answer_text:
        assert True
    else:
        # If it DOES provide an answer, it MUST be cited.
        assert re.search(r"\[[SD]\d+\]", answer_text)
