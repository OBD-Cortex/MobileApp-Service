import os
import httpx
import re
import asyncio
import logging
from core.config import GOOGLE_API_KEY
from services.retrieval import get_manual_context, get_telemetry_context

logger = logging.getLogger(__name__)

# ==========================================
# [*] MODEL SELECTION MENU (Verified: June 21, 2026)
# ==========================================
# Uncomment ONLY the ONE model you want to use.
# If PREFERRED_MODEL = None, the system auto-discovers the best available Flash model.

# --- GEMINI 2.5 SERIES (Stable GA — Recommended) ---
PREFERRED_MODEL = "models/gemini-2.5-flash"         # Active: Best speed/accuracy balance for RAG on mobile
# PREFERRED_MODEL = "models/gemini-2.5-flash-lite"  # Budget: Lowest latency, lowest cost, reduced accuracy
# PREFERRED_MODEL = "models/gemini-2.5-pro"         # Pro: Deep reasoning — higher latency, ~10x cost

# --- AUTO DISCOVERY ---
# PREFERRED_MODEL = None                            # Auto-Select: Dynamically asks Google for the best model


# ==========================================
# GLOBAL STATE
# ==========================================
_ACTIVE_MODEL = None

async def get_gemini_model() -> str:
    """Lazily fetches and caches the model based on the selection menu above."""
    global _ACTIVE_MODEL
    
    if _ACTIVE_MODEL:
        return _ACTIVE_MODEL

    # 1. Use the explicitly selected model from the list above
    if PREFERRED_MODEL:
        _ACTIVE_MODEL = PREFERRED_MODEL
        logger.info(f"[*] Engine Initialized using: {_ACTIVE_MODEL}")
        return _ACTIVE_MODEL

    # 2. Fallback: Auto-Discovery logic if PREFERRED_MODEL = None
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            models = [m['name'] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
            
            # Look for the newest standard flash models first
            for m in models:
                if 'flash' in m and 'lite' not in m and 'preview' not in m:
                    _ACTIVE_MODEL = m
                    logger.info(f"[*] Engine Auto-Discovered: {_ACTIVE_MODEL}")
                    return _ACTIVE_MODEL
                    
            _ACTIVE_MODEL = models[0] if models else "models/gemini-3.5-flash"
            
    except Exception as e:
        error_str = str(e).replace(GOOGLE_API_KEY, "[REDACTED_API_KEY]") if GOOGLE_API_KEY else str(e)
        logger.error(f"[!] Auto-Discovery failed. Error: {error_str}")
        # Safe 2026 fallback
        _ACTIVE_MODEL = "models/gemini-2.5-flash" 
        
    logger.info(f"[*] Engine Initialized using Fallback: {_ACTIVE_MODEL}")
    return _ACTIVE_MODEL


async def _call_gemini_api(payload: dict, timeout: int = 15) -> str:
    """Helper to execute API requests with secure retry logic and response parsing."""
    model_name = await get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={GOOGLE_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    max_retries = 3
    
    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            res = None
            try:
                res = await client.post(url, json=payload, headers=headers, timeout=timeout)
                
                if res.status_code in [429, 500, 503]:
                    logger.warning(f"[!] Google API Busy ({res.status_code}). Retrying {attempt + 1}/{max_retries}...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt) 
                        continue
                        
                res.raise_for_status() 
                
                try:
                    data = res.json()
                except ValueError:
                    return "Diagnostic Engine Error: Received invalid non-JSON response from AI services."
                    
                candidates = data.get('candidates', [])
                
                if not candidates:
                    block_reason = data.get("promptFeedback", {}).get("blockReason")
                    if block_reason:
                        return f"Diagnostic Engine Error: Content blocked by safety filter ({block_reason})."
                    return "Diagnostic Engine Error: API returned an empty response."
                    
                candidate = candidates[0]
                finish_reason = candidate.get("finishReason")
                
                if finish_reason and finish_reason not in ["STOP", "MAX_TOKENS"]:
                    return f"Diagnostic Engine Error: Content generation stopped due to reason ({finish_reason})."
                    
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                if not parts or "text" not in parts[0]:
                    return "Diagnostic Engine Error: API returned a response with no text content."
                    
                return parts[0]['text']
                
            except httpx.TimeoutException:
                if attempt < max_retries - 1:
                    logger.warning(f"[!] Google API Timeout. Retrying {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                return "Diagnostic Engine Error: The Google API took too long to respond."
                
            except httpx.HTTPError as e:
                error_str = str(e)
                if GOOGLE_API_KEY and GOOGLE_API_KEY in error_str:
                    error_str = error_str.replace(GOOGLE_API_KEY, "[REDACTED_API_KEY]")
                    
                logger.error(f"[!] Secure Log - API Request Failed: {error_str}") 
                
                if res is not None and res.is_error and res.status_code not in [429, 500, 503]:
                    return f"Diagnostic Engine Error: Invalid request ({res.status_code}). Check server logs."
                    
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
                return "Diagnostic Engine Error: Could not connect to AI services."




def _build_healthy_guard_suffix() -> str:
    """
    Returns an additional prompt block injected when telemetry shows zero DTCs.
    Prevents the LLM from fabricating fault codes on a healthy vehicle.
    """
    return (
        "\n\nCRITICAL CONSTRAINTS FOR HEALTHY VEHICLE:\n"
        "1. The vehicle telemetry has zero DTCs and is healthy.\n"
        "2. You MUST NOT fabricate any vehicle issues, invent faults, or recommend repairs.\n"
        "3. Inform the user that the vehicle telemetry shows no fault codes and is currently healthy."
    )


async def generate_diagnostic(query: str, chat_history: list, vin: str) -> str:
    """Combines Retrieval and LLM calling using Chain of Thought reasoning."""
    
    # ---------------------------------------------------------
    # 1. GATHER INTELLIGENCE
    # ---------------------------------------------------------
    # Sanitize user query to prevent XML tag injections
    sanitized_query = query.replace("<", "&lt;").replace(">", "&gt;")
    
    # Fetch telemetry context first (R2)
    context_telemetry = await get_telemetry_context(vin)
    
    # Extract DTC codes from telemetry to enrich the knowledge retrieval query (R1)
    # Appending known DTC codes improves recall of DTC-specific manual chunks.
    telemetry_dtcs = re.findall(r'\b[BCPU]\d{4}\b', context_telemetry, re.IGNORECASE)
    # Deduplicate codes and normalize to uppercase
    telemetry_dtcs = list(dict.fromkeys([dtc.upper() for dtc in telemetry_dtcs]))
    
    # Only append DTCs that the user has not already mentioned in their query
    dtcs_to_add = [
        dtc for dtc in telemetry_dtcs
        if not re.search(r'\b' + re.escape(dtc) + r'\b', query, re.IGNORECASE)
    ]
            
    # Formulate enriched retrieval query by appending missing DTCs (R1)
    retrieval_query = f"{query} {' '.join(dtcs_to_add)}" if dtcs_to_add else query
        
    context_knowledge = await get_manual_context(retrieval_query)
    
    formatted_history_list = []
    for msg in chat_history[-4:]:
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                if msg.get("type") in ["image", "audio"]:
                    formatted_history_list.append(f"User: [Sent {msg.get('type')}]")
                else:
                    formatted_history_list.append(f"User: {msg.get('content', '')}")
            elif msg.get("role") == "ai":
                formatted_history_list.append(f"AI: {msg.get('content', '')}")
        else:
            # Backward compatibility for legacy string history
            formatted_history_list.append(str(msg))
            
    formatted_history = "\n".join(formatted_history_list)
    
    # ---------------------------------------------------------
    # 2. CONSTRUCT THE SMART PROMPT
    # ---------------------------------------------------------
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()
        
    if not telemetry_dtcs:
        prompt_template += _build_healthy_guard_suffix()
        
    prompt = prompt_template.format(
        context_telemetry=context_telemetry,
        context_knowledge=context_knowledge,
        formatted_history=formatted_history,
        sanitized_query=sanitized_query
    )
    
    # ---------------------------------------------------------
    # 3. PREPARE THE API REQUEST
    # ---------------------------------------------------------
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            # Low temperature for factual, deterministic diagnostic accuracy
            "temperature": 0.2,
            # 2048 covers both <analysis> (~200 words) and <response> (~350 words) without truncation
            "maxOutputTokens": 2048,
            # thinkingBudget=0 disables chain-of-thought thinking to keep mobile TTFT under 2-4s.
            # Raise to 512-1024 if deeper multi-step reasoning is ever required at the cost of latency.
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }
    
    raw_text = await _call_gemini_api(payload, timeout=15)
    
    if raw_text.startswith("Diagnostic Engine Error:"):
        return raw_text
            
    # ---------------------------------------------------------
    # 4. PARSE OUTPUT
    # ---------------------------------------------------------
    response_match = re.search(r'<response>(.*?)</response>', raw_text, re.DOTALL | re.IGNORECASE)
    
    if response_match:
        return response_match.group(1).strip()
    
    # Fallback: if <response> exists but closing tag </response> is missing
    response_start = re.search(r'<response>(.*)', raw_text, re.DOTALL | re.IGNORECASE)
    if response_start:
        return response_start.group(1).strip()
    else:
        return re.sub(r'<analysis>.*?</analysis>', '', raw_text, flags=re.DOTALL | re.IGNORECASE).strip()


async def generate_multimodal_diagnostic(
    media_base64: str,
    mime_type: str,
    vin: str,
    chat_history: list
) -> str:
    """
    Processes audio or image media through Gemini's multimodal API to extract
    a text description of the symptom, then feeds it into the standard
    diagnostic pipeline for full RAG vector search and telemetry context.
    """
    is_audio = mime_type.startswith("audio/")
    media_label = "audio recording" if is_audio else "image"
    
    extraction_prompt = (
        f"You are an automotive symptom extractor.\n"
        f"A vehicle owner has provided an {media_label}.\n"
    )
    
    if is_audio:
        extraction_prompt += "Listen carefully and describe the abnormal engine sounds (knocking, squealing, grinding, etc.). Be very concise.\n"
    else:
        extraction_prompt += "Examine the image carefully and describe any visible damage, warning lights, leaks, or anomalies. Be very concise.\n"
        
    extraction_prompt += "Return only the extracted symptom description, nothing else."

    # ---------------------------------------------------------
    # 1. EXTRACT SYMPTOM VIA MULTIMODAL API
    # ---------------------------------------------------------
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": media_base64}},
                {"text": extraction_prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            # Symptom extraction needs only a single descriptive sentence; cap tokens to minimize latency
            "maxOutputTokens": 256
        }
    }
    
    extracted_symptom = await _call_gemini_api(payload, timeout=30)
    
    if extracted_symptom.startswith("Diagnostic Engine Error:"):
        return extracted_symptom
    
    extracted_symptom = extracted_symptom.strip()

    # ---------------------------------------------------------
    # 2. PASS TO STANDARD TEXT PIPELINE
    # ---------------------------------------------------------
    logger.info(f"[*] Extracted Symptom from Media: {extracted_symptom}")
    
    # We append a small note so the text pipeline knows it came from media
    enhanced_query = f"I observed the following from a {media_label}: {extracted_symptom}"
    
    return await generate_diagnostic(enhanced_query, chat_history, vin)
