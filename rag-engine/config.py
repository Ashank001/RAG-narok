import os
from dotenv import load_dotenv
from celery import Celery
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

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

# ---------------------------------------------------------
# Async MongoDB Client (Motor) — for session status updates
# ---------------------------------------------------------
mongo_client = AsyncIOMotorClient(MONGO_URI)

def get_db():
    """Returns the async Motor database for session tracking."""
    try:
        return mongo_client.get_default_database()
    except Exception:
        # Fallback if database name is not specified in the URI
        return mongo_client.get_database("api-gateway")

# ---------------------------------------------------------
# Sync MongoDB Client (PyMongo) — for LangChain vector store
# ---------------------------------------------------------
sync_mongo_client = MongoClient(MONGO_URI)

def get_sync_collection(db_name: str, collection_name: str):
    """Returns a synchronous pymongo collection for LangChain integrations."""
    return sync_mongo_client[db_name][collection_name]
