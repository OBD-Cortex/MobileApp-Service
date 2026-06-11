import base64
import json
import hmac
import hashlib
import datetime

class JWTError(Exception):
    pass

class JWTExpiredError(JWTError):
    pass

def _b64url_encode(data: bytes) -> str:
    """Encodes bytes to base64url string."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def _b64url_decode(data: str) -> bytes:
    """Decodes base64url string to bytes."""
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64decode(data + padding)

def encode_jwt(payload: dict, secret: str) -> str:
    """Encodes a payload dictionary into an HS256 JWT."""
    header = {"alg": "HS256", "typ": "JWT"}
    b64_header = _b64url_encode(json.dumps(header).encode('utf-8'))
    b64_payload = _b64url_encode(json.dumps(payload).encode('utf-8'))
    
    signature_input = f"{b64_header}.{b64_payload}"
    signature = hmac.new(
        secret.encode('utf-8'),
        signature_input.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    b64_signature = _b64url_encode(signature)
    return f"{signature_input}.{b64_signature}"

def decode_jwt(token: str, secret: str, audience: str = None, issuer: str = None) -> dict:
    """Decodes and verifies an HS256 JWT, enforcing expiration and claims."""
    parts = token.split('.')
    if len(parts) != 3:
        raise JWTError("Invalid token format")
    
    b64_header, b64_payload, b64_signature = parts
    signature_input = f"{b64_header}.{b64_payload}"
    
    try:
        actual_signature = _b64url_decode(b64_signature)
    except Exception:
        raise JWTError("Invalid token signature encoding")
        
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        signature_input.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise JWTError("Invalid signature")
        
    try:
        payload = json.loads(_b64url_decode(b64_payload).decode('utf-8'))
    except Exception:
        raise JWTError("Invalid token payload")
    
    if 'exp' in payload:
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if now_ts > payload['exp']:
            raise JWTExpiredError("Token has expired")
            
    if issuer and payload.get('iss') != issuer:
        raise JWTError("Invalid issuer")
        
    if audience and payload.get('aud') != audience:
        raise JWTError("Invalid audience")
        
    return payload
