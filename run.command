#!/bin/bash
# macOS：双击启动 CapCut 作者审核（后端 + 前端），并打开浏览器。
cd "$(dirname "$0")" || exit 1
exec /bin/bash ./run.sh "$@"
