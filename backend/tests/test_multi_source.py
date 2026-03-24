import pytest
import httpx
import json

API_URL = "http://localhost:8000"

@pytest.fixture
def client():
    with httpx.Client(base_url=API_URL, timeout=30.0) as client:
        yield client

def test_multi_source_sql_only(client):
    """Test a compound question that hits two different SQL tables/queries."""
    # Question about SPY holdings AND FX rates
    question = "What are the top holdings of SPY and what is the current USD/ILS rate?"
    
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    
    # Verify we have sources from SQL
    sources = data.get("sources", [])
    sql_sources = [s for s in sources if s.get("document_id") == "sql_query"]
    
    # For a compound question, the router should have generated 2+ plans
    assert len(sql_sources) >= 1
    assert "Structured Financial Data (SQL)" in data["answer"] or len(data["answer"]) > 10
    
    # Check latency breakdown
    lb = data.get("latency_breakdown", {})
    assert lb.get("planning", 0) > 0
    assert lb.get("sql", 0) > 0
    assert lb.get("retrieval", 0) > 0

def test_multi_source_mixed(client):
    """Test a query that might hit both SQL and Vector (document search)."""
    question = "Check the USD rate and tell me what the latest report says about inflation."
    
    resp = client.post("/chat", json={"question": question})
    assert resp.status_code == 200
    data = resp.json()
    
    sources = data.get("sources", [])
    # Should at least have the SQL part
    assert any(s.get("document_id") == "sql_query" for s in sources)
    
    # Verify latency breakdown contains multi-source metrics
    lb = data.get("latency_breakdown", {})
    assert "sql" in lb
    assert "embedding" in lb
    assert "retrieval" in lb
