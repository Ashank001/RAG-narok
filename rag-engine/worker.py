import os
import re
import stat
import shutil
import tempfile
import sys
import time
import git

# pyrefly: ignore [missing-import]
from config import celery_app, get_sync_db, get_sync_collection
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# LangChain Imports
# pyrefly: ignore [missing-import]
from langchain_community.document_loaders import GitLoader
# pyrefly: ignore [missing-import]
from langchain_text_splitters import RecursiveCharacterTextSplitter
# pyrefly: ignore [missing-import]
from langchain_huggingface import HuggingFaceEmbeddings
# pyrefly: ignore [missing-import]
from langchain_mongodb import MongoDBAtlasVectorSearch

load_dotenv()

# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------
DB_NAME = "rag_db"
COLLECTION_NAME = "code_vectors"
ATLAS_INDEX_NAME = "vector_index"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Local CPU model; 384 dims; no API key or quota needed
BATCH_SIZE = 50  # Local model has no rate limits; larger batches = faster ingestion


# ---------------------------------------------------------
# Rate-limit helpers
# ---------------------------------------------------------
def _parse_retry_delay_secs(exc: Exception, default: float) -> float:
    """
    Google's 429 errors embed a suggested retry delay in the message.
    e.g. "Please retry in 37.499159864s."  or  "retryDelay: '37s'"
    Parse that value so we never wait less than Google asks for.
    """
    text = str(exc)
    # Match patterns like "37.5s", "37s", "1.9s" from the error body
    match = re.search(r'retry\s+in\s+(\d+(?:\.\d+)?)s', text, re.IGNORECASE)
    if match:
        suggested = float(match.group(1))
        # Add 2 s of headroom and cap at 120 s so we don't block forever
        return min(suggested + 2.0, 120.0)
    return default


def _is_daily_quota_exhausted(exc: Exception) -> bool:
    """
    Returns True if the 429 is a DAILY quota exhaustion (PerDay quotaId),
    as opposed to a transient per-minute rate limit (PerMinute quotaId).
    Daily quota won't reset until midnight — retrying is pointless.
    """
    text = str(exc)
    return "PerDay" in text or "PerDayPer" in text


# ---------------------------------------------------------
# Windows Cleanup Helper
# ---------------------------------------------------------
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
            {"$set": update_fields},
            upsert=True
        )
    else:
        db.sessions.update_one(
            {"sessionId": session_id},
            {"$set": update_fields, "$unset": {"errorLog": ""}},
            upsert=True
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
        # GAP-12 FIX: Only embed source code. Binaries, lock files, and
        # media produce garbage vectors and burn embedding API quota.
        SOURCE_CODE_EXTENSIONS = {
            ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs",
            ".cpp", ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt",
            ".scala", ".r", ".sh", ".bash", ".sql", ".html", ".css",
            ".scss", ".yaml", ".yml", ".toml", ".json", ".md", ".txt",
            ".env.example", ".dockerfile", "dockerfile",
        }

        def is_source_file(file_path: str) -> bool:
            name = file_path.lower()
            # Exclude lock files specifically
            if any(name.endswith(lf) for lf in ["package-lock.json", "yarn.lock", "poetry.lock", "pipfile.lock", "pnpm-lock.yaml"]):
                return False
            # Exclude hidden/vendor/build directories
            if any(seg in name.split("/") for seg in [".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".next"]):
                return False
            import os as _os
            ext = _os.path.splitext(file_path)[1].lower()
            base = _os.path.basename(file_path).lower()
            return ext in SOURCE_CODE_EXTENSIONS or base in SOURCE_CODE_EXTENSIONS

        print(f"[Worker | {session_id}] Cloning repository: {repo_url}")
        print(f"[Worker | {session_id}] Temp directory: {repo_path}")

        try:
            repo = git.Repo.clone_from(
                url=repo_url,
                to_path=repo_path,
                depth=1
            )
            default_branch = repo.active_branch.name
            print(f"[Worker | {session_id}] Successfully cloned shallow copy (depth=1) of branch: {default_branch}")
            
            loader = GitLoader(
                repo_path=repo_path,
                branch=default_branch,
                file_filter=is_source_file,
            )
            docs = loader.load()
        except Exception as clone_err:
            print(f"[Worker | {session_id}] ❌ Clone failed: {clone_err}")
            raise clone_err

        print(f"[Worker | {session_id}] Loaded {len(docs)} source files (binaries/lockfiles excluded).")

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
        print(f"[Worker | {session_id}] Initializing local embedding model: {EMBEDDING_MODEL}")
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            # Run on CPU; set device="cuda" if you have a GPU
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

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

            max_batch_retries = 8
            backoff_delay = 5.0
            for attempt in range(1, max_batch_retries + 1):
                try:
                    vector_store.add_documents(batch)
                    total_uploaded += len(batch)
                    break
                except Exception as exc:
                    # Daily quota is permanent until midnight — fail fast with a clear message.
                    if _is_daily_quota_exhausted(exc):
                        msg = (
                            f"[Worker | {session_id}] Daily embedding quota exhausted on batch {batch_num}. "
                            "Switch to a new GOOGLE_API_KEY or wait until the quota resets at midnight Pacific."
                        )
                        print(msg)
                        raise RuntimeError(msg) from exc
                    if attempt == max_batch_retries:
                        print(f"[Worker | {session_id}] Batch {batch_num} failed after {max_batch_retries} attempts: {exc}")
                        raise exc
                    # Per-minute rate limit — honour the server-suggested retryDelay.
                    wait = _parse_retry_delay_secs(exc, default=backoff_delay)
                    print(f"[Worker | {session_id}] Batch {batch_num} failed (attempt {attempt}/{max_batch_retries}): rate limited. Retrying in {wait:.1f}s...")
                    time.sleep(wait)
                    backoff_delay = min(backoff_delay * 2.0, 120.0)

            # No sleep needed — local model has no API rate limits

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

        # Only mark the session as permanently failed when all retries are
        # exhausted. During retry cycles, keep the status as "processing" so
        # the frontend doesn't show a false failure that later disappears.
        if self.request.retries >= self.max_retries:
            update_session_status(session_id, "failed", error_log=error_msg)
        else:
            print(f"[Worker | {session_id}] ⚠️ Retry {self.request.retries + 1}/{self.max_retries} scheduled.")

        # Retry with exponential backoff (60s, then 120s)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))