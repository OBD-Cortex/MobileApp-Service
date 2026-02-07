import sys
import os 
from dotenv import load_dotenv
import requests
import pymongo
import urllib.parse
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
load_dotenv(os.path.expanduser("/home/bodz/.env_secrets/.env"))

USERNAME = os.getenv("UNAME")          # Your MongoDB Database User
PASSWORD = os.getenv("PW")  # Your Database Password
CLUSTER_URL = os.getenv("C_URL")  # Copy from Atlas (look for the part after @)
GOOGLE_API_KEY =os.getenv("GAPI")  

# Target Vehicle (Matches the one in car_logger.py)
TARGET_VIN = "VIN_12345_TEST"

# --- CONNECT TO DATABASE ---
print("--- STARTING OBD-CORTEX ---")
print("[1/3] Connecting to Cloud Database...")

clean_cluster_url = CLUSTER_URL.replace("mongodb+srv://", "").split("/")[0]
user = urllib.parse.quote_plus(USERNAME)
pw = urllib.parse.quote_plus(PASSWORD)
uri = f"mongodb+srv://{user}:{pw}@{clean_cluster_url}/?retryWrites=true&w=majority"

try:
    client = pymongo.MongoClient(uri)
    db = client["rag_db"]
    col_knowledge = db["knowledge"]           # Stream A
    col_telemetry = db["vehicle_telemetry"]   # Stream B
except Exception as e:
    print(f"❌ Connection Failed: {e}")
    sys.exit(1)

# --- LOAD LOCAL EMBEDDINGS ---
print("[2/3] Loading Embedding Model...")
try:
    embed_model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as e:
    print(f"❌ Model Load Failed: {e}")
    sys.exit(1)

# --- GOOGLE MODEL SETUP ---
print("[3/3] Auto-Discovering Google Model...")
def get_google_model():
    """Finds a working model for your key to avoid 404 errors"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GOOGLE_API_KEY}"
    try:
        data = requests.get(url).json()
        if 'error' in data:
            print(f"❌ API Error: {data['error']['message']}")
            sys.exit(1)
        
        # Prefer Flash -> Pro
        models = [m['name'] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        for m in models:
            if 'flash' in m: return m
        for m in models:
            if 'pro' in m: return m
        return models[0] if models else None
    except:
        return "models/gemini-1.5-flash"

ACTIVE_MODEL = get_google_model()
print(f"✅ Ready! Using Brain: {ACTIVE_MODEL}\n")

# --- CORE FUNCTIONS (The "Two RAGs") ---

def get_stream_a_knowledge(query):
    """Retrieves PDF/Manual info"""
    vector = embed_model.encode(query).tolist()
    results = col_knowledge.aggregate([
        {"$vectorSearch": {
            "index": "vector_index",
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": 50,
            "limit": 2
        }},
        {"$project": {"_id": 0, "text": 1, "source": 1}}
    ])
    
    context = ""
    for doc in results:
        context += f"- From {doc.get('source', 'Manual')}: {doc['text'][:300]}...\n"
    
    return context if context else "No specific manual entry found."

def get_stream_b_context(vin):
    """Retrieves Live Telemetry History"""
    # Get last 3 logs
    logs = col_telemetry.find({"vehicle_id": vin}).sort("timestamp", -1).limit(3)
    
    context = f"VEHICLE IDENTITY: {vin}\nRECENT LOGS:\n"
    found = False
    for log in logs:
        found = True
        context += f"[{log['timestamp'].strftime('%H:%M:%S')}] Status: {log.get('raw_log')} | RPM: {log.get('rpm')} | DTC: {log.get('dtc')}\n"
    
    if not found: return "No live data connection. (Is car_logger.py running?)"
    return context

def ask_obd_cortex(query):
    # 1. Gather Intelligence
    context_knowledge = get_stream_a_knowledge(query)
    context_telemetry = get_stream_b_context(TARGET_VIN)
    
    # 2. Construct the "Expert" Prompt
    prompt = f"""
    ROLE: You are OBD-Cortex, an advanced automotive AI assistant.
    
    --- STREAM 1: LIVE VEHICLE CONTEXT (Priority) ---
    {context_telemetry}
    
    --- STREAM 2: KNOWLEDGE BASE (Reference) ---
    {context_knowledge}
    
    --- USER QUERY ---
    "{query}"
    
    --- INSTRUCTIONS ---
    1. Check STREAM 1 first. If the vehicle has error codes (DTCs) or abnormal stats (High Temp, Zero RPM), MENTION THEM.
    2. If the user asks about specific repair procedures, use STREAM 2.
    3. If STREAM 2 is empty, use your general automotive training (Fallback).
    4. Keep answers concise and helpful.
    
    Answer:
    """
    
    # 3. Call Google
    url = f"https://generativelanguage.googleapis.com/v1beta/{ACTIVE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"Error: {res.text}"
    except Exception as e:
        return f"Connection Error: {e}"

# --- CHAT LOOP ---
if __name__ == "__main__":
    print(f"--- CONNECTED TO CAR: {TARGET_VIN} ---")
    print("Type 'exit', 'quit', or 'bye' to stop the conversation.\n")
    
    try:
        while True:
            # 1. Get User Input
            q = input("You: ").strip()
            
            # 2. Check for ANY exit keyword
            if q.lower() in ["exit", "quit", "bye", "stop"]:
                print("\n🔌 Disconnecting from OBD-Cortex...")
                break
            
            # 3. Process Query
            if q: # Only ask if user typed something
                print("Thinking...", end="\r") # Show loading indicator
                
                response = ask_obd_cortex(q)
                
                # Clear "Thinking..." line for a clean look
                print(" " * 20, end="\r") 
                print(f"AI: {response}\n")

    except KeyboardInterrupt:
        # Handles accidental Ctrl+C gracefully too
        print("\n\nForce close detected.")
        
    finally:
        # 4. Clean up resources
        client.close()
        print("✅ System Shutdown Complete. Goodbye!")
