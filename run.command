#!/bin/bash
# 本机试运行：在后台启动 CapCut 创作者雷达并打开浏览器。停止请双击 stop.command。
# 第一次运行会自动创建 .venv 并安装依赖（约 1–3 分钟）。
# 可选环境变量：CAPCREATOR_PORT（默认 8765）、CAPCREATOR_HOST（默认 127.0.0.1，仅本机可访问）。
cd "$(dirname "$0")" || exit 1

PORT="${CAPCREATOR_PORT:-8765}"
HOST="${CAPCREATOR_HOST:-127.0.0.1}"
URL="http://127.0.0.1:${PORT}/"
DATA_DIR="capcut_local_data"
PID_FILE="${DATA_DIR}/server.pid"
LOG_FILE="${DATA_DIR}/server.log"
mkdir -p "$DATA_DIR"

pause() { [ -t 0 ] && [ -z "$CAPCREATOR_NO_PAUSE" ] && read -r -n 1 -p "按任意键关闭窗口…"; echo; }
open_url() {
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
  fi
}
is_running() { curl --silent --max-time 2 "${URL}health" 2>/dev/null | grep -q "CapCutCreatorReview"; }

if is_running; then
  echo "已经在运行：$URL"
  open_url
  exit 0
fi

# ---- Python：优先使用项目自己的 .venv，没有就创建
if [ ! -x .venv/bin/python ]; then
  base=""
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
      /Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
      "$(command -v python3 2>/dev/null)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] && \
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      base="$candidate"; break
    fi
  done
  if [ -z "$base" ]; then
    echo "需要 Python 3.10 或更新版本：请从 https://www.python.org/downloads/ 安装，或运行 brew install python"
    pause; exit 1
  fi
  echo "首次运行：用 $base 创建 .venv …"
  "$base" -m venv .venv || { echo "创建 .venv 失败"; pause; exit 1; }
fi
PY=".venv/bin/python"
if ! "$PY" -c 'import numpy, cv2, certifi' >/dev/null 2>&1; then
  echo "安装依赖（numpy / OpenCV / ffmpeg 等），请稍候…"
  "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
  if ! "$PY" -m pip install --quiet -r requirements.txt; then
    echo "⚠ 依赖安装失败（请检查网络）。程序仍会启动，但视频风格学习暂不可用。"
  fi
fi

# ---- 后台启动
echo "启动中… 日志：${LOG_FILE}"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 启动 =====" >> "$LOG_FILE"
nohup "$PY" capcut_local.py serve --port "$PORT" --host "$HOST" --no-browser >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 1 60); do
  if is_running; then
    echo "✅ 已启动：$URL"
    echo "   停止：双击 stop.command"
    open_url
    exit 0
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then break; fi
  sleep 1
done

echo "❌ 启动失败。最近的日志："
tail -n 25 "$LOG_FILE"
rm -f "$PID_FILE"
pause
exit 1
