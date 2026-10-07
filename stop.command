#!/bin/bash
# macOS：双击停止 CapCut 作者审核的后端和前端。
cd "$(dirname "$0")" || exit 1
exec /bin/bash ./stop.sh "$@"
