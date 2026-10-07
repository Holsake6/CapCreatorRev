"""JSON HTTP API (stdlib only). All routes live under /api."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import capcut, category, config, db, learning, reviews, scoring
from .jobs import RefreshJob
from .scoring import read_reference_cases

MAX_BODY = 10_000_000


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _aesthetic(conn):
    profile = learning.preference_profile(conn)
    visual = learning.rejected_visual_profiles(conn)
    labels = {}
    for item in visual:
        for label, confidence in item["video_profile"].get("labels", {}).items():
            labels[label] = labels.get(label, 0) + float(confidence)
    return {
        "revision": profile["revision"],
        "updated_at": profile["updated_at"],
        "reference_case_count": len(read_reference_cases().get("videos", [])),
        "positive_terms": profile["positive_terms"],
        "negative_terms": profile["negative_terms"],
        "positive_terms_text": learning.terms_editor_text(profile["positive_terms"]),
        "negative_terms_text": learning.terms_editor_text(profile["negative_terms"]),
        "positive_feedback": [item["text"] for item in profile["positive_phrases"]],
        "negative_feedback": [item["text"] for item in profile["negative_prompts"]],
        "edit_history": list(reversed(profile["edit_history"][-12:])),
        "visual": {
            "profile_count": len(visual),
            "video_count": sum(int(item["video_profile"].get("video_count", 0)) for item in visual),
            "scoring_count": sum(item["affects_visual_score"] for item in visual),
            "top_labels": [label for label, _ in sorted(labels.items(), key=lambda pair: -pair[1])[:12]],
        },
    }


def _learn_rejection_in_background(db_path, key, reason):
    def work():
        try:
            with db.session(db_path) as conn:
                if learning.learn_rejected_creator_video(conn, key, reason):
                    scoring.rescore_queue(conn)
        except Exception as exc:  # background best effort; never break a review
            print(f"负面视频学习失败：{exc}", flush=True)
    threading.Thread(target=work, daemon=True).start()


class Api:
    """Route table bound to one database file and one refresh job."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.job = RefreshJob(db_path)
        self.routes = {
            ("GET", "/api/health"): lambda conn, q, b: {"ok": True, "service": "capcut-creator-review"},
            ("GET", "/api/overview"): lambda conn, q, b: reviews.overview(conn),
            ("GET", "/api/creators"): self.list_creators,
            ("POST", "/api/reviews"): self.save_review,
            ("POST", "/api/profiles/resolve"): self.resolve_profile,
            ("GET", "/api/refresh"): lambda conn, q, b: self.job.snapshot(),
            ("POST", "/api/refresh"): self.start_refresh,
            ("POST", "/api/refresh/cancel"): self.cancel_refresh,
            ("GET", "/api/aesthetic"): lambda conn, q, b: _aesthetic(conn),
            ("PUT", "/api/aesthetic/terms"): self.save_terms,
            ("GET", "/api/categories/new"): lambda conn, q, b: category.state(conn),
            ("POST", "/api/categories/new/cases"): self.add_category_cases,
            ("GET", "/api/exclusions"): lambda conn, q, b: {"terms": reviews.exclusions(conn)},
            ("PUT", "/api/exclusions"): self.save_exclusions,
        }

    def list_creators(self, conn, query, body):
        view = query.get("view", ["pending"])[0]
        if view not in (*config.REVIEW_STATUSES, "all"):
            view = "pending"
        return {"view": view, "items": reviews.list_creators(conn, view)}

    def save_review(self, conn, query, body):
        key = reviews.save(conn, body)
        if body.get("status") == "rejected":
            _learn_rejection_in_background(self.db_path, key, body.get("rejection_reason", ""))
        return {"ok": True, "key": key}

    def resolve_profile(self, conn, query, body):
        try:
            return capcut.resolve_profile_link(body.get("link", ""))
        except OSError as exc:
            raise ApiError(f"无法访问 CapCut：{exc}", 502) from exc

    def start_refresh(self, conn, query, body):
        self.job.start()
        return self.job.snapshot()

    def cancel_refresh(self, conn, query, body):
        if not self.job.cancel():
            raise ApiError("当前没有正在进行的刷新", 409)
        return self.job.snapshot()

    def save_terms(self, conn, query, body):
        positive = learning.parse_terms_editor(body.get("positive_text", ""))
        negative = learning.parse_terms_editor(body.get("negative_text", ""))
        learning.apply_term_edits(conn, positive, negative)
        scoring.rescore_queue(conn)
        return _aesthetic(conn)

    def add_category_cases(self, conn, query, body):
        cases = body.get("cases")
        if isinstance(cases, str):
            if not cases.strip():
                raise ApiError("请先选择 JSON 文件或粘贴正面案例 JSON")
            try:
                cases = json.loads(cases)
            except json.JSONDecodeError as exc:
                raise ApiError(f"JSON 格式错误：{exc}") from exc
        if cases is None:
            raise ApiError("请先选择 JSON 文件或粘贴正面案例 JSON")
        added = category.add_cases(conn, cases, body.get("category_name", ""))
        return {"added": added, "state": category.state(conn)}

    def save_exclusions(self, conn, query, body):
        terms = body.get("terms")
        if not isinstance(terms, list):
            raise ApiError("terms 必须是数组")
        return {"terms": reviews.replace_exclusions(conn, [str(term) for term in terms])}


def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin in config.ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, status, payload, content_type="application/json; charset=utf-8", extra=None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            body = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                if length > MAX_BODY:
                    self.close_connection = True
                    return self._send(413, {"error": "请求内容过大"})
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return self._send(400, {"error": "请求体必须是 JSON"})
                if not isinstance(body, dict):
                    return self._send(400, {"error": "请求体必须是 JSON 对象"})
            if method == "GET" and parsed.path == "/api/export/approved.csv":
                with db.session(api.db_path) as conn:
                    data = reviews.approved_csv(conn)
                return self._send(200, data, "text/csv; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="capcut-approved.csv"'})
            handler = api.routes.get((method, parsed.path))
            if not handler:
                return self._send(404, {"error": f"未知接口：{method} {parsed.path}"})
            try:
                with db.session(api.db_path) as conn:
                    result = handler(conn, parse_qs(parsed.query), body)
                self._send(200, result)
            except ApiError as exc:
                self._send(exc.status, {"error": str(exc)})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": f"服务器错误：{type(exc).__name__}：{exc}"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def log_message(self, *_):
            pass

    return Handler


def make_server(host=config.HOST, port=config.PORT, db_path=None):
    server = ThreadingHTTPServer((host, port), make_handler(Api(db_path)))
    server.daemon_threads = True
    return server
