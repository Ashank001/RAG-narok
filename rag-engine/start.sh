#!/bin/sh

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1

echo "[start.sh] Redis check..."

python -c "
import os, ssl, redis
url = os.getenv('REDIS_URL')
print('[start.sh] REDIS_URL exists:', bool(url), flush=True)
print('[start.sh] REDIS_URL prefix:', url[:12] if url else 'MISSING', flush=True)

r = redis.from_url(url, ssl_cert_reqs=ssl.CERT_NONE)
r.ping()
print('[start.sh] Redis OK', flush=True)
"

echo "[start.sh] Starting Celery..."

python -u -m celery -A worker worker \
    --loglevel=INFO \
    --pool=solo \
    --concurrency=1 \
    --hostname=ragworker@%h &

CELERY_PID=$!
echo "[start.sh] Celery PID=$CELERY_PID"

sleep 20

if kill -0 "$CELERY_PID" 2>/dev/null; then
    echo "[start.sh] ✅ CELERY PROCESS IS ALIVE"
else
    echo "[start.sh] ❌ CELERY PROCESS DIED"
    exit 1
fi

echo "[start.sh] Checking Celery worker..."

python -m celery -A worker inspect ping || true
python -m celery -A worker inspect registered || true

echo "[start.sh] Starting Uvicorn..."

exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}