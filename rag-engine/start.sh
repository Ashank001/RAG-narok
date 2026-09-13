#!/bin/sh

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1
export MALLOC_TRIM_THRESHOLD_=100000

echo "[start.sh] Redis check..."

python -c "
import os
import ssl
import redis

print('[start.sh] REDIS_URL exists:', bool(os.getenv('REDIS_URL')), flush=True)
print('[start.sh] REDIS_URL prefix:', os.getenv('REDIS_URL', '')[:12], flush=True)

r = redis.from_url(
    os.getenv('REDIS_URL'),
    ssl_cert_reqs=ssl.CERT_NONE
)

r.ping()
print('[start.sh] Redis OK', flush=True)
"

echo "[start.sh] Starting Celery..."

python -m celery -A worker worker \
    --loglevel=INFO \
    --pool=solo \
    --concurrency=1 \
    > /tmp/celery.log 2>&1 &

CELERY_PID=$!

echo "[start.sh] Celery PID=$CELERY_PID"

sleep 10

if kill -0 "$CELERY_PID" 2>/dev/null; then
    echo "[start.sh] ✅ CELERY PROCESS IS ALIVE"
else
    echo "[start.sh] ❌ CELERY PROCESS DIED"
    cat /tmp/celery.log
    exit 1
fi

echo "[start.sh] ===== CELERY LOG ====="
cat /tmp/celery.log
echo "[start.sh] ====================="

echo "[start.sh] Process memory:"
ps -o pid,ppid,rss,vsz,comm,args

echo "[start.sh] Starting FastAPI..."

exec uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-10000}