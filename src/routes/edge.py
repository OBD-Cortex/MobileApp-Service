import datetime
import logging
import random
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from core.database import col_telemetry, col_devices
from core.auth import verify_device_token, verify_device_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Edge Gateway"])

class DeviceProvisionRequest(BaseModel):
    device_secret: str
    vin: str
    brand: str = "Unknown"
    model: str = "Unknown"
    year: str = "Unknown"

@router.post("/telemetry")
async def upload_telemetry(payloads: List[Dict[str, Any]], device: dict = Depends(verify_device_signature)):
    """Receives a batch of HMAC-signed telemetry snapshots from the Edge Gateway."""
    if not payloads:
        return {"status": "success", "inserted": 0}
    if len(payloads) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 snapshots per batch")
    try:
        for payload in payloads:
            # Bind the payload to the specific device's VIN
            payload["vin"] = device.get("vin")
            if "timestamp" in payload and isinstance(payload["timestamp"], str):
                try:
                    ts_str = payload["timestamp"]
                    if ts_str.endswith("Z"):
                        ts_str = ts_str[:-1] + "+00:00"
                    payload["timestamp"] = datetime.datetime.fromisoformat(ts_str)
                except Exception as parse_err:
                    logger.warning(f"[!] Failed to parse timestamp '{payload.get('timestamp')}': {parse_err}")

        await col_telemetry.insert_many(payloads)
        return {"status": "success", "inserted": len(payloads)}
    except Exception as e:
        logger.error(f"[!] Telemetry endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/device/provision")
async def provision_device(request: DeviceProvisionRequest, device_token: str = Depends(verify_device_token)):
    """Pairs an Edge Gateway to a specific VIN and exchanges the symmetric HMAC secret."""
    now = datetime.datetime.utcnow().isoformat()
    
    device = await col_devices.find_one({"device_token": device_token})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    # Generate a unique integer ID for the edge device to use
    # Retry loop to prevent database collisions
    max_retries = 10
    device_id = None
    for _ in range(max_retries):
        candidate_id = random.randint(100000, 99999999)
        if not await col_devices.find_one({"device_id": candidate_id}):
            device_id = candidate_id
            break
            
    if device_id is None:
        raise HTTPException(status_code=500, detail="Failed to generate a unique Device ID. Please try again.")
    
    vehicle_entry = {
        "vin": request.vin,
        "brand": request.brand,
        "model": request.model,
        "year": request.year,
        "paired_at": now
    }
    
    # Clean up any existing vehicle entries for this VIN (just in case)
    await col_devices.update_one(
        {"device_token": device_token},
        {"$pull": {"vehicles": {"vin": request.vin}}}
    )
    
    current_status = device.get("status", "manufactured")
    new_status = "paired" if (current_status == "paired" or "owner_id" in device) else "registered"
    
    await col_devices.update_one(
        {"device_token": device_token},
        {
            "$set": {
                "status": new_status,
                "vin": request.vin,
                "brand": request.brand,
                "model": request.model,
                "year": request.year,
                "device_secret": request.device_secret,
                "device_id": device_id,
                "updated_at": now
            },
            "$push": {
                "vehicles": vehicle_entry
            }
        }
    )
    return {"status": "success", "device_id": device_id}
