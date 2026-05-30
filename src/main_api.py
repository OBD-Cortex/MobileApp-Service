import os
import socket
import uvicorn
import shutil
import tempfile
import uuid
import datetime
from fastapi import FastAPI, HTTPException, Security, Depends, UploadFile, File, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from services.llm_agent import generate_diagnostic
from core.database import col_chat_history, col_jobs
from core.config import MOBILE_API_KEY
from services.ingest_service import ingest_pdf, ingest_csv     

app = FastAPI(title="OBD-Cortex API")

# Allow Cross-Origin requests (Adjust in production to your specific needs)
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
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

# ==========================================
# DATA MODELS
# ==========================================
class ChatRequest(BaseModel):
    vin: str  # Required parameter to track history per individual vehicle
    query: str

class ChatResponse(BaseModel):
    response: str

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
        raise HTTPException(status_code=500, detail=str(e))


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
