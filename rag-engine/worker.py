import os
import re
import stat
import shutil
import tempfile
import sys
import time
import json
import traceback
import urllib.request
import urllib.error

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load .env FIRST — BEFORE any heavy C-extension imports (torch/numpy/OpenBLAS).
# OPENBLAS_NUM_THREADS and OMP_NUM_THREADS must be in the process environment
# before numpy is imported, or OpenBLAS will try to allocate too many threads.
load_dotenv()

# Ensure thread limits are set even if .env is missing the keys
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# pyrefly: ignore [missing-import]
from logger import get_logger

# Module-level logger (no session bound at import time)
_log = get_logger(__name__)

def log_memory(label, logger=None):
    """Log Linux RSS memory usage (reads /proc/self/status). Fail-safe."""
    _l = logger or _log
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    mb = kb / 1024
                    _l.info(
                        f"MEMORY | {label} | RSS={mb:.1f} MB"
                    )
                    return
    except Exception as e:
        _l.warning(f"Could not read memory usage: {e}")

log_memory("IMPORT START")

log_memory("BEFORE import git")
import git
log_memory("AFTER import git")

log_memory("BEFORE config imports")
# pyrefly: ignore [missing-import]
from config import celery_app, get_sync_db, get_sync_collection
log_memory("AFTER config imports")

# LangChain Imports — AFTER load_dotenv() so thread limits are active
log_memory("BEFORE langchain_text_splitters")
# pyrefly: ignore [missing-import]
from langchain_text_splitters import RecursiveCharacterTextSplitter
log_memory("AFTER langchain_text_splitters")

log_memory("BEFORE langchain_huggingface")
# pyrefly: ignore [missing-import]
from langchain_huggingface import HuggingFaceEmbeddings
log_memory("AFTER langchain_huggingface")

log_memory("BEFORE langchain_mongodb")
# pyrefly: ignore [missing-import]
from langchain_mongodb import MongoDBAtlasVectorSearch
log_memory("AFTER langchain_mongodb")

log_memory("IMPORT END")

# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------
DB_NAME = "rag_db"
COLLECTION_NAME = "code_vectors"
ATLAS_INDEX_NAME = "vector_index"
# bge-small: 130 MB, 384 dims — fits in Render 512 MB free tier alongside FastAPI+Celery.
# bge-base (438 MB, 768 dims) causes OOM on free tier; use bge-base only on paid plans.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # 130 MB, 384 dims, no API key needed
BATCH_SIZE = 32  # Smaller batches to keep peak RAM usage low on 512 MB containers

# Repo size guard thresholds (configurable via env)
MAX_REPO_SIZE_KB = int(os.getenv("MAX_REPO_SIZE_KB", "51200"))  # 50 MB
MAX_FILE_COUNT_WARNING = int(os.getenv("MAX_FILE_COUNT_WARNING", "2000"))
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB — skip files larger than this
GITHUB_API_TIMEOUT = 8  # seconds

# GitHub URL pattern — matches https://github.com/{owner}/{repo}
_GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/([a-zA-Z0-9](?:[a-zA-Z0-9._-]{0,98}[a-zA-Z0-9])?)"
    r"/([a-zA-Z0-9._-]{1,100})(?:\.git)?/?$"
)

# ---------------------------------------------------------
# File Filter Constants (FIX 3)
# ---------------------------------------------------------
# Extensions and basenames that SHOULD be ingested
SOURCE_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".vue", ".html", ".css", ".scss",
    ".md", ".json", ".yaml", ".yml", ".toml",
    ".sh", ".bash", ".sql", ".r",
    ".txt", ".dockerfile",
}

# Basenames (exact filename match) that should be included even if
# their extension isn't in SOURCE_CODE_EXTENSIONS
SOURCE_CODE_BASENAMES = {
    "dockerfile", ".env.example", "makefile", "cmakelists.txt",
    "rakefile", "gemfile", "procfile",
}

# Directories to always skip
EXCLUDED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", ".output",
    "vendor", "target", "bin", "obj",
    ".tox", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode",
}

# Binary / generated extensions to always skip
EXCLUDED_EXTENSIONS = {
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".wasm", ".jar", ".war", ".ear",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".db", ".sqlite", ".sqlite3",
    ".min.js", ".min.css",
}

# Lock files to always skip
EXCLUDED_BASENAMES = {
    "package-lock.json", "yarn.lock", "poetry.lock",
    "pipfile.lock", "pnpm-lock.yaml", "composer.lock",
    "cargo.lock", "gemfile.lock",
}


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
# Repo Size Guard — rejects oversized repos before cloning
# ---------------------------------------------------------
def _check_repo_size(repo_url: str, session_id: str) -> dict:
    """
    Calls GitHub API GET /repos/{owner}/{repo} and enforces size limits
    BEFORE the expensive git clone operation.

    Guards:
      - Rejects repos larger than MAX_REPO_SIZE_KB (default 50 MB / 51200 KB).
      - Warns if the repo has more than MAX_FILE_COUNT_WARNING files (estimated
        from the GitHub API tree, or the 'size' heuristic as fallback).

    Returns the GitHub API response dict on success.
    Raises ValueError if the repo is too large or the API call fails.
    """
    log = get_logger(__name__, session_id=session_id)

    # Parse owner/repo from the URL
    match = _GITHUB_URL_PATTERN.match(repo_url.strip())
    if not match:
        raise ValueError(
            f"Cannot parse GitHub owner/repo from URL: {repo_url}. "
            "Expected format: https://github.com/{{owner}}/{{repo}}"
        )
    owner, repo = match.group(1), match.group(2)

    # Build request with optional auth
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "RAGnarok-Worker/1.0",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    log.info("Checking repo size via GitHub API", extra={
        "owner": owner, "repo": repo, "api_url": api_url,
    })

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as http_err:
        if http_err.code == 404:
            raise ValueError(
                f"Repository not found: github.com/{owner}/{repo}. "
                "Verify the URL is correct and the repository is publicly accessible."
            ) from http_err
        raise ValueError(
            f"GitHub API error ({http_err.code}) while checking repository size. "
            "Please try again later."
        ) from http_err
    except (urllib.error.URLError, TimeoutError) as net_err:
        raise ValueError(
            f"Could not reach GitHub API to verify repository size: {net_err}. "
            "Please check your network connection and try again."
        ) from net_err

    # ------------------------------------------------------------------
    # Guard 1: Reject repos that exceed the size limit
    # ------------------------------------------------------------------
    repo_size_kb = data.get("size", 0)
    repo_size_mb = round(repo_size_kb / 1024, 2)
    max_size_mb = round(MAX_REPO_SIZE_KB / 1024, 2)

    log.info("Repo size retrieved", extra={
        "size_kb": repo_size_kb, "size_mb": repo_size_mb,
        "limit_mb": max_size_mb,
    })

    if repo_size_kb > MAX_REPO_SIZE_KB:
        raise ValueError(
            f"Repository too large ({repo_size_mb} MB). "
            f"Maximum allowed size is {max_size_mb} MB. "
            "Consider using a smaller repository or a specific branch."
        )

    # ------------------------------------------------------------------
    # Guard 2: Warn if estimated file count is high
    # ------------------------------------------------------------------
    # The GitHub API doesn't return a direct file count on /repos,
    # but we can estimate from the git tree. We'll try the tree API
    # with ?recursive=1 and count entries, falling back to a heuristic.
    file_count = None
    file_count_warning = None
    try:
        default_branch = data.get("default_branch", "main")
        tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
        tree_req = urllib.request.Request(tree_url, headers=headers)
        with urllib.request.urlopen(tree_req, timeout=GITHUB_API_TIMEOUT) as tree_resp:
            tree_data = json.loads(tree_resp.read().decode())
            if tree_data.get("truncated"):
                # Tree is truncated = definitely >2000 files
                file_count = MAX_FILE_COUNT_WARNING + 1
                file_count_warning = (
                    f"Repository has a very large number of files (tree API truncated). "
                    f"Ingestion may take a long time."
                )
            else:
                # Count only blobs (files), not trees (directories)
                blobs = [e for e in tree_data.get("tree", []) if e.get("type") == "blob"]
                file_count = len(blobs)
    except Exception as tree_err:
        log.warning("Could not fetch tree for file count estimate", extra={
            "error": str(tree_err),
        })

    if file_count is not None and file_count > MAX_FILE_COUNT_WARNING and not file_count_warning:
        file_count_warning = (
            f"Repository contains approximately {file_count} files "
            f"(threshold: {MAX_FILE_COUNT_WARNING}). Ingestion may take a long time."
        )

    if file_count_warning:
        log.warning("High file count", extra={
            "file_count": file_count, "warning": file_count_warning,
        })
        # Persist warning in session metadata so the frontend can display it
        try:
            db = get_sync_db()
            db.sessions.update_one(
                {"sessionId": session_id},
                {"$set": {"metadata.fileCountWarning": file_count_warning}},
            )
        except Exception as db_err:
            log.warning("Failed to persist file count warning", extra={"error": str(db_err)})

    log.info("Repo size guard passed", extra={
        "size_mb": repo_size_mb, "file_count": file_count,
    })
    return data


# ---------------------------------------------------------
# Session Status Helpers (FIX 4)
# ---------------------------------------------------------
def update_session_status(session_id: str, status: str, error_log: str | None = None,
                          message: str = "") -> None:
    """
    Updates the session document in MongoDB with the current processing status.
    Uses the synchronous PyMongo client to avoid 'Event loop is closed' errors
    inside Celery worker processes.
    Optionally attaches an error log on failure and a human-readable statusMessage.
    """
    log = get_logger(__name__, session_id=session_id)
    log.info(f"Attempting to update session status to '{status}'", extra={"session_id": session_id, "status": status})
    try:
        db = get_sync_db()
        db_name = db.name
        log.info(f"update_session_status: using db='{db_name}', collection='sessions'", extra={
            "session_id": session_id, "db_name": db_name,
        })

        update_fields: dict = {"status": status}
        if message:
            update_fields["statusMessage"] = message

        if error_log:
            update_fields["errorLog"] = error_log
            result = db.sessions.update_one(
                {"sessionId": session_id},
                {"$set": update_fields},
            )
        else:
            unset_fields: dict = {"errorLog": ""}
            result = db.sessions.update_one(
                {"sessionId": session_id},
                {"$set": update_fields, "$unset": unset_fields},
            )

        if result.matched_count == 0:
            log.error(f"NO SESSION FOUND for {session_id}")
        else:
            log.info(f"Session {session_id} → {status}")

    except Exception as e:
        log.error(f"Failed to update session status to '{status}'", extra={"session_id": session_id, "status": status, "error": str(e)})


# ---------------------------------------------------------
# File Filter (FIX 3)
# ---------------------------------------------------------
def is_source_file(file_path: str) -> bool:
    """
    Determines whether a file should be included in the ingestion pipeline.

    Accepts common source code, config, and documentation files.
    Rejects binaries, lock files, build artifacts, and files > 1 MB.

    Args:
        file_path: Relative path of the file within the cloned repository.

    Returns:
        True if the file should be ingested, False otherwise.
    """
    name = file_path.lower()
    parts = name.replace("\\", "/").split("/")

    # 1. Exclude files inside blocked directories
    if EXCLUDED_DIRS.intersection(parts):
        return False

    basename = os.path.basename(name)

    # 2. Exclude lock files by exact basename
    if basename in EXCLUDED_BASENAMES:
        return False

    # 3. Exclude binary/generated extensions
    ext = os.path.splitext(basename)[1]
    if ext in EXCLUDED_EXTENSIONS:
        return False

    # 4. Include by exact basename match (e.g. .env.example, Dockerfile)
    if basename in SOURCE_CODE_BASENAMES:
        return True

    # 5. Include by extension
    if ext in SOURCE_CODE_EXTENSIONS:
        return True

    # 6. Reject everything else (unknown extensions, extensionless files, etc.)
    return False


# ---------------------------------------------------------
# Core Ingestion Logic
# ---------------------------------------------------------
def ingest_repository(session_id: str, repo_url: str) -> dict:
    """
    Synchronous ingestion pipeline:
    1. Clones the repository to a temporary OS-safe directory using GitLoader.
    2. Splits loaded files into chunks using RecursiveCharacterTextSplitter.
    3. Generates vector embeddings using HuggingFaceEmbeddings (BAAI/bge-small-en-v1.5, 384 dims).
    4. Uploads embedded documents to MongoDB Atlas Vector Search (rag_db.code_vectors).
    5. Cleans up the temporary clone directory.

    Returns a summary dict with chunk and document counts.
    """
    log = get_logger(__name__, session_id=session_id)
    log_memory("START", logger=log)
    # Create a temporary directory using the OS temp path (works on Windows, Linux, macOS)
    repo_path = tempfile.mkdtemp(prefix=f"ragnarok_{session_id}_")

    try:
        # --------------------------------------------------
        # Step 1: Clone the repository
        # --------------------------------------------------
        log.info("Starting clone...", extra={"repo_url": repo_url})
        update_session_status(session_id, "processing", message="Cloning repository...")

        # --------------------------------------------------
        # Step 0: Repo size guard — reject oversized repos
        # --------------------------------------------------
        _check_repo_size(repo_url, session_id)

        try:
            repo = git.Repo.clone_from(
                url=repo_url,
                to_path=repo_path,
                depth=1
            )
            default_branch = repo.active_branch.name
            log.info("Repository cloned", extra={"branch": default_branch, "depth": 1})
            log_memory("AFTER CLONE", logger=log)
        except Exception as clone_err:
            log.error("Clone failed", extra={"error": str(clone_err)})
            raise clone_err

        # Count all files before filtering (for diagnostics)
        all_files = []
        for root, dirs, files in os.walk(repo_path):
            # Skip .git directory during walk
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                all_files.append(os.path.join(root, f))

        log.info("Clone complete, %d files found", len(all_files),
                 extra={"total_files_in_repo": len(all_files)})

        # --------------------------------------------------
        # Step 1b: Filter and load files
        # --------------------------------------------------
        update_session_status(session_id, "processing", message="Filtering files...")

        # pyrefly: ignore [missing-import]
        from langchain_community.document_loaders import GitLoader
        loader = GitLoader(
            repo_path=repo_path,
            branch=default_branch,
            file_filter=is_source_file,
        )
        docs = loader.load()
        log_memory(f"AFTER LOAD DOCS ({len(docs)} raw docs)", logger=log)

        # Apply 1 MB file-size guard: drop documents whose source file is too large
        oversized_count = 0
        filtered_docs = []
        for doc in docs:
            source = doc.metadata.get("source", "")
            full_path = os.path.join(repo_path, source) if source else ""
            if full_path and os.path.isfile(full_path):
                if os.path.getsize(full_path) > MAX_FILE_SIZE_BYTES:
                    oversized_count += 1
                    continue
            filtered_docs.append(doc)
        docs = filtered_docs
        log_memory(f"AFTER FILTER ({len(docs)} docs, {oversized_count} oversized skipped)", logger=log)

        log.info("After filtering, %d files remain", len(docs),
                 extra={
                     "files_after_filter": len(docs),
                     "oversized_skipped": oversized_count,
                 })

        if not docs:
            raise ValueError(
                "No source files found in repository. "
                "The repository may contain only binary files, lock files, or unsupported formats."
            )

        # --------------------------------------------------
        # Step 2: Split documents into chunks
        # --------------------------------------------------
        update_session_status(session_id, "processing",
                              message=f"Splitting {len(docs)} files into chunks...")
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )
        chunks = splitter.split_documents(docs)
        log_memory(f"AFTER CHUNKING ({len(chunks)} chunks)", logger=log)
        log.info("Chunking complete, %d chunks created", len(chunks),
                 extra={"chunk_count": len(chunks)})

        if not chunks:
            raise ValueError(
                "Document splitting produced zero chunks. "
                "Files may be empty or contain only whitespace."
            )

        # Enrich each chunk's metadata with the session ID for traceability
        for chunk in chunks:
            chunk.metadata["session_id"] = session_id
            chunk.metadata["repo_url"] = repo_url

        # --------------------------------------------------
        # Step 3: Initialize embedding model
        # --------------------------------------------------
        update_session_status(session_id, "processing",
                              message=f"Embedding {len(chunks)} chunks...")
        log.info("Initializing embedding model", extra={"model": EMBEDDING_MODEL})
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            # Run on CPU; set device="cuda" if you have a GPU
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        log_memory("AFTER EMBEDDING MODEL", logger=log)

        # --------------------------------------------------
        # Step 4: Upload to MongoDB Atlas Vector Search
        # --------------------------------------------------
        update_session_status(session_id, "processing", message="Storing vectors...")
        log.info("Connecting to MongoDB Atlas", extra={"db": DB_NAME, "collection": COLLECTION_NAME})
        collection = get_sync_collection(DB_NAME, COLLECTION_NAME)

        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=ATLAS_INDEX_NAME,
            text_key="text",
            embedding_key="embedding",
        )
        log_memory("AFTER VECTOR STORE", logger=log)

        # Batch upload to avoid overwhelming the embedding API
        total_uploaded = 0
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
            log.info("Embedding and uploading batch", extra={"batch": batch_num, "total_batches": total_batches, "chunk_count": len(batch)})
            log_memory(f"BEFORE BATCH {batch_num}/{total_batches}", logger=log)

            max_batch_retries = 8
            backoff_delay = 5.0
            for attempt in range(1, max_batch_retries + 1):
                try:
                    vector_store.add_documents(batch)
                    total_uploaded += len(batch)
                    log_memory(f"AFTER BATCH {batch_num}/{total_batches}", logger=log)
                    break
                except Exception as exc:
                    # Daily quota is permanent until midnight — fail fast with a clear message.
                    if _is_daily_quota_exhausted(exc):
                        msg = (
                            f"Daily embedding quota exhausted on batch {batch_num}. "
                            "Switch to a new GOOGLE_API_KEY or wait until the quota resets at midnight Pacific."
                        )
                        log.error(msg, extra={"batch": batch_num})
                        raise RuntimeError(msg) from exc
                    if attempt == max_batch_retries:
                        log.error("Batch upload failed — max retries exhausted", extra={"batch": batch_num, "attempts": max_batch_retries, "error": str(exc)})
                        raise exc
                    # Per-minute rate limit — honour the server-suggested retryDelay.
                    wait = _parse_retry_delay_secs(exc, default=backoff_delay)
                    log.warning("Batch rate limited, retrying", extra={"batch": batch_num, "attempt": attempt, "max_retries": max_batch_retries, "retry_in_secs": round(wait, 1)})
                    time.sleep(wait)
                    backoff_delay = min(backoff_delay * 2.0, 120.0)

            # No sleep needed — local model has no API rate limits

        log.info("Embedding complete")
        log.info("Stored %d vectors in MongoDB", total_uploaded,
                 extra={"vectors_uploaded": total_uploaded})

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
                log.debug("Temp directory cleaned up", extra={"temp_path": repo_path})
            except Exception as cleanup_err:
                log.warning("Failed to clean up temp directory", extra={"temp_path": repo_path, "error": str(cleanup_err)})


# ---------------------------------------------------------
# Celery Task Definition (FIX 1 + FIX 4)
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
        _log.error(
            "Missing required arguments",
            extra={
                "sessionId": session_id,
                "repositoryUrl": repo_url,
                "payload": str(payload),
            },
        )
        raise ValueError(
            f"Missing required arguments: sessionId='{session_id}', "
            f"repositoryUrl='{repo_url}' in payload='{payload}'"
        )

    log = get_logger(__name__, session_id=session_id)

    # --- FIX 1 + FIX 4: Wrap entire body with comprehensive logging ---
    try:
        # Update session status to 'processing'
        update_session_status(session_id, "processing", message="Cloning repository...")
        log.info("Task started", extra={
            "repo_url": repo_url,
            "celery_task_id": self.request.id,
            "retry": self.request.retries,
        })

        # Execute the full ingestion pipeline
        result = ingest_repository(session_id, repo_url)

        # Mark session as completed with "Ready" message
        try:
            update_session_status(session_id, "completed", message="Ready")
            log.info("Session status explicitly updated to completed", extra={"session_id": session_id})
        except Exception as e:
            log.error("Failed to update session status to completed in process_repository", extra={"session_id": session_id, "error": str(e)})
            
        log.info("Task complete", extra={"result": result})
        return result

    except Exception as exc:
        # --- FIX 1: Log FULL traceback, not just str(exc) ---
        full_tb = traceback.format_exc()
        error_msg = str(exc)
        log.error(
            "Task failed with exception",
            extra={
                "error": error_msg,
                "traceback": full_tb,
                "celery_task_id": self.request.id,
                "retry": self.request.retries,
                "max_retries": self.max_retries,
            },
        )

        # Print traceback to stderr as well — guarantees it shows in Render logs
        # even if JSON logger output is somehow swallowed.
        print(f"[CELERY TASK FAILED] session={session_id}\n{full_tb}", file=sys.stderr, flush=True)

        # Only mark the session as permanently failed when all retries are
        # exhausted. During retry cycles, keep the status as "processing" so
        # the frontend doesn't show a false failure that later disappears.
        if self.request.retries >= self.max_retries:
            update_session_status(
                session_id, "failed",
                error_log=error_msg,
                message=error_msg,
            )
        else:
            log.warning("Retry scheduled", extra={"retry": self.request.retries + 1, "max_retries": self.max_retries})

        # Retry with exponential backoff (60s, then 120s)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))