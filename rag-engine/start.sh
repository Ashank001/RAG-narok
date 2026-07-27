#!/bin/sh
# RAG Engine startup script

# 0. Set thread limits BEFORE any Python import touches numpy/torch/OpenBLAS.
#    This prevents "Memory allocation still failed after 10 retries" on Windows
#    and high-thread-count Linux hosts.
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

# 1. Install system dependencies (git is required by GitPython for repo cloning)
apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1

# 2. Install/update Python dependencies
# Using --upgrade ensures pymongo and cryptography stay current for Atlas TLS compatibility
pip install --upgrade pip --quiet
pip install -r requirements.txt

# 3. Flush orphaned Celery tasks from Redis so stale jobs don't run on startup.
#    The -f flag skips the confirmation prompt.
echo "[start.sh] Purging orphaned Celery tasks from Redis..."
python -m celery -A worker purge -f 2>/dev/null || echo "[start.sh] No tasks to purge (or Redis not yet ready)."

# 3. Start FastAPI server in the background
uvicorn main:app --host 0.0.0.0 --port 8000 &

# 4. Start Celery worker in the foreground (keeps the container alive)
python -m celery -A worker worker --loglevel=info
