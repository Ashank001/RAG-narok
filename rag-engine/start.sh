#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

echo "Starting on PORT: ${PORT}"

# Purge stale tasks
python -m celery -A worker purge -f 2>/dev/null || true

# Start uvicorn FIRST in foreground briefly to bind port
# Then background it and start Celery
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 &
UVICORN_PID=$!

echo "Uvicorn PID: $UVICORN_PID"

# Start Celery in foreground
python -m celery -A worker worker --loglevel=info --concurrency=1

# Keep alive if Celery exits
wait $UVICORN_PID