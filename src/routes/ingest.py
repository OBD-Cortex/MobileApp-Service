import os
import uuid
import shutil
import tempfile
import datetime
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.concurrency import run_in_threadpool

from core.database import col_jobs
from core.auth import verify_jwt
from services.ingest_service import ingest_pdf, ingest_csv, ingest_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

async def process_ingestion_background(job_id: str, temp_path: str, filename: str):
    """Worker task that runs the ingestion service in a background thread."""
    try:
        if filename.endswith(".pdf"):
            await ingest_pdf(temp_path, filename, job_id=job_id)
        elif filename.endswith(".csv"):
            await ingest_csv(temp_path, filename, job_id=job_id)
        elif filename.endswith(".md") or filename.endswith(".txt"):
            await ingest_text(temp_path, filename, job_id=job_id)
    except Exception as e:
        logger.error(f"[!] Background Ingestion Task Failed for Job {job_id}: {e}")
    finally:
        # Guarantee cleanup of temporary uploaded file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as cleanup_err:
                logger.warning(f"[!] Warning: Failed to delete temp file {temp_path}: {cleanup_err}")

@router.post("")
async def start_ingestion_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(verify_jwt)
):
    """Receives a manual PDF/CSV file upload and starts background vector ingestion."""
    filename = file.filename
    if not (filename.endswith(".pdf") or filename.endswith(".csv") or filename.endswith(".md") or filename.endswith(".txt")):
        raise HTTPException(status_code=400, detail="Unsupported file format. Only PDF, CSV, MD, and TXT files are allowed.")
        
    job_id = str(uuid.uuid4())
    suffix = os.path.splitext(filename)[1]
    
    # SECURITY: Prevent disk exhaustion using native UploadFile.size check
    if getattr(file, "size", 0) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10MB.")

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
    await col_jobs.insert_one(job_doc)
    
    # Enqueue background processing task
    background_tasks.add_task(process_ingestion_background, job_id, temp_path, filename)
    
    return {"job_id": job_id, "status": "queued"}

@router.get("/status/{job_id}")
async def get_ingestion_status(job_id: str, user: dict = Depends(verify_jwt)):
    """Retrieves the current execution status and logs for a background ingestion job."""
    job_doc = await col_jobs.find_one({"_id": job_id})
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
