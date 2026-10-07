#!/usr/bin/env bash
# ./run-production.sh [web|worker]
# Web defaults to 4 workers x 16 request threads; run report workers separately.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MODE="${1:-web}"
if [ "$#" -gt 1 ] || { [ "$MODE" != web ] && [ "$MODE" != worker ]; }; then
    echo "Usage: $0 [web|worker]" >&2
    exit 2
fi

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT_DIR/.env"
    set +a
fi

# Force production behavior even when .env still contains development values.
export APP_ENV=production
export FLASK_ENV=production
export FLASK_DEBUG=0
export USE_RELOADER=False
export REPORT_QUEUE_MODE=rq
export APP_HOST="${APP_HOST:-127.0.0.1}"
export APP_PORT="${APP_PORT:-5001}"
export WEB_WORKERS="${WEB_WORKERS:-4}"
export WEB_THREADS="${WEB_THREADS:-16}"
export ASR_NUM_THREADS="${ASR_NUM_THREADS:-1}"
export PYTHONUNBUFFERED=1

PY_BIN=""
for candidate in \
    "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/venv/bin/python" \
    "$ROOT_DIR/.venv/bin/python3" \
    "$ROOT_DIR/venv/bin/python3"; do
    if [ -x "$candidate" ]; then
        PY_BIN="$candidate"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    PY_BIN="$(command -v python3 || true)"
fi
if [ -z "$PY_BIN" ]; then
    echo "[production] ERROR: 未找到 Python 解释器" >&2
    exit 1
fi

NIX_LIB="${NIX_LIB:-/nix/store/dj06r96j515npcqi9d8af1d1c60bx2vn-gcc-14.3.0-lib/lib}"
if [ -d "$NIX_LIB" ]; then
    export LD_LIBRARY_PATH="${NIX_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [ "$MODE" = worker ]; then
    echo "[production] 独立报告 Worker / Python: $PY_BIN"
    exec "$PY_BIN" -c 'import production_settings; from worker import main; main()'
fi

echo "[production] Web: ${APP_HOST}:${APP_PORT}, ${WEB_WORKERS} workers x ${WEB_THREADS} threads"
exec "$PY_BIN" -m gunicorn --config "$ROOT_DIR/gunicorn.conf.py" production_wsgi:app
