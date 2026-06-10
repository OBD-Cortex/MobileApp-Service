"""
Models Module - OBD-Cortex
Provides the local SentenceTransformer model for vector embeddings.
"""
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

logger.info("Loading local SentenceTransformer model (microsoft/harrier-oss-v1-270m)...")
embed_model = SentenceTransformer('microsoft/harrier-oss-v1-270m')
logger.info("Local model loaded successfully for zero-token-cost embeddings.")
