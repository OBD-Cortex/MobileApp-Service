from core.database import col_knowledge, col_telemetry, col_devices
from core.models import embed_model

def get_manual_context(query: str, limit: int = 5, score_threshold: float = 0.55) -> str:
    """
    Retrieves highly relevant PDF/Manual info using Semantic Vector Search.
    Filters out "junk" matches using a strict similarity score threshold.
    """
    try:
        # 0. Validate query input
        if not query or not query.strip():
            return "No specific manual entry found in the database."

        # 1. Convert the user's text query into a mathematical vector
        vector = embed_model.encode(query).tolist()
        
        # 2. Query MongoDB Atlas Vector Database
        results = list(col_knowledge.aggregate([
            {"$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": 50, # Number of nearest neighbors to consider
                "limit": limit       # Max documents to return
            }},
            # Project the text, source, AND expose the hidden similarity score
            {"$project": {
                "_id": 0, 
                "text": 1, 
                "source": 1, 
                "score": {"$meta": "vectorSearchScore"}
            }}
        ]))
        
        if not results: 
            return "No specific manual entry found in the database."
        
        # 3. Filter by Threshold & Format output
        formatted_docs = []
        for doc in results:
            # Only feed the AI documents that are actually relevant to the query
            if doc.get("score", 0) >= score_threshold:
                
                # REMOVED the [:400] truncation! 
                # Let it read the full chunk so it doesn't miss crucial diagnostic steps.
                # We also provide the "Relevance Score" so the AI knows how much to trust this chunk.
                formatted_chunk = (
                    f"--- SOURCE: {doc.get('source', 'Unknown Manual')} "
                    f"(Relevance: {doc['score']:.2f}) ---\n"
                    f"{doc.get('text', '')}\n"
                )
                formatted_docs.append(formatted_chunk)
        
        # If all documents were below the threshold (e.g. the user just said "Hello")
        if not formatted_docs:
            return "No highly relevant manual entries found for this specific query."
            
        return "\n".join(formatted_docs)

    except Exception as e:
        print(f"[!] Retrieval Error (Knowledge Base): {e}")
        return "Knowledge Base temporarily offline. Proceeding with general knowledge."


def get_telemetry_context(vin: str) -> str:
    """
    Retrieves Live Telemetry History for a specific vehicle.
    Provides the AI with a temporal understanding of the car's state.
    """
    try:
        # 0. Validate VIN input
        if not vin or not vin.strip():
            return "No live CAN-bus data connection detected (missing VIN)."

        # Fetch device registration metadata (brand, model, year)
        metadata_str = ""
        try:
            device_info = col_devices.find_one({"vin": vin})
            if device_info:
                brand = device_info.get("brand")
                model = device_info.get("model")
                year = device_info.get("year")
                if brand or model or year:
                    metadata_str = f"VEHICLE SPECS: {year or 'Unknown'} {brand or 'Unknown'} {model or 'Unknown'}\n"
        except Exception as e:
            print(f"[!] Warning: Could not retrieve vehicle metadata: {e}")

        # Fetch the 3 most recent telemetry logs
        logs = list(col_telemetry.find({"vehicle_id": vin}).sort("timestamp", -1).limit(3))
        
        if not logs: 
            return f"No live CAN-bus data connection detected for VIN: {vin}."
            
        context = f"VEHICLE IDENTITY: {vin}\n"
        if metadata_str:
            context += metadata_str
        context += "RECENT TELEMETRY SNAPSHOTS (Most Recent First):\n"
        for log in logs:
            ts = log.get('timestamp')
            if hasattr(ts, 'strftime'):
                time_str = ts.strftime('%H:%M:%S')
            else:
                time_str = str(ts) if ts else "Unknown Time"
            
            # New DTC-focused format or Legacy format backward compatibility
            if 'scan_summary' in log:
                context += f"[{time_str}] {log['scan_summary']}\n"
                
                # Append structured DTC details for deeper analysis
                for dtc in log.get('confirmed_dtcs', []):
                    context += f"  → CONFIRMED: {dtc['code']} — {dtc.get('description', 'Unknown')} [{dtc.get('severity', 'unknown')}]\n"
                for dtc in log.get('pending_dtcs', []):
                    context += f"  → PENDING: {dtc['code']} — {dtc.get('description', 'Unknown')} [{dtc.get('severity', 'unknown')}]\n"
            else:
                context += (
                    f"[{time_str}] "
                    f"Status: '{log.get('raw_log', 'N/A')}' | "
                    f"RPM: {log.get('rpm', 'N/A')} | "
                    f"Speed: {log.get('speed', 'N/A')} km/h | "
                    f"Coolant Temp: {log.get('coolant_temp', 'N/A')}°C | "
                    f"Active DTCs: {log.get('dtc', 'None')}\n"
                )
            
        return context

    except Exception as e:
        print(f"[!] Retrieval Error (Telemetry): {e}")
        return "Vehicle Telemetry database offline."
