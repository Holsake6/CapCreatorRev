#!/bin/zsh
# macOS：安装每天上午 9:00 的自动扫描（launchd）。先实际测试一次扫描，成功后才安装。
cd "${0:A:h}/.." || exit 1
root="$(pwd)"
python=""
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  exe="$($candidate -c 'import sys; assert sys.version_info >= (3, 9); print(sys.executable)' 2>/dev/null)"
  if [[ -n "$exe" ]]; then python="$exe"; break; fi
done
if [[ -z "$python" ]]; then echo "未找到 Python 3.9+。"; read -k 1; exit 1; fi
export PYTHONUTF8=1
echo "正在执行一次测试扫描，成功后才会安装每日任务……"
if ! "$python" backend/main.py --scan-only --pages 30; then
  echo "测试扫描失败，没有修改每日任务。请检查网络后重试。"
  read -k 1
  exit 1
fi
logs="$root/backend/data"
mkdir -p "$logs"
: > "$logs/daily.log"
: > "$logs/daily-error.log"
agent="$HOME/Library/LaunchAgents/com.capcut-review.daily-scan.plist"
mkdir -p "${agent:h}"
cat > "$agent" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.capcut-review.daily-scan</string>
<key>ProgramArguments</key><array>
<string>$python</string>
<string>$root/backend/main.py</string>
<string>--scan-only</string>
</array>
<key>EnvironmentVariables</key><dict><key>PYTHONUTF8</key><string>1</string></dict>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
<key>StandardOutPath</key><string>$logs/daily.log</string>
<key>StandardErrorPath</key><string>$logs/daily-error.log</string>
</dict></plist>
PLIST
# Remove the job installed by the previous single-file version, if any.
old_agent="$HOME/Library/LaunchAgents/com.codex.capcut-review.plist"
if [[ -f "$old_agent" ]]; then
  /bin/launchctl bootout "gui/$(id -u)" "$old_agent" 2>/dev/null
  rm -f "$old_agent"
fi
/bin/launchctl bootout "gui/$(id -u)" "$agent" 2>/dev/null
if /bin/launchctl bootstrap "gui/$(id -u)" "$agent"; then
  echo "测试扫描成功，已设置每天上午 9:00 自动扫描。审核时双击 run.command。"
else
  echo "定时任务未能启动，请检查上面的错误信息。"
fi
read -k 1
