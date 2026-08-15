#!/bin/sh

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

python -m celery -A worker purge -f 2>/dev/null || true

uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &

# concurrency=1 prevents OOM on free tier
python -m celery -A worker worker --loglevel=info --concurrency=1