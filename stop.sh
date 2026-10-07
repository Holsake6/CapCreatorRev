#!/usr/bin/env bash
# 停止 run.sh / run.command 启动的后端和前端。Windows 在 Git Bash 中运行；macOS/Linux 同样可用。

cd "$(dirname "$0")" || exit 1
RUN_DIR="$(pwd)/.run"
BACKEND_PORT="${BACKEND_PORT:-8765}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
  *) IS_WINDOWS=0 ;;
esac

pid_alive() {
  if [ "$IS_WINDOWS" = 1 ]; then
    tasklist //FI "PID eq $1" 2>/dev/null | grep -q " $1 "
  else
    kill -0 "$1" 2>/dev/null
  fi
}

kill_pid() {
  local pid="$1" i=0
  if [ "$IS_WINDOWS" = 1 ]; then
    taskkill //PID "$pid" //T //F >/dev/null 2>&1
  else
    kill "$pid" 2>/dev/null
    while pid_alive "$pid" && [ "$i" -lt 10 ]; do sleep 0.5; i=$((i + 1)); done
    pid_alive "$pid" && kill -9 "$pid" 2>/dev/null
  fi
}

# PID listening on a TCP port (used when the pid file is missing).
port_pid() {
  if [ "$IS_WINDOWS" = 1 ]; then
    netstat -ano 2>/dev/null | tr -d '\r' | awk -v p=":$1" '$1 == "TCP" && $2 ~ p"$" && $4 == "LISTENING" {print $5; exit}'
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1
  fi
}

# Only kill a port owner that is really this app.
port_is_ours() {
  local body
  body="$(curl -s --noproxy "*" --max-time 2 "$1" 2>/dev/null)" || return 1
  case "$body" in *"$2"*) return 0 ;; *) return 1 ;; esac
}

stop_service() {
  local name="$1" label="$2" port="$3" url="$4" marker="$5" pid=""
  local pid_file="$RUN_DIR/$name.pid"
  [ -f "$pid_file" ] && pid="$(tr -d '\r\n ' <"$pid_file")"
  if [ -z "$pid" ] || ! pid_alive "$pid"; then
    pid=""
    port_is_ours "$url" "$marker" && pid="$(port_pid "$port")"
  fi
  if [ -n "$pid" ]; then
    kill_pid "$pid"
    echo "✔ 已停止$label（PID $pid）"
  else
    echo "· $label没有在运行"
  fi
  rm -f "$pid_file"
}

stop_service frontend "前端" "$FRONTEND_PORT" "http://127.0.0.1:$FRONTEND_PORT/" "capcut-creator-review-frontend"
stop_service backend "后端" "$BACKEND_PORT" "http://127.0.0.1:$BACKEND_PORT/api/health" "capcut-creator-review"

# A double-clicked window on Windows would otherwise close before it can be read.
if [ "$IS_WINDOWS" = 1 ] && [ -t 0 ]; then read -r -t 10 -p "（10 秒后自动关闭）" _; fi
