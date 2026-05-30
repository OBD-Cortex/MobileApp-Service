import os
import requests
import re
import time
from core.config import GOOGLE_API_KEY
from services.retrieval import get_manual_context, get_telemetry_context

# ==========================================
# ⚙️ MODEL SELECTION MENU (Verified: May 20, 2026)
# ==========================================
# Instructions: Uncomment ONLY the ONE model you want to use. 
# If you leave all of them commented out (PREFERRED_MODEL = None), 
# the system will auto-discover the best available Flash model.

# --- GEMINI 3 SERIES (The Cutting Edge) ---
PREFERRED_MODEL = "models/gemini-3.5-flash"           # Recommended: Best overall speed/intelligence ratio
# PREFERRED_MODEL = "models/gemini-3.1-pro-preview"   # Smartest: Deepest reasoning for complex diagnostics
# PREFERRED_MODEL = "models/gemini-3.1-flash-lite"    # Fastest: Cost-efficient workhorse

# --- GEMINI 2.5 SERIES (Highly Stable) ---
# PREFERRED_MODEL = "models/gemini-2.5-pro"           # Stable Pro: Deep reasoning, highly reliable
# PREFERRED_MODEL = "models/gemini-2.5-flash"         # Stable Flash: Fast, production-ready reasoning
# PREFERRED_MODEL = "models/gemini-2.5-flash-lite"    # Budget: Lowest latency, lowest cost

# --- GEMINI 2.0 SERIES (Legacy) ---
# PREFERRED_MODEL = "models/gemini-2.0-flash"         # Warning: Scheduled for deprecation June 1, 2026

# --- AUTO DISCOVERY ---
# PREFERRED_MODEL = None                              # Auto-Select: Dynamically asks Google for the best model


# ==========================================
# GLOBAL STATE
# ==========================================
_ACTIVE_MODEL = None

def get_gemini_model() -> str:
    """Lazily fetches and caches the model based on the selection menu above."""
    global _ACTIVE_MODEL
    
    if _ACTIVE_MODEL:
        return _ACTIVE_MODEL

    # 1. Use the explicitly selected model from the list above
    if PREFERRED_MODEL:
        _ACTIVE_MODEL = PREFERRED_MODEL
        print(f"[LLM Agent] Engine Initialized using: {_ACTIVE_MODEL}")
        return _ACTIVE_MODEL

    # 2. Fallback: Auto-Discovery logic if PREFERRED_MODEL = None
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        models = [m['name'] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # Look for the newest standard flash models first
        for m in models:
            if 'flash' in m and 'lite' not in m and 'preview' not in m:
                _ACTIVE_MODEL = m
                print(f"[LLM Agent] Engine Auto-Discovered: {_ACTIVE_MODEL}")
                return _ACTIVE_MODEL
                
        _ACTIVE_MODEL = models[0] if models else "models/gemini-3.5-flash"
        
    except Exception as e:
        error_str = str(e).replace(GOOGLE_API_KEY, "[REDACTED_API_KEY]") if GOOGLE_API_KEY else str(e)
        print(f"[!] [LLM Agent] Auto-Discovery failed. Error: {error_str}")
        # Safe 2026 fallback
        _ACTIVE_MODEL = "models/gemini-2.5-flash" 
        
    print(f"[LLM Agent] Engine Initialized using Fallback: {_ACTIVE_MODEL}")
    return _ACTIVE_MODEL


def generate_diagnostic(query: str, chat_history: list, vin: str) -> str:
    """Combines Retrieval and LLM calling using Chain of Thought reasoning."""
    
    # ---------------------------------------------------------
    # 1. GATHER INTELLIGENCE
    # ---------------------------------------------------------
    # Sanitize user query to prevent XML tag injections
    sanitized_query = query.replace("<", "&lt;").replace(">", "&gt;")
    
    context_knowledge = get_manual_context(query)
    context_telemetry = get_telemetry_context(vin)
    formatted_history = "\n".join(chat_history[-4:]) 
    
    # ---------------------------------------------------------
    # 2. CONSTRUCT THE SMART PROMPT
    # ---------------------------------------------------------
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()
        
    prompt = prompt_template.format(
        context_telemetry=context_telemetry,
        context_knowledge=context_knowledge,
        formatted_history=formatted_history,
        sanitized_query=sanitized_query
    )
    
    # ---------------------------------------------------------
    # 3. PREPARE THE API REQUEST
    # ---------------------------------------------------------
    model_name = get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GOOGLE_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2} 
    }
    headers = {'Content-Type': 'application/json'}
    
    # ---------------------------------------------------------
    # 4. EXECUTE WITH SECURE RETRY LOGIC
    # ---------------------------------------------------------
    max_retries = 3
    
    for attempt in range(max_retries):
        res = None # Initialize to prevent UnboundLocalError on connection failure
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if res.status_code in [429, 500, 503]:
                print(f"[!] Google API Busy ({res.status_code}). Retrying {attempt + 1}/{max_retries}...")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt) 
                    continue
                    
            res.raise_for_status() 
            
            try:
                data = res.json()
            except ValueError:
                return "Diagnostic Engine Error: Received invalid non-JSON response from AI services."
                
            candidates = data.get('candidates', [])
            
            if not candidates:
                # Check for blockReason if safety filter blocked the content
                block_reason = data.get("promptFeedback", {}).get("blockReason")
                if block_reason:
                    return f"Diagnostic Engine Error: Content blocked by safety filter ({block_reason})."
                return "Diagnostic Engine Error: API returned an empty response."
                
            candidate = candidates[0]
            finish_reason = candidate.get("finishReason")
            
            # If the generation finished due to safety blocking or similar issues
            if finish_reason and finish_reason not in ["STOP", "MAX_TOKENS"]:
                return f"Diagnostic Engine Error: Content generation stopped due to reason ({finish_reason})."
                
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            if not parts or "text" not in parts[0]:
                return "Diagnostic Engine Error: API returned a response with no text content."
                
            raw_text = parts[0]['text']
            
            # ---------------------------------------------------------
            # 5. PARSE OUTPUT
            # ---------------------------------------------------------
            response_match = re.search(r'<response>(.*?)</response>', raw_text, re.DOTALL | re.IGNORECASE)
            
            if response_match:
                return response_match.group(1).strip()
            
            # Fallback: if <response> exists but closing tag </response> is missing (e.g., token limit cutoff)
            response_start = re.search(r'<response>(.*)', raw_text, re.DOTALL | re.IGNORECASE)
            if response_start:
                return response_start.group(1).strip()
            else:
                return re.sub(r'<analysis>.*?</analysis>', '', raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
                
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"[!] Google API Timeout. Retrying {attempt + 1}/{max_retries}...")
                time.sleep(2 ** attempt)
                continue
            return "Diagnostic Engine Error: The Google API took too long to respond."
            
        except requests.exceptions.RequestException as e:
            error_str = str(e)
            if GOOGLE_API_KEY and GOOGLE_API_KEY in error_str:
                error_str = error_str.replace(GOOGLE_API_KEY, "[REDACTED_API_KEY]")
                
            print(f"[!] Secure Log - API Request Failed: {error_str}") 
            
            if res is not None and not res.ok and res.status_code not in [429, 500, 503]:
                return f"Diagnostic Engine Error: Invalid request ({res.status_code}). Check server logs."
                
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
                
            return f"Diagnostic Engine Error: Could not connect to AI services."
