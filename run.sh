#!/usr/bin/env bash
# 通用前台启动脚本（macOS 开发 / Linux 生产）
#
#   ./run.sh                前台运行（Ctrl+C 停止）
#   APP_PORT=5050 ./run.sh  覆盖端口
#   APP_RUN_MODE=development ./run.sh  Linux 上显式使用开发服务器
#
# 行为：
#   - 本地（macOS）：优先使用项目 .venv/bin/python
#   - 服务器（Linux）：若存在 venv/bin/python 则使用之
#   - 仅当 Nix 库目录真实存在时才设置 LD_LIBRARY_PATH
#   - 通过 exec 直接接管进程，Ctrl+C 干净退出，不残留

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# ---- 加载 .env ----
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT_DIR/.env"
    set +a
fi

# Linux defaults to the production server; macOS keeps local development.
if [ "$(uname -s)" = "Linux" ] && [ "${APP_RUN_MODE:-production}" = production ]; then
    exec /bin/bash "$ROOT_DIR/run-production.sh" web
fi

export APP_HOST="${APP_HOST:-127.0.0.1}"
export APP_PORT="${APP_PORT:-5001}"
export FLASK_APP="${FLASK_APP:-run.py}"
export FLASK_ENV="${FLASK_ENV:-development}"
export FLASK_DEBUG="${FLASK_DEBUG:-1}"
export USE_RELOADER="${USE_RELOADER:-True}"
export PYTHONUNBUFFERED=1

# ---- 选择 Python 解释器 ----
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
    if command -v python3 >/dev/null 2>&1; then
        PY_BIN="$(command -v python3)"
    else
        echo "[run.sh] ERROR: 未找到可用的 Python 解释器（.venv/bin/python 或 python3）" >&2
        exit 1
    fi
fi

# ---- 仅当 Nix 库目录真实存在时才设置（服务器需要，本地不需要）----
NIX_LIB="/nix/store/dj06r96j515npcqi9d8af1d1c60bx2vn-gcc-14.3.0-lib/lib"
if [ -d "$NIX_LIB" ]; then
    export LD_LIBRARY_PATH="${NIX_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

echo "[run.sh] Python : $PY_BIN"
echo "[run.sh] 地址   : http://${APP_HOST}:${APP_PORT}"
echo "[run.sh] Ctrl+C 停止"

exec "$PY_BIN" run.py
