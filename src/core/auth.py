"""
Authentication Module -- OBD-Cortex
Provides JWT token management, bcrypt password hashing, API key
verification, and HMAC device signature validation.

Security Hardening Applied:
  [*] Timing-safe API key comparison (hmac.compare_digest)
  [*] JWT lifetime reduced to 7 days with iss/aud/jti claims
  [*] Minimum secret length validation at startup
  [*] HMAC replay protection with timestamp window + nonce cache
  [*] Failed auth attempt logging (without leaking secrets)
"""

import time
import datetime
import logging
import bcrypt
import jwt
import hmac
import hashlib
import uuid
from collections import OrderedDict
from fastapi import HTTPException, Header, Security, Request
from fastapi.security import APIKeyHeader
from core.config import JWT_SECRET, MOBILE_API_KEY
from core.database import col_devices
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------
# STARTUP VALIDATION
# ----------------------------------------------------------
# Enforce minimum secret lengths to prevent weak keys.
_MIN_SECRET_LENGTH = 32

if JWT_SECRET and len(JWT_SECRET) < _MIN_SECRET_LENGTH:
    logger.warning(
        f"[!] JWT_SECRET is only {len(JWT_SECRET)} characters. "
        f"Minimum recommended length is {_MIN_SECRET_LENGTH}."
    )

if MOBILE_API_KEY and len(MOBILE_API_KEY) < _MIN_SECRET_LENGTH:
    logger.warning(
        f"[!] MOBILE_API_KEY is only {len(MOBILE_API_KEY)} characters. "
        f"Minimum recommended length is {_MIN_SECRET_LENGTH}."
    )

# Token lifetime: 7 days
_TOKEN_LIFETIME = datetime.timedelta(days=7)

# JWT issuer and audience for token binding
_JWT_ISSUER = "obd-cortex"
_JWT_AUDIENCE = "obd-cortex-mobile"


# ==========================================
# 1. PASSWORD HASHING (bcrypt)
# ==========================================

def hash_password(plain: str) -> str:
    """Hashes a plaintext password using bcrypt with 12 rounds (auto-salted)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison of a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ==========================================
# 2. JWT TOKEN MANAGEMENT
# ==========================================

def create_jwt(user_id: str, username: str, device_token: str, vin: str) -> str:
    """Creates a signed JWT containing the user's identity and device binding."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "device_token": device_token,
        "vin": vin,
        "iss": _JWT_ISSUER,       # Issuer claim for token binding
        "aud": _JWT_AUDIENCE,     # Audience claim for token binding
        "jti": str(uuid.uuid4()), # Unique token ID for future revocation
        "iat": now,
        "exp": now + _TOKEN_LIFETIME,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """Verifies signature + expiry and returns the decoded payload."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")

    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer=_JWT_ISSUER,
            audience=_JWT_AUDIENCE,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ==========================================
# 3. FASTAPI DEPENDENCY
# ==========================================

def verify_jwt(authorization: str = Header(..., alias="Authorization")) -> dict:
    """
    FastAPI dependency that extracts and validates a Bearer JWT from the
    Authorization header. Returns the decoded payload dict on success.

    Usage:
        @router.get("/protected")
        def protected_route(user: dict = Depends(verify_jwt)):
            user_id = user["sub"]
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization[7:]  # Strip "Bearer " prefix
    return decode_jwt(token)


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    """Verifies the API key using timing-safe comparison to prevent timing attacks."""
    if not MOBILE_API_KEY:
        logger.error("[!] MOBILE_API_KEY is not configured")
        raise HTTPException(status_code=500, detail="Server misconfiguration")

    # SECURITY: hmac.compare_digest prevents timing-based key extraction
    if not hmac.compare_digest(api_key.encode("utf-8"), MOBILE_API_KEY.encode("utf-8")):
        logger.warning(f"[!] Invalid API key attempt (key length: {len(api_key)})")
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key


device_token_header = APIKeyHeader(name="X-Device-Token", auto_error=True)

async def verify_device_token(device_token: str = Security(device_token_header)):
    """Verifies that the incoming request contains a valid hardware device token."""
    normalized_token = device_token.strip().upper()
    device = await col_devices.find_one({"device_token": normalized_token})
    if not device:
        logger.warning(f"[!] Invalid device token attempt (token length: {len(device_token)})")
        raise HTTPException(status_code=403, detail="Invalid Device Token")
    return normalized_token


# ----------------------------------------------------------
# 5. HMAC SIGNATURE VERIFICATION (Edge Devices)
# ----------------------------------------------------------
# Replay protection: reject timestamps outside a 5-minute window
# and cache recent nonces to prevent exact replays.
_HMAC_WINDOW_SECONDS = 300  # 5 minutes
_NONCE_CACHE_MAX = 10000

# Ordered dict acts as an LRU nonce cache with bounded size
_nonce_cache = OrderedDict()


def _check_nonce(nonce_key: str) -> bool:
    """Returns True if this nonce has been seen before (replay detected)."""
    if nonce_key in _nonce_cache:
        return True
    # Evict oldest entries if cache is full
    while len(_nonce_cache) >= _NONCE_CACHE_MAX:
        _nonce_cache.popitem(last=False)
    _nonce_cache[nonce_key] = True
    return False


async def verify_device_signature(request: Request):
    """Verifies the HMAC-SHA256 signature with replay protection for edge endpoints."""
    device_id_str = request.headers.get("X-Device-ID")
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not device_id_str or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing signature headers")

    try:
        device_id = int(device_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Device ID format")

    # SECURITY: Enforce timestamp window to prevent replay attacks.
    # Reject requests with timestamps outside +/- 5 minutes of server time.
    try:
        req_time = datetime.datetime.fromisoformat(timestamp)
        now = datetime.datetime.now(datetime.timezone.utc)
        drift = abs((now - req_time).total_seconds())
        if drift > _HMAC_WINDOW_SECONDS:
            logger.warning(
                f"[!] HMAC timestamp rejected for device {device_id}: "
                f"drift={drift:.0f}s (max={_HMAC_WINDOW_SECONDS}s)"
            )
            raise HTTPException(status_code=401, detail="Request timestamp expired")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    # SECURITY: Nonce check -- reject exact (device_id, timestamp, signature) replays
    nonce_key = f"{device_id}:{timestamp}:{signature}"
    if _check_nonce(nonce_key):
        logger.warning(f"[!] Replay attack detected for device {device_id}")
        raise HTTPException(status_code=401, detail="Replayed request")

    device = await col_devices.find_one({"device_id": device_id})
    if not device or "device_secret" not in device:
        raise HTTPException(status_code=403, detail="Invalid or unprovisioned Device ID")

    body = await request.body()
    signed_data = timestamp.encode('utf-8') + body

    expected_sig = hmac.new(device["device_secret"].encode('utf-8'), signed_data, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        logger.warning(f"[!] Invalid HMAC signature for device {device_id}")
        raise HTTPException(status_code=403, detail="Invalid signature")

    return device
