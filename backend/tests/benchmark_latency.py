import time
import requests
import json

BASE_URL = "http://localhost:8000"

def test_query(label, question):
    print(f"\n--- Testing: {label} ---")
    print(f"Question: {question}")
    t0 = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/chat", json={"question": question}, timeout=30)
        t1 = time.time()
        data = resp.json()
        
        duration = t1 - t0
        ans_preview = data.get("answer", "")[:100] + "..."
        source_type = data.get("source_type", "unknown")
        planning_time = data.get("latency_breakdown", {}).get("planning", 0.0)
        
        print(f"Status: {resp.status_code}")
        print(f"Total Latency: {duration:.2f}s (Planning: {planning_time:.3f}s)")
        print(f"Source Type: {source_type}")
        print(f"Answer: {ans_preview}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Wait for service to be healthy
    for _ in range(10):
        try:
            if requests.get(f"{BASE_URL}/health").status_code == 200: break
        except: time.sleep(2)

    # 1. Heuristic Bypass (Fast Track)
    test_query("Heuristic Bypass (SPY holdings)", "What are the holdings of SPY?")

    # 2. Plan Cache (Slow Track -> Cache Hit)
    test_query("Plan Cache (Initial - LLM)", "What is the latest USD rate?")
    test_query("Plan Cache (Secondary - Semantic hit)", "Tell me the price of the dollar.")

    # 3. Answer Cache (Exact match)
    test_query("Answer Cache (Repeat Question)", "What is the latest USD rate?")
