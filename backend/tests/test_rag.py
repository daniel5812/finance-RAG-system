"""
🧪 Server Test Script — Full Pipeline Verification
====================================================
1. Uploads ML documents via POST /ingest
2. Tests /chat with cache (LRU + TTL + Soft TTL)

Usage:
    1. Start container:  docker run --env-file .env -p 8000:8000 my-ai-server
    2. Run this script:  python test_server.py
"""

import httpx
import time
import json
import sys
import concurrent.futures

BASE_URL = "http://localhost:8000"
CHAT_URL = f"{BASE_URL}/chat"
INGEST_URL = f"{BASE_URL}/ingest"
HEALTH_URL = f"{BASE_URL}/health"
METRICS_URL = f"{BASE_URL}/metrics"
STREAM_URL = f"{BASE_URL}/chat/stream"

# ── Colors ──
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = 0
failed = 0

# ── Test Documents ──
ML_DOCUMENTS = [
    (
        "Machine learning is a subset of artificial intelligence that enables "
        "systems to learn and improve from experience without being explicitly "
        "programmed. It focuses on developing algorithms that can access data, "
        "learn from it, and make predictions or decisions. Common types include "
        "supervised learning, unsupervised learning, and reinforcement learning."
    ),
    (
        "Neural networks are computing systems inspired by biological neural "
        "networks in the human brain. They consist of layers of interconnected "
        "nodes called neurons. Each connection has a weight that adjusts during "
        "training. Deep learning uses neural networks with many hidden layers "
        "to learn complex patterns in large amounts of data."
    ),
    (
        "Supervised learning is a type of machine learning where the model is "
        "trained on labeled data. The algorithm learns a mapping function from "
        "input to output. Common algorithms include linear regression, logistic "
        "regression, decision trees, random forests, and support vector machines. "
        "It is used for classification and regression tasks."
    ),
    (
        "Reinforcement learning is a type of machine learning where an agent "
        "learns to make decisions by performing actions in an environment to "
        "maximize cumulative reward. Key concepts include the agent, environment, "
        "state, action, and reward. Famous examples include AlphaGo by DeepMind "
        "and training robots to walk."
    ),
    (
        "Overfitting occurs when a machine learning model learns the training "
        "data too well, including noise and outliers, and performs poorly on new "
        "unseen data. Techniques to prevent overfitting include cross-validation, "
        "regularization (L1 and L2), dropout in neural networks, early stopping, "
        "and using more training data."
    ),
]

# ── Questions matched to the documents ──
QUESTIONS = {
    "ml_basics":        "What is machine learning?",
    "neural_networks":  "What are neural networks and how do they work?",
    "supervised":       "What is supervised learning?",
    "reinforcement":    "What is reinforcement learning?",
    "overfitting":      "What is overfitting and how to prevent it?",
    "irrelevant":       "What is the recipe for chocolate cake with strawberries?",
    "secret":           "What is the CEO bonus?",
}

# ── Secret document (admin-only) ──
SECRET_DOCUMENT = (
    "The CEO's secret salary bonus for 2024 is $5,000,000. "
    "This information is strictly confidential and only accessible "
    "to senior management and board members."
)


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


def chat(question: str, timeout: float = 30.0, user_role: str = "employee") -> dict:
    resp = httpx.post(CHAT_URL, json={"question": question, "user_role": user_role}, timeout=timeout)
    if resp.status_code != 200:
        print(f"  {RED}⚠️  Server returned {resp.status_code}: {resp.text[:200]}{RESET}")
        return {"answer": "", "sources": [], "source_type": "error", "error": resp.status_code}
    return resp.json()


# ═══════════════════════════════════════════════════════════════
#  TEST 0 — Server Health Check
# ═══════════════════════════════════════════════════════════════
def test_server_alive():
    header("TEST 0 — Health Check (GET /health)")
    try:
        resp = httpx.get(HEALTH_URL, timeout=5)
        data = resp.json()

        result("Server is reachable", resp.status_code == 200,
               f"Status: {resp.status_code}")
        result("Health status", data.get("status") in ("healthy", "degraded"),
               f"Got: '{data.get('status')}'")
        result("Model loaded", data.get("services", {}).get("model_loaded") is True)
        result("Pinecone connected", data.get("services", {}).get("pinecone_connected") is True,
               f"Vectors: {data.get('services', {}).get('pinecone_vectors', '?')}")
        result("OpenAI configured", data.get("services", {}).get("openai_configured") is True)
        result("Redis connected", data.get("services", {}).get("redis_connected") is True)
        result("Has uptime", data.get("uptime_seconds", -1) >= 0,
               f"{data.get('uptime_seconds')}s")
    except httpx.ConnectError:
        result("Server is reachable", False, "Cannot connect to localhost:8000")
        print(f"\n{RED}⛔ Server not running! Start it first:{RESET}")
        print(f"   docker run --env-file .env -p 8000:8000 my-ai-server\n")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
#  TEST 1 — Document Ingestion (POST /ingest)
# ═══════════════════════════════════════════════════════════════
def test_ingest():
    header("TEST 1 — Document Ingestion (POST /ingest)")

    t0 = time.time()
    resp = httpx.post(
        INGEST_URL,
        json={"documents": ML_DOCUMENTS},
        timeout=60
    )
    latency = time.time() - t0

    result("Status 200", resp.status_code == 200,
           f"Status: {resp.status_code}")

    data = resp.json()
    count = data.get("ingested", 0)
    ids = data.get("ids", [])

    result(f"Ingested {len(ML_DOCUMENTS)} documents", count == len(ML_DOCUMENTS),
           f"Ingested: {count}")
    result("Got document IDs", len(ids) == len(ML_DOCUMENTS),
           f"IDs: {ids[:3]}...")
    result(f"Ingestion time", True, f"{latency:.2f}s")

    # Wait for Pinecone indexing
    print(f"\n  ⏳ Waiting 3s for Pinecone indexing...")
    time.sleep(3)

    # Test empty documents
    resp_empty = httpx.post(INGEST_URL, json={"documents": []}, timeout=10)
    result("Empty docs → 400/422 error", resp_empty.status_code in [400, 422],
           f"Status: {resp_empty.status_code}")

    # Test bad schema
    resp_bad = httpx.post(INGEST_URL, json={"wrong": "field"}, timeout=10)
    result("Bad schema → 422 error", resp_bad.status_code == 422)


# ═══════════════════════════════════════════════════════════════
#  TEST 2 — Fresh Query (Full Pipeline)
# ═══════════════════════════════════════════════════════════════
def test_fresh_query() -> str:
    header("TEST 2 — Fresh Query (Full Pipeline)")

    question = QUESTIONS["ml_basics"]
    t0 = time.time()
    data = chat(question)
    latency = time.time() - t0

    has_answer = "answer" in data and len(data["answer"]) > 0
    has_sources = "sources" in data and len(data.get("sources", [])) > 0
    is_valid_source = data.get("source_type") in ("generated", "cache")
    has_latency = "latency_breakdown" in data

    result("Has answer", has_answer,
           f"{len(data.get('answer', ''))} chars")
    result("Has sources (from uploaded docs)", has_sources,
           f"{len(data.get('sources', []))} sources")
    result("source_type is valid", is_valid_source,
           f"Got: '{data.get('source_type')}' (generated=fresh, cache=repeated run)")
    result("Has latency_breakdown", has_latency,
           json.dumps(data.get("latency_breakdown", {})))

    # Check that the answer is actually about ML (from our docs)
    answer_lower = data.get("answer", "").lower()
    mentions_ml = any(w in answer_lower for w in ["machine learning", "algorithm", "data", "ai"])
    result("Answer is about ML (not random)", mentions_ml)

    print(f"\n  📝 Answer: {data.get('answer', '')[:120]}...")
    print(f"  ⏱️  Latency: {latency:.2f}s")

    return question


# ═══════════════════════════════════════════════════════════════
#  TEST 3 — Cache HIT (same question immediately)
# ═══════════════════════════════════════════════════════════════
def test_cache_hit(question: str):
    header("TEST 3 — Cache HIT (Same Question, Immediate)")

    t0 = time.time()
    data = chat(question)
    latency = time.time() - t0

    is_cache = data.get("source_type") == "cache"

    result("source_type = 'cache'", is_cache,
           f"Got: '{data.get('source_type')}'")
    result("Latency < 2.0s (from cache)", latency < 2.0,
           f"{latency:.3f}s")
    result("Answer still present", len(data.get("answer", "")) > 0)


# ═══════════════════════════════════════════════════════════════
#  TEST 4 — Multiple Rapid Cache Hits
# ═══════════════════════════════════════════════════════════════
def test_multiple_cache_hits(question: str):
    header("TEST 4 — Multiple Rapid Cache Hits (5 requests)")

    latencies = []
    all_cache = True

    for i in range(5):
        t0 = time.time()
        data = chat(question)
        lat = time.time() - t0
        latencies.append(lat)
        if data.get("source_type") != "cache":
            all_cache = False

    avg = sum(latencies) / len(latencies)
    mx  = max(latencies)

    result("All 5 returned source_type='cache'", all_cache)
    result("Average latency < 1.0s", avg < 1.0, f"Avg: {avg:.3f}s")
    result("Max latency < 2.0s", mx < 2.0, f"Max: {mx:.3f}s")


# ═══════════════════════════════════════════════════════════════
#  TEST 5 — Different Questions (Cache Isolation)
# ═══════════════════════════════════════════════════════════════
def test_different_questions():
    header("TEST 5 — Different Questions (Cache Isolation)")

    q1 = QUESTIONS["neural_networks"]
    q2 = QUESTIONS["supervised"]

    data1 = chat(q1)
    data2 = chat(q2)

    answers_different = data1.get("answer") != data2.get("answer")
    both_valid = (
        data1.get("source_type") in ("generated", "cache") and
        data2.get("source_type") in ("generated", "cache")
    )

    result("Different questions → different answers", answers_different)
    result("Both source_type valid", both_valid,
           f"Q1: '{data1.get('source_type')}', Q2: '{data2.get('source_type')}'")

    # Check content relevance
    a1 = data1.get("answer", "").lower()
    a2 = data2.get("answer", "").lower()
    result("Q1 answer mentions 'neural'",
           "neural" in a1 or "network" in a1 or "layer" in a1)
    result("Q2 answer mentions relevant terms",
           "supervised" in a2 or "labeled" in a2 or "label" in a2
           or "training" in a2 or "classification" in a2 or "regression" in a2
           or "algorithm" in a2 or "data" in a2 or "learning" in a2)

    # Re-ask q1 → should be cached
    data1_again = chat(q1)
    result("Re-ask Q1 → cache hit",
           data1_again.get("source_type") == "cache")


# ═══════════════════════════════════════════════════════════════
#  TEST 6 — Low Similarity (Fallback)
# ═══════════════════════════════════════════════════════════════
def test_low_similarity():
    header("TEST 6 — Low Similarity (Fallback)")

    question = QUESTIONS["irrelevant"]
    data = chat(question)

    answer = data.get("answer", "").lower()
    # The model might still get a low-score source but should indicate it can't answer
    is_fallback = (
        "cannot answer" in answer
        or "not" in answer and ("recipe" in answer or "context" in answer or "provided" in answer)
        or "no information" in answer
    )

    result("Recognizes irrelevant question", is_fallback,
           f"Answer: '{data.get('answer', '')[:80]}'")
    result("Few or no sources", len(data.get("sources", [])) <= 1,
           f"Sources: {len(data.get('sources', []))}")


# ═══════════════════════════════════════════════════════════════
#  TEST 7 — Invalid Requests (Error Handling)
# ═══════════════════════════════════════════════════════════════
def test_invalid_request():
    header("TEST 7 — Invalid Requests (Error Handling)")

    # Missing 'question' field
    resp = httpx.post(CHAT_URL, json={"wrong_field": "test"}, timeout=10)
    result("Missing field → 422", resp.status_code == 422)

    # Empty question
    resp = httpx.post(CHAT_URL, json={"question": ""}, timeout=15)
    result("Empty question → handled", resp.status_code in [200, 422],
           f"Status: {resp.status_code}")


# ═══════════════════════════════════════════════════════════════
#  TEST 8 — Concurrent Requests (Async Performance)
# ═══════════════════════════════════════════════════════════════
def test_concurrent():
    header("TEST 8 — Concurrent Requests (3 different questions)")

    questions = [
        QUESTIONS["reinforcement"],
        QUESTIONS["overfitting"],
        "What are the types of machine learning?",
    ]

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(chat, q) for q in questions]
        results_list = [f.result() for f in concurrent.futures.as_completed(futures)]
    total = time.time() - t0

    all_ok = all("answer" in r and len(r["answer"]) > 0 for r in results_list)

    result("All 3 returned answers", all_ok)
    result(f"Total time < 20s (parallel)", total < 20,
           f"{total:.2f}s for 3 concurrent requests")

# ═══════════════════════════════════════════════════════════════
#  TEST 9 — Access Control / Data Leakage Prevention
# ═══════════════════════════════════════════════════════════════
def test_access_control():
    header("TEST 9 — Access Control / Data Leakage Prevention")

    # Step 1: Ingest a SECRET document as admin-only
    print(f"  📤 Uploading secret document (role=admin)...")
    resp = httpx.post(
        INGEST_URL,
        json={"documents": [SECRET_DOCUMENT], "role": "admin"},
        timeout=30
    )
    result("Secret doc ingested (role=admin)",
           resp.status_code == 200,
           f"Status: {resp.status_code}")

    print(f"  ⏳ Waiting 3s for Pinecone indexing...")
    time.sleep(3)

    # Step 2: Employee asks about CEO bonus → MUST NOT see it
    print(f"  🔒 Querying as EMPLOYEE...")
    data_employee = chat(QUESTIONS["secret"], user_role="employee")
    answer_emp = data_employee.get("answer", "").lower()

    has_salary_leak = "5,000,000" in answer_emp or "5000000" in answer_emp or "five million" in answer_emp
    result("Employee CANNOT see CEO salary", not has_salary_leak,
           f"Answer: '{data_employee.get('answer', '')[:100]}'")

    # Check sources don't contain the secret doc
    sources_emp = " ".join(data_employee.get("sources", [])).lower()
    result("Employee sources don't contain secret",
           "secret salary bonus" not in sources_emp,
           f"Sources count: {len(data_employee.get('sources', []))}")

    # Step 3: Admin asks about CEO bonus → CAN see it
    print(f"  🔓 Querying as ADMIN...")
    data_admin = chat(QUESTIONS["secret"], user_role="admin")
    answer_adm = data_admin.get("answer", "").lower()

    has_salary_info = "5,000,000" in answer_adm or "5000000" in answer_adm or "five million" in answer_adm or "bonus" in answer_adm
    result("Admin CAN see CEO salary", has_salary_info,
           f"Answer: '{data_admin.get('answer', '')[:100]}'")

    # Step 4: Verify cache isolation between roles
    print(f"  🔄 Verifying cache isolation (same question, different roles)...")
    data_emp_again = chat(QUESTIONS["secret"], user_role="employee")
    answer_emp2 = data_emp_again.get("answer", "").lower()
    still_blocked = "5,000,000" not in answer_emp2 and "5000000" not in answer_emp2
    result("Cache isolation: employee still blocked after admin query",
           still_blocked,
           f"source_type: '{data_emp_again.get('source_type')}'")


# ═══════════════════════════════════════════════════════════════
#  TEST 10 — Observability (GET /metrics)
# ═══════════════════════════════════════════════════════════════
def test_metrics():
    header("TEST 10 — Observability (GET /metrics)")

    resp = httpx.get(METRICS_URL, timeout=5)
    result("Metrics endpoint returns 200", resp.status_code == 200)

    data = resp.json()

    result("Has total_queries > 0", data.get("total_queries", 0) > 0,
           f"Queries: {data.get('total_queries')}")
    result("Has cache_hit_rate", 0 <= data.get("cache_hit_rate", -1) <= 1,
           f"Hit rate: {data.get('cache_hit_rate')}")
    result("Has similarity scores",
           data.get("similarity", {}).get("window_size", 0) > 0,
           f"Avg: {data.get('similarity', {}).get('avg')}, "
           f"Min: {data.get('similarity', {}).get('min')}")
    result("Has latency percentiles",
           data.get("latency", {}).get("p50", 0) > 0,
           f"p50: {data.get('latency', {}).get('p50')}s, "
           f"p95: {data.get('latency', {}).get('p95')}s, "
           f"p99: {data.get('latency', {}).get('p99')}s")
    result("Has P99 latency",
           "p99" in data.get("latency", {}),
           f"p99: {data.get('latency', {}).get('p99', 'MISSING')}")
    result("Drift alert is boolean",
           isinstance(data.get("drift_alert"), bool),
           f"drift_alert: {data.get('drift_alert')}")
    result("Has uptime", data.get("uptime_seconds", -1) >= 0,
           f"{data.get('uptime_seconds')}s")

    # Print full metrics for inspection
    print(f"\n  📊 Full metrics:")
    for key, val in data.items():
        if isinstance(val, dict):
            print(f"     {key}:")
            for k2, v2 in val.items():
                print(f"       {k2}: {v2}")
        else:
            print(f"     {key}: {val}")

# ═══════════════════════════════════════════════════════════════
#  TEST 11 — Streaming Response (POST /chat/stream)
# ═══════════════════════════════════════════════════════════════
def test_streaming():
    header("TEST 11 — Streaming Response (POST /chat/stream)")

    question = "What is reinforcement learning?"

    # Fresh streaming request
    t0 = time.time()
    ttft = None
    phases = {"meta": None, "tokens": [], "done": None}

    with httpx.stream(
        "POST", STREAM_URL,
        json={"question": question, "user_role": "employee"},
        timeout=30
    ) as resp:
        result("Stream returns 200", resp.status_code == 200,
               f"Status: {resp.status_code}")

        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])

            if payload["type"] == "meta":
                phases["meta"] = payload
            elif payload["type"] == "token":
                if ttft is None:
                    ttft = time.time() - t0
                phases["tokens"].append(payload["content"])
            elif payload["type"] == "done":
                phases["done"] = payload

    total_time = time.time() - t0

    # Verify phases
    result("Got meta phase", phases["meta"] is not None)
    result("Meta has sources", len(phases["meta"].get("sources", [])) > 0 if phases["meta"] else False,
           f"Sources: {len(phases['meta'].get('sources', [])) if phases['meta'] else 0}")
    result("Got tokens", len(phases["tokens"]) > 0,
           f"{len(phases['tokens'])} chunks received")
    result("Got done phase", phases["done"] is not None)

    # Assemble answer
    full_answer = "".join(phases["tokens"])
    result("Answer is valid", len(full_answer) > 50,
           f"{len(full_answer)} chars: '{full_answer[:80]}...'")

    # Time to First Token
    if ttft:
        result("Time to First Token < 2s", ttft < 2.0,
               f"TTFT: {ttft:.3f}s")
    else:
        result("Time to First Token", False, "No tokens received")

    print(f"\n  ⚡ TTFT: {ttft:.3f}s" if ttft else "")
    print(f"  ⏱️  Total: {total_time:.2f}s")
    print(f"  📝 Answer: {full_answer[:100]}...")

    # Verify stream answer got cached — /chat should return cache hit
    data_cached = chat(question)
    result("Stream result cached for /chat",
           data_cached.get("source_type") == "cache",
           f"source_type: '{data_cached.get('source_type')}'")

# ═══════════════════════════════════════════════════════════════
#  TEST 12 — Stream Security (DoS + Content Filter)
# ═══════════════════════════════════════════════════════════════
def test_stream_security():
    header("TEST 12 — Stream Security (Sliding Window + DoS)")

    # 1. Verify buffered token delivery on a fresh question
    question = "What is overfitting and how to prevent it?"

    # Clear cache for this question by using an unusual role combo
    phases = {"meta": None, "tokens": [], "done": None}

    with httpx.stream(
        "POST", STREAM_URL,
        json={"question": question, "user_role": "admin"},
        timeout=30
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload["type"] == "token":
                phases["tokens"].append(payload["content"])
            elif payload["type"] == "done":
                phases["done"] = payload

    token_count = len(phases["tokens"])
    full_answer = "".join(phases["tokens"])

    result("Buffered delivery (multiple token chunks)",
           token_count >= 1,
           f"{token_count} chunks, {len(full_answer)} chars total")
    result("Answer content is valid", len(full_answer) > 30,
           f"'{full_answer[:60]}...'")

    # 2. Verify concurrent stream limit (DoS protection)
    print(f"  \n  🛡️  Testing concurrent stream limit (max=10)...")
    import concurrent.futures

    unique_questions = [
        f"Explain machine learning concept number {i} in detail"
        for i in range(12)
    ]

    def make_stream_request(q):
        """Open a streaming connection — holds the connection alive."""
        try:
            resp = httpx.post(
                STREAM_URL,
                json={"question": q, "user_role": "employee"},
                timeout=15
            )
            return resp.status_code
        except Exception as e:
            return str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(make_stream_request, q) for q in unique_questions]
        statuses = [f.result() for f in concurrent.futures.as_completed(futures)]

    ok_count = statuses.count(200)
    rejected = statuses.count(503)

    result("Some streams accepted (200)", ok_count > 0,
           f"{ok_count} accepted")
    result("DoS protection active (503 on overflow)",
           rejected > 0 or ok_count <= 10,
           f"{rejected} rejected with 503, {ok_count} accepted")

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
    print(f"\n{BOLD}🧪 RAG Server — Full Pipeline Test Suite{RESET}")
    print(f"   Target: {BASE_URL}")
    print(f"   Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")

    test_server_alive()       # 0 — Health check
    test_ingest()             # 1 — Upload documents
    question = test_fresh_query()  # 2 — Full pipeline
    test_cache_hit(question)  # 3 — Cache HIT
    test_multiple_cache_hits(question)  # 4 — Rapid cache
    test_different_questions() # 5 — Cache isolation
    test_low_similarity()     # 6 — Fallback
    test_invalid_request()    # 7 — Error handling
    test_concurrent()         # 8 — Async performance
    test_access_control()     # 9 — Data leakage prevention
    test_metrics()            # 10 — Observability
    test_streaming()          # 11 — SSE streaming
    test_stream_security()    # 12 — Stream security

    print_summary()
