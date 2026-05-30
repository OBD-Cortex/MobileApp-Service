import sys
from sentence_transformers import SentenceTransformer

# Load the embedding model globally so it stays in RAM for the module's lifecycle
print("[Models] Loading Embedding Model (harrier-oss-v1-270m)...")
try:
    # SentenceTransformers downloads this directly from Hugging Face on first boot
    embed_model = SentenceTransformer('microsoft/harrier-oss-v1-270m')
    print("[✓] Embedder Ready.")
except Exception as e:
    print(f"[!] Model Load Failed: {e}")
    sys.exit(1)
