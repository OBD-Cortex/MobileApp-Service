import pymongo
import certifi
import sys
from core.config import MONGO_URI

print("[Database] Initializing MongoDB Connection...")
try:
    # Use certifi to prevent SSL handshake errors on strict networks
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
    client.admin.command('ping') # Test connection
    db = client["rag_db"]
    
    # Expose collections for the rest of the app to import
    col_knowledge = db["knowledge"]
    col_telemetry = db["vehicle_telemetry"]
    print("Database Connected.")
except Exception as e:
    print(f"DB Connection Failed: {e}")
    sys.exit(1)
