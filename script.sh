#!/bin/zsh

# 启动本地 CapCut 作者审核网页。
set -e
cd "${0:A:h}"

url="http://127.0.0.1:8765/"
if /usr/bin/curl --silent --fail --max-time 2 "$url" >/dev/null; then
  /usr/bin/open "$url" 2>/dev/null || true
  echo "审核页已在运行：$url"
  exit 0
fi

python="/Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$python" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]]; then
      python="$candidate"
      break
    fi
  done
fi

if [[ ! -x "$python" ]]; then
  echo "未找到 Python 运行环境。"
  exit 1
fi

echo "审核网页启动中：$url"
"$python" capcut_local.py
