import requests
from core.config import GOOGLE_API_KEY, TARGET_VIN
from services.retrieval import get_manual_context, get_telemetry_context

def get_gemini_model() -> str:
    """Dynamically fetches the latest active model from Google to prevent 404 errors."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}"
    try:
        data = requests.get(url).json()
        
        # Get all models that support text generation
        models = [m['name'] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # Automatically pick the newest 'flash' model (e.g., gemini-2.5-flash)
        for m in models:
            if 'flash' in m: return m
            
        return models[0] if models else "models/gemini-2.5-flash"
    except Exception as e:
        print(f"⚠️ Model Auto-Discovery failed, falling back to default. Error: {e}")
        # The new modern fallback instead of the deprecated 1.5 version
        return "models/gemini-2.5-flash" 

# Set the model globally when the server starts
ACTIVE_MODEL = get_gemini_model()
print(f"🧠 [LLM Agent] Engine Initialized using: {ACTIVE_MODEL}")

def generate_diagnostic(query: str, chat_history: list) -> str:
    """Combines Retrieval and LLM calling into the final response"""
    
    # 1. Gather Intelligence
    context_knowledge = get_manual_context(query)
    context_telemetry = get_telemetry_context(TARGET_VIN)
    formatted_history = "\n".join(chat_history[-4:]) 
    
    # 2. Construct Prompt
    prompt = f"""
    SYSTEM INSTRUCTIONS:
    You are OBD-Cortex, an elite automotive diagnostic AI.
    
    CURRENT VEHICLE STATE:
    {context_telemetry}
    
    REFERENCE MANUALS:
    {context_knowledge}
    
    RECENT CONVERSATION:
    {formatted_history}
    
    CURRENT USER QUERY:
    "{query}"
    
    STRICT RULES:
    1. DO NOT repeat the vehicle state or VIN.
    2. DO NOT introduce yourself.
    3. Give specific mechanical troubleshooting steps.
    4. Keep it concise.
    
    Answer:
    """
    
    # 3. Call Google API
    url = f"https://generativelanguage.googleapis.com/v1beta/{ACTIVE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        res.raise_for_status() # This throws an error if we get a 404 or 400
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Diagnostic Engine Error: {e}"
