import os
import socket
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Clean imports from our new modules!
from services.llm_agent import generate_diagnostic

app = FastAPI(title="OBD-Cortex API")

# CORS is set to allow origins=["*"]
# This allows Flutter to bypass security restrictions.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

session_chat_history = []

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    response: str

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    global session_chat_history
    try:
        answer = generate_diagnostic(request.query, session_chat_history)
        
        session_chat_history.append(f"User: {request.query}")
        session_chat_history.append(f"AI: {answer}")
        
        return ChatResponse(response=answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear-chat")
async def clear_chat_endpoint():
    global session_chat_history
    session_chat_history = []
    return {"status": "success", "message": "Memory cleared."}

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "web-app")
os.makedirs(static_dir, exist_ok=True) 
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# --- NETWORK HELPER FOR FLUTTER ---
def get_local_ip():
    """Finds the local Wi-Fi IP address of this computer so Flutter can connect."""
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
    # requests from other devices on the Wi-Fi network.
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=False)
