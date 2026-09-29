#!/bin/zsh
cd "${0:A:h}" || exit 1
url="http://127.0.0.1:8765/"
if /usr/bin/curl --silent --fail --max-time 2 "$url" >/dev/null; then
  /usr/bin/open "$url" 2>/dev/null || echo "审核页已启动，请在浏览器打开：$url"
  exit 0
fi
python="/Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$python" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$candidate" ]]; then python="$candidate"; break; fi
  done
fi
if [[ ! -x "$python" ]]; then
  echo "未找到 Python 运行环境。请在 Codex 中重新打开本任务。"
  read -k 1
  exit 1
fi
echo "如浏览器未自动打开，请访问：http://127.0.0.1:8765/"
"$python" capcut_local.py
