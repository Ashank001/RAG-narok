#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

python -m celery -A worker purge -f 2>/dev/null || true

# Start uvicorn and log output explicitly
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level debug &
UVICORN_PID=$!

# Wait 10 seconds for uvicorn to start
sleep 10

# Check if uvicorn is still running
if ! kill -0 $UVICORN_PID 2>/dev/null; then
    echo "UVICORN CRASHED - check logs above"
fi

python -m celery -A worker worker --loglevel=info --concurrency=1