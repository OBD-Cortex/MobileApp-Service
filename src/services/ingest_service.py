import os
import sys
import datetime
import polars as pl
from llama_cloud import LlamaCloud

from core.config import LLAMA_INDEX_API_KEY
from core.database import col_knowledge, col_jobs
from core.models import embed_model

async def update_job_status(job_id: str, status: str, progress: str = None, error: str = None):
    """Updates the status of a background ingestion job in MongoDB."""
    if not job_id:
        return
    update_data = {
        "status": status,
        "updated_at": datetime.datetime.utcnow()
    }
    if progress is not None:
        update_data["progress"] = progress
    if error is not None:
        update_data["error_message"] = error
        
    await col_jobs.update_one({"_id": job_id}, {"$set": update_data})

async def ingest_pdf(filepath: str, filename: str, job_id: str = None) -> dict:
    """Parses a PDF manual using LlamaCloud, embeds pages, and saves to MongoDB."""
    try:
        await update_job_status(job_id, "processing", "Checking duplicates...")
        
        # 0. Deduplicate: Check if already indexed in local MongoDB
        if await col_knowledge.find_one({"source": filename}):
            msg = f"Skipped: PDF {filename} already indexed in database."
            await update_job_status(job_id, "completed", msg)
            return {"status": "skipped", "message": msg}

        # 1. Deduplicate: Check if file already exists on LlamaCloud
        await update_job_status(job_id, "processing", "Connecting to LlamaCloud...")
        
        if not LLAMA_INDEX_API_KEY:
            raise ValueError("LLAMA_INDEX_API_KEY environment variable is not configured.")
            
        llama_client = LlamaCloud(api_key=LLAMA_INDEX_API_KEY)
        
        existing_files = llama_client.files.list()
        file_obj = None
        for f in existing_files:
            f_name = getattr(f, 'name', getattr(f, 'file_name', ''))
            if f_name == filename:
                file_obj = f
                print(f"   [o] Reusing existing LlamaCloud file ID: {file_obj.id}")
                break

        if not file_obj:
            await update_job_status(job_id, "processing", "Uploading PDF to LlamaCloud...")
            file_obj = llama_client.files.create(file=filepath, purpose="parse")
        
        await update_job_status(job_id, "processing", "LlamaCloud parsing PDF (this can take 1-2 minutes)...")
        result = llama_client.parsing.parse(
            file_id=file_obj.id, tier="agentic", version="latest", expand=["markdown"]
        )
        
        upload_count = 0
        batch_docs = []
        
        # Step 1: Gather plain text documents from pages
        await update_job_status(job_id, "processing", "Extracting parsed pages...")
        for i, page in enumerate(result.markdown.pages):
            text_content = page.markdown
            if not text_content or not text_content.strip(): 
                continue
            
            batch_docs.append({
                "text": text_content,
                "source": filename,
                "page_number": i + 1,
                "doc_type": "repair_manual"
            })

        # Step 2: Batch Encode and Bulk Insert
        if batch_docs:
            await update_job_status(job_id, "processing", f"Vectorizing {len(batch_docs)} pages (generating 640D embeddings)...")
            texts = [doc["text"] for doc in batch_docs]
            vectors = embed_model.encode(texts).tolist() 
            
            for doc, vector in zip(batch_docs, vectors):
                doc["embedding"] = vector
                
            await col_knowledge.insert_many(batch_docs)
            upload_count += len(batch_docs)

        msg = f"Completed: Successfully indexed {upload_count} pages."
        await update_job_status(job_id, "completed", msg)
        return {"status": "success", "message": msg, "count": upload_count}
    except Exception as e:
        err_msg = str(e)
        await update_job_status(job_id, "failed", error=err_msg)
        raise e

async def ingest_csv(filepath: str, filename: str, job_id: str = None) -> dict:
    """Parses a CSV database using Pandas, embeds rows in batches, and saves to MongoDB."""
    try:
        await update_job_status(job_id, "processing", "Checking duplicates...")
        
        # 0. Deduplicate: Check if already indexed in local MongoDB
        if await col_knowledge.find_one({"source": filename}):
            msg = f"Skipped: CSV {filename} already indexed in database."
            await update_job_status(job_id, "completed", msg)
            return {"status": "skipped", "message": msg}

        await update_job_status(job_id, "processing", "Reading CSV data...")
        df = pl.read_csv(filepath, null_values=[""]).fill_null("") 
        
        upload_count = 0
        batch_docs = []
        batch_size = 256
        total_rows = len(df)
        
        for index, row in enumerate(df.iter_rows(named=True)):
            row_text = ", ".join([f"{col}: {val}" for col, val in row.items() if val != ""])
            batch_docs.append({
                "text": row_text,
                "source": filename,
                "row_number": index + 1,
                "doc_type": "dtc_database" 
            })
            
            if len(batch_docs) >= batch_size:
                processed = index + 1
                await update_job_status(job_id, "processing", f"Vectorizing CSV rows ({processed}/{total_rows})...")
                texts = [doc["text"] for doc in batch_docs]
                vectors = embed_model.encode(texts).tolist()
                
                for doc, vector in zip(batch_docs, vectors):
                    doc["embedding"] = vector
                    
                await col_knowledge.insert_many(batch_docs)
                upload_count += len(batch_docs)
                batch_docs = []
                
        if batch_docs:
            await update_job_status(job_id, "processing", f"Vectorizing remaining CSV rows ({total_rows}/{total_rows})...")
            texts = [doc["text"] for doc in batch_docs]
            vectors = embed_model.encode(texts).tolist()
            for doc, vector in zip(batch_docs, vectors): 
                doc["embedding"] = vector
            await col_knowledge.insert_many(batch_docs)
            upload_count += len(batch_docs)
            
        msg = f"Completed: Successfully indexed {upload_count} rows."
        await update_job_status(job_id, "completed", msg)
        return {"status": "success", "message": msg, "count": upload_count}
    except Exception as e:
        err_msg = str(e)
        await update_job_status(job_id, "failed", error=err_msg)
        raise e

async def ingest_text(filepath: str, filename: str, job_id: str = None) -> dict:
    """Parses a text/markdown file, chunks it, embeds it, and saves to MongoDB."""
    try:
        await update_job_status(job_id, "processing", "Checking duplicates...")
        
        if await col_knowledge.find_one({"source": filename}):
            msg = f"Skipped: Text file {filename} already indexed in database."
            await update_job_status(job_id, "completed", msg)
            return {"status": "skipped", "message": msg}

        await update_job_status(job_id, "processing", "Reading text data...")
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        upload_count = 0
        batch_docs = []
        batch_size = 256
        total_chunks = len(paragraphs)
        
        for index, text in enumerate(paragraphs):
            batch_docs.append({
                "text": text,
                "source": filename,
                "chunk_number": index + 1,
                "doc_type": "text_document" 
            })
            
            if len(batch_docs) >= batch_size:
                processed = index + 1
                await update_job_status(job_id, "processing", f"Vectorizing text chunks ({processed}/{total_chunks})...")
                texts = [doc["text"] for doc in batch_docs]
                vectors = embed_model.encode(texts).tolist()
                
                for doc, vector in zip(batch_docs, vectors):
                    doc["embedding"] = vector
                    
                await col_knowledge.insert_many(batch_docs)
                upload_count += len(batch_docs)
                batch_docs = []
                
        if batch_docs:
            await update_job_status(job_id, "processing", f"Vectorizing remaining text chunks ({total_chunks}/{total_chunks})...")
            texts = [doc["text"] for doc in batch_docs]
            vectors = embed_model.encode(texts).tolist()
            for doc, vector in zip(batch_docs, vectors): 
                doc["embedding"] = vector
            await col_knowledge.insert_many(batch_docs)
            upload_count += len(batch_docs)
            
        msg = f"Completed: Successfully indexed {upload_count} chunks."
        await update_job_status(job_id, "completed", msg)
        return {"status": "success", "message": msg, "count": upload_count}
    except Exception as e:
        err_msg = str(e)
        await update_job_status(job_id, "failed", error=err_msg)
        raise e
