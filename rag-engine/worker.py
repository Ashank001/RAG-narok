import os
import stat
import shutil
import tempfile

from config import celery_app, get_sync_db, get_sync_collection
from dotenv import load_dotenv

# LangChain Imports
from langchain_community.document_loaders import GitLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch

load_dotenv()

# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------
DB_NAME = "rag_db"
COLLECTION_NAME = "code_vectors"
ATLAS_INDEX_NAME = "vector_index"
EMBEDDING_MODEL = "gemini-embedding-001"
BATCH_SIZE = 50  # Documents per embedding batch to respect API rate limits


# ---------------------------------------------------------
# Windows Cleanup Helper
# ---------------------------------------------------------
import sys

def _rmtree_onexc(func, path, exc):
    """
    Error handler for shutil.rmtree (Python 3.12+ `onexc` signature).
    Git pack files are often marked read-only, causing WinError 5 (Access Denied).
    This callback removes the read-only flag and retries the deletion.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree_onerror(func, path, exc_info):
    """Legacy `onerror` callback for Python < 3.12."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree_safe(path):
    """Calls shutil.rmtree with the correct error-handler kwarg for the Python version."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_rmtree_onexc)
    else:
        shutil.rmtree(path, onerror=_rmtree_onerror)


# ---------------------------------------------------------
# Core Ingestion Logic
# ---------------------------------------------------------
def update_session_status(session_id: str, status: str, error_log: str | None = None) -> None:
    """
    Updates the session document in MongoDB with the current processing status.
    Uses the synchronous PyMongo client to avoid 'Event loop is closed' errors
    inside Celery worker processes.
    Optionally attaches an error log on failure.
    """
    db = get_sync_db()
    update_fields = {"status": status}
    if error_log:
        update_fields["errorLog"] = error_log
    db.sessions.update_one(
        {"sessionId": session_id},
        {"$set": update_fields}
    )


def ingest_repository(session_id: str, repo_url: str) -> dict:
    """
    Synchronous ingestion pipeline:
    1. Clones the repository to a temporary OS-safe directory using GitLoader.
    2. Splits loaded files into chunks using RecursiveCharacterTextSplitter.
    3. Generates vector embeddings using GoogleGenerativeAIEmbeddings (gemini-embedding-001).
    4. Uploads embedded documents to MongoDB Atlas Vector Search (rag_db.code_vectors).
    5. Cleans up the temporary clone directory.

    Returns a summary dict with chunk and document counts.
    """
    # Create a temporary directory using the OS temp path (works on Windows, Linux, macOS)
    repo_path = tempfile.mkdtemp(prefix=f"ragnarok_{session_id}_")

    try:
        # --------------------------------------------------
        # Step 1: Clone the repository
        # --------------------------------------------------
        print(f"[Worker | {session_id}] Cloning repository: {repo_url}")
        print(f"[Worker | {session_id}] Temp directory: {repo_path}")

        # Try cloning with 'main' first, fall back to 'master' for older repos
        try:
            loader = GitLoader(
                clone_url=repo_url,
                repo_path=repo_path,
                branch="main",
            )
            docs = loader.load()
        except Exception as branch_err:
            print(f"[Worker | {session_id}] ⚠️ 'main' branch failed ({branch_err}), retrying with 'master'...")
            # Clean up the failed clone before retrying
            if os.path.exists(repo_path):
                _rmtree_safe(repo_path)
            repo_path = tempfile.mkdtemp(prefix=f"ragnarok_{session_id}_")
            loader = GitLoader(
                clone_url=repo_url,
                repo_path=repo_path,
                branch="master",
            )
            docs = loader.load()

        print(f"[Worker | {session_id}] Loaded {len(docs)} files from repository.")

        if not docs:
            raise ValueError("Repository cloned but contained no loadable documents.")

        # --------------------------------------------------
        # Step 2: Split documents into chunks
        # --------------------------------------------------
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )
        chunks = splitter.split_documents(docs)
        print(f"[Worker | {session_id}] Split into {len(chunks)} text chunks.")

        if not chunks:
            raise ValueError("Document splitting produced zero chunks.")

        # Enrich each chunk's metadata with the session ID for traceability
        for chunk in chunks:
            chunk.metadata["session_id"] = session_id
            chunk.metadata["repo_url"] = repo_url

        # --------------------------------------------------
        # Step 3: Initialize embedding model
        # --------------------------------------------------
        print(f"[Worker | {session_id}] Initializing embedding model: {EMBEDDING_MODEL}")
        embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)

        # --------------------------------------------------
        # Step 4: Upload to MongoDB Atlas Vector Search
        # --------------------------------------------------
        print(f"[Worker | {session_id}] Connecting to MongoDB Atlas: {DB_NAME}.{COLLECTION_NAME}")
        collection = get_sync_collection(DB_NAME, COLLECTION_NAME)

        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=ATLAS_INDEX_NAME,
            text_key="text",
            embedding_key="embedding",
        )

        # Batch upload to avoid overwhelming the embedding API
        total_uploaded = 0
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"[Worker | {session_id}] Embedding & uploading batch {batch_num}/{total_batches} ({len(batch)} chunks)...")

            vector_store.add_documents(batch)
            total_uploaded += len(batch)

        print(f"[Worker | {session_id}] ✅ Successfully uploaded {total_uploaded} vectors to Atlas.")

        return {
            "files_loaded": len(docs),
            "chunks_created": len(chunks),
            "vectors_uploaded": total_uploaded,
        }

    finally:
        # --------------------------------------------------
        # Step 5: Clean up temporary clone directory
        # --------------------------------------------------
        if os.path.exists(repo_path):
            try:
                _rmtree_safe(repo_path)
                print(f"[Worker | {session_id}] Cleaned up temp directory: {repo_path}")
            except Exception as cleanup_err:
                print(f"[Worker | {session_id}] ⚠️ Failed to clean up {repo_path}: {cleanup_err}")


# ---------------------------------------------------------
# Celery Task Definition
# ---------------------------------------------------------
@celery_app.task(name="process-repo", bind=True, max_retries=2)
def process_repository(self, payload: dict | None = None, sessionId: str | None = None, repositoryUrl: str | None = None) -> dict:
    """
    Celery task entry point for repository ingestion.

    Accepts arguments either as keyword args or nested inside a `payload` dict:
        - sessionId (str): Unique session identifier for status tracking.
        - repositoryUrl (str): HTTPS URL of the GitHub repository to ingest.

    Lifecycle:
        1. Validates inputs.
        2. Sets session status to 'processing'.
        3. Runs the synchronous ingestion pipeline (clone → chunk → embed → upload).
        4. Sets session status to 'completed' on success, or 'failed' on error.
    """
    # Resolve arguments from payload dict or direct kwargs
    session_id = sessionId
    repo_url = repositoryUrl

    if payload and isinstance(payload, dict):
        session_id = session_id or payload.get("sessionId")
        repo_url = repo_url or payload.get("repositoryUrl")

    if not session_id or not repo_url:
        raise ValueError(
            f"Missing required arguments: sessionId='{session_id}', "
            f"repositoryUrl='{repo_url}' in payload='{payload}'"
        )

    # Update session status to 'processing'
    update_session_status(session_id, "processing")
    print(f"[Worker | {session_id}] ▶ Task started for: {repo_url}")

    try:
        # Execute the full ingestion pipeline
        result = ingest_repository(session_id, repo_url)

        # Mark session as completed
        update_session_status(session_id, "completed")
        print(f"[Worker | {session_id}] ✅ Task completed: {result}")
        return result

    except Exception as exc:
        error_msg = str(exc)
        print(f"[Worker | {session_id}] ❌ Task failed: {error_msg}")

        # Mark session as failed with the error log
        update_session_status(session_id, "failed", error_log=error_msg)

        # Retry with exponential backoff (60s, then 120s)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
