#!/bin/zsh
cd "${0:A:h}" || exit 1
python="/Users/a1-6/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$python" ]]; then
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$candidate" ]]; then python="$candidate"; break; fi
  done
fi
if [[ ! -x "$python" ]]; then echo "未找到 Python 运行环境。"; read -k 1; exit 1; fi
echo "正在执行一次测试扫描，成功后才会安装每日任务……"
"$python" capcut_local.py --refresh --scan-only --pages 30
if [[ $? -ne 0 ]]; then
  echo "测试扫描失败，没有修改每日任务。请检查网络后重试。"
  read -k 1
  exit 1
fi
mkdir -p capcut_local_data
: > capcut_local_data/daily.log
: > capcut_local_data/daily-error.log
agent="$HOME/Library/LaunchAgents/com.codex.capcut-review.plist"
mkdir -p "${agent:h}"
cat > "$agent" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.codex.capcut-review</string>
<key>ProgramArguments</key><array>
<string>$python</string>
<string>${0:A:h}/capcut_local.py</string>
<string>--refresh</string><string>--scan-only</string>
</array>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
<key>StandardOutPath</key><string>${0:A:h}/capcut_local_data/daily.log</string>
<key>StandardErrorPath</key><string>${0:A:h}/capcut_local_data/daily-error.log</string>
</dict></plist>
EOF
/bin/launchctl bootout "gui/$(id -u)" "$agent" 2>/dev/null
/bin/launchctl bootstrap "gui/$(id -u)" "$agent"
if [[ $? == 0 ]]; then
  echo "测试扫描成功，已设置每天上午 9:00 自动扫描。审核时双击“打开审核.command”。"
else
  echo "定时任务未能启动，请在 Codex 中报告此错误。"
fi
read -k 1
