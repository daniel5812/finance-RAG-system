from __future__ import annotations

import asyncpg

from rag_v2.schemas import QueryPlanV2, RetrievalResultV2


async def execute_retrieval(plan: QueryPlanV2, pool: asyncpg.Pool) -> RetrievalResultV2:
    if not plan.supported or not plan.sql:
        return RetrievalResultV2(
            executed=False,
            success=False,
            error=plan.reason or "unsupported query plan",
        )

    from rag.sql_tool import run_sql_query

    rows = await run_sql_query(pool, plan.sql)
    if rows and "error" in rows[0]:
        return RetrievalResultV2(
            executed=True,
            success=False,
            executed_query=plan.sql,
            rows=[],
            row_count=0,
            error=str(rows[0]["error"]),
        )

    return RetrievalResultV2(
        executed=True,
        success=True,
        executed_query=plan.sql,
        rows=rows,
        row_count=len(rows),
    )
