import pytest
from rag.router import QueryPlanner


# -----------------------------
# Helper
# -----------------------------
async def get_plans(question: str):
    result = await QueryPlanner.plan(question)
    return result.plans


# =========================================================
# 🔥 FX TESTS
# =========================================================

@pytest.mark.asyncio
async def test_fx_determinism():
    q = "What is USD/ILS rate?"

    results = []
    for _ in range(3):
        plans = await get_plans(q)
        results.append(plans[0].query)

    assert len(set(results)) == 1


@pytest.mark.asyncio
async def test_fx_variants_english():
    questions = [
        "USD to ILS",
        "ILS to USD",
        "dollar shekel rate",
    ]

    for q in questions:
        plans = await get_plans(q)
        query = plans[0].query

        assert "base_currency='USD'" in query
        assert "quote_currency='ILS'" in query


@pytest.mark.asyncio
async def test_fx_hebrew():
    q = "מה שער הדולר לשקל?"

    plans = await get_plans(q)

    assert plans[0].source == "sql"
    assert "USD" in plans[0].query
    assert "ILS" in plans[0].query


# =========================================================
# 📈 PRICE TESTS
# =========================================================

@pytest.mark.asyncio
async def test_price_lookup_english():
    q = "Show me AAPL price"

    plans = await get_plans(q)

    assert plans[0].source == "sql"
    assert "AAPL" in plans[0].query


@pytest.mark.asyncio
async def test_price_lookup_hebrew():
    q = "מה מחיר מניית אפל?"

    plans = await get_plans(q)

    # יכול להיות SQL או fallback ל-vector אם אין זיהוי ticker
    assert plans[0].source in ["sql", "vector"]


@pytest.mark.asyncio
async def test_invalid_price_fallback():
    q = "What is the price of that company?"

    plans = await get_plans(q)

    assert plans[0].source == "vector"


# =========================================================
# 🌍 MACRO TESTS (UPDATED)
# =========================================================

@pytest.mark.asyncio
async def test_macro_definition():
    q = "What is inflation?"

    plans = await get_plans(q)

    # definition → vector
    assert plans[0].source == "vector"


@pytest.mark.asyncio
async def test_macro_data_query():
    q = "What is the current inflation rate?"

    plans = await get_plans(q)

    assert plans[0].source == "sql"
    assert "CPIAUCNS" in plans[0].query


@pytest.mark.asyncio
async def test_macro_hebrew():
    q = "מה האינפלציה בארה״ב?"

    plans = await get_plans(q)

    assert plans[0].source == "sql"
    assert "CPIAUCNS" in plans[0].query


# =========================================================
# 📄 VECTOR / ANALYSIS TESTS
# =========================================================

@pytest.mark.asyncio
async def test_analysis_english():
    q = "Explain currency risks"

    plans = await get_plans(q)

    assert plans[0].source == "vector"


@pytest.mark.asyncio
async def test_analysis_hebrew():
    q = "תסביר את הסיכון במטבעות"

    plans = await get_plans(q)

    assert plans[0].source == "vector"


# =========================================================
# 🔀 MIXED QUERY TESTS
# =========================================================

@pytest.mark.asyncio
async def test_mixed_query_english():
    q = "What is USD/ILS and how does it affect bonds?"

    plans = await get_plans(q)

    sources = [p.source for p in plans]

    assert "sql" in sources
    assert "vector" in sources


@pytest.mark.asyncio
async def test_mixed_query_hebrew():
    q = "מה שער הדולר לשקל ואיך זה משפיע על התיק שלי?"

    plans = await get_plans(q)

    sources = [p.source for p in plans]

    assert "sql" in sources
    assert "vector" in sources


# =========================================================
# ⚠️ FALLBACK TESTS
# =========================================================

@pytest.mark.asyncio
async def test_structured_fallback_hebrew():
    q = "שער דולר שקל"

    plans = await get_plans(q)

    assert plans[0].source == "sql"


@pytest.mark.asyncio
async def test_unstructured_fallback_hebrew():
    q = "סכם לי את המסמכים שהעליתי"

    plans = await get_plans(q)

    assert plans[0].source == "vector"


# =========================================================
# 🔒 SECURITY TEST
# =========================================================

@pytest.mark.asyncio
async def test_sql_injection_safety():
    q = "USD; DROP TABLE users;"

    plans = await get_plans(q)

    if plans[0].source == "sql":
        assert ";" not in plans[0].query


# =========================================================
# 🧠 CONSISTENCY TEST
# =========================================================

@pytest.mark.asyncio
async def test_consistency_multilang():
    q1 = "What is USD/ILS rate?"
    q2 = "מה שער הדולר לשקל?"

    plans1 = await get_plans(q1)
    plans2 = await get_plans(q2)

    assert plans1[0].query == plans2[0].query