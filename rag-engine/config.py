import os
from dotenv import load_dotenv
from celery import Celery
from motor.motor_asyncio import AsyncIOMotorClient

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

# Initialize AsyncIOMotorClient
mongo_client = AsyncIOMotorClient(MONGO_URI)

# Helper function to access the database
def get_db():
    try:
        return mongo_client.get_default_database()
    except Exception:
        # Fallback if database name is not specified in the URI
        return mongo_client.get_database("api-gateway")
