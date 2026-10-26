import json
import shutil
import threading
import urllib.request
import zipfile

import pytest

from capcreator import capcut, category as categories, ingest, learn, paths, server


def test_netdisk_url_helpers():
    assert ingest.google_drive_id("https://drive.google.com/drive/folders/1AbC_d-9?usp=sharing") == ("folder", "1AbC_d-9")
    assert ingest.google_drive_id("https://drive.google.com/file/d/XYZ123/view") == ("file", "XYZ123")
    assert ingest.google_drive_id("https://example.com/a") == (None, None)
    assert ingest.dropbox_direct("https://www.dropbox.com/scl/fo/abc/xyz?rlkey=k&dl=0").endswith("rlkey=k&dl=1")
    assert ingest.dropbox_direct("https://www.dropbox.com/s/abc/a.mp4").endswith("?dl=1")


def build_zip(tmp_path, videos):
    archive = tmp_path / "client.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(videos["fast0"], "旅行vlog/a.mp4")
        zf.write(videos["fast1"], "旅行vlog/反例/b.mp4")
        zf.write(videos["slow0"], "夜景/c.mp4")
        zf.writestr("__MACOSX/旅行vlog/._a.mp4", b"junk")
        zf.writestr("../evil.mp4", b"zip slip")
    return archive


def test_zip_by_folder_creates_categories_and_negatives(tmp_path, videos):
    counts = ingest.ingest(str(build_zip(tmp_path, videos)), "dance", by_folder=True, log=None)
    by_name = {c.config["name"]: c for c in categories.list_categories()}
    assert set(by_name) >= {"旅行vlog", "夜景"}
    travel = by_name["旅行vlog"].examples()
    assert sorted(e["label"] for e in travel) == ["negative", "positive"]
    assert sum(counts.values()) == 3
    assert not (tmp_path / "evil.mp4").exists()
    stored = paths.media_dir() / travel[0]["file"]
    assert stored.exists() and travel[0]["key"].startswith("f")


def test_text_file_of_capcut_links(tmp_path, monkeypatch):
    seen = []

    def page(tid, force=False, region="ja-jp", fetch=None):
        seen.append(tid)
        return {"detail": {"templateId": tid, "title": "サンプル", "videoUrl": "", "author": {"name": "x"}},
                "recommendations": []}
    monkeypatch.setattr(capcut, "template_page", page)
    folder = tmp_path / "links"
    folder.mkdir()
    (folder / "links.txt").write_text("https://www.capcut.com/template-detail/7402910946471071032\n7650611251730550017\n")
    counts = ingest.ingest(str(folder), "linked", log=None)
    assert counts == {"linked": 2} and seen == ["7402910946471071032", "7650611251730550017"]
    examples = categories.get("linked").examples()
    assert {e["template_id"] for e in examples} == set(seen) and examples[0]["kind"] == "capcut"


def test_migrates_v2_layout(data_dir):
    repo_data = paths.ROOT / "capcut_local_data" / "categories" / "dance"
    for name in ("candidates.json", "decisions.json", "preference_profile.json", "seen_creators.json",
                 "reference_positive_cases.json"):
        shutil.copy(repo_data / name, data_dir / name)
    moved = categories.ensure_default()
    assert "candidates.json" in moved and "config.json" in moved
    dance = categories.get("dance")
    assert dance.config["visual_gate"] == "people_motion" and dance.config["reference_cases"]
    data = learn.rescore(dance, dance.candidates())
    first = data["candidates"][0]
    assert first["name"] == "メロディ/melody" and first["score"] == 45.3  # identical to the v2 ranking
    assert categories.ensure_default() == []  # idempotent


def test_newer_v2_files_win_over_repo_copy(data_dir):
    """A Mac that kept scanning with v2 copies its files back after pulling v3."""
    repo_data = paths.ROOT / "capcut_local_data" / "categories" / "dance"
    shutil.copytree(repo_data, data_dir / "categories" / "dance")
    newer = json.loads((repo_data / "decisions.json").read_text(encoding="utf-8"))
    newer["new-creator"] = {"key": "new-creator", "status": "rejected", "rejection_reason": "x"}
    (data_dir / "decisions.json").write_text(json.dumps(newer), encoding="utf-8")
    shutil.copy(repo_data / "candidates.json", data_dir / "candidates.json")
    categories.ensure_default()
    assert "new-creator" in categories.get("dance").decisions()
    assert list((data_dir / "categories" / "dance").glob("before-v3-migration-*/decisions.json"))
    # an older leftover never overwrites newer v3 state
    (data_dir / "decisions.json").write_text("{}", encoding="utf-8")
    (data_dir / "candidates.json").write_text('{"generated_at": "2000-01-01"}', encoding="utf-8")
    categories.ensure_default()
    assert "new-creator" in categories.get("dance").decisions()
    assert not (data_dir / "decisions.json").exists()


@pytest.fixture
def live(data_dir):
    categories.create("Test", slug="test", keywords=["ダンス"], language="any")
    cat = categories.get("test")
    cat.save_candidates({"candidates": [{"name": "ゆい", "sec_uid": "k1", "bio": "", "works": [
        {"template_id": "7000000000000000001", "title": "ダンス", "uses": 5000, "video_url": "https://v/1.mp4",
         "category_signal": True}]}]})
    httpd = server.make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, method=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=headers or ({"Content-Type": "application/json"} if body is not None else {}))
    try:
        with urllib.request.urlopen(req) as response:
            text = response.read()
            return response.status, (json.loads(text) if "json" in response.headers.get("Content-Type", "") else text)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_api_review_flow(live):
    status, cats = call(live, "/api/categories")
    assert status == 200 and cats["categories"][0]["slug"] == "test"
    status, page = call(live, "/c/test")
    assert status == 200 and b"<html" in page
    status, rows = call(live, "/api/c/test/candidates?view=pending")
    assert [r["name"] for r in rows["rows"]] == ["ゆい"]
    status, err = call(live, "/api/c/test/decision", {"key": "k1", "status": "rejected"})
    assert status == 400 and "不通过原因" in err["error"]
    status, _ = call(live, "/api/c/test/decision", {"key": "k1", "status": "approved", "non_ai_confirmed": True,
                                                    "category_confirmed": True, "cc_id": "yui", "specialty": "群舞",
                                                    "aesthetic_notes": "卡点很准"})
    assert status == 200
    status, csv = call(live, "/api/c/test/export.csv")
    assert "yui" in csv.decode("utf-8-sig") and "群舞；卡点很准" in csv.decode("utf-8-sig")
    assert categories.get("test").text_profile()["positive_terms"]
    status, err = call(live, "/api/c/nope/candidates")
    assert status == 404


def test_api_upload_and_train(live, videos):
    import time
    boundary = "----capcreator"
    payload = videos["fast0"].read_bytes()
    raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"label\"\r\n\r\npositive\r\n"
           f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"ex.mp4\"\r\n"
           f"Content-Type: video/mp4\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    status, job = call(live, "/api/c/test/examples/upload", raw=raw,
                       headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert status == 200
    for _ in range(60):
        status, state = call(live, f"/api/jobs/{job['job']}")
        if state["status"] != "running":
            break
        time.sleep(0.5)
    assert state["status"] == "done", state
    status, ex = call(live, "/api/c/test/examples")
    assert ex["examples"][0]["title"] == "ex" and ex["examples"][0]["analysed"]
    status, media = call(live, ex["examples"][0]["media"])
    assert status == 200 and media[:8] == payload[:8]
    status, grid = call(live, "/api/c/test/train/next?size=2")
    assert status == 200 and [i["key"] for i in grid["items"]] == ["t7000000000000000001"]
    status, fb = call(live, "/api/c/test/train/feedback", {"shown": ["t7000000000000000001"], "picked": []})
    assert status == 200 and fb["rounds"] == 1
    assert categories.get("test").labels()["points"][0]["label"] == 0
    status, _ = call(live, "/media/../../etc/passwd")
    assert status == 404
