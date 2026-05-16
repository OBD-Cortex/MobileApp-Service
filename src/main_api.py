from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

# Clean imports from our new modules!
from services.llm_agent import generate_diagnostic

app = FastAPI(title="OBD-Cortex API")

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
        # All the messy DB and API logic is handled in one clean function call
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