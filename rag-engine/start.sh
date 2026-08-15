#!/bin/sh
# -----------------------------------------------------------
# RAG Engine entrypoint for Railway
# - Uvicorn runs in the FOREGROUND (PID 1) so Railway's health
#   check can reach the /health endpoint.
# - Celery worker runs in the BACKGROUND.
# - SIGTERM/SIGINT propagate to both processes for clean shutdown.
# -----------------------------------------------------------

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

# Purge stale Celery tasks from a previous deploy
python -m celery -A worker purge -f 2>/dev/null || true

echo "=== Starting Celery worker (background) ==="
python -m celery -A worker worker --loglevel=info --concurrency=1 &
CELERY_PID=$!

# Trap signals so both processes shut down cleanly
trap "echo 'Shutting down...'; kill $CELERY_PID 2>/dev/null; exit 0" SIGTERM SIGINT

echo "=== Starting uvicorn (foreground) ==="
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info