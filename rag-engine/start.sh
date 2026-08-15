#!/bin/sh

# Thread limits before any numpy/torch import
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

# Install git (needed by GitPython)
apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1

# Purge orphaned Celery tasks
echo "[start.sh] Purging orphaned Celery tasks..."
python -m celery -A worker purge -f 2>/dev/null || echo "[start.sh] No tasks to purge."

# Start FastAPI on Railway's dynamic PORT (fallback 8000 for local)
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &

# Start Celery worker in foreground (keeps container alive)
python -m celery -A worker worker --loglevel=info