"""Backend tests (stdlib unittest, no network).

    python -m unittest discover -s backend/tests
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BACKEND = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="capcut-test-"))
os.environ["CAPCUT_DATA_DIR"] = str(TMP)
shutil.copytree(BACKEND / "data" / "legacy", TMP / "legacy")
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402
from app import api, capcut, category, config, db, discovery, learning, repository, reviews, scoring  # noqa: E402

config.OLD_LOCAL_DATA = TMP / "no-old-data"
LEGACY = json.loads((TMP / "legacy" / "candidates.json").read_text(encoding="utf-8"))
LEGACY_REVIEWS = json.loads((TMP / "legacy" / "decisions.json").read_text(encoding="utf-8"))


def fresh_db():
    for path in TMP.glob("capcut.db*"):
        path.unlink()
    main.bootstrap()
    return db.connect()


class LegacyImportTest(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db()

    def tearDown(self):
        self.conn.close()

    def test_queue_and_reviews_are_imported(self):
        self.assertEqual(len(repository.queued_creators(self.conn)), len(LEGACY["candidates"]))
        self.assertEqual(len(repository.all_reviews(self.conn)), len(LEGACY_REVIEWS))
        first = LEGACY["candidates"][0]
        author = repository.load_creator(self.conn, first["sec_uid"])
        self.assertEqual(author["name"], first["name"])
        self.assertEqual(len(author["works"]), len(first["works"]))

    def test_learned_terms_match_old_profile(self):
        old = json.loads((TMP / "legacy" / "preference_profile.json").read_text(encoding="utf-8"))
        profile = learning.preference_profile(self.conn)
        self.assertEqual(profile["positive_terms"], old["positive_terms"])
        self.assertEqual(profile["negative_terms"], old["negative_terms"])
        self.assertEqual(profile["revision"], old["revision"])

    def test_import_runs_only_once(self):
        main.bootstrap()
        self.assertEqual(len(repository.all_reviews(self.conn)), len(LEGACY_REVIEWS))


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db()
        self.key = reviews.list_creators(self.conn, "pending")[0]["key"]

    def tearDown(self):
        self.conn.close()

    def test_validation_rules(self):
        with self.assertRaisesRegex(ValueError, "不通过原因"):
            reviews.save(self.conn, {"key": self.key, "status": "rejected"})
        with self.assertRaisesRegex(ValueError, "非AI"):
            reviews.save(self.conn, {"key": self.key, "status": "approved"})
        with self.assertRaisesRegex(ValueError, "未知作者"):
            reviews.save(self.conn, {"key": "nobody", "status": "pending"})
        with self.assertRaisesRegex(ValueError, "无效"):
            reviews.save(self.conn, {"key": self.key, "status": "maybe"})

    def test_approval_is_learned_and_exported(self):
        before = learning.preference_profile(self.conn)["revision"]
        reviews.save(self.conn, {
            "key": self.key, "status": "approved", "non_ai_confirmed": True, "dance_confirmed": True,
            "cc_id": "new.creator", "specialty": "群舞テスト", "aesthetic_notes": "落書き包装", "total_posts": "42"})
        profile = learning.preference_profile(self.conn)
        self.assertEqual(profile["revision"], before + 1)
        self.assertIn("テスト", profile["positive_terms"])
        self.assertIn("new.creator", reviews.approved_csv(self.conn).decode("utf-8-sig"))
        self.assertEqual(repository.all_reviews(self.conn)[self.key]["total_posts"], 42)

    def test_term_edits_override_and_delete(self):
        profile = learning.preference_profile(self.conn)
        positive = dict(profile["positive_terms"])
        removed = next(iter(positive))
        positive.pop(removed)
        positive["新規ワード"] = 7
        learning.apply_term_edits(self.conn, positive, profile["negative_terms"])
        edited = learning.preference_profile(self.conn)
        self.assertNotIn(removed, edited["positive_terms"])
        self.assertEqual(edited["positive_terms"]["新規ワード"], 7)
        self.assertEqual(edited["revision"], profile["revision"] + 1)
        self.assertIn("正向新增：新規ワード", edited["edit_history"][-1]["summary"])
        with self.assertRaisesRegex(ValueError, "0–10"):
            learning.parse_terms_editor("x = 11")


def landing_item(template_id, author, title, uses=5000, age_days=2, desc="#ダンス かわいい"):
    return {"templateId": template_id, "title": title, "desc": desc, "usageAmount": uses,
            "createTime": int(time.time()) - age_days * 86400, "segmentAmount": 2,
            "coverUrl": "", "videoUrl": "", "canonicalPath": "",
            "author": {"name": author, "secUid": f"uid-{author}", "profileUrl": ""}}


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db()
        rejected_key = next(key for key, review in LEGACY_REVIEWS.items() if review["status"] == "rejected")
        items = [
            landing_item("7700000000000000001", "ダンサーあい", "推しダンス テンプレ"),
            landing_item("7700000000000000002", "ダンサーあい", "落書き ダンス", uses=900, age_days=10),  # stale
            landing_item("7700000000000000003", "みゆ", "アイドルダンス 音ハメ"),
            landing_item("7700000000000000004", "AIさん", "AI写真 ダンス"),          # AI only
            landing_item("7700000000000000005", "English Only", "dance", desc="dance"),  # no Japanese
            landing_item("7700000000000000006", "rin_go.x", "ダンス ですよ"),        # excluded
        ]
        rejected = landing_item("7700000000000000007", "却下された", "ダンス です")
        rejected["author"]["secUid"] = rejected_key
        items.append(rejected)
        self.summaries = {item["templateId"]: item for item in items}

    def tearDown(self):
        self.conn.close()

    def run_refresh(self):
        with mock.patch.object(capcut, "landing_template_ids", return_value=(list(self.summaries), self.summaries)), \
                mock.patch.object(capcut, "fetch_jp_tiktok_chart", side_effect=OSError("offline")), \
                mock.patch.object(capcut, "fetch_template_detail", side_effect=OSError("offline")):
            return discovery.run_refresh(self.conn, 1200, replace_pending=True)

    def test_manual_refresh_replaces_pending_batch(self):
        kept_before = {key for key, review in repository.all_reviews(self.conn).items()
                       if review["status"] in ("approved", "aesthetic_only")}
        message, changed = self.run_refresh()
        self.assertTrue(changed, message)
        queue = {author["key"]: author for author in repository.queued_creators(self.conn)}
        self.assertEqual(set(queue) - kept_before, {"uid-ダンサーあい", "uid-みゆ"})
        self.assertTrue(kept_before & set(queue))  # approved creators stay in the queue
        # The stale 10-day / 900-use template never counts.
        self.assertEqual(queue["uid-ダンサーあい"]["indexed_count"], 1)
        self.assertEqual(queue["uid-ダンサーあい"]["stale_low_use_excluded_count"], 1)
        scan = self.conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((scan["status"], scan["new_candidates"], scan["skipped_rejected"]), ("succeeded", 2, 1))

    def test_second_refresh_without_new_templates_keeps_queue(self):
        self.run_refresh()
        before = {author["key"] for author in repository.queued_creators(self.conn)}
        with self.assertRaisesRegex(RuntimeError, "首次索引"):
            self.run_refresh()
        self.assertEqual(before, {author["key"] for author in repository.queued_creators(self.conn)})

    def test_cancel_keeps_previous_queue(self):
        before = {author["key"] for author in repository.queued_creators(self.conn)}
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(discovery.RefreshCancelled):
            discovery.run_refresh(self.conn, 1200, replace_pending=True, cancel_event=cancel)
        self.assertEqual(before, {author["key"] for author in repository.queued_creators(self.conn)})

    def test_scoring_is_bounded(self):
        author = {"name": "x", "bio": "", "works": [
            {"title": "落書き 音ハメ ダンス", "desc": "", "uses": 50000, "clips": 2, "dance_signal": True}],
            "high_use_non_ai_indexed": 1, "dance_non_ai_indexed": 1, "japanese_post_count": 1}
        score = scoring.score_author(author, {"reference": scoring.read_reference_cases(),
                                              "profile": {"positive_terms": {}, "negative_terms": {}},
                                              "negatives": []})
        self.assertGreater(author["reference_match_score"], 0)
        self.assertAlmostEqual(score, author["reference_match_score"] * .7 + author["quality_data_score"] * .3)


class CategoryTest(unittest.TestCase):
    def test_duplicates_are_ignored(self):
        conn = fresh_db()
        self.addCleanup(conn.close)
        self.assertEqual(category.add_cases(conn, {"cases": [{"style": "旅行 vlog"}, {"style": "夏の海"}]}, "旅行"), 2)
        self.assertEqual(category.add_cases(conn, [{"style": "旅行 vlog"}]), 0)
        state = category.state(conn)
        self.assertEqual((state["category_name"], state["case_count"], state["revision"]), ("旅行", 2, 1))
        self.assertIn("旅行", state["positive_terms"])


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_db().close()
        cls.server = api.make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read() or b"{}"), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}"), error.headers

    def test_health_and_cors(self):
        origin = f"http://127.0.0.1:{config.FRONTEND_PORT}"
        status, body, headers = self.call("GET", "/api/health", headers={"Origin": origin})
        self.assertEqual((status, body["service"]), (200, "capcut-creator-review"))
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
        _, _, headers = self.call("GET", "/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(headers["Access-Control-Allow-Origin"])

    def test_review_flow(self):
        status, data, _ = self.call("GET", "/api/creators?view=pending")
        self.assertEqual(status, 200)
        key = data["items"][0]["key"]
        status, body, _ = self.call("POST", "/api/reviews", {"key": key, "status": "rejected"})
        self.assertEqual(status, 400)
        self.assertIn("不通过原因", body["error"])
        with mock.patch.object(learning, "learn_rejected_creator_video", return_value=False):
            status, _, _ = self.call("POST", "/api/reviews", {"key": key, "status": "rejected", "rejection_reason": "测试原因"})
        self.assertEqual(status, 200)
        _, data, _ = self.call("GET", "/api/creators?view=rejected")
        self.assertIn(key, [item["key"] for item in data["items"]])

    def test_errors(self):
        self.assertEqual(self.call("GET", "/api/missing")[0], 404)
        self.assertEqual(self.call("POST", "/api/refresh/cancel")[0], 409)
        status, body, _ = self.call("PUT", "/api/aesthetic/terms", {"positive_text": "bad line", "negative_text": ""})
        self.assertEqual(status, 400)
        self.assertIn("第 1 行", body["error"])


if __name__ == "__main__":
    unittest.main()
