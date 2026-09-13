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
    2>&1 | tee /tmp/celery.log &

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

echo "[start.sh] ===== PROCESS MEMORY ====="

echo "[start.sh] Shell PID: $$"

if [ -f "/proc/$$/status" ]; then
    echo "[start.sh] Shell memory:"
    grep -E "VmRSS|VmSize" /proc/$$/status || true
fi

if [ -n "$CELERY_PID" ] && [ -f "/proc/$CELERY_PID/status" ]; then
    echo "[start.sh] Celery PID: $CELERY_PID"
    echo "[start.sh] Celery memory:"
    grep -E "VmRSS|VmSize" "/proc/$CELERY_PID/status" || true
else
    echo "[start.sh] Celery /proc entry not found"
fi

echo "[start.sh] Python/Celery processes:"
for proc in /proc/[0-9]*; do
    pid="${proc##*/}"

    if [ -r "$proc/cmdline" ]; then
        cmd=$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)

        case "$cmd" in
            *python*|*celery*|*uvicorn*)
                echo "PID=$pid CMD=$cmd"
                grep -E "VmRSS|VmSize" "$proc/status" 2>/dev/null || true
                ;;
        esac
    fi
done

echo "[start.sh] =========================="

echo "[start.sh] Starting FastAPI..."

exec uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-10000}