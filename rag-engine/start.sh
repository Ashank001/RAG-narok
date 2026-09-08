#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1

echo "[start.sh] Starting Celery worker..."
celery -A worker worker --loglevel=info --pool=solo --concurrency=1 2>&1 &
CELERY_PID=$!
echo "[start.sh] Celery PID=$CELERY_PID. Starting uvicorn..."

uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}