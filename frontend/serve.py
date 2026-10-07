#!/usr/bin/env python3
"""Minimal static file server for the frontend (stdlib only, no build step).

    python frontend/serve.py --port 5173
"""

import argparse
import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript; charset=utf-8"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description="CapCut 审核前端静态服务")
    parser.add_argument("--host", default=os.environ.get("CAPCUT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FRONTEND_PORT", "5173")))
    parser.add_argument("--pid-file")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), functools.partial(Handler, directory=str(ROOT)))
    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")
    print(f"前端已启动：http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.pid_file:
            Path(args.pid_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
