import os
from dotenv import load_dotenv
import pymongo
import urllib.parse
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
load_dotenv(os.path.expanduser("/home/bodz/.env_secrets/.env"))

USERNAME = os.getenv("UNAME")          # Your MongoDB Database User
PASSWORD = os.getenv("PW")  # Your Database Password
CLUSTER_URL = os.getenv("C_URL")  # Copy from Atlas (look for the part after @)

DB_NAME = "rag_db"
COLLECTION_NAME = "knowledge"

# --- CONNECT TO DB ---
clean_cluster_url = CLUSTER_URL.replace("mongodb+srv://", "").split("/")[0]
user = urllib.parse.quote_plus(USERNAME)
pw = urllib.parse.quote_plus(PASSWORD)
uri = f"mongodb+srv://{user}:{pw}@{clean_cluster_url}/?retryWrites=true&w=majority"

try:
    client = pymongo.MongoClient(uri)
    collection = client[DB_NAME][COLLECTION_NAME]
    print("✅ Connected to MongoDB (Knowledge Collection)")
except Exception as e:
    print(f"❌ DB Connection Failed: {e}")
    exit()

# --- LOAD EMBEDDING MODEL ---
print("Loading embedding model (this may take a moment)...")
embed_model = SentenceTransformer('all-MiniLM-L6-v2')

def ingest_pdfs():
    data_folder = "./data"
    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"Created {data_folder}. Please put your PDFs inside and run again.")
        return

    files = [f for f in os.listdir(data_folder) if f.endswith('.pdf')]
    if not files:
        print("No PDF files found in ./data/")
        return

    # Clear old knowledge (Optional - remove this line if you want to append)
    print("Clearing old data...")
    collection.delete_many({})

    total_chunks = 0

    for filename in files:
        print(f"Processing: {filename}...")
        try:
            reader = PdfReader(os.path.join(data_folder, filename))
            
            # Read and Chunk (Page by Page)
            file_chunks = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if not text: continue
                
                # Create a meaningful chunk
                # We prepend filename/page so the AI knows the source
                chunk_text = f"Source: {filename} (Page {i+1})\nContent: {text}"
                
                # Embed locally
                vector = embed_model.encode(chunk_text).tolist()
                
                doc = {
                    "text": chunk_text,
                    "embedding": vector,
                    "source": filename,
                    "page": i + 1
                }
                file_chunks.append(doc)

            if file_chunks:
                collection.insert_many(file_chunks)
                total_chunks += len(file_chunks)
                print(f"   -> Uploaded {len(file_chunks)} pages.")
                
        except Exception as e:
            print(f"   ❌ Error reading {filename}: {e}")

    print(f"\n✅ Success! Total knowledge chunks available: {total_chunks}")

if __name__ == "__main__":
    ingest_pdfs()
