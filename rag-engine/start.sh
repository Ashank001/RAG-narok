#!/bin/sh

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

# Start Celery worker in the background
celery -A worker worker --loglevel=info --pool=solo --concurrency=1 &

# Start Uvicorn in the foreground to bind the port and keep the container alive
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1