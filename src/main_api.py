import os
import uuid
import socket
import uvicorn
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager

# Set up logging for the application
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from core.auth import limiter

from routes.mobile import router as mobile_router
from routes.ingest import router as ingest_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import init_db
    await init_db()
    yield

# Disable interactive docs in production (reduces attack surface)
app = FastAPI(
    title="OBD-Cortex API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount mobile application routers
app.include_router(mobile_router)
app.include_router(ingest_router)


# ----------------------------------------------------------
# SECURITY: Request ID Middleware
# ----------------------------------------------------------
# Attaches a unique request ID to every request for audit
# trail correlation across logs.
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)


# ----------------------------------------------------------
# SECURITY: Global Exception Handler
# ----------------------------------------------------------
# Catches unhandled exceptions and returns a generic error
# response. Stack traces are logged server-side but never
# exposed to the client.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"[{request_id}] Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": request_id},
    )


# ----------------------------------------------------------
# SECURITY: CORS Configuration
# ----------------------------------------------------------
# CORS_ORIGINS must be set explicitly in production.
# Wildcard (*) is rejected with a startup warning.
_cors_raw = os.getenv("CORS_ORIGINS", "")
if _cors_raw.strip() == "*":
    logger.error("[!] CORS_ORIGINS cannot be set to wildcard '*' in production for security reasons.")
    raise ValueError("Insecure CORS configuration. Please specify explicit origins.")
elif not _cors_raw:
    logger.warning(
        "[!] CORS_ORIGINS is not set. "
        "This blocks all cross-origin requests. "
        "Set CORS_ORIGINS to a comma-separated list of allowed origins."
    )
    CORS_ORIGINS = []
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "X-API-Key", "X-Device-Token", "X-Device-ID", "X-Signature", "X-Timestamp", "Content-Type"],
)

@app.get("/api/health")
async def health_endpoint():
    """Returns database and service health status."""
    try:
        from core.database import db
        await db.client.admin.command("ping")
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status
    }

# ==========================================
# NETWORK HELPER
# ==========================================

def get_local_ip():
    """Finds the local Wi-Fi IP address of this computer so Flutter can connect over LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    local_ip = get_local_ip()

    logger.info("="*60)
    logger.info(" OBD-CORTEX SERVER IS LIVE!")
    logger.info("="*60)
    logger.info(f" Loopback:            http://127.0.0.1:8000")
    logger.info(f" LAN (if applicable): http://{local_ip}:8000")
    logger.info("="*60)

    # SECURITY: Bind to loopback only. In production, Nginx
    # reverse proxy handles public-facing traffic on port 443
    # and forwards to this process on 127.0.0.1:8000.
    # --proxy-headers trusts X-Forwarded-For from Nginx.
    uvicorn.run(
        "main_api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
