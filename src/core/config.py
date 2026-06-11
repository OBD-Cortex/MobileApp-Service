"""
System Configuration Module - OBD-Cortex RAG

This module handles loading environmental variables for both local testing
and production execution on DigitalOcean Droplets.
"""

import os

# -------------------------------------------------------------
# 1. ENVIRONMENT CONFIGURATION FILE LOADER
# -------------------------------------------------------------
# During local development, developers must rely on the environment variables
# injected by the test runner or IDE.
# In production deployments, variables are read directly from OS environment 
# variables (systemd/Docker configuration).
#
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists.
# This makes local testing and environment variable management easier.
load_dotenv()


# -------------------------------------------------------------
# 2. APPLICATION CONSTANTS
# -------------------------------------------------------------
# MONGO_URI: The connection string for the MongoDB Atlas database instance.
MONGO_URI = os.getenv("MONGO_URI")

# GOOGLE_API_KEY: Authentication key required to call the Gemini API.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# LLAMA_INDEX_API_KEY: Authentication token required to parse PDF/manual data.
LLAMA_INDEX_API_KEY = os.getenv("LLAMA_INDEX_API_KEY")



# JWT_SECRET: Secret key used for signing JWT authentication tokens.
# SECURITY: Must be >= 32 characters in production.
JWT_SECRET = os.getenv("JWT_SECRET")

# CORS_ORIGINS: Comma-separated list of allowed CORS origins.
# SECURITY: Must be explicitly set in production. Do NOT use "*".
# Example: "https://admin.example.com,https://app.example.com"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")

