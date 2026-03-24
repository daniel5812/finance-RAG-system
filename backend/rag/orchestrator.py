import json
import numpy as np
import core.state as state
from core.logger import get_logger, trace_latency
from core.cache import plan_cache_lookup, plan_cache_store
from rag.heuristics import FinancialHeuristics
from rag.router import QueryPlanner
from rag.schemas import MultiQueryPlan

logger = get_logger(__name__)

class QueryOrchestrator:
    """
    Intelligent gateway for query planning.
    Logic: Fast Track (Heuristics) -> Cache (Semantic) -> Slow Track (LLM).
    """

    @staticmethod
    @trace_latency("orchestrator_latency")
    async def get_plan(question: str, query_vector: np.ndarray, role: str) -> MultiQueryPlan:
        # 1. FAST TRACK: Rule-based Heuristics
        entities = FinancialHeuristics.extract_entities(question)
        heuristic_plan = FinancialHeuristics.classify_intent(question, entities)
        
        if heuristic_plan:
            logger.info(json.dumps({"event": "plan_source", "source": "heuristics", "entities": entities}))
            return heuristic_plan

        # 2. CACHE TRACK: Semantic Plan Cache
        cached_plan_dict = await plan_cache_lookup(query_vector, role)
        if cached_plan_dict:
            logger.info(json.dumps({"event": "plan_source", "source": "cache"}))
            return MultiQueryPlan(**cached_plan_dict)

        # 3. SLOW TRACK: LLM Router
        logger.info(json.dumps({"event": "plan_source", "source": "llm_router"}))
        llm_plan = await QueryPlanner.plan(question)
        
        # Store in cache for future use
        await plan_cache_store(query_vector, role, llm_plan.dict())
        
        return llm_plan
