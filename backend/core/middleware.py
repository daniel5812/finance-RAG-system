import uuid
import time
import json
from fastapi import Request
from core.logger import request_id_var, get_logger

# Paths that generate constant polling noise — skip observability entirely
_SYSTEM_PATHS = frozenset({
    "/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/favicon.ico",
})


def _classify_request_type(path: str) -> str:
    if path in _SYSTEM_PATHS:
        return "system"
    if path.startswith("/admin"):
        return "admin"
    return "user"


async def add_request_id(request: Request, call_next):
    """
    1. Generate Request ID.
    2. Extract User ID from JWT.
    3. Measure Latency.
    4. Log Structured Request Data.
    5. Emit observability lifecycle events (request_start / response).
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

    # Skip all observability for health/system endpoints — they generate constant noise
    request_type = _classify_request_type(request.url.path)
    if request_type == "system":
        try:
            response = await call_next(request)
            # Add a simple, non-noisy structured log even for system requests
            logger.info(json.dumps({
                "event": "system_request",
                "path": request.url.path,
                "status_code": response.status_code
            }))
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(rid_token)
            user_id_var.reset(uid_token)

    # Emit request_start — earliest possible signal for this request
    try:
        from observability.service import obs
        from observability.schemas import PipelineStage, EventStatus
        obs.emit(
            PipelineStage.REQUEST_START, "request_received",
            summary=f"{request.method} {request.url.path} — user={uid}",
            data={
                "method": request.method,
                "path":   request.url.path,
                "ip":     request.client.host if request.client else "unknown",
                "user_id": uid,
            },
        )
    except Exception:
        pass  # observability must never block requests

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code

        # Calculate Latency
        duration = round((time.time() - t0) * 1000, 2)

        # Structured Logging
        logger.info(json.dumps({
            "request_id": rid,
            "user_id":    uid,
            "method":     request.method,
            "path":       request.url.path,
            "status_code": status_code,
            "latency_ms": duration,
            "ip":         request.client.host if request.client else "unknown",
        }))

        response.headers["X-Request-ID"] = rid

        # Emit request_end + persist request run summary
        try:
            from observability.service import obs
            from observability.schemas import PipelineStage, EventStatus, RequestRun
            obs.emit(
                PipelineStage.RESPONSE, "request_complete",
                summary=f"HTTP {status_code} in {duration}ms",
                latency_ms=duration,
                data={"status_code": status_code, "latency_ms": duration},
                status=EventStatus.SUCCESS if status_code < 400 else EventStatus.FAILED,
            )
            obs.finalize_request(RequestRun(
                req_id=rid,
                user_id=uid,
                path=request.url.path,
                method=request.method,
                status_code=status_code,
                total_latency_ms=duration,
                request_type=request_type,
            ))
        except Exception:
            pass

        return response
    except Exception as e:
        duration = round((time.time() - t0) * 1000, 2)
        logger.error(f"Request Failed [{rid}]: {e}")
        try:
            from observability.service import obs
            from observability.schemas import PipelineStage, EventStatus, ErrorCategory, RequestRun
            obs.emit_error(
                stage=PipelineStage.RESPONSE,
                error_category=ErrorCategory.INFRA,
                error_code="REQUEST_UNHANDLED_EXCEPTION",
                message=str(e),
                exc=e,
            )
            obs.finalize_request(RequestRun(
                req_id=rid,
                user_id=uid,
                path=request.url.path,
                method=request.method,
                status_code=500,
                total_latency_ms=duration,
                error_count=1,
                request_type=request_type,
            ))
        except Exception:
            pass
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
