from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sys
import os

# Add src to path to import obd-cortex_chat safely if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the existing functionality
# Note: This import will trigger the initialization code in obd-cortex_chat.py
# (Database connection, Model loading, etc.)
try:
    from . import obd_cortex_chat as ai_core
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location("obd_cortex_chat", os.path.join(os.path.dirname(__file__), "obd-cortex_chat.py"))
    ai_core = importlib.util.module_from_spec(spec)
    sys.modules["obd_cortex_chat"] = ai_core
    spec.loader.exec_module(ai_core)

app = FastAPI(title="OBD-Cortex API")

# Allow CORS (useful if we were splitting fontend/backend, harmless here)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    response: str

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # Call the existing function from the original script
        answer = ai_core.ask_obd_cortex(request.query)
        return ChatResponse(response=answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount the static directory to serve the frontend
# We mount it at the root "/"
static_dir = os.path.join(os.path.dirname(__file__), "web-app")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
