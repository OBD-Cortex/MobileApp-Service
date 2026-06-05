import sys
import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Load the embedding model globally so it stays in RAM for the module's lifecycle
logger.info("[*] Loading Embedding Model (harrier-oss-v1-270m)...")
try:
    # SentenceTransformers downloads this directly from Hugging Face on first boot
    embed_model = SentenceTransformer('microsoft/harrier-oss-v1-270m')
    logger.info("[✓] Embedder Ready.")
except Exception as e:
    logger.error(f"[!] Model Load Failed: {e}")
    sys.exit(1)
