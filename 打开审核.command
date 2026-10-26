#!/bin/bash
# 旧入口，保留兼容：等同于 run.command（后台启动并打开浏览器；停止用 stop.command）。
exec "$(dirname "$0")/run.command" "$@"
