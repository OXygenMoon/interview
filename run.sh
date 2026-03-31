#!/bin/bash

# 停止旧服务
echo "正在停止旧服务..."
pkill -f "python run.py" || true
pkill -f "gunicorn" || true

# 等待一下确保端口释放
sleep 2

# 设置环境变量
export LD_LIBRARY_PATH=/nix/store/dj06r96j515npcqi9d8af1d1c60bx2vn-gcc-14.3.0-lib/lib

# 启动新服务
echo "正在启动新服务..."
nohup ./venv/bin/python3 run.py > server.log 2>&1 &

echo "服务已重启! 日志输出在 server.log"
