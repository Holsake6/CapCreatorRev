"""Regressions for what live testing against CapCut turned up (network mocked here)."""

import pytest

from capcreator import capcut, explore, net


def test_sitemap_keywords_and_matching():
    assert explore.keyword_of("旅行vlogテンプレート/7512714204488976385") == "旅行vlogテンプレート"
    assert explore.keyword_of("TikTok-旅行-テンプレート/7512807349184497665") == "TikTok 旅行 テンプレート"
    assert explore.keyword_of("7512723713641515009") == ""
    pages = {"ペット動画/1": "ペット動画", "犬 ペット/2": "犬 ペット", "fyp/3": "fyp", "ダンス/4": "ダンス"}
    keywords = [s["keyword"] for s in explore.suggest(pages, ["ペット", "犬", "#fyp", "fyp"])]
    assert keywords[0] == "犬 ペット" and "fyp" not in keywords and "ダンス" not in keywords


def test_category_words_ignore_hashtags_and_file_numbers():
    words = explore.category_words({"keywords": ["ペット"]}, [
        {"label": "positive", "title": "00_dancing dog", "desc": "#fyp #meme"},
        {"label": "negative", "title": "ダンス"}])
    assert "ペット" in words and "dog" in words
    assert not {"fyp", "meme", "00", "ダンス"} & set(words)


def test_homepage_api_items_use_top_level_urls(monkeypatch):
    payload = {"templates": [{"id": 7700703243705306386, "title": "#ネタ", "short_title": "てめえ",
                              "usage_amount": 12, "create_time": 1792959958, "fragment_count": 1,
                              "cover_url": "https://img/c.jpg", "video_url": "https://vid/v.mp4",
                              "author": {"name": "melody"}}], "has_more": False}
    monkeypatch.setattr(capcut, "api_post", lambda path, body, fetch=None: payload)
    item = capcut.creator_templates("pid")[0]
    assert item["videoUrl"] == "https://vid/v.mp4" and item["coverUrl"] == "https://img/c.jpg"
    assert item["templateId"] == "7700703243705306386" and item["title"] == "てめえ"


def test_expired_signed_url_is_refreshed_once(monkeypatch, tmp_path):
    calls = []

    def download(url, target, **kwargs):
        calls.append(url)
        if url == "https://old":
            raise net.NetError("http", url, "HTTP 403")
        open(target, "wb").write(b"video")
        return url, {}
    monkeypatch.setattr(net, "download", download)
    monkeypatch.setattr(capcut, "fresh_media_urls", lambda tid, region="ja-jp", force=False: ("https://new", ""))
    path = capcut.download_preview("7000000000000000001", "https://old")
    assert path.read_bytes() == b"video" and calls == ["https://old", "https://new"]


def test_dns_failure_is_not_retried_with_fresh_url(monkeypatch):
    monkeypatch.setattr(net, "download", lambda url, target, **k: (_ for _ in ()).throw(net.NetError("dns", url, "x")))
    monkeypatch.setattr(capcut, "fresh_media_urls", lambda *a, **k: pytest.fail("must not refetch offline"))
    with pytest.raises(net.NetError):
        capcut.download_preview("7000000000000000002", "https://old")
