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

echo "[start.sh] Testing Celery worker import..."
python -c "
from config import celery_app
print(f'Celery app: {celery_app.main}', flush=True)
print(f'Broker: {celery_app.conf.broker_url[:30]}', flush=True)
import worker
print('worker.py imported OK', flush=True)
" 2>&1

echo "[start.sh] Starting Celery worker..."
celery -A worker worker --loglevel=debug --pool=solo --concurrency=1 2>&1 &
CELERY_PID=$!
echo "[start.sh] Celery PID=$CELERY_PID. Waiting 10s to check if alive..."
sleep 10
if kill -0 $CELERY_PID 2>/dev/null; then
    echo "[start.sh] Celery still running after 10s - OK"
else
    echo "[start.sh] CELERY CRASHED within 10 seconds"
fi

echo "[start.sh] Starting uvicorn..."
uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}