import json
from typing import AsyncGenerator

from core.connections import openai_client
from core.config import OPENAI_TIMEOUT
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

# ── Custom Exceptions ──
class LLMAPIError(Exception): pass
class LLMTimeoutError(LLMAPIError): pass
class LLMRateLimitError(LLMAPIError): pass

def _map_openai_error(e: Exception) -> Exception:
    if isinstance(e, openai.APITimeoutError):
        return LLMTimeoutError(str(e))
    elif isinstance(e, openai.RateLimitError):
        return LLMRateLimitError(str(e))
    elif isinstance(e, openai.APIStatusError) and e.status_code >= 500:
        return LLMAPIError(f"API Error {e.status_code}: {str(e)}")
    elif isinstance(e, openai.OpenAIError):
        return LLMAPIError(str(e))
    return e

def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, LLMRateLimitError): return True
    if isinstance(exc, LLMTimeoutError): return True
    if isinstance(exc, LLMAPIError) and "API Error" in str(exc): return True
    
    # Catch raw openai errors just in case retry is wrapped on the inner call
    if isinstance(exc, openai.RateLimitError): return True
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500: return True
    if isinstance(exc, openai.APITimeoutError): return True
        
    return False

retry_llm = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)

class RoutingAgentClient:
    """Adapter for the Routing LLM (JSON output)."""
    
    @staticmethod
    @retry_llm
    async def generate_json(messages: list[dict], temperature: float = 0, timeout: int = OPENAI_TIMEOUT) -> str:
        if openai_client is None:
            raise RuntimeError("LLM client is not configured.")
        
        try:
            completion = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=timeout,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise _map_openai_error(e) from e

class ChatAgentClient:
    """Adapter for the main Chat LLM."""
    
    @staticmethod
    @retry_llm
    async def generate(messages: list[dict], temperature: float = 0, timeout: int = OPENAI_TIMEOUT) -> str:
        if openai_client is None:
            raise RuntimeError("LLM client is not configured.")
            
        try:
            completion = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=temperature,
                timeout=timeout,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise _map_openai_error(e) from e

    @staticmethod
    @retry_llm
    async def generate_stream(messages: list[dict], temperature: float = 0, timeout: int = OPENAI_TIMEOUT) -> AsyncGenerator[str, None]:
        if openai_client is None:
            raise RuntimeError("LLM client is not configured.")
            
        try:
            stream = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=temperature,
                stream=True,
                timeout=timeout,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise _map_openai_error(e) from e
