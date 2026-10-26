#!/bin/zsh
# 启动本地 CapCut 创作者雷达网页。
cd "${0:A:h}" || exit 1
url="http://127.0.0.1:8765/"
if /usr/bin/curl --silent --fail --max-time 2 "${url}health" >/dev/null; then
  /usr/bin/open "$url" 2>/dev/null || echo "已在运行，请在浏览器打开：$url"
  exit 0
fi
python=""
for candidate in .venv/bin/python /Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]]; then python="$candidate"; break; fi
done
if [[ -z "$python" ]]; then
  echo "未找到 Python。请先双击“安装依赖.command”。"
  read -k 1; exit 1
fi
if ! "$python" -c 'import numpy, cv2' 2>/dev/null; then
  echo "提示：尚未安装视频分析依赖，风格学习不可用。双击“安装依赖.command”即可安装。"
fi
echo "如浏览器未自动打开，请访问：$url"
"$python" capcut_local.py
