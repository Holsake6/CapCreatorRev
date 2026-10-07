#!/usr/bin/env bash
# 启动 CapCut 作者审核（后端 API + 前端页面），然后打开浏览器。
# Windows：在 Git Bash 中运行（或双击，若 .sh 已关联 Git Bash）。
# macOS / Linux 同样可用；macOS 也可以直接双击 run.command。
# 停止服务请运行 stop.sh / stop.command。

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
RUN_DIR="$ROOT/.run"
BACKEND_PORT="${BACKEND_PORT:-8765}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT/api/health"
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT/"
# Chinese log output must not depend on the Windows code page.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 BACKEND_PORT FRONTEND_PORT

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
  *) IS_WINDOWS=0 ;;
esac

fail() {
  echo ""
  echo "❌ $1"
  [ -n "${2:-}" ] && [ -f "$2" ] && { echo "---- $2（最后 20 行）----"; tail -n 20 "$2"; }
  read -r -p "按回车键关闭…" _
  exit 1
}

# Find a Python 3.9+ interpreter; prints its absolute executable path.
find_python() {
  local candidate exe
  for candidate in "py -3" python3 python /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    exe="$($candidate -c 'import sys; assert sys.version_info >= (3, 9); print(sys.executable)' 2>/dev/null | tr -d '\r')"
    if [ -n "$exe" ]; then
      echo "$exe"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python)" || fail "未找到 Python 3.9 或更新版本。请先安装 Python：https://www.python.org/downloads/ （Windows 安装时勾选 Add python.exe to PATH）"

# Returns 0 when the URL answers and its body contains the marker text.
url_ok() {
  "$PYTHON" -c '
import sys, urllib.request
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    body = opener.open(sys.argv[1], timeout=2).read().decode("utf-8", "replace")
except Exception:
    sys.exit(1)
sys.exit(0 if sys.argv[2] in body else 1)
' "$1" "$2" 2>/dev/null
}

# start_service NAME SCRIPT PORT: launch a detached Python server.
start_service() {
  local name="$1" script="$2" port="$3"
  local log="$RUN_DIR/$name.log" err="$RUN_DIR/$name.err.log"
  rm -f "$RUN_DIR/$name.pid"
  if [ "$IS_WINDOWS" = 1 ]; then
    # Start-Process detaches the server from this console window, so closing
    # Git Bash does not stop it. Arguments are relative to WorkingDirectory.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
      "Start-Process -FilePath '$PYTHON' -ArgumentList '$script --port $port --pid-file .run/$name.pid' -WorkingDirectory '$(cygpath -w "$ROOT")' -WindowStyle Hidden -RedirectStandardOutput '$(cygpath -w "$log")' -RedirectStandardError '$(cygpath -w "$err")'" \
      || fail "无法启动 $name"
  else
    nohup "$PYTHON" "$script" --port "$port" --pid-file ".run/$name.pid" >"$log" 2>"$err" </dev/null &
    disown 2>/dev/null || true
  fi
}

wait_for() {
  local url="$1" marker="$2" seconds="$3"
  local i=0
  while [ "$i" -lt "$seconds" ]; do
    url_ok "$url" "$marker" && return 0
    sleep 1
    i=$((i + 1))
  done
  return 1
}

open_browser() {
  if [ "$IS_WINDOWS" = 1 ]; then
    powershell.exe -NoProfile -Command "Start-Process '$1'" >/dev/null 2>&1
  elif command -v open >/dev/null 2>&1; then
    open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1
  fi
}

mkdir -p "$RUN_DIR"
echo "使用 Python：$PYTHON"

if url_ok "$BACKEND_URL" "capcut-creator-review"; then
  echo "✔ 后端已在运行：http://127.0.0.1:$BACKEND_PORT"
else
  echo "… 启动后端（首次启动会把旧版 JSON 数据导入 SQLite）"
  start_service backend backend/main.py "$BACKEND_PORT"
  wait_for "$BACKEND_URL" "capcut-creator-review" 60 || fail "后端没有在 60 秒内启动（端口 $BACKEND_PORT 可能被占用）。" "$RUN_DIR/backend.err.log"
  echo "✔ 后端已启动：http://127.0.0.1:$BACKEND_PORT"
fi

if url_ok "$FRONTEND_URL" "capcut-creator-review-frontend"; then
  echo "✔ 前端已在运行：$FRONTEND_URL"
else
  echo "… 启动前端"
  start_service frontend frontend/serve.py "$FRONTEND_PORT"
  wait_for "$FRONTEND_URL" "capcut-creator-review-frontend" 20 || fail "前端没有在 20 秒内启动（端口 $FRONTEND_PORT 可能被占用）。" "$RUN_DIR/frontend.err.log"
  echo "✔ 前端已启动：$FRONTEND_URL"
fi

open_browser "$FRONTEND_URL"
echo ""
echo "审核页：$FRONTEND_URL"
echo "服务在后台运行，可以关闭此窗口。需要停止时运行 stop.sh（macOS 双击 stop.command）。"
echo "日志目录：$RUN_DIR"

# A double-clicked window on Windows would otherwise close before it can be read.
if [ "$IS_WINDOWS" = 1 ] && [ -t 0 ]; then read -r -t 15 -p "（15 秒后自动关闭）" _; fi
