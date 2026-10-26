"""Local web app: JSON API + static pages. Standard library only."""

import csv
import io
import json
import mimetypes
import re
import threading
import time
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import (capcut, category as categories, discovery, dna, doctor, ingest, jobs, learn, paths,
               store, taste, textlearn)
from .textlearn import author_key

STATIC = Path(__file__).resolve().parent / "web"
PAGES = {"": "index.html", "review": "review.html", "train": "train.html",
         "examples": "examples.html", "profile": "profile.html"}
MAX_UPLOAD = 1024 ** 3


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def cat_or_404(slug):
    try:
        return categories.get(slug)
    except (KeyError, ValueError) as exc:
        raise HttpError(404, f"没有这个类别：{slug}") from exc


def decision_of(decisions, author):
    decision = dict(decisions.get(author_key(author), {}))
    if "category_confirmed" not in decision and "dance_confirmed" in decision:
        decision["category_confirmed"] = decision["dance_confirmed"]
    return decision


def media_url(item):
    if item.get("file"):
        return "/media/" + item["file"]
    return item.get("video_url", "")


# ---------------------------------------------------------------- API handlers

def api_categories(method, body, query):
    if method == "POST":
        name = (body.get("name") or "").strip()
        if not name:
            raise HttpError(400, "请填写类别名称")
        keywords = [k.strip() for k in re.split(r"[\n,，、]+", body.get("keywords") or "") if k.strip()]
        overrides = {"keywords": keywords, "description": body.get("description", "")}
        if body.get("language") in ("ja", "any"):
            overrides["language"] = body["language"]
        if body.get("region"):
            overrides["region"] = body["region"]
        category = categories.create(name, slug=body.get("slug") or None, **overrides)
        return category.summary()
    return {"categories": [c.summary() for c in categories.list_categories()],
            "dna_available": dna.available()}


EDITABLE_CONFIG = {"name": str, "description": str, "region": str, "language": str, "keywords": list,
                   "landing_urls": list, "seed_template_ids": list, "include_regex": str, "exclude_regex": str,
                   "exclude_ai": bool, "max_pending": int, "stale_days": int, "stale_min_uses": int,
                   "high_use_threshold": int, "scan_pages": int, "analyze_top": int, "style_strength": int,
                   "visual_gate": str, "trend_source": str, "labels": dict}


def api_config(category, body):
    changes = {}
    for key, kind in EDITABLE_CONFIG.items():
        if key not in body:
            continue
        value = body[key]
        if kind is list and isinstance(value, str):
            value = [v.strip() for v in re.split(r"[\n,，、]+", value) if v.strip()]
        elif kind is int:
            value = int(value)
        elif kind is bool:
            value = bool(value)
        if key in ("include_regex", "exclude_regex") and value:
            re.compile(value)
        changes[key] = value
    if "style_strength" in changes:
        changes["style_strength"] = max(0, min(100, changes["style_strength"]))
    config = category.update_config(**changes)
    if "style_strength" in changes or "keywords" in changes:
        with store.LOCK:
            data = learn.rescore(category, category.candidates())
            category.save_candidates(data)
    return config


def api_candidates(category, query):
    view = query.get("view", ["pending"])[0]
    data = learn.normalize_candidates(category.candidates())
    decisions = category.decisions()
    model = category.model()
    index_records = learn.records_for({f't{w["template_id"]}' for a in data.get("candidates", [])
                                       for w in a.get("works", [])[:12]})
    rows = []
    for author in data.get("candidates", []):
        decision = decision_of(decisions, author)
        status = decision.get("status", "pending")
        if view != "all" and status != view:
            continue
        works = []
        for work in author.get("works", [])[:12]:
            key = f't{work["template_id"]}'
            record = index_records.get(key)
            works.append({**{k: work.get(k) for k in ("template_id", "title", "uses", "url", "cover_url", "video_url",
                                                       "likely_ai", "category_signal", "category_seed",
                                                       "published_at", "style_prob", "from_homepage")},
                          "dna_tags": dna.describe(record["scalars"]) if record else [],
                          "reasons": taste.explain_record(model, record) if (model and record) else []})
        rows.append({"key": author_key(author), "status": status, "decision": decision,
                     "works": works, **{k: v for k, v in author.items() if k != "works"}})
    rows.sort(key=lambda r: (1 if r.get("recommendation_type") == "随机探索" else 0,
                             -float(r.get("score", 0)), int(r.get("match_rank", 10 ** 9))))
    meta = {k: v for k, v in data.items() if k != "candidates"}
    return {"view": view, "rows": rows, "meta": meta, "config": category.config,
            "model": None if not model else {"code": model["code"], "confidence": model["confidence"]}}


def api_decision(category, body):
    status = body.get("status")
    if status not in ("approved", "aesthetic_only", "rejected", "pending"):
        raise HttpError(400, "invalid status")
    labels = category.config["labels"]
    with store.LOCK:
        data = learn.normalize_candidates(category.candidates())
        if body.get("key") not in {author_key(a) for a in data.get("candidates", [])}:
            raise HttpError(400, "unknown author")
        if status in ("approved", "aesthetic_only"):
            if not body.get("non_ai_confirmed"):
                raise HttpError(400, "通过前需确认作者以非AI模板为主")
            if not body.get("category_confirmed"):
                raise HttpError(400, f"通过前需确认：{labels['confirm']}")
            if not body.get("specialty") or not body.get("aesthetic_notes"):
                raise HttpError(400, "请填写擅长类型，以及包装与节奏评价")
            if status == "approved" and not (body.get("cc_id") or body.get("cc_link")):
                raise HttpError(400, "通过前需填写 CC ID 或主页链接")
        if status == "rejected" and not (body.get("rejection_reason") or "").strip():
            raise HttpError(400, "排除前请填写不通过原因；它会作为反向提示词")
        decisions = category.decisions()
        previous = decisions.get(body["key"], {})
        fields = ("key", "status", "cc_id", "cc_link", "tt_link", "total_posts", "high_use_posts",
                  "non_ai_confirmed", "category_confirmed", "priority", "specialty", "aesthetic_notes",
                  "rejection_reason")
        updated = {**previous, **{k: body.get(k) for k in fields if k in body}, "updated_at": categories.now()}
        updated["dance_confirmed"] = updated.get("category_confirmed")  # v2 export compatibility
        decisions[body["key"]] = updated
        category.save_decisions(decisions)
        learn.rebuild_text_profile(category, data, decisions)
    # Review verdicts are training labels for the video model, too.
    threading.Thread(target=_retrain_quietly, args=(category, status == "rejected", body["key"]), daemon=True).start()
    return {"ok": True}


def _retrain_quietly(category, analyse_rejected, key):
    try:
        if analyse_rejected and dna.available():
            data = learn.normalize_candidates(category.candidates())
            author = next((a for a in data["candidates"] if author_key(a) == key), None)
            if author:
                learn.analyze_works(learn.best_works(author, 2))
        if dna.available():
            learn.retrain(category)
        with store.LOCK:
            data = learn.rescore(category, category.candidates())
            category.save_candidates(data)
    except Exception as exc:
        print("retrain failed:", exc, flush=True)


def api_resolve_profile(category, body):
    profile = capcut.resolve_profile_link(body.get("link", ""))
    key = body.get("key")
    if key:
        def deep(job):
            job.write(f"读取 {profile['name']} 的主页全部模板…")
            result = discovery.deep_check(category, key, profile["public_id"])
            job.write(f"主页模板 {result['templates']} 条，其中本类别占比 {round(result['category_share'] * 100)}%")
            return result
        job, _ = jobs.start("deep", category.slug, f"主页深度核查：{profile['name']}", deep)
        profile["job"] = job.id
    return profile


def api_refresh(category, body):
    pages = int(body.get("pages") or category.config["scan_pages"])

    def run(job):
        _, message, changed = discovery.refresh(category, max_pages=pages, log=job.write)
        job.write(message)
        return {"message": message, "changed": changed}
    job, started = jobs.start("scan", category.slug, "扫描新作者", run)
    return {"job": job.id, "started": started}


def api_examples(category):
    model = category.model()
    out = []
    for item in category.examples():
        record = dna.cached(item["key"])
        out.append({**item, "media": media_url(item), "analysed": bool(record),
                    "dna": record["scalars"] if record else None,
                    "tags": dna.describe(record["scalars"]) if record else [],
                    "prototype": bool(model and item["key"] in model.get("prototype_keys", []))})
    return {"examples": out, "dna_available": dna.available(), "config": category.config}


def parse_multipart(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length > MAX_UPLOAD:
        raise HttpError(413, "单次上传超过 1GB，请分批或改用网盘链接导入")
    body = handler.rfile.read(length)
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + handler.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + body)
    fields, files = {}, []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append((Path(filename).name, payload))
        elif name:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


def api_upload(category, handler):
    fields, files = parse_multipart(handler)
    if not files:
        raise HttpError(400, "没有收到视频文件")
    label = "negative" if fields.get("label") == "negative" else "positive"
    staging = paths.media_dir() / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    saved = []
    for name, payload in files:
        if Path(name).suffix.lower() not in ingest.VIDEO_EXT:
            raise HttpError(400, f"{name} 不是支持的视频格式（mp4/mov/m4v/webm/mkv/avi）")
        target = staging / f"{int(time.time() * 1000)}-{name}"
        target.write_bytes(payload)
        saved.append(target)

    def run(job):
        added = 0
        for path in saved:
            original = path.name.split("-", 1)[-1]
            job.write(f"分析 {original} …")
            added += ingest.add_video(category, path, label=label, source="网页上传", log=job.write,
                                      title=Path(original).stem)
            path.unlink(missing_ok=True)
        if dna.available():
            learn.retrain(category)
        return {"added": added}
    job, _ = jobs.start(f"upload-{time.time()}", category.slug, "上传示例视频", run)
    return {"job": job.id, "files": len(saved)}


def api_import(category, body):
    source = body.get("source", "")
    by_folder = bool(body.get("by_folder"))
    label = "negative" if body.get("label") == "negative" else "positive"

    def run(job):
        if label == "negative" and not re.match(r"https?://", source.strip()) and not Path(source.strip()).exists():
            added, total = ingest.ingest_text(category, source, label="negative", log=job.write)
            counts = {category.slug: added}
        else:
            counts = ingest.ingest(source, category.slug, by_folder=by_folder, log=job.write)
        for slug in counts:
            if dna.available():
                learn.retrain(categories.get(slug))
        job.write("完成：" + "，".join(f"{categories.get(s).config['name']} +{n}" for s, n in counts.items()))
        return {"counts": counts}
    job, _ = jobs.start("import", category.slug, "导入示例", run)
    return {"job": job.id}


def api_example_update(category, key, body, method):
    if method == "DELETE":
        category.remove_example(key)
    else:
        label = body.get("label")
        if label not in ("positive", "negative"):
            raise HttpError(400, "label 只能是 positive 或 negative")
        category.update_example(key, label=label)
    if dna.available():
        learn.retrain(category)
    return {"ok": True}


def trainer_pool(category):
    index = learn.template_index(category)
    examples = {e["key"] for e in category.examples()}
    return {k: v for k, v in index.items() if k not in examples and (v.get("video_url") or v.get("file"))}


def api_train_next(category, query):
    size = max(2, min(8, int(query.get("size", ["6"])[0])))
    pool = trainer_pool(category)
    model = category.model()
    records = learn.records_for(pool)
    labels = category.labels()
    labelled = {p["key"] for p in labels["points"]}
    keys = taste.choose_grid(model, records, list(pool), labelled, size=size,
                             author_of=lambda k: pool[k].get("author_key") or k)
    scores = taste.score_records(model, {k: records[k] for k in keys if k in records}) if model else {}
    items = [{"key": k, "title": pool[k].get("title", ""), "media": media_url(pool[k]),
              "cover_url": pool[k].get("cover_url", ""), "url": pool[k].get("url", ""),
              "author_name": pool[k].get("author_name", ""), "uses": pool[k].get("uses", 0),
              "analysed": k in records, "score": None if k not in scores else round(scores[k] * 100)}
             for k in keys]
    analysed_pool = sum(1 for k in pool if k in records)
    return {"items": items, "pool": len(pool), "analysed_pool": analysed_pool,
            "unlabelled": len([k for k in pool if k not in labelled]),
            "rounds": labels["rounds"], "model": model_summary(model), "dna_available": dna.available()}


def model_summary(model):
    if not model:
        return None
    return {k: model.get(k) for k in ("code", "revision", "trained_at", "confidence", "counts", "explanation",
                                      "prototype_keys")}


def api_train_feedback(category, body):
    shown = [k for k in body.get("shown", []) if isinstance(k, str)]
    picked = [k for k in body.get("picked", []) if k in shown]
    disliked = [k for k in body.get("disliked", []) if k in shown and k not in picked]
    if not shown:
        raise HttpError(400, "shown 不能为空")
    at = categories.now() + f".{int(time.time() * 1000) % 1000:03d}"
    points, pairs = taste.grid_feedback(shown, picked, at=at)
    for point in points:
        if point["key"] in disliked:
            point["source"] = "dislike"
    category.add_labels(points, pairs, round_done=True)
    model = learn.retrain(category) if dna.available() else None
    return {"model": model_summary(model or category.model()), "rounds": category.labels()["rounds"]}


def api_train_undo(category):
    category.undo_last_round()
    model = learn.retrain(category) if dna.available() else None
    return {"model": model_summary(model or category.model()), "rounds": category.labels()["rounds"]}


def api_prepare(category, body):
    limit = int(body.get("limit") or 60)

    def run(job):
        if not dna.available():
            raise RuntimeError("未安装视频分析依赖（numpy / opencv-python-headless），请先双击 安装依赖.command")
        done, todo = learn.prepare_pool(category, limit=limit,
                                        progress=lambda d, n: job.write(f"已分析 {d}/{n}"))
        learn.retrain(category)
        with store.LOCK:
            data = learn.rescore(category, category.candidates())
            category.save_candidates(data)
        job.write(f"完成：新分析 {done} 条（待分析共 {todo} 条）")
        return {"analysed": done, "todo": todo}
    job, _ = jobs.start("prepare", category.slug, "分析候选视频", run)
    return {"job": job.id}


def api_retrain(category):
    model = learn.retrain(category)
    with store.LOCK:
        data = learn.rescore(category, category.candidates())
        category.save_candidates(data)
    if not model:
        raise HttpError(400, "还没有可用的已分析正例：请先添加示例视频或模板链接，并等待分析完成")
    return model_summary(model)


def api_profile(category):
    model = category.model()
    profile = category.text_profile()
    examples = {e["key"]: e for e in category.examples()}
    index = learn.template_index(category)
    prototypes = [{"key": k, "title": index.get(k, {}).get("title", ""), "media": media_url(index.get(k, {}))}
                  for k in (model or {}).get("prototype_keys", [])]
    reference = learn.reference_cases(category)
    return {"model": model_summary(model), "prototypes": prototypes,
            "history": category.read("taste_history.json", [])[-30:],
            "text": {"positive_terms": profile.get("positive_terms", {}),
                     "negative_terms": profile.get("negative_terms", {}),
                     "positive_phrases": [p.get("text") for p in profile.get("positive_phrases", [])],
                     "negative_prompts": [p.get("text") for p in profile.get("negative_prompts", [])],
                     "edit_history": profile.get("edit_history", [])[-12:],
                     "revision": profile.get("revision"), "updated_at": profile.get("updated_at")},
            "examples": len(examples), "labels": category.labels(),
            "reference_cases": len(reference.get("videos", [])), "config": category.config,
            "features": [{"name": n, **dna.FEATURE_INFO[n]} for n in dna.FEATURE_NAMES]}


def api_terms(category, body):
    positive = textlearn.parse_terms_editor(body.get("positive_terms", ""))
    negative = textlearn.parse_terms_editor(body.get("negative_terms", ""))
    with store.LOCK:
        profile = textlearn.apply_edits(category.text_profile(), positive, negative)
        category.save_text_profile(profile)
        data = learn.rescore(category, category.candidates())
        category.save_candidates(data)
    return {"ok": True, "revision": profile["revision"]}


def export_csv(category):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["CC用户名称", "CC ID", "CC主页link", "TT主页link", "作者擅长类型", "类别", "风格档案", "综合分"])
    decisions = category.decisions()
    model = category.model() or {}
    for author in category.candidates().get("candidates", []):
        d = decisions.get(author_key(author), {})
        if d.get("status") == "approved":
            specialty = "；".join(x for x in [d.get("specialty", ""), d.get("aesthetic_notes", "")] if x)
            writer.writerow([author["name"], d.get("cc_id", ""), d.get("cc_link", ""), d.get("tt_link", ""),
                             specialty, category.config["name"], model.get("code", ""), author.get("score", "")])
    return stream.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------- HTTP plumbing

class Handler(BaseHTTPRequestHandler):
    server_version = "CapCreator/3"

    def log_message(self, *_):
        pass

    def send(self, status, payload, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(payload, (dict, list)) or payload is None:
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def json_body(self):
        length = min(int(self.headers.get("Content-Length", "0")), 20_000_000)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HttpError(400, "请求不是有效 JSON") from exc

    def serve_file(self, path, content_type=None):
        if not path.is_file():
            raise HttpError(404, "not found")
        content_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header and content_type.startswith("video/"):
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            start = int(match.group(1) or 0) if match else 0
            end = int(match.group(2)) if match and match.group(2) else size - 1
            end = min(end, size - 1)
            with open(path, "rb") as handle:
                handle.seek(start)
                chunk = handle.read(end - start + 1)
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send(200, path.read_bytes(), content_type, {"Accept-Ranges": "bytes"})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and not path.startswith("/api/"):
                return self.route_page(path, query)
            body = {} if method == "GET" or path.endswith("/examples/upload") else self.json_body()
            result = self.route_api(method, path, query, body)
            if isinstance(result, tuple):
                self.send(200, result[0], result[1], result[2] if len(result) > 2 else None)
            else:
                self.send(200, result)
        except HttpError as exc:
            self.send(exc.status, {"error": str(exc)})
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            advice = exc.advice() if hasattr(exc, "advice") else ""
            self.send(400, {"error": f"{exc}{(' ' + advice) if advice else ''}"})

    def route_page(self, path, query):
        if path == "/health":
            return self.send(200, f"CapCutCreatorReview:{paths.ROOT}", "text/plain; charset=utf-8")
        if path.startswith("/static/"):
            target = (STATIC / "static" / path[len("/static/"):]).resolve()
            if not target.is_relative_to((STATIC / "static").resolve()):
                raise HttpError(404, "not found")
            return self.serve_file(target)
        if path.startswith("/media/"):
            root = paths.media_dir().resolve()
            target = (root / path[len("/media/"):]).resolve()
            if not target.is_relative_to(root):
                raise HttpError(404, "not found")
            return self.serve_file(target)
        if path in ("/", "/index.html"):
            return self.serve_file(STATIC / "index.html", "text/html; charset=utf-8")
        if path == "/doctor":
            return self.serve_file(STATIC / "doctor.html", "text/html; charset=utf-8")
        # v2 bookmarks: "/", "/aesthetic", "/new-category" and "/?view=..."
        if path == "/aesthetic":
            return self.redirect("/c/dance/profile")
        if path == "/new-category":
            return self.redirect("/")
        if path == "/export.csv":
            return self.redirect("/api/c/dance/export.csv")
        match = re.fullmatch(r"/c/([a-z0-9-]+)(?:/(review|train|examples|profile))?/?", path)
        if match:
            cat_or_404(match.group(1))
            return self.serve_file(STATIC / PAGES[match.group(2) or "review"], "text/html; charset=utf-8")
        raise HttpError(404, "页面不存在")

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def route_api(self, method, path, query, body):
        if path == "/api/categories":
            return api_categories(method, body, query)
        if path == "/api/doctor":
            return doctor.report()
        if path == "/api/jobs":
            return {"jobs": jobs.recent(query.get("category", [None])[0])}
        match = re.fullmatch(r"/api/jobs/(\d+)", path)
        if match:
            job = jobs.get(match.group(1))
            if not job:
                raise HttpError(404, "job not found")
            return job.as_dict()
        match = re.fullmatch(r"/api/c/([a-z0-9-]+)(/.*)?", path)
        if not match:
            raise HttpError(404, "unknown endpoint")
        category = cat_or_404(match.group(1))
        sub = match.group(2) or ""
        routes = {
            ("GET", ""): lambda: {"config": category.config, "summary": category.summary()},
            ("POST", "/config"): lambda: api_config(category, body),
            ("GET", "/candidates"): lambda: api_candidates(category, query),
            ("POST", "/decision"): lambda: api_decision(category, body),
            ("POST", "/resolve-profile"): lambda: api_resolve_profile(category, body),
            ("POST", "/refresh"): lambda: api_refresh(category, body),
            ("GET", "/examples"): lambda: api_examples(category),
            ("POST", "/examples/upload"): lambda: api_upload(category, self),
            ("POST", "/examples/import"): lambda: api_import(category, body),
            ("GET", "/train/next"): lambda: api_train_next(category, query),
            ("POST", "/train/feedback"): lambda: api_train_feedback(category, body),
            ("POST", "/train/undo"): lambda: api_train_undo(category),
            ("POST", "/train/prepare"): lambda: api_prepare(category, body),
            ("POST", "/retrain"): lambda: api_retrain(category),
            ("GET", "/profile"): lambda: api_profile(category),
            ("POST", "/terms"): lambda: api_terms(category, body),
            ("GET", "/export.csv"): lambda: (export_csv(category), "text/csv; charset=utf-8",
                                             {"Content-Disposition": f'attachment; filename="capcut-{category.slug}-approved.csv"'}),
        }
        if (method, sub) in routes:
            return routes[(method, sub)]()
        match = re.fullmatch(r"/examples/([A-Za-z0-9]+)", sub)
        if match and method in ("POST", "DELETE"):
            return api_example_update(category, match.group(1), body, method)
        raise HttpError(404, "unknown endpoint")


def make_server(port=8765, host="127.0.0.1"):
    return ThreadingHTTPServer((host, port), Handler)


def serve(port=8765, open_browser=True, host="127.0.0.1"):
    server = make_server(port, host)
    url = f"http://127.0.0.1:{port}/"
    print(f"审核页：{url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
