import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from celery import Celery
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
import certifi

# Load environment variables
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/api-gateway")

# Initialize Celery app
celery_app = Celery(
    "rag_engine_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Sync MongoDB Client (PyMongo)
# tlsCAFile=certifi.where() fixes TLSV1_ALERT_INTERNAL_ERROR on Windows/older OpenSSL
# tlsAllowInvalidCertificates=True is a dev-only fallback for Windows TLS handshake issues
sync_mongo_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)

def get_sync_db():
    """Returns the synchronous pymongo database for session tracking."""
    try:
        return sync_mongo_client.get_default_database()
    except Exception:
        # Fallback if database name is not specified in the URI
        return sync_mongo_client.get_database("api-gateway")

def get_sync_collection(db_name: str, collection_name: str):
    """Returns a synchronous pymongo collection for LangChain integrations."""
    return sync_mongo_client[db_name][collection_name]
