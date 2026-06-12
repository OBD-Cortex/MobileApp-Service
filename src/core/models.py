"""
Models Module - OBD-Cortex
Provides the local SentenceTransformer model for vector embeddings.
"""
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

# Suppress the verbose HTTP request logs from huggingface_hub's underlying httpx client
logging.getLogger("httpx").setLevel(logging.WARNING)

logger.info("Loading local SentenceTransformer model (microsoft/harrier-oss-v1-270m)...")
try:
    # Attempt to load entirely from the local cache without checking for updates online
    embed_model = SentenceTransformer('microsoft/harrier-oss-v1-270m', local_files_only=True)
except Exception:
    logger.info("Model not found in local cache. Downloading from Hugging Face for the first time...")
    embed_model = SentenceTransformer('microsoft/harrier-oss-v1-270m', local_files_only=False)
    
logger.info("Local model loaded successfully for zero-token-cost embeddings.")
