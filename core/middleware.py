import uuid
from fastapi import Request
from core.logger import request_id_var

async def add_request_id(request: Request, call_next):
    """Generate a unique ID for each request and store it in ContextVar."""
    rid = str(uuid.uuid4())
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token)

async def verify_prompt_injection(request: Request):
    """
    Dependency to check for prompt injection in all requests with a JSON body 
    that contains a 'question' or 'query' field.
    """
    from core.security import detect_prompt_injection
    from fastapi import HTTPException
    import json
    from core.logger import get_logger

    logger = get_logger(__name__)

    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            # We must use body() and decode to avoid consuming the stream for downstream
            body_bytes = await request.body()
            if not body_bytes:
                return True
                
            body = json.loads(body_bytes)
            text_to_check = body.get("question") or body.get("query") or ""
            
            if text_to_check and detect_prompt_injection(text_to_check):
                logger.warning(json.dumps({
                    "event": "prompt_injection_detected", 
                    "path": request.url.path,
                    "method": request.method
                }))
                raise HTTPException(status_code=400, detail="Your query was flagged as potentially unsafe. Please rephrase.")
                
        except json.JSONDecodeError:
            pass

    return True
