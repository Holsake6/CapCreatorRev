"""Everything that talks to CapCut: web pages, the app feed API and share links.

Two data sources are used:

* ``www.capcut.com`` server-renders template detail pages and explore (keyword)
  pages with the data embedded as JSON. A detail page also carries CapCut's own
  "related templates" list, which is the graph we crawl.
* ``feed-api.capcutapi.com`` is the API behind the mobile creator homepage. It
  needs a public id that only appears after resolving a homepage share link
  (``mobile.capcutshare.com/sv2/...``).
"""

import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import net, paths, store

TEMPLATE_ID = re.compile(r"(?<!\d)(\d{18,20})(?!\d)")
DETAIL_URL_ID = re.compile(r"/template-detail/(?:[^\"<>\s?#]*/)?(\d{18,20})")
PROFILE_SHARE = re.compile(r"https?://mobile\.capcutshare\.com/sv2/[A-Za-z0-9]+/?")
CAPCUT_LINK = re.compile(r"https?://(?:www\.|m\.)?capcut\.(?:com|net)/[^\s\"'<>]+|https?://mobile\.capcutshare\.com/[^\s\"'<>]+")
API_HOST = "https://feed-api.capcutapi.com"
DETAIL_TTL = 12 * 3600


class _RouterData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__MODERN_ROUTER_DATA__":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def router_data(page):
    parser = _RouterData()
    parser.feed(page)
    return json.loads("".join(parser.parts))


def embedded_json_object(page, key):
    """Read a named JSON object embedded anywhere in server-rendered HTML."""
    marker = f'"{key}":'
    index = page.find(marker)
    start = page.find("{", index + len(marker)) if index >= 0 else -1
    if start < 0:
        return {}
    depth, in_string, escaped = 0, False, False
    for end in range(start, len(page)):
        char = page[end]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(page[start:end + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def detail_url(template_id, region="ja-jp"):
    return f"https://www.capcut.com/{region}/template-detail/{template_id}"


def explore_url(keyword, region="ja-jp", page=1):
    url = f"https://www.capcut.com/{region}/explore/{quote(keyword, safe='')}"
    return url if page == 1 else f"{url}?page={page}"


def parse_detail_page(page):
    router = router_data(page)
    loader = router.get("loaderData") or {}
    data = loader.get("template-detail_$") or next(
        (value for key, value in loader.items() if key.startswith("template-detail") and isinstance(value, dict)), {})
    if not data.get("templateDetail"):
        raise ValueError("页面里没有 templateDetail 数据")
    return {"detail": data["templateDetail"], "recommendations": data.get("recommendList") or []}


def template_page(template_id, force=False, region="ja-jp", fetch=None):
    """Detail + related templates, cached for 12 hours. Falls back to stale cache offline."""
    fetch = fetch or net.fetch_text
    cache = paths.template_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{template_id}.json"
    if not force and path.exists() and time.time() - path.stat().st_mtime < DETAIL_TTL:
        cached = store.read_json(path, None)
        if cached:
            return cached
    try:
        _, page = fetch(detail_url(template_id, region), timeout=20)
        result = parse_detail_page(page)
        store.write_json(path, result)
        return result
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        cached = store.read_json(path, None)
        if cached:
            return cached
        return {"error": str(exc), "detail": None, "recommendations": []}


def landing_template_ids(url, fetch=None):
    fetch = fetch or net.fetch_text
    _, page = fetch(url, timeout=25)
    payload = embedded_json_object(page, "videoTemplateListResolved")
    templates = (payload.get("data") or {}).get("videoTemplates") or []
    ids = [str(item.get("templateId")) for item in templates if item.get("templateId")]
    if not ids:
        ids = DETAIL_URL_ID.findall(page.replace("\\u002F", "/"))
    return list(dict.fromkeys(ids))


def cached_pages():
    """Iterate every cached detail page (used to grow seeds and backfill fields)."""
    for path in paths.template_cache_dir().glob("*.json"):
        cached = store.read_json(path, None)
        if cached:
            yield cached


def page_items(page):
    return [item for item in [page.get("detail"), *(page.get("recommendations") or [])] if item]


def item_id(item):
    return str(item.get("templateId") or item.get("id") or item.get("template_id") or "")


# ---------------------------------------------------------------- feed API

def api_post(path, payload, fetch=None):
    timestamp = int(time.time())
    signature = hashlib.md5(f"9e2c|{path[-7:]}|0||{timestamp}||11ac".encode()).hexdigest()
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone)", "Content-Type": "application/json",
        "appvr": "", "device-time": str(timestamp), "loc": "BR", "pf": "0",
        "sign": signature, "sign-ver": "1", "app-sdk-version": "1000.0.0",
    }
    request = fetch or net.request
    _, body, _ = request(API_HOST + path, data=json.dumps(payload).encode(), headers=headers, timeout=20)
    result = json.loads(body)
    if str(result.get("ret")) != "0":
        raise ValueError(result.get("errmsg") or f"CapCut API 返回 {result.get('ret')}")
    return result["data"]


def resolve_share_link(link):
    """Follow a share short link; return the final URL."""
    final_url, _, _ = net.request(link, headers={"User-Agent": net.MOBILE_UA}, timeout=15, max_bytes=4 << 20)
    return final_url


def profile_public_id(link):
    parsed = urlparse(link.strip())
    if parsed.scheme not in ("https", "http") or parsed.hostname != "mobile.capcutshare.com":
        raise ValueError("请粘贴 CapCut 主页分享链接（mobile.capcutshare.com/...）")
    if parsed.path.startswith("/sv2/"):
        parsed = urlparse(resolve_share_link(link.strip()))
    if parsed.hostname != "mobile.capcutshare.com" or parsed.path != "/imlv/personal-homepage":
        raise ValueError("这不是 CapCut 作者主页链接")
    public_id = parse_qs(parsed.query).get("publicid", [""])[0]
    if not public_id:
        raise ValueError("主页链接里没有作者标识")
    return public_id


def resolve_profile_link(link):
    public_id = profile_public_id(link)
    profile = api_post("/lv/v1/homepage/profile", {"public_id": public_id})
    user = profile.get("user") or {}
    stats = profile.get("user_statistics") or {}
    if not user.get("unique_id"):
        raise ValueError("CapCut 未返回 CC ID")
    tt = user.get("tiktok_user_info") or {}
    return {"name": user.get("name", ""), "cc_id": str(user["unique_id"]),
            "system_uid": str(user.get("uid") or ""), "public_id": public_id,
            "bio": user.get("description", ""),
            "total_posts": stats.get("template_count"),
            "tt_link": tt.get("link") or tt.get("url") or ""}


def creator_templates(public_id, max_pages=5, page_size=100):
    """A creator's own template list from the homepage API, normalised to web field names."""
    cursor, seen, items = "0", set(), []
    for _ in range(max_pages):
        data = api_post("/lv/v1/homepage/templates", {
            "cursor": cursor, "count": page_size, "uid": 1,
            "public_id": public_id, "sdk_version": "100.0.0",
        })
        for raw in data.get("templates") or []:
            template_id = str(raw.get("id") or "")
            if not template_id or template_id in seen:
                continue
            seen.add(template_id)
            author = raw.get("author") or {}
            video = raw.get("video_info") or {}
            cover = raw.get("cover") or {}
            items.append({
                "templateId": template_id,
                "title": raw.get("short_title") or raw.get("title") or "",
                "desc": raw.get("title") or "",
                "usageAmount": raw.get("usage_amount") or 0,
                "createTime": raw.get("create_time") or 0,
                "segmentAmount": raw.get("fragment_count"),
                "coverUrl": cover.get("url") if isinstance(cover, dict) else (raw.get("cover_url") or ""),
                "videoUrl": video.get("url") if isinstance(video, dict) else (raw.get("video_url") or ""),
                "author": {"name": author.get("name", ""), "description": author.get("description", "")},
            })
        if not data.get("has_more") or not data.get("new_cursor"):
            break
        cursor = data["new_cursor"]
    return items


def template_ids_from_text(text, resolve=True):
    """Extract template ids from pasted links / ids. Short links are resolved over the network."""
    ids, unresolved = [], []
    for link in CAPCUT_LINK.findall(text or ""):
        match = DETAIL_URL_ID.search(link) or re.search(r"template[_-]?id=(\d{18,20})", link)
        if match:
            ids.append(match.group(1))
        elif resolve:
            try:
                final = resolve_share_link(link)
                match = DETAIL_URL_ID.search(final) or re.search(r"template[_-]?id=(\d{18,20})", final) \
                    or TEMPLATE_ID.search(final)
                (ids if match else unresolved).append(match.group(1) if match else link)
            except (OSError, ValueError):
                unresolved.append(link)
        else:
            unresolved.append(link)
    stripped = CAPCUT_LINK.sub(" ", text or "")
    ids.extend(TEMPLATE_ID.findall(stripped))
    return list(dict.fromkeys(ids)), unresolved


def cached_video_path(template_id):
    return paths.media_dir() / "capcut" / f"{template_id}.mp4"


def download_preview(template_id, video_url, max_bytes=80 * 1024 * 1024):
    """Download a template preview video once; returns the local path."""
    target = cached_video_path(template_id)
    if target.exists() and target.stat().st_size > 0:
        return target
    if not video_url:
        raise ValueError("模板没有预览视频地址")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(target) + ".part")
    try:
        net.download(video_url, temp, max_bytes=max_bytes)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target
