#!/bin/bash
# 停止 run.command 启动的 CapCut 创作者雷达。
# 正在进行的扫描/分析会被中断；已保存的数据不受影响（所有文件都是原子写入）。
cd "$(dirname "$0")" || exit 1

PORT="${CAPCREATOR_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"
PID_FILE="capcut_local_data/server.pid"

is_running() { curl --silent --max-time 2 "${URL}health" 2>/dev/null | grep -q "CapCutCreatorReview"; }
ours() { ps -p "$1" -o command= 2>/dev/null | grep -q "capcut_local.py"; }

stop_pid() {
  local pid="$1"
  kill "$pid" 2>/dev/null || return 1
  for _ in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  kill -9 "$pid" 2>/dev/null
  return 0
}

stopped=0
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE")"
  if [ -n "$pid" ] && ours "$pid"; then
    stop_pid "$pid" && stopped=1
  fi
  rm -f "$PID_FILE"
fi

# 也处理用其他方式（打开审核.command、终端）启动的实例：只停监听该端口的本程序进程。
if is_running && command -v lsof >/dev/null 2>&1; then
  for pid in $(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null); do
    if ours "$pid"; then stop_pid "$pid" && stopped=1; fi
  done
fi

if is_running; then
  echo "⚠ 端口 ${PORT} 上的服务仍在运行，且无法确认它属于本程序，未强制停止。"
  exit 1
elif [ "$stopped" = 1 ]; then
  echo "✅ 已停止。"
else
  echo "没有正在运行的实例。"
fi
