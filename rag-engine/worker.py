import os
import asyncio
from celery import Celery
from motor.motor_asyncio import AsyncIOMotorClient

# Environment Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/eih")

# Initialize Celery
app = Celery(
    "rag_engine_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Listen to the "ingestion-queue"
app.conf.task_default_queue = "ingestion-queue"

async def _update_session_status(session_id: str, status: str):
    """
    Connects to MongoDB and updates the ChatSession status.
    """
    client = AsyncIOMotorClient(MONGO_URI)
    try:
        # Get default DB from connection string or fallback to 'eih'
        try:
            db = client.get_default_database()
        except Exception:
            db = client.get_database("eih")
            
        collection = db.chatsessions
        
        result = await collection.update_one(
            {"sessionId": session_id},
            {"$set": {"status": status}}
        )
        print(f"Updated status for session {session_id} to '{status}'. Modified count: {result.modified_count}")
    except Exception as e:
        print(f"Error updating status in MongoDB: {e}")
    finally:
        client.close()

async def async_process_repository(session_id: str, repo_url: str):
    """
    Asynchronous repository processing pipeline.
    """
    print(f"Starting processing for repository: {repo_url} (Session: {session_id})")
    
    # 1. Update status to processing
    await _update_session_status(session_id, "processing")
    
    # 2. Add placeholder comment
    # TODO: Clone repo, chunk files, embed, and save to Vector Search
    print(f"# TODO: Clone repo, chunk files, embed, and save to Vector Search for {repo_url}")
    await asyncio.sleep(2)  # Simulate processing time
    
    # 3. Update status to completed
    await _update_session_status(session_id, "completed")
    print(f"Finished processing for repository: {repo_url} (Session: {session_id})")

@app.task(name="worker.process_repository")
def process_repository(session_id: str, repo_url: str):
    """
    Celery task entrypoint.
    """
    asyncio.run(async_process_repository(session_id, repo_url))
