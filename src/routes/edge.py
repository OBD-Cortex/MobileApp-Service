import datetime
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.database import col_telemetry, col_devices
from core.auth import verify_device_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Edge Gateway"])

class DeviceRegisterRequest(BaseModel):
    vin: str
    brand: str = "Unknown"
    model: str = "Unknown"
    year: str = "Unknown"

@router.post("/telemetry")
def upload_telemetry(payloads: List[Dict[str, Any]], device_token: str = Depends(verify_device_token)):
    """Receives a batch of telemetry snapshots from the Edge Gateway."""
    if not payloads:
        return {"status": "success", "inserted": 0}
    if len(payloads) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 snapshots per batch")
    try:
        for payload in payloads:
            if "timestamp" in payload and isinstance(payload["timestamp"], str):
                try:
                    ts_str = payload["timestamp"]
                    if ts_str.endswith("Z"):
                        ts_str = ts_str[:-1] + "+00:00"
                    payload["timestamp"] = datetime.datetime.fromisoformat(ts_str)
                except Exception as parse_err:
                    logger.warning(f"[!] Failed to parse timestamp '{payload.get('timestamp')}': {parse_err}")

        col_telemetry.insert_many(payloads)
        return {"status": "success", "inserted": len(payloads)}
    except Exception as e:
        logger.error(f"[!] Telemetry endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/device/register")
def register_device(request: DeviceRegisterRequest, device_token: str = Depends(verify_device_token)):
    """Pairs an Edge Gateway to a specific VIN if the token is valid."""
    now = datetime.datetime.utcnow().isoformat()
    vehicle_entry = {
        "vin": request.vin,
        "brand": request.brand,
        "model": request.model,
        "year": request.year,
        "paired_at": now
    }
    
    col_devices.update_one(
        {"device_token": device_token},
        {"$pull": {"vehicles": {"vin": request.vin}}}
    )
    
    device = col_devices.find_one({"device_token": device_token})
    current_status = device.get("status") if device else "manufactured"
    new_status = "paired" if (current_status == "paired" or (device and "owner_id" in device)) else "registered"
    
    col_devices.update_one(
        {"device_token": device_token},
        {
            "$set": {
                "status": new_status,
                "vin": request.vin,
                "brand": request.brand,
                "model": request.model,
                "year": request.year,
                "updated_at": now
            },
            "$push": {
                "vehicles": vehicle_entry
            }
        }
    )
    return {"status": "success", "message": "Device registered."}
