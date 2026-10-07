#!/usr/bin/env python3
"""CapCut creator review backend: JSON API server and command-line scans.

    python backend/main.py                 # start the API on 127.0.0.1:8765
    python backend/main.py --scan-only     # one incremental scan, then exit
    python backend/main.py --check-profiles URL [URL ...]
"""

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import api, capcut, config, db, discovery, legacy_import  # noqa: E402


def bootstrap(db_path=None):
    """Create the schema and import the old JSON data into an empty database."""
    with db.session(db_path) as conn:
        db.init(conn)
        if db.is_empty(conn):
            legacy_import.run(conn)


def enrich_in_background():
    try:
        with db.session() as conn:
            discovery.enrich_queue_profiles(conn)
    except Exception as exc:  # offline is fine; it is retried on the next start
        print(f"主页资料核验跳过：{exc}", flush=True)


def check_profiles(urls):
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(capcut.check_profile_templates, url): url for url in urls}
        for future in as_completed(futures):
            try:
                print(json.dumps(future.result(), ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"cc_link": futures[future], "error": str(exc)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="CapCut 日本区舞蹈模板创作者审核后端（不调用 OpenAI）")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--pages", type=int, default=1200, help="每次扫描的模板页面数上限，默认1200")
    parser.add_argument("--refresh", action="store_true", help="启动前先执行一次增量扫描")
    parser.add_argument("--scan-only", action="store_true", help="只扫描并保存数据，适合定时任务")
    parser.add_argument("--pid-file", help="启动后写入进程号，供 stop 脚本使用")
    parser.add_argument("--check-profiles", nargs="+", metavar="URL", help="批量核验作者主页分享链接")
    args = parser.parse_args()

    if args.check_profiles:
        check_profiles(args.check_profiles)
        return

    bootstrap()
    with db.session() as conn:
        if args.refresh or args.scan_only:
            print(f"正在执行增量扫描，最多 {args.pages} 页…", flush=True)
            message, _ = discovery.run_refresh(conn, args.pages, progress=lambda stage, msg: print(f"[{stage}] {msg}", flush=True))
            print(message, flush=True)
        discovery.startup_maintenance(conn)
        if args.scan_only:
            discovery.enrich_queue_profiles(conn)
            return
    threading.Thread(target=enrich_in_background, daemon=True).start()

    server = api.make_server(args.host, args.port)
    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")
    print(f"后端 API 已启动：http://{args.host}:{args.port}/api/health", flush=True)
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
