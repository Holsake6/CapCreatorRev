"""Command line. ``python capcut_local.py`` with no arguments opens the web app.

    python capcut_local.py                      # open the web app (v2 behaviour)
    python capcut_local.py --refresh --scan-only  # v2 daily job: scan every category
    python capcut_local.py doctor               # check network + dependencies
    python capcut_local.py ingest <path|link> --category dance [--by-folder]
    python capcut_local.py new "旅行vlog" --keywords "旅行,vlog,trip"
    python capcut_local.py scan --category dance [--pages 300]
    python capcut_local.py analyze --category dance --limit 80
    python capcut_local.py train --category dance
    python capcut_local.py categories
"""

import argparse
import sys

from . import category as categories, discovery, dna, doctor, ingest, learn, store


def _categories(slug):
    if slug in (None, "all"):
        return categories.list_categories()
    return [categories.get(slug)]


def cmd_serve(args):
    from . import server
    for category in categories.list_categories():
        with store.LOCK:
            data = learn.normalize_candidates(category.candidates())
            if data.get("candidates"):
                discovery.apply_stale_rule(category, data)
                if discovery.enrich_profiles(category, data):
                    print(f"[{category.slug}] 已从自我介绍里的主页链接补全作者信息")
                learn.rebuild_text_profile(category, data)
                # Keep each creator's 高匹配/随机探索 label from the batch it arrived in.
                learn.rescore(category, data)
                data["scoring_version"] = 3
                category.save_candidates(data)
    server.serve(args.port, not args.no_browser)


def cmd_scan(args):
    failed = False
    for category in _categories(args.category):
        print(f"== {category.config['name']} ({category.slug})", flush=True)
        try:
            _, message, _ = discovery.refresh(category, max_pages=args.pages)
            print(message, flush=True)
        except Exception as exc:
            failed = True
            print(f"扫描失败：{exc}", flush=True)
    return 1 if failed else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    moved = categories.ensure_default()
    if moved:
        print("已把 v2 数据迁移到 capcut_local_data/categories/dance/：" + "、".join(moved), flush=True)

    commands = {"doctor", "ingest", "new", "scan", "analyze", "train", "categories", "serve"}
    if not argv or argv[0] not in commands:
        legacy = argparse.ArgumentParser(description="CapCut 模板创作者发现与审核")
        legacy.add_argument("--pages", type=int, default=None)
        legacy.add_argument("--port", type=int, default=8765)
        legacy.add_argument("--refresh", action="store_true")
        legacy.add_argument("--no-browser", action="store_true")
        legacy.add_argument("--scan-only", action="store_true")
        legacy.add_argument("--category", default="all")
        args = legacy.parse_args(argv)
        if args.refresh:
            code = cmd_scan(args)
            if args.scan_only:
                return code
        elif args.scan_only:
            return 0
        return cmd_serve(args)

    parser = argparse.ArgumentParser(prog="capcut_local.py")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("categories")
    new = sub.add_parser("new")
    new.add_argument("name")
    new.add_argument("--slug")
    new.add_argument("--keywords", default="")
    new.add_argument("--language", choices=("ja", "any"), default="ja")
    imp = sub.add_parser("ingest")
    imp.add_argument("source", help="文件夹 / zip / 网盘链接 / 含模板链接的文本文件")
    imp.add_argument("--category", default="dance")
    imp.add_argument("--by-folder", action="store_true", help="按一级子文件夹名自动创建/归入类别")
    imp.add_argument("--no-analyze", action="store_true")
    scan = sub.add_parser("scan")
    scan.add_argument("--category", default="all")
    scan.add_argument("--pages", type=int, default=None)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--category", default="all")
    analyze.add_argument("--limit", type=int, default=80)
    train = sub.add_parser("train")
    train.add_argument("--category", default="all")
    args = parser.parse_args(argv)

    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "doctor":
        result = doctor.print_report()
        return 0 if result["capcut_ok"] else 2
    if args.command == "categories":
        for category in categories.list_categories():
            s = category.summary()
            print(f"{s['slug']:<16} {s['name']:<20} 示例 {s['examples']:>4} · 作者 {s['creators']:>4} "
                  f"(待审 {s['pending']}) · 训练 {s['rounds']} 轮 · 档案 {s['model_code'] or '—'}")
        return 0
    if args.command == "new":
        keywords = [k.strip() for k in args.keywords.replace("，", ",").split(",") if k.strip()]
        category = categories.create(args.name, slug=args.slug, keywords=keywords, language=args.language)
        print(f"已创建类别 {category.slug}")
        return 0
    if args.command == "ingest":
        counts = ingest.ingest(args.source, args.category, by_folder=args.by_folder, log=print,
                               analyze=not args.no_analyze)
        for slug, added in counts.items():
            category = categories.get(slug)
            model = learn.retrain(category) if dna.available() else None
            print(f"{category.config['name']}: 新增 {added} 个示例"
                  + (f"，风格档案 {model['code']}（置信度 {model['confidence']:.0%}）" if model else ""))
        return 0
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "analyze":
        for category in _categories(args.category):
            done, todo = learn.prepare_pool(category, limit=args.limit,
                                            progress=lambda d, n: print(f"  {d}/{n}", flush=True))
            print(f"{category.slug}: 新分析 {done} 条视频（待分析 {todo}）")
            learn.retrain(category)
        return 0
    if args.command == "train":
        for category in _categories(args.category):
            model = learn.retrain(category)
            if model:
                with store.LOCK:
                    data = learn.rescore(category, category.candidates())
                    category.save_candidates(data)
                print(f"{category.slug}: 档案 {model['code']}，置信度 {model['confidence']:.0%}，"
                      f"偏好 " + "、".join(x["text"] for x in model["explanation"]["likes"][:4]))
            else:
                print(f"{category.slug}: 还没有已分析的正例，无法训练")
        return 0
    return 0
