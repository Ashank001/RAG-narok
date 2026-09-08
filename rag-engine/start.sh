#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1

echo "[start.sh] Testing Redis connection..."
python -c "
import os, ssl, redis
url = os.getenv('REDIS_URL', 'NOT SET')
print(f'REDIS_URL prefix: {url[:30]}', flush=True)
try:
    r = redis.from_url(url, ssl_cert_reqs=ssl.CERT_NONE)
    r.ping()
    print('Redis ping: OK', flush=True)
except Exception as e:
    print(f'Redis FAILED: {e}', flush=True)
" 2>&1

echo "[start.sh] Starting Celery worker..."
celery -A worker worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    --logfile=/dev/stdout 2>/dev/stdout &

CELERY_PID=$!
echo "[start.sh] Celery PID=$CELERY_PID"

echo "[start.sh] Starting uvicorn..."
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}