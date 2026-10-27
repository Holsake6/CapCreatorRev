"""Index of CapCut explore (keyword) pages that really exist.

Only some keywords have an explore page (``/ja-jp/explore/変身`` works,
``/ja-jp/explore/旅行`` is a 404) and CapCut's real search needs anti-bot
tokens. CapCut's public sitemap, however, lists every keyword explore page
(``kep-ja``: ~90,000 pages for Japan) with the keyword in the URL. A category
picks crawl entry points by matching its keywords and example titles against
that list, so a category built only from uploaded mp4 files still finds the
right corner of CapCut.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

from . import capcut, net, paths, store, textlearn

TTL = 7 * 24 * 3600
SITEMAP_INDEX = "https://www.capcut.com/sitemap/new/348188/kep-all/sitemap_index.xml"
LOC = re.compile(r"<loc>([^<]+)</loc>")
# Generic words that appear in thousands of page names and say nothing about the topic.
GENERIC = {"テンプレート", "テンプレ", "template", "templates", "capcut", "動画", "video", "編集", "無料", "tiktok",
           # social-media hashtags that say nothing about the topic
           "fyp", "foryou", "foryoupage", "fy", "trend", "trending", "viral", "goviral", "go viral", "meme",
           "おすすめ", "おすすめにのりたい", "バズれ", "バズりたい", "流行り", "人気", "capcutテンプレート"}


def index_path(region):
    return paths.data_root() / f"explore_index_{region}.json"


def keyword_of(path):
    """``旅行vlogテンプレート/7512714204488976385`` -> ``旅行vlogテンプレート``."""
    slug = path.split("/")[0]
    return "" if slug.isdigit() else slug.replace("-", " ").strip()


def build(region="ja-jp", log=None):
    """Download the region's keyword sitemaps. Returns ``{path: keyword}``."""
    lang = region.split("-")[0]
    _, index = net.fetch_text(SITEMAP_INDEX, timeout=30)
    sitemaps = [loc for loc in LOC.findall(index) if f"/kep-{lang}/" in loc]
    pages = {}

    def fetch(url):
        try:
            return LOC.findall(net.fetch_text(url, timeout=40)[1])
        except OSError:
            return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for urls in pool.map(fetch, sitemaps):
            for url in urls:
                url = unquote(url)
                if f"/{region}/explore/" not in url:
                    continue
                path = url.split("/explore/", 1)[1]
                keyword = keyword_of(path)
                if keyword:
                    pages[path] = keyword
    if log:
        log(f"CapCut 专题页索引：{len(pages)} 个（{region}）")
    if pages:
        store.write_json(index_path(region), {"built_at": time.time(), "region": region, "pages": pages})
    return pages


def load(region="ja-jp", build_if_missing=True, log=None):
    cached = store.read_json(index_path(region), {})
    if cached.get("pages") and time.time() - float(cached.get("built_at", 0)) < TTL:
        return cached["pages"]
    if not build_if_missing:
        return cached.get("pages", {})
    try:
        return build(region, log=log) or cached.get("pages", {})
    except OSError:
        return cached.get("pages", {})


def _terms(words):
    out = []
    for word in words:
        word = (word or "").casefold().replace("-", " ").strip()
        if len(word) >= 2 and word not in GENERIC:
            out.append(word)
    return list(dict.fromkeys(out))


def suggest(pages, words, limit=15):
    """Explore pages whose keyword contains the category's words, best first.

    A page matching several words beats one matching a single word; among
    equals, shorter (more specific) keywords win.
    """
    terms = _terms(words)
    if not terms:
        return []
    scored = []
    for path, keyword in pages.items():
        lowered = keyword.casefold()
        hits = [t for t in terms if t in lowered]
        if not hits:
            continue
        exact = any(lowered == t for t in terms)
        score = len(hits) * 2 + (3 if exact else 0) + sum(len(t) for t in hits) / max(4, len(lowered))
        scored.append((score, -len(lowered), path, keyword))
    scored.sort(reverse=True)
    return [{"path": path, "keyword": keyword, "score": round(score, 2),
             "url": f"https://www.capcut.com/ja-jp/explore/{path}"} for score, _, path, keyword in scored[:limit]]


def category_words(config, examples):
    words = list(config.get("keywords", []))
    for example in examples:
        # Titles only: CapCut descriptions are mostly hashtags (#fyp #trend) that match junk pages.
        if example.get("label", "positive") == "positive":
            title = re.sub(r"[_\-.]+", " ", example.get("title", ""))  # "00_dancing dog" -> "00 dancing dog"
            words += [w for w in textlearn.learned_terms(title) if not w.isdigit()]
    return words


def check_keywords(keywords, region="ja-jp"):
    """Which configured keywords have their own explore page (``{keyword: template_count}``)."""
    result = {}
    for keyword in keywords:
        try:
            result[keyword] = len(capcut.landing_template_ids(capcut.explore_url(keyword, region)))
        except OSError:
            result[keyword] = 0
    return result


def template_counts(urls, region="ja-jp"):
    """Templates on each explore page (cached a week; a page with few templates is a poor entry point)."""
    cache_file = paths.data_root() / f"explore_counts_{region}.json"
    cache = store.read_json(cache_file, {})
    now = time.time()
    todo = [u for u in urls if u not in cache or now - cache[u][1] > TTL]

    def count(url):
        try:
            return url, len(capcut.landing_template_ids(url))
        except OSError:
            return url, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, n in pool.map(count, todo):
            cache[url] = [n, now]
    if todo:
        store.write_json(cache_file, cache)
    return {u: cache[u][0] for u in urls}


def entry_points(config, examples, want=12, min_templates=6, log=None):
    """Verified explore pages for a category: matching keyword + enough templates."""
    pages = load(config.get("region", "ja-jp"), log=log)
    candidates = suggest(pages, category_words(config, examples), limit=want * 3)
    counts = template_counts([c["url"] for c in candidates], config.get("region", "ja-jp"))
    good = [dict(c, templates=counts[c["url"]]) for c in candidates if counts[c["url"]] >= min_templates]
    return good[:want]
