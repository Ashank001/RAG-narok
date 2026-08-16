#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

echo "Starting on PORT: ${PORT}"

python -m celery -A worker purge -f 2>/dev/null || true

uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} &

python -m celery -A worker worker --loglevel=info --concurrency=1