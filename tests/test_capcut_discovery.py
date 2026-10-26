import json
import time

import pytest

from capcreator import capcut, category as categories, discovery, learn, net


def item(tid, author, title="ダンス 踊ってみた", uses=50000, days=30, ai=False, sec=None, desc="#ダンス",
         bio="よろしくお願いします"):
    return {"templateId": tid, "title": ("AI生成 " if ai else "") + title, "desc": desc,
            "usageAmount": uses, "createTime": int(time.time() - days * 86400), "segmentAmount": 2,
            "coverUrl": f"https://img/{tid}.jpg", "videoUrl": f"https://vid/{tid}.mp4",
            "author": {"name": author, "description": bio, "secUid": sec or f"sec-{author}"}}


def detail_html(detail, recs):
    router = {"loaderData": {"template-detail_$": {"templateDetail": detail, "recommendList": recs}}}
    return f'<html><script id="__MODERN_ROUTER_DATA__">{json.dumps(router)}</script></html>'


def test_parse_detail_page_and_embedded_json():
    page = detail_html(item("7000000000000000001", "a"), [item("7000000000000000002", "b")])
    parsed = capcut.parse_detail_page(page)
    assert parsed["detail"]["templateId"] == "7000000000000000001"
    assert len(parsed["recommendations"]) == 1
    html = 'x "videoTemplateListResolved": {"data": {"videoTemplates": [{"templateId": "7000000000000000009", "t": "}{"}]}} y'
    assert capcut.landing_template_ids.__name__
    assert capcut.embedded_json_object(html, "videoTemplateListResolved")["data"]["videoTemplates"][0]["t"] == "}{"


def test_landing_ids_with_fallback(monkeypatch):
    fake = lambda url, timeout=0: (url, '<a href="/ja-jp/template-detail/x/7111111111111111111">a</a>')
    assert capcut.landing_template_ids("https://x", fetch=fake) == ["7111111111111111111"]


def test_template_ids_from_text_without_network():
    text = ("https://www.capcut.com/ja-jp/template-detail/%E3%83%80/7402910946471071032\n"
            "7650611251730550017\nhttps://www.capcut.com/t/Zs8abc/")
    ids, unresolved = capcut.template_ids_from_text(text, resolve=False)
    assert ids == ["7402910946471071032", "7650611251730550017"]
    assert unresolved == ["https://www.capcut.com/t/Zs8abc/"]


def test_api_post_signs_and_checks_ret(monkeypatch):
    seen = {}

    def fake(url, data=None, headers=None, timeout=0):
        seen.update(url=url, headers=headers, body=json.loads(data))
        return url, json.dumps({"ret": "0", "data": {"ok": 1}}).encode(), {}
    assert capcut.api_post("/lv/v1/homepage/profile", {"public_id": "p"}, fetch=fake) == {"ok": 1}
    assert len(seen["headers"]["sign"]) == 32 and seen["url"].endswith("/homepage/profile")
    bad = lambda *a, **k: ("u", json.dumps({"ret": "1001", "errmsg": "nope"}).encode(), {})
    with pytest.raises(ValueError, match="nope"):
        capcut.api_post("/x", {}, fetch=bad)


def test_net_error_classification():
    import socket
    from urllib.error import URLError
    assert net.classify(URLError(socket.gaierror(-2, "Name or service not known")), "https://a.b").kind == "dns"
    assert net.classify(OSError("Tunnel connection failed: 403 Forbidden"), "https://a.b").kind == "proxy_blocked"
    assert net.classify(URLError("CERTIFICATE_VERIFY_FAILED"), "https://a.b").kind == "ssl"
    assert "Allowed domains" in net.NetError("proxy_blocked", "https://a.b").advice()


@pytest.fixture
def fake_capcut(monkeypatch):
    """A tiny template graph: seed -> related templates from several creators."""
    graph = {
        "7000000000000000001": (item("7000000000000000001", "ゆい"), [
            item("7000000000000000002", "ゆい", uses=8000),
            item("7000000000000000003", "AIさん", ai=True),
            item("7000000000000000004", "english guy", title="dance edit", desc="#dance", bio="hello"),
            item("7000000000000000005", "ふるい", uses=200, days=30),     # stale, low use
            item("7000000000000000006", "ねこ", title="かわいい写真まとめ", desc="#写真"),  # off-category
            item("7000000000000000007", "みお", uses=4000, days=3),
        ]),
    }
    for tid, (detail, recs) in list(graph.items()):
        for rec in recs:
            graph.setdefault(rec["templateId"], (rec, []))

    def page(tid, force=False, region="ja-jp", fetch=None):
        detail, recs = graph.get(tid, (None, []))
        return {"detail": detail, "recommendations": recs} if detail else {"error": "404", "detail": None, "recommendations": []}
    monkeypatch.setattr(capcut, "template_page", page)
    monkeypatch.setattr(capcut, "landing_template_ids", lambda url, fetch=None: ["7000000000000000001"])
    monkeypatch.setattr(discovery, "current_jp_tiktok_songs", lambda cat, force=False: [])
    return graph


def test_discover_applies_hard_rules(fake_capcut):
    cat = categories.create("舞蹈测试", slug="dance-test", **{k: v for k, v in categories.DANCE_CONFIG.items()
                                                              if k not in ("name", "slug")})
    cat.update_config(analyze_top=0, keywords=["ダンス"], landing_urls=[])
    result = discovery.discover(cat, max_pages=20, log=lambda *_: None)
    names = {a["name"] for a in result["candidates"]}
    assert names == {"ゆい", "みお"}, names  # AI, non-Japanese, stale-only and off-category creators dropped
    yui = next(a for a in result["candidates"] if a["name"] == "ゆい")
    assert yui["high_use_non_ai_indexed"] == 2 and yui["japanese_signal"] == "投稿文案"


def test_refresh_merges_and_never_repeats_creators(fake_capcut):
    cat = categories.create("generic", slug="generic-test", keywords=["ダンス"])
    cat.update_config(analyze_top=0)
    data, message, changed = discovery.refresh(cat, max_pages=20, log=lambda *_: None)
    assert changed and data["latest_batch_candidates"] == 2 and "本次补充 2 位" in message
    data, _, _ = discovery.refresh(cat, max_pages=20, log=lambda *_: None)
    assert data["latest_batch_candidates"] == 0 and len(data["candidates"]) == 2


def test_merge_keeps_60_40_split():
    cat = categories.create("merge", slug="merge-test")
    new = {"generated_at": "2026-01-01", "candidates": [{"name": f"a{i}", "sec_uid": f"s{i}"} for i in range(80)]}
    merged = discovery.merge_results(cat, {"candidates": []}, new)
    assert merged["latest_ranked_candidates"] == 30 and merged["latest_random_candidates"] == 20
    assert [a["sec_uid"] for a in merged["candidates"][:30]] == [f"s{i}" for i in range(30)]


def test_stale_rule_reapplied_to_saved_work():
    cat = categories.create("stale", slug="stale-test")
    old = int(time.time() - 10 * 86400)
    data = {"candidates": [{"name": "x", "sec_uid": "x", "works": [
        {"template_id": "1", "uses": 10, "created_at_epoch": old, "category_signal": True},
        {"template_id": "2", "uses": 5000, "created_at_epoch": old, "category_signal": True}]}]}
    removed_authors, removed_templates = discovery.apply_stale_rule(cat, data)
    assert removed_templates == 1 and [w["template_id"] for w in data["candidates"][0]["works"]] == ["2"]
    assert data["candidates"][0]["high_use_non_ai_indexed"] == 1


def test_v2_field_names_are_normalised():
    data = {"candidates": [{"dance_non_ai_indexed": 3, "explicit_dance_indexed": 2,
                            "works": [{"dance_signal": True, "dance_seed": False, "non_dance_gimmick": False}]}]}
    learn.normalize_candidates(data)
    author = data["candidates"][0]
    assert author["category_non_ai_indexed"] == 3 and author["works"][0]["category_signal"] is True
