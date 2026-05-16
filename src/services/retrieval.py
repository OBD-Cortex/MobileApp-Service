from core.database import col_knowledge, col_telemetry
from core.models import embed_model

def get_manual_context(query: str, limit: int = 5) -> str:
    """Retrieves PDF/Manual info using Vector Search"""
    vector = embed_model.encode(query).tolist()
    results = list(col_knowledge.aggregate([
        {"$vectorSearch": {
            "index": "vector_index",
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": 50,
            "limit": limit
        }},
        {"$project": {"_id": 0, "text": 1, "source": 1}}
    ]))
    
    if not results: return "No specific manual entry found."
    
    return "\n".join([f"- From {doc.get('source', 'Manual')}: {doc['text'][:400]}..." for doc in results])

def get_telemetry_context(vin: str) -> str:
    """Retrieves Live Telemetry History"""
    logs = list(col_telemetry.find({"vehicle_id": vin}).sort("timestamp", -1).limit(3))
    
    if not logs: 
        return "No live data connection. (Is logger running?)"
        
    context = f"VEHICLE IDENTITY: {vin}\nRECENT LOGS:\n"
    for log in logs:
        # Gracefully handle missing fields with .get()
        ts = log.get('timestamp')
        time_str = ts.strftime('%H:%M:%S') if ts else "Unknown Time"
        context += f"[{time_str}] Status: {log.get('raw_log')} | RPM: {log.get('rpm')} | DTC: {log.get('dtc')}\n"
        
    return context
