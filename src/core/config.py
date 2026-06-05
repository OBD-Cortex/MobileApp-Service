"""
System Configuration Module - OBD-Cortex RAG

This module handles loading environmental variables for both local testing
and production execution on DigitalOcean Droplets.
"""

import os
from dotenv import load_dotenv

# -------------------------------------------------------------
# 1. ENVIRONMENT CONFIGURATION FILE LOADER
# -------------------------------------------------------------
# During local development, developers can specify a custom configuration file 
# path (via the ENV_PATH environment variable) to load parameters.
# In production deployments, this loader is bypassed, and variables are read
# directly from OS environment variables (systemd/Docker configuration).
env_path = os.getenv("ENV_PATH")
if env_path and os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)


# -------------------------------------------------------------
# 2. APPLICATION CONSTANTS
# -------------------------------------------------------------
# MONGO_URI: The connection string for the MongoDB Atlas database instance.
MONGO_URI = os.getenv("MONGO_URI")

# GOOGLE_API_KEY: Authentication key required to call the Gemini API.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# LLAMA_INDEX_API_KEY: Authentication token required to parse PDF/manual data.
LLAMA_INDEX_API_KEY = os.getenv("LLAMA_INDEX_API_KEY")

# MOBILE_API_KEY: Secure token header used to validate incoming Flutter client requests.
MOBILE_API_KEY = os.getenv("MOBILE_API_KEY")

# JWT_SECRET: Secret key used for signing JWT authentication tokens.
JWT_SECRET = os.getenv("JWT_SECRET")

