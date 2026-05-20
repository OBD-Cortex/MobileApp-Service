import requests
from core.config import GOOGLE_API_KEY, TARGET_VIN
from services.retrieval import get_manual_context, get_telemetry_context

# Global cache for the model so we only fetch it once
_ACTIVE_MODEL = None

def get_gemini_model() -> str:
    """Lazily fetches and caches the latest active flash model."""
    global _ACTIVE_MODEL
    
    # If we already found the model on a previous turn, use it immediately
    if _ACTIVE_MODEL:
        return _ACTIVE_MODEL

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}"
    try:
        # 5-second timeout so the server doesn't hang indefinitely
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        models = [m['name'] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        for m in models:
            if 'flash' in m:
                _ACTIVE_MODEL = m
                print(f"[LLM Agent] Engine Initialized using: {_ACTIVE_MODEL}")
                return _ACTIVE_MODEL
                
        _ACTIVE_MODEL = models[0] if models else "models/gemini-1.5-flash"
    except Exception as e:
        print(f"[LLM Agent] Model Auto-Discovery failed. Error: {e}")
        _ACTIVE_MODEL = "models/gemini-1.5-flash"
        
    print(f"[LLM Agent] Engine Initialized using: {_ACTIVE_MODEL}")
    return _ACTIVE_MODEL

def generate_diagnostic(query: str, chat_history: list) -> str:
    """Combines Retrieval and LLM calling into the final response"""
    
    # 1. Gather Intelligence
    context_knowledge = get_manual_context(query)
    context_telemetry = get_telemetry_context(TARGET_VIN)
    formatted_history = "\n".join(chat_history[-4:]) 
    
    # 2. Construct Prompt (Using the Upgraded Social Skills Prompt)
    prompt = f"""
    You are OBD-Cortex, an elite, professional automotive diagnostic AI. 

    CURRENT VEHICLE TELEMETRY:
    {context_telemetry}
    
    RELEVANT REPAIR MANUALS (Only use if needed):
    {context_knowledge}
    
    RECENT CONVERSATION HISTORY:
    {formatted_history}
    
    CURRENT USER MESSAGE:
    "{query}"
    
    STRICT BEHAVIORAL RULES:
    1. CONVERSATION AWARENESS: If the user greets you or asks a casual question, DO NOT list troubleshooting steps. Greet them, acknowledge the current vehicle state, and ask how to proceed.
    2. DIAGNOSIS ONLY WHEN ASKED: Only provide mechanical repair steps if the user asks for help or asks about a specific part.
    3. NO REPETITION: Do not blindly repeat the VIN or raw telemetry data.
    4. TONE: Be concise, highly technical, and conversational.
    
    Respond directly to the CURRENT USER MESSAGE based on these rules.
    """
    
    # 3. Call Google API
    model_name = get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GOOGLE_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}
    
    try:
        # 15-second timeout to prevent the API from locking up your server
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        res.raise_for_status() 
        
        # Safe extraction to prevent KeyErrors if Google returns an unexpected format
        data = res.json()
        candidates = data.get('candidates', [])
        
        if not candidates:
            return "Diagnostic Engine Error: API returned an empty response."
            
        return candidates[0]['content']['parts'][0]['text']
        
    except requests.exceptions.Timeout:
        return "Diagnostic Engine Error: The Google API took too long to respond."
    except Exception as e:
        return f"Diagnostic Engine Error: {e}"
