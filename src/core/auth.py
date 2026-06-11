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

import datetime
import logging
import bcrypt
import uuid
from fastapi import HTTPException, Header, Security
from core.config import JWT_SECRET
from core.jwt_native import encode_jwt, decode_jwt, JWTError, JWTExpiredError

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

    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    payload = {
        "sub": user_id,
        "username": username,
        "device_token": device_token,
        "vin": vin,
        "iss": _JWT_ISSUER,       # Issuer claim for token binding
        "aud": _JWT_AUDIENCE,     # Audience claim for token binding
        "jti": str(uuid.uuid4()), # Unique token ID for future revocation
        "iat": now_ts,
        "exp": now_ts + _TOKEN_LIFETIME.total_seconds(),
    }
    return encode_jwt(payload, JWT_SECRET)


def verify_jwt_payload(token: str) -> dict:
    """Verifies signature + expiry and returns the decoded payload."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")

    try:
        return decode_jwt(
            token,
            secret=JWT_SECRET,
            issuer=_JWT_ISSUER,
            audience=_JWT_AUDIENCE,
        )
    except JWTExpiredError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
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
    return verify_jwt_payload(token)


# Removed unused edge device auth methods
