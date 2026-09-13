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

# Keep Celery logs visible in Render
tail -f /tmp/celery.log &

# Background 60-second polling diagnostic
(
    echo "[start.sh] [Diag-BG] Starting 60s Celery monitor for PID $CELERY_PID..."
    for i in $(seq 1 60); do
        if kill -0 "$CELERY_PID" 2>/dev/null; then
            if [ $((i % 5)) -eq 0 ]; then
                echo "[start.sh] [Diag-BG] ($i/60s) Celery PID: $CELERY_PID"
                if [ -d "/proc/$CELERY_PID" ]; then
                    grep -E "^(State|VmRSS|VmSize|Threads):" /proc/$CELERY_PID/status 2>/dev/null | tr '\n' ' '
                    wchan=$(cat /proc/$CELERY_PID/wchan 2>/dev/null || echo "N/A")
                    echo -n " Wchan: $wchan "
                fi
                if [ -f "/tmp/celery.log" ]; then
                    size=$(wc -c < /tmp/celery.log)
                    echo " LogSize: $size bytes"
                else
                    echo ""
                fi
            fi
        else
            echo "[start.sh] [Diag-BG] Celery process DIED unexpectedly at second $i!"
            exit 1
        fi
        sleep 1
    done
    echo "[start.sh] [Diag-BG] 60s check complete. Celery is still ALIVE."
) &

sleep 10

if kill -0 "$CELERY_PID" 2>/dev/null; then
    echo "[start.sh] ✅ CELERY PROCESS IS ALIVE"
else
    echo "[start.sh] ❌ CELERY PROCESS DIED"
    cat /tmp/celery.log
    exit 1
fi

echo "[start.sh] ===== CELERY DIAGNOSTICS ====="
if [ -d "/proc/$CELERY_PID" ]; then
    echo "[start.sh] 1. Process Status:"
    grep -E "^(Name|State|VmRSS|VmSize|Threads):" /proc/$CELERY_PID/status || true
    echo "[start.sh] 2. Wchan:"
    cat /proc/$CELERY_PID/wchan 2>/dev/null || echo "N/A"
    echo ""
    echo "[start.sh] 3. Cmdline:"
    tr '\0' ' ' < /proc/$CELERY_PID/cmdline 2>/dev/null || echo "N/A"
    echo ""
    echo "[start.sh] 4. Open FDs:"
    ls -1 /proc/$CELERY_PID/fd 2>/dev/null | wc -l || echo "N/A"
else
    echo "[start.sh] /proc/$CELERY_PID not found."
fi

echo "[start.sh] 5. Log File:"
if [ -f "/tmp/celery.log" ]; then
    ls -l /tmp/celery.log
else
    echo "/tmp/celery.log does not exist."
fi

echo "[start.sh] 6. Redis Queue Check:"
python <<'EOF'
import os, ssl, redis
try:
    r = redis.from_url(os.getenv('REDIS_URL'), ssl_cert_reqs=ssl.CERT_NONE)
    print('[start.sh] Checking specific Celery queues (read-only)...')
    for q in ['celery', 'ingestion-queue']:
        t_bytes = r.type(q)
        t = t_bytes.decode("utf-8") if isinstance(t_bytes, bytes) else str(t_bytes)
        if t == 'list':
            print(f'  - {q} (list, len={r.llen(q)})')
        elif t != 'none':
            print(f'  - {q} (type={t})')
        else:
            print(f'  - {q} (empty/not found)')
except Exception as e:
    print(f'[start.sh] Redis diag error: {e}')
EOF
echo "[start.sh] ================================"

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