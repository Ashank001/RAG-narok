#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1

echo "PORT is: ${PORT}"

# Start uvicorn immediately — no purge, no delay
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} &
UVICORN_PID=$!

echo "Uvicorn started with PID: $UVICORN_PID"

# Start Celery after uvicorn
python -m celery -A worker worker --loglevel=info --concurrency=1

wait $UVICORN_PID