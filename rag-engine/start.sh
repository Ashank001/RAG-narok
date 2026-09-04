#!/bin/sh

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

echo "[start.sh] Starting Celery worker..."

# Start Celery; redirect stderr to stdout so Render captures ALL output
celery -A worker worker --loglevel=info --pool=solo --concurrency=1 2>&1 &
CELERY_PID=$!

# Give Celery 5 seconds to start and fail fast if it crashes immediately
sleep 5
if ! kill -0 $CELERY_PID 2>/dev/null; then
  echo "[start.sh] ERROR: Celery worker crashed at startup. Check logs above."
  echo "[start.sh] Continuing anyway — uvicorn will start but ingestion will not work."
fi

echo "[start.sh] Celery PID=$CELERY_PID. Starting uvicorn..."

# Start Uvicorn in the foreground (binds port, keeps container alive)
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1