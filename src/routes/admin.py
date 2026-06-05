import re
import datetime
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from core.database import col_devices, col_users, col_knowledge
from core.auth import verify_api_key

router = APIRouter(prefix="/api/admin", tags=["Admin Dashboard"])

class GenerateDevicesRequest(BaseModel):
    count: int

@router.get("/devices")
async def get_admin_devices(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
):
    filter_query = {}
    if status and status != 'all':
        filter_query["status"] = status
    if search:
        query = re.escape(search.strip())
        filter_query["$or"] = [
            { "device_token": { "$regex": query, "$options": "i" } },
            { "vin": { "$regex": query, "$options": "i" } },
        ]
    devices = await col_devices.find(filter_query).sort("created_at", -1).limit(200).to_list(length=None)
    for d in devices:
        d["_id"] = str(d["_id"])
    return {"devices": devices, "count": len(devices)}

@router.get("/stats")
async def get_admin_stats(api_key: str = Depends(verify_api_key)):
    total = await col_devices.count_documents({})
    manufactured = await col_devices.count_documents({"status": "manufactured"})
    registered = await col_devices.count_documents({"status": "registered"})
    paired = await col_devices.count_documents({"status": "paired"})
    return {
        "total": total,
        "manufactured": manufactured,
        "registered": registered,
        "paired": paired
    }

@router.post("/devices/generate")
async def generate_devices(request: GenerateDevicesRequest, api_key: str = Depends(verify_api_key)):
    if request.count < 1 or request.count > 100:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 100")
        
    new_devices = []
    tokens = []
    now = datetime.datetime.utcnow().isoformat()
    
    for _ in range(request.count):
        token = secrets.token_hex(16).upper()
        tokens.append(token)
        new_devices.append({
            "device_token": token,
            "status": "manufactured",
            "created_at": now,
            "updated_at": now
        })
        
    await col_devices.insert_many(new_devices)
    return {"status": "success", "generated": request.count, "tokens": tokens}

@router.delete("/devices/{token}")
async def delete_device(
    token: str,
    force: bool = Query(False),
    api_key: str = Depends(verify_api_key)
):
    normalized_token = token.strip().upper()
    device = await col_devices.find_one({"device_token": normalized_token})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    owner_id = device.get("owner_id")
    is_paired = device.get("status") == "paired" or bool(owner_id)
    
    if is_paired and not force:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a paired device. Use force=true to delete and unpair."
        )
        
    # If forced and paired, clean up the linked user document
    if is_paired and force and owner_id:
        now = datetime.datetime.utcnow().isoformat()
        await col_users.update_one(
            {"user_id": owner_id},
            {
                "$unset": {"device_token": ""},
                "$set": {"updated_at": now}
            }
        )
        
    await col_devices.delete_one({"device_token": normalized_token})
    return {"status": "success"}

@router.post("/devices/{token}/unpair")
async def admin_unpair_device(token: str, api_key: str = Depends(verify_api_key)):
    """Force unpairs a device from its owner (administrative action)."""
    normalized_token = token.strip().upper()
    device = await col_devices.find_one({"device_token": normalized_token})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    owner_id = device.get("owner_id")
    now = datetime.datetime.utcnow().isoformat()
    
    # 1. Unset owner_id and reset status on device
    await col_devices.update_one(
        {"device_token": normalized_token},
        {
            "$set": {
                "status": "registered",
                "updated_at": now,
            },
            "$unset": {"owner_id": ""},
        }
    )
    
    # 2. Update user document to remove device link
    if owner_id:
        await col_users.update_one(
            {"user_id": owner_id},
            {
                "$unset": {"device_token": ""},
                "$set": {"updated_at": now}
            }
        )
        
    return {"status": "success", "message": "Device successfully unpaired from its owner."}

@router.get("/knowledge")
async def list_knowledge(api_key: str = Depends(verify_api_key)):
    """Lists all ingested knowledge base documents grouped by source file."""
    pipeline = [
        {"$group": {
            "_id": "$source",
            "doc_type": {"$first": "$doc_type"},
            "chunk_count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}}
    ]
    docs = await col_knowledge.aggregate(pipeline).to_list(length=None)
    return {"documents": [
        {"source": d["_id"], "doc_type": d["doc_type"], "chunks": d["chunk_count"]}
        for d in docs
    ]}

@router.delete("/knowledge/{source}")
async def delete_knowledge(source: str, api_key: str = Depends(verify_api_key)):
    """Deletes all chunks for a given source document from the knowledge base."""
    result = await col_knowledge.delete_many({"source": source})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "source": source, "chunks_removed": result.deleted_count}
