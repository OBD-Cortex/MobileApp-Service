import os
import socket
import uvicorn
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Set up logging for the application
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from routes.mobile import router as mobile_router
from routes.admin import router as admin_router
from routes.edge import router as edge_router
from routes.ingest import router as ingest_router
from routes.chat import router as chat_router

app = FastAPI(title="OBD-Cortex API")

# Mount all application routers
app.include_router(mobile_router)
app.include_router(admin_router)
app.include_router(edge_router)
app.include_router(ingest_router)
app.include_router(chat_router)

# Load allowed CORS origins from environment (default: allow all)
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
    
    logger.info("="*60)
    logger.info(" OBD-CORTEX SERVER IS LIVE!")
    logger.info("="*60)
    logger.info(f" Local Web Testing:   http://localhost:8000/docs")
    logger.info(f" Flutter API Base:    http://{local_ip}:8000")
    logger.info("="*60)
    
    # host="0.0.0.0" allows the server to listen to incoming 
    # requests from other devices on the same Wi-Fi network.
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=False)
