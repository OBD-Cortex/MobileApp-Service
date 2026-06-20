import os
import sys
import time
import asyncio
import datetime
from pathlib import Path

# Dynamically calculate the SERVICE_ROOT based on this script's location
SERVICE_ROOT = Path(__file__).resolve().parent
if SERVICE_ROOT.name == "src":
    SERVICE_ROOT = SERVICE_ROOT.parent

sys.path.insert(0, str(SERVICE_ROOT / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(SERVICE_ROOT / ".env")
except ImportError:
    pass

import core.config
from core.database import init_db, db, col_devices, col_users, col_telemetry
from core.auth import hash_password, verify_password, create_jwt

def print_table(title, headers, rows):
    print(f"\n=== {title} ===")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
            
    header_str = " | ".join(f"{headers[i]:<{widths[i]}}" for i in range(len(headers)))
    print(header_str)
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))
    
    for row in rows:
        row_str = " | ".join(f"{str(row[i]):<{widths[i]}}" for i in range(len(row)))
        print(row_str)
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))

def test_auth_crypto():
    print("\n[*] Benchmarking CPU Bcrypt Password Hashing Latency...")
    print("    [!] Bcrypt uses salting and stretching by design; timing this evaluates hardware CPU speed.")
    
    password = "SuperSecurePassword123"
    
    # Measure 5 password hashes
    hash_latencies = []
    print("[*] Running 5 password hashing iterations...")
    for i in range(5):
        start = time.time()
        pw_hash = hash_password(password)
        latency = (time.time() - start) * 1000
        hash_latencies.append(latency)
        
    avg_hash = sum(hash_latencies) / len(hash_latencies)
    
    # Measure password verification
    print("[*] Running 5 password verification iterations...")
    verify_latencies = []
    for _ in range(5):
        start = time.time()
        verify_password(password, pw_hash)
        verify_latencies.append((time.time() - start) * 1000)
        
    avg_verify = sum(verify_latencies) / len(verify_latencies)

    # JWT generation
    print("[*] Benchmarking JWT generation...")
    jwt_latencies = []
    for _ in range(100):
        start = time.time()
        create_jwt({"user_id": "test_user_123", "role": "user"})
        jwt_latencies.append((time.time() - start) * 1000)
        
    avg_jwt = sum(jwt_latencies) / len(jwt_latencies)

    headers = ["Cryptographic Operation", "Min (ms)", "Max (ms)", "Average (ms)", "Throughput"]
    rows = [
        ["Bcrypt Hash Password", f"{min(hash_latencies):.2f}", f"{max(hash_latencies):.2f}", f"{avg_hash:.2f}", f"{(1000/avg_hash):.2f} hashes/sec"],
        ["Bcrypt Verify Password", f"{min(verify_latencies):.2f}", f"{max(verify_latencies):.2f}", f"{avg_verify:.2f}", f"{(1000/avg_verify):.2f} verifications/sec"],
        ["JWT Token Creation", f"{min(jwt_latencies):.4f}", f"{max(jwt_latencies):.4f}", f"{avg_jwt:.4f}", f"{(1000/avg_jwt):.2f} tokens/sec"]
    ]
    print_table("Cryptographic Performance (Bcrypt & JWT)", headers, rows)

async def test_rag_retrieval():
    print("\n[*] Benchmarking RAG Context Retrieval Latency...")
    try:
        await init_db()
    except Exception as e:
        print(f"    [-] MongoDB connection failed: {e}")
        return

    from services.retrieval import get_manual_context, get_telemetry_context

    # 1. Test Semantic Search Retrieval
    print("[*] Querying Vector Database for Repair Manual context (10 iterations)...")
    rag_latencies = []
    for _ in range(10):
        start = time.time()
        # This calls SentenceTransformer embedding + MongoDB aggregate $vectorSearch
        await get_manual_context("P0300 cylinder misfire random spark plug", limit=3)
        rag_latencies.append((time.time() - start) * 1000)
        
    avg_rag = sum(rag_latencies) / len(rag_latencies)

    # 2. Test Telemetry History Retrieval
    print("[*] Querying database for historical vehicle telemetry (10 iterations)...")
    telemetry_latencies = []
    for _ in range(10):
        start = time.time()
        await get_telemetry_context("TEST_VIN_PERF_123")
        telemetry_latencies.append((time.time() - start) * 1000)
        
    avg_telemetry = sum(telemetry_latencies) / len(telemetry_latencies)

    headers = ["Retrieval Pipeline", "Min (ms)", "Max (ms)", "Average (ms)"]
    rows = [
        ["RAG Manual Vector Search", f"{min(rag_latencies):.2f}", f"{max(rag_latencies):.2f}", f"{avg_rag:.2f}"],
        ["Vehicle Telemetry Query", f"{min(telemetry_latencies):.2f}", f"{max(telemetry_latencies):.2f}", f"{avg_telemetry:.2f}"]
    ]
    print_table("RAG Diagnostic Data Retrieval Speeds", headers, rows)

async def test_gemini_api():
    print("\n[*] Running Gemini LLM Diagnostic Generation Benchmark...")
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if not google_api_key:
        print("    [-] GOOGLE_API_KEY is not configured in .env. Skipping real API call.")
        print("    [-] Falling back to SIMULATED Gemini response benchmark.")
        run_simulated_gemini_test()
        return

    from services.llm_agent import generate_diagnostic, get_gemini_model
    model_name = await get_gemini_model()
    print(f"    [+] Target Model: {model_name}")

    print("[*] Generating live vehicle diagnostic using Gemini API...")
    start_time = time.time()
    try:
        # Run a diagnostic for a typical engine code
        diagnostic = await generate_diagnostic(
            vin="TEST_VIN_PERF_123",
            dtc_code="P0302",
            dtc_description="Cylinder 2 Misfire Detected",
            mil_status=True
        )
        end_time = time.time()
        
        latency = (end_time - start_time) * 1000
        output_len = len(diagnostic)
        print(f"    [+] Diagnostic generated successfully in {latency:.2f} ms")
        
        headers = ["Metric", "Value"]
        rows = [
            ["Model", model_name],
            ["Response Length (chars)", f"{output_len}"],
            ["Round-Trip Latency (ms)", f"{latency:.2f}"],
            ["Estimated Token Count", f"~ {output_len / 4:.0f} tokens"],
            ["Average Generation Speed", f"{(output_len / 4) / (latency / 1000):.1f} tokens/sec"]
        ]
        print_table("Gemini API Diagnostic Latency", headers, rows)
    except Exception as e:
        print(f"    [-] Gemini API call failed: {e}")

def run_simulated_gemini_test():
    headers = ["Metric", "Expected/Simulated Value"]
    rows = [
        ["Model Selected", "models/gemini-3.5-flash"],
        ["Average API Round-Trip Time", "1250 ms"],
        ["Average Generation Speed", "72 tokens/sec"],
        ["Context Processing Time", "300 ms"]
    ]
    print_table("Simulated Gemini API Metrics", headers, rows)

async def test_fastapi_endpoints():
    print("\n[*] Running FastAPI Mobile App Routing Latency Test...")
    
    # Gracefully load FastAPI app to avoid crash if dead imports exist
    app = None
    try:
        from main_api import app
        from fastapi.testclient import TestClient
    except Exception as e:
        print(f"    [-] FastAPI App import failed: {e}")
        print("    [-] This is due to the known startup crash issue described in issues.md.")
        print("    [-] Please resolve imports in main_api.py to execute FastAPI client routing tests.")
        return

    if not app:
        return

    client = TestClient(app)
    
    # 1. Benchmark public routes (e.g. login with invalid credentials to test hashing speed limit)
    print("[*] Benchmarking POST /api/mobile/login (5 iterations)...")
    login_payload = {
        "username": "nonexistent_perf_user",
        "password": "incorrect_password_123"
    }
    
    latencies = []
    for _ in range(5):
        start = time.time()
        client.post("/api/mobile/login", json=login_payload)
        latencies.append((time.time() - start) * 1000)
        
    headers = ["Endpoint Route", "Min (ms)", "Max (ms)", "Average (ms)"]
    rows = [
        ["POST /api/mobile/login (Rejected Auth)", f"{min(latencies):.2f}", f"{max(latencies):.2f}", f"{(sum(latencies)/len(latencies)):.2f}"]
    ]
    print_table("Mobile App API Endpoint Latency Metrics", headers, rows)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MobileApp-Service Performance Benchmarking")
    parser.add_argument("--test", choices=['auth', 'rag', 'gemini', 'api', 'all'], default='all', help="Select benchmark to run")
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    print("==================================================")
    print(" OBD-Cortex Mobile Diagnostic Service Benchmarks")
    print("==================================================")

    if args.test in ['auth', 'all']:
        test_auth_crypto()
    if args.test in ['rag', 'all']:
        loop.run_until_complete(test_rag_retrieval())
    if args.test in ['gemini', 'all']:
        loop.run_until_complete(test_gemini_api())
    if args.test in ['api', 'all']:
        loop.run_until_complete(test_fastapi_endpoints())

    print("\n[+] Performance evaluation completed successfully.")

if __name__ == "__main__":
    main()
