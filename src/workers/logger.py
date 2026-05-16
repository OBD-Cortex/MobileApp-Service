import time
import os
from dotenv import load_dotenv
import random
import pymongo
import datetime
import urllib.parse

# --- CONFIGURATION ---
# Set to FALSE if you have a real Raspberry Pi + MCP2515 connected
SIMULATION_MODE = True 

# MongoDB Credentials
load_dotenv(os.path.expanduser("/home/bodz/.env_secrets/.env"))

USERNAME = os.getenv("UNAME")          # Your MongoDB Database User
PASSWORD = os.getenv("PW")  # Your Database Password
CLUSTER_URL = os.getenv("C_URL")  # Copy from Atlas (look for the part after @)


# Connect to Cloud DB
clean_cluster_url = CLUSTER_URL.replace("mongodb+srv://", "").split("/")[0]
user = urllib.parse.quote_plus(USERNAME)
pw = urllib.parse.quote_plus(PASSWORD)
uri = f"mongodb+srv://{user}:{pw}@{clean_cluster_url}/?retryWrites=true&w=majority"

try:
    client = pymongo.MongoClient(uri)
    db = client["rag_db"]
    collection = db["vehicle_telemetry"]
    print("✅ Connected to MongoDB Cloud (Telemetry Stream)")
except Exception as e:
    print(f"❌ DB Connection Failed: {e}")
    exit()

# --- FUNCTIONS ---

def get_real_can_data():
    """
    Code for Phase 4 (Raspberry Pi). 
    Requires 'pip install python-can' and hardware.
    """
    import can
    bus = can.interface.Bus(channel='can0', bustype='socketcan')
    msg = bus.recv()
    return {
        "can_id": hex(msg.arbitration_id),
        "data": msg.data.hex()
    }

def get_simulated_data():
    """
    Generates fake car scenarios for testing.
    """
    scenarios = [
        {"rpm": 800, "speed": 0, "temp": 90, "dtc": "None", "status": "Idle"},
        {"rpm": 2500, "speed": 65, "temp": 95, "dtc": "None", "status": "Cruising"},
        {"rpm": 3000, "speed": 40, "temp": 110, "dtc": "P0113", "status": "Overheating"}, # Scenario A
        {"rpm": 600, "speed": 0, "temp": 92, "dtc": "P0300", "status": "Misfire Rough Idle"} # Scenario B
    ]
    # Pick a random state
    data = random.choice(scenarios)
    return {
        "vehicle_id": "VIN_12345_TEST",  # The "Identity"
        "timestamp": datetime.datetime.utcnow(),
        "rpm": data['rpm'],
        "speed": data['speed'],
        "coolant_temp": data['temp'],
        "dtc": data['dtc'],
        "raw_log": f"Engine Status: {data['status']}"
    }

# --- MAIN LOOP ---
if __name__ == "__main__":
    print(f"--- STARTING CAR LOGGER (Mode: {'SIMULATION' if SIMULATION_MODE else 'REAL'}) ---")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while True:
            # 1. Get Data (Real or Fake)
            if SIMULATION_MODE:
                telemetry = get_simulated_data()
            else:
                # This will fail on Laptop without CAN hardware
                telemetry = get_simulated_data() 
            
            # 2. Upload to MongoDB (Stream B)
            collection.insert_one(telemetry)
            
            print(f"📡 Uploaded: {telemetry['timestamp']} | DTC: {telemetry['dtc']} | RPM: {telemetry['rpm']}")
            
            # Wait 5 seconds to simulate real-time logging
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n🛑 Logger Stopped.")
