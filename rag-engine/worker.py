import os
import asyncio
import shutil
from config import celery_app, get_db
from langchain_community.document_loaders import GitLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

async def process_repository_async(session_id: str, repo_url: str) -> None:
    """
    Asynchronously processes the repository:
    1. Updates MongoDB session status to 'processing'.
    2. Clones the repository to a temporary directory using LangChain's GitLoader.
    3. Splits the loaded files using RecursiveCharacterTextSplitter.
    4. Updates MongoDB session status to 'completed' upon success,
       or to 'failed' with error log if any exception occurs.
    """
    db = get_db()
    # MongoDB collection mapping to Mongoose "Session" model is "sessions"
    collection = db.sessions
    
    # Path where repo will be cloned locally
    repo_path = f"/tmp/repos/{session_id}"
    
    try:
        # 1. Update session status to 'processing'
        await collection.update_one(
            {"sessionId": session_id},
            {"$set": {"status": "processing"}}
        )
        print(f"[Session: {session_id}] Status set to 'processing'. Cloning repository {repo_url}...")
        
        # Ensure temporary path doesn't already exist from a dirty previous run
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
            
        # 2. Use LangChain's GitLoader to clone the repo
        loader = GitLoader(
            clone_url=repo_url,
            repo_path=repo_path,
            branch="main"  # Assumes default branch is 'main'.
        )
        docs = loader.load()
        print(f"[Session: {session_id}] Cloned repository successfully. Loaded {len(docs)} files.")
        
        # 3. Use RecursiveCharacterTextSplitter to split the documents
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        chunks = splitter.split_documents(docs)
        print(f"[Session: {session_id}] Split loaded documents into {len(chunks)} text chunks.")
        
        # 4. # TODO: Vector Embeddings Generation
        # In the next phase, the text chunks will be passed to an Embedding model
        # (e.g., Google Vertex AI or OpenAI embeddings) and stored in a vector
        # search store (such as Pinecone, Chroma, or MongoDB Atlas Vector Search).
        
        # 5. Update MongoDB session status to 'completed'
        await collection.update_one(
            {"sessionId": session_id},
            {"$set": {"status": "completed"}}
        )
        print(f"[Session: {session_id}] Processing completed successfully.")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[Session: {session_id}] Error occurred: {error_msg}")
        # Update MongoDB status to 'failed' and store the error log
        await collection.update_one(
            {"sessionId": session_id},
            {"$set": {
                "status": "failed",
                "errorLog": error_msg
            }}
        )
    finally:
        # Clean up cloned repository directory after parsing
        if os.path.exists(repo_path):
            try:
                shutil.rmtree(repo_path)
                print(f"[Session: {session_id}] Cleaned up temporary directory {repo_path}")
            except Exception as cleanup_err:
                print(f"[Session: {session_id}] Failed to clean up {repo_path}: {cleanup_err}")

@celery_app.task(name='process-repo')
def process_repository(payload: dict = None, sessionId: str = None, repositoryUrl: str = None) -> None:
    """
    Celery task wrapper that runs the async repository processing function.
    Accepts payload keys: 'sessionId' and 'repositoryUrl' directly or via a payload dict.
    """
    session_id = sessionId
    repo_url = repositoryUrl
    
    if payload is not None:
        if isinstance(payload, dict):
            session_id = session_id or payload.get("sessionId")
            repo_url = repo_url or payload.get("repositoryUrl")
            
    if not session_id or not repo_url:
        raise ValueError(f"Missing required arguments: sessionId='{session_id}', repositoryUrl='{repo_url}' in payload='{payload}'")
        
    asyncio.run(process_repository_async(session_id, repo_url))
