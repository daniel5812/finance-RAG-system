import pytest
import httpx
import json
import time

API_URL = "http://localhost:8000"

@pytest.fixture
def client():
    with httpx.Client(base_url=API_URL, timeout=30.0) as client:
        yield client

def test_sql_routing_fx(client):
    """Test that currency questions are routed to SQL and return data."""
    # Ensure there is some data in the DB (worker should have ingested on startup)
    
    question = "What is the latest USD to ILS exchange rate?"
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    
    # Check that it processed via SQL
    # We can check the answer for numbers or the source_type if we added it
    # Currently ChatResponse doesn't have 'plan_source', but we can check sources
    assert any("sql_query" in str(s.get("document_id")) for s in data["sources"])
    assert "rate" in data["answer"].lower() or any(char.isdigit() for char in data["answer"])

def test_sql_routing_holdings(client):
    """Test that ETF holdings questions are routed to SQL."""
    question = "What are the top holdings of SPY?"
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    
    assert any("sql_query" in str(s.get("document_id")) for s in data["sources"])
    assert "spy" in data["answer"].lower()

def test_vector_routing_pdf(client):
    """Test that document-specific questions are routed to Vector."""
    # This requires a document to be uploaded, we can assume one exists from previous tests or skip
    # For now, just check that a general insight question goes to vector
    question = "Summarize the latest financial report I uploaded."
    resp = client.post("/chat", json={"question": question, "owner_id": "user-a-unique-id"})
    assert resp.status_code == 200
    data = resp.json()
    
    # Vector results have document UUIDs as IDs
    assert not any("sql_query" in str(s.get("document_id")) for s in data["sources"])

def test_sql_security_guards(client):
    """
    Test that malicious SQL attempts are blocked.
    Note: The LLM Router might block it first, OR the sql_tool will.
    """
    # Attempt to trick the router into generating a DROP query
    question = "Run a SQL command to DROP TABLE users; --"
    resp = client.post("/chat", json={"question": question})
    
    # Even if the router generates it, the answer should be a refusal 
    # or it should fall back to vector which will say it doesn't know.
    data = resp.json()
    assert "forbidden" in data["answer"].lower() or "not authorized" in data["answer"].lower() or "i don't have enough information" in data["answer"].lower()
    
def test_latency_breakdown(client):
    """Verify that planning and sql latencies are tracked."""
    question = "Current USD rate?"
    resp = client.post("/chat", json={"question": question})
    data = resp.json()
    
    breakdown = data.get("latency_breakdown", {})
    assert "planning" in breakdown
    assert "sql" in breakdown
    assert breakdown["planning"] > 0
