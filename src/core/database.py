"""
Database Connection Module — OBD-Cortex RAG
Establishes a single, pooled MongoDB Atlas connection and exposes named
collection handles for the entire application to import.
"""

import sys
import pymongo
import certifi
from core.config import MONGO_URI

# ==========================================
# 1. CLIENT INITIALIZATION
# ==========================================
# MongoClient manages an internal connection pool — a set of reusable TCP
# sockets to the Atlas cluster. We configure it for a lightweight edge server.

_CLIENT_OPTIONS = {
    "tlsCAFile": certifi.where(),       # CA bundle for TLS certificate verification
    "serverSelectionTimeoutMS": 5000,   # Fail fast if cluster is unreachable (5s cap)
    "maxPoolSize": 10,                  # Right-sized for a single Droplet (default 100 is excessive)
    "minPoolSize": 1,                   # Keep one socket warm to avoid cold-start latency
    "appName": "obd-cortex-api",        # Identifies this app in Atlas performance profiler
    "retryWrites": True,                # Auto-retry writes on transient network failures
    "retryReads": True,                 # Auto-retry reads on transient network failures
}

print("[Database] Initializing MongoDB Connection...")

try:
    client = pymongo.MongoClient(MONGO_URI, **_CLIENT_OPTIONS)

    # Verify: DNS resolved, TCP connected, TLS passed, credentials accepted.
    client.admin.command("ping")

except Exception as e:
    # Sanitize error output to prevent credential leakage in terminal/log files.
    error_msg = str(e)
    if MONGO_URI:
        error_msg = error_msg.replace(MONGO_URI, "[REDACTED_URI]")
    print(f"[!] Database Connection Failed: {error_msg}")
    sys.exit(1)

# ==========================================
# 2. DATABASE & COLLECTION HANDLES
# ==========================================
# These are lightweight references — no network calls or memory allocation
# occurs until an actual read/write operation is performed on them.

db = client["rag_db"]

col_knowledge = db["knowledge"]             # Vector-embedded repair manuals & DTC docs
col_telemetry = db["vehicle_telemetry"]     # Live CAN-bus telemetry snapshots
col_chat_history = db["chat_history"]       # Per-VIN conversational context
col_devices = db["devices"]                 # Pi device registration & owner pairing
col_jobs = db["ingestion_jobs"]             # Temporary status logs for async manual uploads

# Create index on telemetry collection for faster retrieval
try:
    col_telemetry.create_index([("vehicle_id", 1), ("timestamp", -1)])
except Exception as e:
    print(f"[!] Warning: Could not create index on col_telemetry: {e}")

# Create unique index on chat history for fast per-VIN session lookups
try:
    col_chat_history.create_index("vin", unique=True)
except Exception as e:
    print(f"[!] Warning: Could not create index on col_chat_history: {e}")

# Create TTL index on ingestion jobs to auto-delete documents after 24 hours (86400 seconds)
try:
    col_jobs.create_index("created_at", expireAfterSeconds=86400)
except Exception as e:
    print(f"[!] Warning: Could not create TTL index on col_jobs: {e}")

print("[✓] Database Connected.")
