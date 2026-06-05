import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.database import col_chat_history
from core.auth import verify_api_key
from services.llm_agent import generate_diagnostic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Legacy Chat"])

class ChatRequest(BaseModel):
    vin: str
    query: str

class ChatResponse(BaseModel):
    response: str

class ClearChatRequest(BaseModel):
    vin: str

@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, api_key: str = Depends(verify_api_key)):
    """Handles incoming chat queries from the Flutter mobile app."""
    try:
        chat_doc = col_chat_history.find_one({"vin": request.vin})
        history = chat_doc["history"] if chat_doc else []
        
        answer = generate_diagnostic(request.query, history, request.vin)
        
        history.append(f"User: {request.query}")
        history.append(f"AI: {answer}")
        
        history = history[-6:]
        
        col_chat_history.update_one(
            {"vin": request.vin},
            {"$set": {"history": history}},
            upsert=True
        )
        
        return ChatResponse(response=answer)
    except Exception as e:
        logger.error(f"[!] Chat endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/clear-chat")
def clear_chat_endpoint(request: ClearChatRequest, api_key: str = Depends(verify_api_key)):
    """Wipes the conversation memory for a specific vehicle."""
    col_chat_history.delete_one({"vin": request.vin})
    return {"status": "success", "message": f"Memory cleared for {request.vin}."}
