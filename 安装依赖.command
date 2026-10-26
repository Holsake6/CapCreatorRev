#!/bin/zsh
# 创建本地 Python 环境（.venv）并安装视频分析依赖。只需运行一次；重复运行会更新依赖。
cd "${0:A:h}" || exit 1
python=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    python="$candidate"; break
  fi
done
if [[ -z "$python" ]]; then
  echo "需要 Python 3.10 或更新版本。请先从 https://www.python.org/downloads/ 安装，或运行：brew install python"
  read -k 1; exit 1
fi
echo "使用 $python 创建 .venv …"
"$python" -m venv .venv || { echo "创建虚拟环境失败"; read -k 1; exit 1; }
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt || { echo "安装依赖失败，请检查网络后重试。"; read -k 1; exit 1; }
if [[ "$1" == "--clip" ]]; then
  .venv/bin/python -m pip install -r requirements-clip.txt
fi
echo ""
echo "依赖安装完成。下面检查网络与 CapCut 连接："
.venv/bin/python capcut_local.py doctor
echo ""
echo "完成。之后双击“打开审核.command”即可。"
read -k 1
