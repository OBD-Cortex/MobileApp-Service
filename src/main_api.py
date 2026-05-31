import os
import socket
import uvicorn
import shutil
import tempfile
import uuid
import datetime
import re as re_module
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Security, Depends, UploadFile, File, BackgroundTasks, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import secrets

from services.llm_agent import generate_diagnostic
from core.database import col_chat_history, col_jobs, col_telemetry, col_devices
from core.config import MOBILE_API_KEY
from services.ingest_service import ingest_pdf, ingest_csv     

app = FastAPI(title="OBD-Cortex API")

# Load allowed CORS origins from environment (default: allow all)
# Note: Dashboard makes server-side fetch() calls, not browser requests, so CORS
# doesn't apply to it. This is mainly for the web-app test UI and future frontends.
_cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = ["*"] if _cors_raw.strip() == "*" else [o.strip() for o in _cors_raw.split(",")]

# Allow Cross-Origin requests
app.add_middleware(
    CORSMiddleware, 
    allow_origins=CORS_ORIGINS, 
    allow_credentials=False, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ==========================================
# SECURITY: API Key Validation
# ==========================================
# This ensures that only the Flutter app (or authorized clients) can call the AI
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    """Verifies that the incoming request contains the correct API key."""
    if api_key != MOBILE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# This ensures that physical Edge devices are authenticated via their unique token
device_token_header = APIKeyHeader(name="X-Device-Token", auto_error=True)

def verify_device_token(device_token: str = Security(device_token_header)):
    """Verifies that the incoming request contains a valid hardware device token."""
    device = col_devices.find_one({"device_token": device_token})
    if not device:
        raise HTTPException(status_code=403, detail="Invalid Device Token")
    return device_token

# ==========================================
# DATA MODELS
# ==========================================
class ChatRequest(BaseModel):
    vin: str  # Required parameter to track history per individual vehicle
    query: str

class ChatResponse(BaseModel):
    response: str

class DeviceRegisterRequest(BaseModel):
    vin: str
    brand: str = "Unknown"
    model: str = "Unknown"
    year: str = "Unknown"

class GenerateDevicesRequest(BaseModel):
    count: int

# ==========================================
# API ENDPOINTS
# ==========================================
@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, api_key: str = Depends(verify_api_key)):
    """Handles incoming chat queries from the Flutter mobile app."""
    try:
        # 1. Fetch Chat History from MongoDB for this specific VIN
        chat_doc = col_chat_history.find_one({"vin": request.vin})
        history = chat_doc["history"] if chat_doc else []
        
        # 2. Generate AI Answer
        answer = generate_diagnostic(request.query, history, request.vin)
        
        # 3. Append new messages to the history
        history.append(f"User: {request.query}")
        history.append(f"AI: {answer}")
        
        # 4. Truncate history to save token limits (Keeps the last 6 messages)
        history = history[-6:]
        
        # 5. Save the updated history back to MongoDB (Upsert will create if missing)
        col_chat_history.update_one(
            {"vin": request.vin},
            {"$set": {"history": history}},
            upsert=True
        )
        
        return ChatResponse(response=answer)
    except Exception as e:
        print(f"[!] Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/clear-chat")
def clear_chat_endpoint(request: ChatRequest, api_key: str = Depends(verify_api_key)):
    """Wipes the conversation memory for a specific vehicle."""
    col_chat_history.delete_one({"vin": request.vin})
    return {"status": "success", "message": f"Memory cleared for {request.vin}."}


@app.get("/api/health")
def health_endpoint():
    """Returns database and service health status."""
    try:
        from core.database import db
        db.client.admin.command("ping")
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status
    }


# ==========================================
# FILE INGESTION ENDPOINTS (Background Jobs)
# ==========================================

def process_ingestion_background(job_id: str, temp_path: str, filename: str):
    """Worker task that runs the ingestion service in a background thread."""
    try:
        if filename.endswith(".pdf"):
            ingest_pdf(temp_path, filename, job_id=job_id)
        elif filename.endswith(".csv"):
            ingest_csv(temp_path, filename, job_id=job_id)
    except Exception as e:
        print(f"[!] Background Ingestion Task Failed for Job {job_id}: {e}")
    finally:
        # Guarantee cleanup of temporary uploaded file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as cleanup_err:
                print(f"[!] Warning: Failed to delete temp file {temp_path}: {cleanup_err}")


@app.post("/api/ingest")
async def start_ingestion_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key)
):
    """Receives a manual PDF/CSV file upload and starts background vector ingestion."""
    filename = file.filename
    if not (filename.endswith(".pdf") or filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Unsupported file format. Only PDF and CSV files are allowed.")
        
    job_id = str(uuid.uuid4())
    suffix = os.path.splitext(filename)[1]
    
    # Save the upload stream to a secure temporary file
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            await run_in_threadpool(shutil.copyfileobj, file.file, tmp_file)
            temp_path = tmp_file.name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write temporary upload file: {e}")

    # Register the job state in MongoDB
    job_doc = {
        "_id": job_id,
        "filename": filename,
        "status": "queued",
        "progress": "File upload complete. Initializing worker thread...",
        "error_message": None,
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow()
    }
    col_jobs.insert_one(job_doc)
    
    # Enqueue background processing task
    background_tasks.add_task(process_ingestion_background, job_id, temp_path, filename)
    
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/ingest/status/{job_id}")
def get_ingestion_status(job_id: str, api_key: str = Depends(verify_api_key)):
    """Retrieves the current execution status and logs for a background ingestion job."""
    job_doc = col_jobs.find_one({"_id": job_id})
    if not job_doc:
        raise HTTPException(status_code=404, detail="Job ID not found or already expired.")
        
    return {
        "job_id": job_id,
        "filename": job_doc.get("filename"),
        "status": job_doc.get("status"),
        "progress": job_doc.get("progress"),
        "error_message": job_doc.get("error_message"),
        "updated_at": job_doc.get("updated_at")
    }


# ==========================================
# EDGE HARDWARE ENDPOINTS
# ==========================================

@app.post("/api/telemetry")
def upload_telemetry(payloads: List[Dict[str, Any]], device_token: str = Depends(verify_device_token)):
    """Receives a batch of telemetry snapshots from the Edge Gateway."""
    if not payloads:
        return {"status": "success", "inserted": 0}
    if len(payloads) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 snapshots per batch")
    try:
        col_telemetry.insert_many(payloads)
        return {"status": "success", "inserted": len(payloads)}
    except Exception as e:
        print(f"[!] Telemetry endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/device/register")
def register_device(request: DeviceRegisterRequest, device_token: str = Depends(verify_device_token)):
    """Pairs an Edge Gateway to a specific VIN if the token is valid."""
    col_devices.update_one(
        {"device_token": device_token},
        {"$set": {
            "status": "registered",
            "vin": request.vin,
            "brand": request.brand,
            "model": request.model,
            "year": request.year,
            "updated_at": datetime.datetime.utcnow().isoformat()
        }}
    )
    return {"status": "success", "message": "Device registered."}


# ==========================================
# ADMIN DASHBOARD ENDPOINTS
# ==========================================

@app.get("/api/admin/devices")
def get_admin_devices(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
):
    filter_query = {}
    if status and status != 'all':
        filter_query["status"] = status
    if search:
        query = re_module.escape(search.strip())
        filter_query["$or"] = [
            { "device_token": { "$regex": query, "$options": "i" } },
            { "vin": { "$regex": query, "$options": "i" } },
        ]
    devices = list(col_devices.find(filter_query).sort("created_at", -1).limit(200))
    for d in devices:
        d["_id"] = str(d["_id"])
    return {"devices": devices, "count": len(devices)}

@app.get("/api/admin/stats")
def get_admin_stats(api_key: str = Depends(verify_api_key)):
    total = col_devices.count_documents({})
    manufactured = col_devices.count_documents({"status": "manufactured"})
    registered = col_devices.count_documents({"status": "registered"})
    paired = col_devices.count_documents({"status": "paired"})
    return {
        "total": total,
        "manufactured": manufactured,
        "registered": registered,
        "paired": paired
    }

@app.post("/api/admin/devices/generate")
def generate_devices(request: GenerateDevicesRequest, api_key: str = Depends(verify_api_key)):
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
        
    col_devices.insert_many(new_devices)
    return {"status": "success", "generated": request.count, "tokens": tokens}

@app.delete("/api/admin/devices/{token}")
def delete_device(token: str, api_key: str = Depends(verify_api_key)):
    device = col_devices.find_one({"device_token": token})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.get("status") == "paired":
        raise HTTPException(status_code=400, detail="Cannot delete a paired device")
        
    col_devices.delete_one({"device_token": token})
    return {"status": "success"}

# ==========================================
# STATIC FILES & NETWORK HELPER
# ==========================================
# Serve the web interface if navigated to in a browser
static_dir = os.path.join(os.path.dirname(__file__), "web-app")
os.makedirs(static_dir, exist_ok=True) 
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


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
    
    print("\n" + "="*60)
    print(" OBD-CORTEX SERVER IS LIVE!")
    print("="*60)
    print(f" Local Web Testing:   http://localhost:8000/docs")
    print(f" Flutter API Base:    http://{local_ip}:8000")
    print("="*60 + "\n")
    
    # host="0.0.0.0" allows the server to listen to incoming 
    # requests from other devices on the same Wi-Fi network.
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=False)
