import os
import sys
import urllib.parse
from dotenv import load_dotenv
from llama_cloud import LlamaCloud
import pymongo
import certifi
from sentence_transformers import SentenceTransformer
import pandas as pd

# --- 1. CONFIGURATION & SECURITY ---
print("--- OBD-CORTEX BULK INGESTION ENGINE ---")
load_dotenv(os.path.expanduser("/home/bodz/.env_secrets/.env"))

DATA_DIR = "../data" 

if not os.path.exists(DATA_DIR):
    print(f"❌ ERROR: Folder '{DATA_DIR}' not found. Please create it and add files.")
    sys.exit(1)

# --- 2. CONNECT TO MONGODB ---
print("[1/4] Connecting to Vector Database...")
USERNAME = os.getenv("UNAME")          
PASSWORD = os.getenv("PW")  
CLUSTER_URL = os.getenv("C_URL")  

clean_cluster_url = CLUSTER_URL.replace("mongodb+srv://", "").split("/")[0]
user = urllib.parse.quote_plus(USERNAME)
pw = urllib.parse.quote_plus(PASSWORD)
uri = f"mongodb+srv://{user}:{pw}@{clean_cluster_url}/?retryWrites=true&w=majority"

try:
    mongo_client = pymongo.MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
    mongo_client.admin.command('ping')
    db = mongo_client["rag_db"]
    col_knowledge = db["knowledge"]
    print("✅ Database Connected.")
except Exception as e:
    print(f"❌ Database Connection Failed: {e}")
    sys.exit(1)

# --- 3. LOAD AI MODELS ---
print("[2/4] Loading Local AI Embedder...")
embed_model = SentenceTransformer('all-MiniLM-L6-v2')

print("[3/4] Connecting to LlamaCloud API...")
# Using the exact V2 client from the docs you found!
llama_client = LlamaCloud() 

# --- 4. BULK PROCESSING LOOP ---
print("\n[4/4] Scanning 'data/' folder for files...")

all_files = os.listdir(DATA_DIR)
if len(all_files) == 0:
    print("⚠️ The 'data' folder is empty. Nothing to process.")
    sys.exit(0)

for filename in all_files:
    filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.isfile(filepath) or filename.startswith('.'):
        continue

    # ==========================================
    # LOGIC A: Process PDF Files (Cloud Vision)
    # ==========================================
    if filename.endswith(".pdf"):
        print(f"\n📄 Processing PDF: {filename}...")
        try:
            # 1. Upload exactly like the docs say
            file_obj = llama_client.files.create(file=filepath, purpose="parse")
            
            # 2. Parse (Requesting 'markdown' so we can iterate by page)
            result = llama_client.parsing.parse(
                file_id=file_obj.id,
                tier="agentic",
                version="latest",
                expand=["markdown"]
            )
            
            upload_count = 0
            # 3. Iterate through pages instead of using markdown_full
            for i, page in enumerate(result.markdown.pages):
                text_content = page.markdown
                if not text_content or not text_content.strip(): continue
                    
                vector = embed_model.encode(text_content).tolist()
                
                col_knowledge.insert_one({
                    "text": text_content,
                    "embedding": vector,
                    "source": filename,
                    "page_number": i + 1,
                    "doc_type": "repair_manual" 
                })
                upload_count += 1
            print(f"✅ Indexed {upload_count} pages from {filename}.")
        except Exception as e:
            print(f"❌ Failed to parse PDF {filename}: {e}")

    # ==========================================
    # LOGIC B: Process CSV Files (Local Pandas)
    # ==========================================
    elif filename.endswith(".csv"):
        print(f"\n📊 Processing CSV: {filename}...")
        try:
            df = pd.read_csv(filepath)
            df = df.fillna("") 
            
            upload_count = 0
            for index, row in df.iterrows():
                row_text = ", ".join([f"{col}: {val}" for col, val in row.items() if val != ""])
                vector = embed_model.encode(row_text).tolist()
                
                col_knowledge.insert_one({
                    "text": row_text,
                    "embedding": vector,
                    "source": filename,
                    "row_number": index + 1,
                    "doc_type": "dtc_database" 
                })
                upload_count += 1
            print(f"✅ Indexed {upload_count} rows from {filename}.")
        except Exception as e:
            print(f"❌ Failed to parse CSV {filename}: {e}")

    else:
        print(f"\n⏭️ Skipping {filename} (Unsupported format).")

print("\n🎉 ALL FILES PROCESSED SUCCESSFULLY!")
mongo_client.close()
