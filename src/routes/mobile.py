"""
Mobile Application API Router — OBD-Cortex
All endpoints under /api/mobile/* are authenticated via JWT Bearer tokens.
This module handles user signup (device pairing), login, AI chat, media uploads,
and account management for the Flutter mobile application.
"""

import re
import uuid
import base64
import datetime
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

from core.auth import hash_password, verify_password, create_jwt, verify_jwt
from core.database import (
    col_users, col_devices, col_chat_history,
    col_telemetry, col_media
)
from services.llm_agent import generate_diagnostic, generate_multimodal_diagnostic

router = APIRouter(prefix="/api/mobile", tags=["Mobile"])

# Allowed username pattern: alphanumeric + underscores, 3-30 characters
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,30}$")

# Media upload constraints
_MAX_MEDIA_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_AUDIO_TYPES = {"audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/x-m4a", "audio/webm"}
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


# ==========================================
# DATA MODELS
# ==========================================

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str
    device_token: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        v = v.strip()
        if not _USERNAME_PATTERN.match(v):
            raise ValueError("Username must be 3-30 characters: letters, numbers, underscores only")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8 or len(v) > 128:
            raise ValueError("Password must be between 8 and 128 characters")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class MobileChatRequest(BaseModel):
    query: str
    session_id: str = None


class RenameSessionRequest(BaseModel):
    title: str


# ==========================================
# PUBLIC ENDPOINTS (No Auth Required)
# ==========================================

@router.post("/signup")
async def signup(request: Request, payload: SignupRequest):
    """
    Creates a new user account and pairs a registered device.
    The device must be in 'registered' status (edge device has booted
    and bound to a VIN). After signup, the device transitions to 'paired'.
    """
    # 1. Validate device exists
    normalized_token = payload.device_token.strip().upper()
    device = await col_devices.find_one({"device_token": normalized_token})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # 2. Check device status
    status = device.get("status")
    if status == "manufactured":
        raise HTTPException(
            status_code=400,
            detail="Device has not been activated yet. Plug the device into a vehicle first."
        )
    if status == "paired":
        raise HTTPException(
            status_code=409,
            detail="Device is already claimed by another user"
        )

    # 3. Check username uniqueness (case-insensitive, stored lowercase)
    if await col_users.find_one({"username": payload.username}):
        raise HTTPException(status_code=409, detail="Username is already taken")

    # 4. Create user document
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    vin = device.get("vin", "")

    user_doc = {
        "user_id": user_id,
        "username": payload.username,
        "email": payload.email.strip().lower(),
        "password_hash": hash_password(payload.password),
        "device_token": normalized_token,
        "vin": vin,
        "created_at": now,
        "updated_at": now,
    }

    # Pre-check device token uniqueness to prevent misleading error message
    if await col_users.find_one({"device_token": normalized_token}):
        raise HTTPException(status_code=409, detail="Device is already linked to another account")

    try:
        await col_users.insert_one(user_doc)
    except Exception as e:
        # Handle race condition on unique index
        if "duplicate key" in str(e).lower():
            if "device_token" in str(e).lower():
                raise HTTPException(status_code=409, detail="Device is already linked to another account")
            raise HTTPException(status_code=409, detail="Username is already taken")
        raise HTTPException(status_code=500, detail="Failed to create account")

    # 5. Update device: set status to 'paired' and record owner
    await col_devices.update_one(
        {"device_token": normalized_token},
        {
            "$set": {
                "status": "paired",
                "owner_id": user_id,
                "updated_at": now,
            }
        }
    )

    # 6. Generate JWT
    token = create_jwt(user_id, payload.username, normalized_token, vin)

    return {
        "status": "success",
        "user_id": user_id,
        "username": payload.username,
        "vin": vin,
        "token": token,
    }


@router.post("/login")
async def login(request: Request, payload: LoginRequest):
    """
    Authenticates a user with username + password and returns a JWT.
    Also refreshes the VIN from the device document in case the device
    was re-registered to a different vehicle.
    """
    username_or_email = payload.username.strip().lower()

    # 1. Lookup user by username or email
    user = await col_users.find_one({
        "$or": [
            {"username": username_or_email},
            {"email": username_or_email}
        ]
    })
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 2. Verify password (constant-time bcrypt comparison)
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 3. Refresh VIN from device (device may have been plugged into a new car)
    device_token = user.get("device_token", "")
    vin = user.get("vin", "")

    if device_token:
        device = await col_devices.find_one({"device_token": device_token})
        if device:
            current_vin = device.get("vin", "")
            if current_vin and current_vin != vin:
                vin = current_vin
                await col_users.update_one(
                    {"user_id": user["user_id"]},
                    {"$set": {"vin": vin, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}}
                )

    # 4. Generate JWT
    token = create_jwt(user["user_id"], user["username"], device_token, vin)

    return {
        "status": "success",
        "user_id": user["user_id"],
        "username": user["username"],
        "vin": vin,
        "token": token,
    }

class ForgotPasswordRequest(BaseModel):
    email: str

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    """
    Dummy endpoint for password reset.
    In a real system, this would trigger an email with a reset link/OTP.
    """
    email = payload.email.strip().lower()
    user = await col_users.find_one({"email": email})
    
    # We always return success to prevent email enumeration attacks
    return {
        "status": "success",
        "message": "If an account with that email exists, a password reset link has been sent."
    }


# ==========================================
# PROTECTED ENDPOINTS (JWT Required)
# ==========================================

@router.get("/me")
async def get_profile(user: dict = Depends(verify_jwt)):
    """Returns the current user's profile, device info, and latest telemetry."""
    user_doc = await col_users.find_one({"user_id": user["sub"]})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")

    # Fetch device info
    device_info = None
    device_token = user_doc.get("device_token")
    if device_token:
        device = await col_devices.find_one({"device_token": device_token})
        if device:
            device.pop("_id", None)
            device.pop("owner_id", None)
            device_info = device

    # Fetch latest telemetry snapshot
    last_telemetry = None
    vin = user_doc.get("vin")
    if vin:
        telem = await col_telemetry.find_one(
            {"vehicle_id": vin},
            sort=[("timestamp", -1)]
        )
        if telem:
            telem.pop("_id", None)
            last_telemetry = telem

    return {
        "user_id": user_doc["user_id"],
        "username": user_doc["username"],
        "vin": vin,
        "created_at": user_doc.get("created_at"),
        "device": device_info,
        "last_telemetry": last_telemetry,
    }


@router.get("/chat/history")
async def get_chat_history(session_id: str = None, user: dict = Depends(verify_jwt)):
    """
    Retrieves chat history and parses the stored strings into a JSON array for the mobile app.
    """
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")

    vin = user_doc.get("vin", "")
    if not vin:
        return {"history": []}

    try:
        if session_id:
            chat_doc = await col_chat_history.find_one({"vin": vin, "session_id": session_id})
        else:
            chat_doc = await col_chat_history.find_one({"vin": vin}, sort=[("updated_at", -1)])
        history = chat_doc["history"] if chat_doc else []
        
        formatted = []
        i = 0
        while i < len(history):
            item = history[i]
            if isinstance(item, dict):
                if item.get("role") == "user":
                    response_msg = ""
                    if i + 1 < len(history):
                        next_item = history[i+1]
                        if isinstance(next_item, dict) and next_item.get("role") == "ai":
                            response_msg = next_item.get("content", "")
                            i += 1 # Skip AI
                            
                    if item.get("type") in ["image", "audio"]:
                        formatted.append({
                            "type": item["type"],
                            "file_id": item.get("file_id", ""),
                            "response": response_msg,
                            "timestamp": item.get("timestamp", "")
                        })
                    else:
                        formatted.append({
                            "type": "text",
                            "query": item.get("content", ""),
                            "response": response_msg,
                            "timestamp": item.get("timestamp", "")
                        })
            elif isinstance(item, str) and item.startswith("User:"):
                user_msg = item.replace("User: ", "", 1)
                ai_msg = ""
                if i + 1 < len(history):
                    next_item = history[i+1]
                    if isinstance(next_item, str) and next_item.startswith("AI:"):
                        ai_msg = next_item.replace("AI: ", "", 1)
                        i += 1 # Skip AI
                
                dummy_time = str(datetime.datetime.now(datetime.timezone.utc))
                if user_msg.startswith("[Sent image:"):
                    file_id = user_msg.replace("[Sent image: ", "").replace("]", "")
                    formatted.append({"type": "image", "file_id": file_id, "response": ai_msg, "timestamp": dummy_time})
                elif user_msg.startswith("[Sent audio:"):
                    file_id = user_msg.replace("[Sent audio: ", "").replace("]", "")
                    formatted.append({"type": "audio", "file_id": file_id, "response": ai_msg, "timestamp": dummy_time})
                else:
                    formatted.append({"type": "text", "query": user_msg, "response": ai_msg, "timestamp": dummy_time})
            i += 1
                
        return {"history": formatted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat")
async def mobile_chat(request: MobileChatRequest, user: dict = Depends(verify_jwt)):
    """
    AI diagnostic chat endpoint for mobile users. The VIN is resolved
    dynamically from the user's database record to avoid JWT claim staleness.
    """
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")

    vin = user_doc.get("vin", "")
    if not vin:
        raise HTTPException(
            status_code=400,
            detail="No vehicle linked to your account. Ensure your device is registered."
        )

    try:
        session_id = request.session_id
        is_new_session = False
        if not session_id:
            session_id = str(uuid.uuid4())
            is_new_session = True

        # 1. Fetch chat history for this session
        chat_doc = None
        if not is_new_session:
            chat_doc = await col_chat_history.find_one({"vin": vin, "session_id": session_id})
        history = chat_doc["history"] if chat_doc else []

        # 2. Generate AI diagnostic
        answer = await generate_diagnostic(request.query, history, vin)

        if answer.startswith("Diagnostic Engine Error:"):
            raise HTTPException(status_code=502, detail=answer)

        # 3. Update chat history
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        history.append({"role": "user", "type": "text", "content": request.query, "timestamp": now_ts})
        history.append({"role": "ai", "type": "text", "content": answer, "timestamp": now_ts})
        history = history[-100:] # Keep the last 50 exchanges (100 entries) in the database

        title = chat_doc.get("title") if chat_doc else None
        if not title:
            q = request.query.strip()
            title = q[:25] + "..." if len(q) > 25 else q

        await col_chat_history.update_one(
            {"vin": vin, "session_id": session_id},
            {
                "$set": {
                    "title": title,
                    "history": history,
                    "updated_at": now_ts
                }
            },
            upsert=True
        )

        return {
            "response": answer,
            "session_id": session_id,
            "title": title
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[!] Mobile chat error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def _process_media_upload(file: UploadFile, user: dict, allowed_types: set, media_type: str, session_id: str = None):
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")

    vin = user_doc.get("vin", "")
    if not vin:
        raise HTTPException(status_code=400, detail="No vehicle linked to your account.")

    content_type = file.content_type or ""
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {media_type} format: {content_type}."
        )

    media_bytes = await file.read()
    if len(media_bytes) > _MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail=f"{media_type.capitalize()} file exceeds 5MB limit")
    if len(media_bytes) == 0:
        raise HTTPException(status_code=400, detail=f"{media_type.capitalize()} file is empty")

    media_b64 = base64.b64encode(media_bytes).decode("utf-8")

    is_new_session = False
    if not session_id:
        session_id = str(uuid.uuid4())
        is_new_session = True

    chat_doc = None
    if not is_new_session:
        chat_doc = await col_chat_history.find_one({"vin": vin, "session_id": session_id})
    history = chat_doc["history"] if chat_doc else []

    analysis = await generate_multimodal_diagnostic(media_b64, content_type, vin, history)

    if analysis.startswith("Diagnostic Engine Error:"):
        raise HTTPException(status_code=502, detail=analysis)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    media_doc = {
        "user_id": user["sub"],
        "vin": vin,
        "media_type": media_type,
        "filename": file.filename or f"upload.{content_type.split('/')[-1]}",
        "content_base64": media_b64,
        "mime_type": content_type,
        "size_bytes": len(media_bytes),
        "ai_analysis": analysis,
        "created_at": now,
    }
    result = await col_media.insert_one(media_doc)

    history.append({
        "role": "user", 
        "type": media_type, 
        "file_id": str(result.inserted_id), 
        "timestamp": now
    })
    history.append({
        "role": "ai", 
        "type": "text", 
        "content": analysis, 
        "timestamp": now
    })
    history = history[-100:] # Keep the last 50 exchanges in the database

    title = chat_doc.get("title") if chat_doc else None
    if not title:
        title = f"Uploaded {media_type.capitalize()}"

    await col_chat_history.update_one(
        {"vin": vin, "session_id": session_id},
        {
            "$set": {
                "title": title,
                "history": history,
                "updated_at": now
            }
        },
        upsert=True
    )

    return {
        "analysis": analysis,
        "response": analysis,
        "file_id": str(result.inserted_id),
        "session_id": session_id,
        "title": title,
    }

@router.post("/audio")
async def upload_audio(file: UploadFile = File(...), session_id: str = None, user: dict = Depends(verify_jwt)):
    """Accepts an audio recording, sends it to Gemini's multimodal API."""
    return await _process_media_upload(file, user, _ALLOWED_AUDIO_TYPES, "audio", session_id)

@router.post("/image")
async def upload_image(file: UploadFile = File(...), session_id: str = None, user: dict = Depends(verify_jwt)):
    """Accepts an image upload, sends it to Gemini's multimodal API."""
    return await _process_media_upload(file, user, _ALLOWED_IMAGE_TYPES, "image", session_id)


@router.get("/chat/sessions")
async def get_chat_sessions(user: dict = Depends(verify_jwt)):
    """Retrieves all chat sessions for the user's vehicle, migrating any legacy ones."""
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")

    vin = user_doc.get("vin", "")
    if not vin:
        return {"sessions": []}

    # Check for legacy document migration
    legacy_doc = await col_chat_history.find_one({"vin": vin, "session_id": {"$exists": False}})
    if legacy_doc:
        new_sid = str(uuid.uuid4())
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        history = legacy_doc.get("history", [])
        await col_chat_history.insert_one({
            "vin": vin,
            "session_id": new_sid,
            "title": "Vehicle Diagnostics",
            "updated_at": now_iso,
            "history": history
        })
        await col_chat_history.delete_one({"_id": legacy_doc["_id"]})

    cursor = col_chat_history.find({"vin": vin}).sort("updated_at", -1)
    sessions = []
    async for s in cursor:
        sessions.append({
            "session_id": s["session_id"],
            "title": s.get("title", "Vehicle Diagnostics"),
            "updated_at": s.get("updated_at", "")
        })
    return {"sessions": sessions}


@router.put("/chat/session/{session_id}")
async def rename_session(session_id: str, payload: RenameSessionRequest, user: dict = Depends(verify_jwt)):
    """Renames an existing chat session."""
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")
    vin = user_doc.get("vin", "")
    if not vin:
        raise HTTPException(status_code=400, detail="No vehicle linked to your account.")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    result = await col_chat_history.update_one(
        {"vin": vin, "session_id": session_id},
        {"$set": {"title": title}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat session not found")

    return {"status": "success", "title": title}


@router.delete("/chat/session/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(verify_jwt)):
    """Deletes a chat session."""
    user_id = user["sub"]
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")
    vin = user_doc.get("vin", "")
    if not vin:
        raise HTTPException(status_code=400, detail="No vehicle linked to your account.")

    result = await col_chat_history.delete_one({"vin": vin, "session_id": session_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chat session not found")

    return {"status": "success"}


@router.delete("/account")
async def delete_account(user: dict = Depends(verify_jwt)):
    """
    Permanently deletes the user's account, unpairs their device, and wipes
    all associated data (chat history, media). After deletion, the device
    returns to 'registered' status and can be claimed by a new owner.
    """
    user_id = user["sub"]
    
    # Fetch user first to get the most up-to-date device_token and vin (avoid stale JWT claims)
    user_doc = await col_users.find_one({"user_id": user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User account not found")
        
    vin = user_doc.get("vin", "")
    device_token = user_doc.get("device_token", "")

    # 1. Delete user document
    del_result = await col_users.delete_one({"user_id": user_id})
    if del_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User account not found")

    # 2. Unpair device: reset status to 'registered', remove owner binding
    if device_token:
        await col_devices.update_one(
            {"device_token": device_token},
            {
                "$set": {
                    "status": "registered",
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                "$unset": {"owner_id": ""},
            }
        )

    # 3. Wipe chat history for this VIN (all sessions)
    if vin:
        await col_chat_history.delete_many({"vin": vin})

    # 4. Wipe media uploads for this user
    await col_media.delete_many({"user_id": user_id})

    return {
        "status": "success",
        "message": "Account deleted. Device is now available for a new owner.",
    }
