"""
Authentication Module — OBD-Cortex Mobile App
Provides JWT token management and bcrypt password hashing for the mobile
application tier. This module does NOT affect the admin (X-API-Key) or
edge device (X-Device-Token) authentication pathways.
"""

import datetime
import bcrypt
import jwt
from fastapi import HTTPException, Header, Security
from fastapi.security import APIKeyHeader
from core.config import JWT_SECRET, MOBILE_API_KEY
from core.database import col_devices

# Token lifetime: 14 days (2 weeks)
_TOKEN_LIFETIME = datetime.timedelta(days=14)


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
        "iat": now,
        "exp": now + _TOKEN_LIFETIME,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """Verifies signature + expiry and returns the decoded payload."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")

    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
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


# ==========================================
# 4. API KEY SECURITY DEPENDENCIES
# ==========================================

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    """Verifies that the incoming request contains the correct API key."""
    if api_key != MOBILE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

device_token_header = APIKeyHeader(name="X-Device-Token", auto_error=True)

def verify_device_token(device_token: str = Security(device_token_header)):
    """Verifies that the incoming request contains a valid hardware device token."""
    normalized_token = device_token.strip().upper()
    device = col_devices.find_one({"device_token": normalized_token})
    if not device:
        raise HTTPException(status_code=403, detail="Invalid Device Token")
    return normalized_token
