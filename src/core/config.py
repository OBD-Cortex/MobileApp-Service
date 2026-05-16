import os
import urllib.parse
from dotenv import load_dotenv

# Load env variables exactly ONCE for the whole project
load_dotenv(os.path.expanduser("/home/bodz/.env_secrets/.env"))

# Database Config
USERNAME = os.getenv("UNAME")
PASSWORD = os.getenv("PW")
CLUSTER_URL = os.getenv("C_URL")

# Format the MongoDB URI safely
clean_cluster_url = CLUSTER_URL.replace("mongodb+srv://", "").split("/")[0]
user = urllib.parse.quote_plus(USERNAME or "")
pw = urllib.parse.quote_plus(PASSWORD or "")
MONGO_URI = f"mongodb+srv://{user}:{pw}@{clean_cluster_url}/?retryWrites=true&w=majority"

# API Keys
GOOGLE_API_KEY = os.getenv("GAPI")
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

# App Config
TARGET_VIN = "VIN_12345_TEST"
