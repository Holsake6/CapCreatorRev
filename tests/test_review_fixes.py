"""Regressions for the issues found in the v3 code review."""

import json
import shutil
import threading
import time
import urllib.request
import zipfile

from capcreator import capcut, category as categories, discovery, ingest, paths, server


def fake_page(monkeypatch):
    def page(tid, force=False, region="ja-jp", fetch=None):
        return {"detail": {"templateId": tid, "title": "t", "videoUrl": "", "author": {"name": "x"}},
                "recommendations": []}
    monkeypatch.setattr(capcut, "template_page", page)


def test_negative_label_applies_to_link_imports(monkeypatch):
    fake_page(monkeypatch)
    categories.create("neg", slug="neg")
    ingest.ingest("https://www.capcut.com/ja-jp/template-detail/7402910946471071032", "neg", label="negative")
    assert [e["label"] for e in categories.get("neg").examples()] == ["negative"]


def test_long_pasted_id_list_is_not_treated_as_a_path(monkeypatch):
    fake_page(monkeypatch)
    categories.create("ids", slug="ids")
    text = " ".join(f"74029109464710710{i:02d}" for i in range(20))
    assert ingest.ingest(text, "ids") == {"ids": 20}


def test_folder_names_resolve_without_collisions(tmp_path, videos):
    categories.create("舞蹈", slug="dance")
    archive = tmp_path / "finder.zip"
    with zipfile.ZipFile(archive, "w") as zf:  # Finder wraps everything in one top folder
        zf.write(videos["fast0"], "客户素材/旅行vlog/a.mp4")
        zf.write(videos["fast1"], "客户素材/美食vlog/b.mp4")
        zf.write(videos["fast2"], "客户素材/Dance/c.mp4")
    counts = ingest.ingest(str(archive), "dance", by_folder=True)
    names = {c.config["name"]: c.slug for c in categories.list_categories()}
    assert "客户素材" not in names
    assert names["旅行vlog"] != names["美食vlog"]
    assert counts.get("dance") == 1  # "Dance" folder -> existing dance category
    assert sum(counts.values()) == 3


def test_single_category_zip_keeps_its_folder_name(tmp_path, videos):
    archive = tmp_path / "one.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(videos["fast0"], "旅行vlog/a.mp4")
        zf.write(videos["fast1"], "旅行vlog/反例/b.mp4")
    ingest.ingest(str(archive), "dance", by_folder=True)
    travel = next(c for c in categories.list_categories() if c.config["name"] == "旅行vlog")
    assert sorted(e["label"] for e in travel.examples()) == ["negative", "positive"]


def test_cp932_zip_names_are_not_read_as_gbk():
    assert ingest.decode_member_name("ダンス/反例".encode("cp932")) == "ダンス/反例"
    assert ingest.decode_member_name("舞蹈/反例".encode("gbk")) == "舞蹈/反例"


def test_migration_keeps_newer_v3_decision(data_dir):
    repo = paths.ROOT / "capcut_local_data" / "categories" / "dance"
    shutil.copytree(repo, data_dir / "categories" / "dance")
    dance = categories.get("dance")
    decisions = dance.decisions()
    decisions["NEW_V3"] = {"key": "NEW_V3", "status": "approved", "updated_at": "2026-11-01 10:00:00"}
    dance.save_decisions(decisions)
    (data_dir / "decisions.json").write_text(json.dumps({"A": {"status": "rejected"}}), encoding="utf-8")
    shutil.copy(repo / "candidates.json", data_dir / "candidates.json")
    categories.ensure_default()
    merged = categories.get("dance").decisions()
    assert "NEW_V3" in merged and "A" in merged and len(merged) == len(decisions) + 1


def test_scan_does_not_overwrite_changes_made_meanwhile(monkeypatch):
    cat = categories.create("race", slug="race")
    cat.save_candidates({"candidates": [{"name": "old", "sec_uid": "old", "works": [
        {"template_id": "1", "uses": 5000, "category_signal": True}]}]})

    def slow_discover(category, max_pages=None, log=None):
        data = category.candidates()  # someone deep-checks while the scan runs
        data["candidates"][0]["homepage_checked_at"] = "now"
        category.save_candidates(data)
        return {"generated_at": "2026-01-01 00:00:00", "indexed_templates": 1, "candidates": []}
    monkeypatch.setattr(discovery, "discover", slow_discover)
    data, _, _ = discovery.refresh(cat, max_pages=20, log=lambda *_: None)
    assert data["candidates"][0].get("homepage_checked_at") == "now"


def test_server_errors_and_ranges(data_dir):
    categories.create("srv", slug="srv")
    media = paths.media_dir() / "uploads"
    media.mkdir(parents=True)
    (media / "v.mp4").write_bytes(bytes(range(200)))
    httpd = server.make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path, headers=None, data=None):
        req = urllib.request.Request(base + path, headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
    try:
        status, body = get("/media/uploads/v.mp4", {"Range": "bytes=-10"})
        assert status == 206 and body == bytes(range(190, 200))
        assert get("/media/uploads/v.mp4", {"Range": "bytes=500-"})[0] == 416
        status, body = get("/api/c/srv/config", {"Content-Type": "application/json"}, b"[1,2]")
        assert status == 400 and "JSON" in json.loads(body)["error"]
        status, body = get("/api/c/srv/config", {"Content-Type": "application/json"}, b'{"max_pending": null}')
        assert status == 400
        status, body = get("/api/c/srv/config", {"Content-Type": "application/json"}, b'{"include_regex": "("}')
        assert status == 400
        payload = json.dumps({"source": "7402910946471071032"}).encode()
        first = json.loads(get("/api/c/srv/examples/import", {"Content-Type": "application/json"}, payload)[1])
        second = json.loads(get("/api/c/srv/examples/import", {"Content-Type": "application/json"}, payload)[1])
        assert first["job"] != second["job"]
        time.sleep(0.5)
    finally:
        httpd.shutdown()
