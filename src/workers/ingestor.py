import os
import sys

# Add 'src/' to path so we can resolve the 'core' package
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(TOOL_DIR)
sys.path.insert(0, SRC_DIR)

import asyncio
from core.database import client
from services.ingest_service import ingest_pdf, ingest_csv, ingest_text

# ==========================================
# 1. CONFIGURATION & DIRECTORY CHECK
# ==========================================
print("--- OBD-CORTEX BULK INGESTION ENGINE ---")

# Dynamically resolve absolute path to project root data directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

if not os.path.exists(DATA_DIR):
    print(f"[!] ERROR: Folder '{DATA_DIR}' not found. Please create it and add files.")
    sys.exit(1)

# ==========================================
# 2. BULK PROCESSING LOOP
# ==========================================
async def main():
    print("\nScanning 'data/' folder for files...")

    all_files = os.listdir(DATA_DIR)
    if len(all_files) == 0:
        print("[!] The 'data' folder is empty. Nothing to process.")
        sys.exit(0)

    for filename in all_files:
        filepath = os.path.join(DATA_DIR, filename)
        
        if not os.path.isfile(filepath) or filename.startswith('.'):
            continue

        # ------------------------------------------
        # LOGIC A: Process PDF Files (Cloud Vision)
        # ------------------------------------------
        if filename.endswith(".pdf"):
            print(f"\n[•] Processing PDF: {filename}...")
            try:
                res = await ingest_pdf(filepath, filename)
                print(f"[>>] Result: {res.get('message')}")
            except Exception as e:
                print(f"[!] Failed to parse PDF {filename}: {e}")

        # ------------------------------------------
        # LOGIC B: Process CSV Files (Local Pandas)
        # ------------------------------------------
        elif filename.endswith(".csv"):
            print(f"\n[•] Processing CSV: {filename}...")
            try:
                res = await ingest_csv(filepath, filename)
                print(f"[>>] Result: {res.get('message')}")
            except Exception as e:
                print(f"[!] Failed to parse CSV {filename}: {e}") 

        # ------------------------------------------
        # LOGIC C: Process Text/Markdown Files
        # ------------------------------------------
        elif filename.endswith(".md") or filename.endswith(".txt"):
            print(f"\n[•] Processing Text/Markdown: {filename}...")
            try:
                res = await ingest_text(filepath, filename)
                print(f"[>>] Result: {res.get('message')}")
            except Exception as e:
                print(f"[!] Failed to parse Text/Markdown {filename}: {e}")

        else:
            print(f"\n[>>] Skipping {filename} (Unsupported format).")

    print("\n[✓] ALL FILES PROCESSED SUCCESSFULLY!")
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
