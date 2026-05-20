import sys
from sentence_transformers import SentenceTransformer

# Load the embedding model globally so it stays in RAM for the module's lifecycle
print("[Models] Loading Embedding Model (all-MiniLM-L6-v2)...")
try:
    # Using the requested MiniLM model
    embed_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    print("Embedder Ready.")
except Exception as e:
    print(f"Model Load Failed: {e}")
    sys.exit(1)
