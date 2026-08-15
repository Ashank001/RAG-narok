#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1

python -m celery -A worker purge -f 2>/dev/null || true

echo "=== Testing main.py import ==="
python -c "import main; print('main.py imported OK')" 2>&1

echo "=== Starting uvicorn ==="
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level debug &

sleep 15
echo "=== Starting Celery ==="
python -m celery -A worker worker --loglevel=info --concurrency=1