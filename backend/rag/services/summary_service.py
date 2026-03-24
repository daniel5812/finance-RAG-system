import json
from core.llm_client import ChatAgentClient
from core.prompts import SOURCE_OVERVIEW_PROMPT
from core.logger import get_logger

logger = get_logger(__name__)

async def generate_source_overview(text: str) -> dict:
    """
    Generate a structured overview for a document using LLM.
    Returns: {summary: str, key_topics: list, suggested_questions: list}
    """
    try:
        # Use first 8000 chars as representative sample to save tokens/time
        sample_text = text[:8000]
        prompt = SOURCE_OVERVIEW_PROMPT.format(text=sample_text)
        
        raw_json = await ChatAgentClient.generate_json(
            messages=[{"role": "user", "content": prompt}]
        )
        
        overview = json.loads(raw_json)
        return {
            "summary": overview.get("summary", ""),
            "key_topics": overview.get("key_topics", []),
            "suggested_questions": overview.get("suggested_questions", [])
        }
    except Exception as e:
        logger.error(f"Failed to generate source overview: {e}")
        return {
            "summary": "Summary generation failed.",
            "key_topics": [],
            "suggested_questions": []
        }
