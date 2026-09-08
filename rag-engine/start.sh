#!/bin/sh
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export PYTHONUNBUFFERED=1

echo "[start.sh] Redis check..."
python -c "
import os,ssl,redis
r=redis.from_url(os.getenv('REDIS_URL'),ssl_cert_reqs=ssl.CERT_NONE)
r.ping()
print('Redis OK',flush=True)
" 2>&1

echo "[start.sh] Starting Celery..."
python -m celery -A worker worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 &

CELERY_PID=$!
echo "[start.sh] Celery PID=$CELERY_PID"

exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}