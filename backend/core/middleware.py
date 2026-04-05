import uuid
import time
import json
from fastapi import Request
from core.logger import request_id_var, get_logger


async def add_request_id(request: Request, call_next):
    """
    1. Generate Request ID.
    2. Extract User ID from JWT.
    3. Measure Latency.
    4. Log Structured Request Data.
    """
    from core.logger import request_id_var, user_id_var
    from jose import jwt, JWTError
    from core.auth import JWT_SECRET_KEY, ALGORITHM
    
    logger = get_logger("core.middleware")
    t0 = time.time()

    rid = str(uuid.uuid4())
    rid_token = request_id_var.set(rid)
    
    # Try to extract user_id from JWT for logging
    uid = "none"
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
            uid = payload.get("sub", "none")
        except JWTError:
            pass
            
    uid_token = user_id_var.set(uid)
    
    try:
        response = await call_next(request)
        
        # Calculate Latency
        duration = round((time.time() - t0) * 1000, 2)
        
        # Structured Logging (matches user request #5)
        logger.info(json.dumps({
            "request_id": rid,
            "user_id": uid,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": duration,
            "ip": request.client.host if request.client else "unknown"
        }))
        
        response.headers["X-Request-ID"] = rid
        return response
    except Exception as e:
        # Log critical error
        logger.error(f"Request Failed [{rid}]: {e}")
        raise e
    finally:
        request_id_var.reset(rid_token)
        user_id_var.reset(uid_token)


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
