import os
import ssl
from dotenv import load_dotenv
from celery import Celery
from pymongo import MongoClient
import certifi

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/api-gateway")

# Check if using TLS (Upstash rediss://)
redis_use_ssl = REDIS_URL.startswith("rediss://")

# Celery SSL config for Upstash
ssl_options = {"ssl_cert_reqs": ssl.CERT_NONE} if redis_use_ssl else {}

celery_app = Celery(
    "rag_engine_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    broker_use_ssl=ssl_options if redis_use_ssl else None,
    redis_backend_use_ssl=ssl_options if redis_use_ssl else None,
    broker_transport_options={"visibility_timeout": 3600},
)

# MongoDB client
sync_mongo_client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where(),
    tlsAllowInvalidCertificates=True
)

def get_sync_db():
    try:
        return sync_mongo_client.get_default_database()
    except Exception:
        return sync_mongo_client.get_database("api-gateway")

def get_sync_collection(db_name: str, collection_name: str):
    return sync_mongo_client[db_name][collection_name]