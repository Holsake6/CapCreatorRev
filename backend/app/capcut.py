"""Network access: CapCut pages, the CapCut feed API and the Oricon chart.

Functions here only fetch and parse; they never touch the database, so they
can run safely inside thread pools.
"""

import hashlib
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlparse, urlunparse
from urllib.request import Request, urlopen

from . import config


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


class _Headings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.current = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.depth = 1
            self.current = []
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag):
        if not self.depth:
            return
        self.depth -= 1
        if tag == "h2" and self.depth == 0:
            text = re.sub(r"\s+", " ", "".join(self.current)).strip()
            if text:
                self.headings.append(text)

    def handle_data(self, data):
        if self.depth:
            self.current.append(data)


def fetch(url, timeout=18):
    parsed = urlparse(url)
    # urllib requires ASCII request targets; Japanese landing slugs need quoting.
    safe_url = urlunparse(parsed._replace(path=quote(parsed.path, safe="/%")))
    req = Request(safe_url, headers={"User-Agent": config.USER_AGENT, "Accept-Language": "ja-JP,ja;q=0.9"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        if not charset and urlparse(response.url).hostname == "www.oricon.co.jp":
            charset = "cp932"
        return response.url, raw.decode(charset or "utf-8", "replace")


def fetch_template_detail(template_id):
    """Return {"detail", "recommendations"} from a template detail page."""
    _, page = fetch(f"https://www.capcut.com/ja-jp/template-detail/{template_id}")
    parser = _RouterData()
    parser.feed(page)
    router = json.loads("".join(parser.parts))
    data = router["loaderData"]["template-detail_$"]
    return {"detail": data["templateDetail"], "recommendations": data["recommendList"]}


def embedded_json_object(page, key):
    """Read a named JSON object embedded in CapCut's server-rendered HTML."""
    marker = f'"{key}":'
    index = page.find(marker)
    start = page.find("{", index + len(marker)) if index >= 0 else -1
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escaped = False
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


def parse_landing_page(page):
    """Return (template_ids, {template_id: summary}) from a landing page."""
    payload = embedded_json_object(page, "videoTemplateList")
    templates = payload.get("videoTemplates") or []
    summaries = {}
    for item in templates:
        template_id = str(item.get("templateId") or "")
        structured = item.get("structuredData") or {}
        creator = structured.get("creator") or {}
        if not template_id or not creator.get("name"):
            continue
        summaries[template_id] = {
            "templateId": template_id,
            "title": item.get("title") or structured.get("name") or "",
            "desc": item.get("titleDesc") or structured.get("description") or "",
            "usageAmount": item.get("useCount") or 0,
            "createTime": structured.get("uploadDate") or 0,
            "segmentAmount": structured.get("clipsCount"),
            "coverUrl": item.get("coverUrl") or structured.get("thumbnailUrl") or "",
            "videoUrl": item.get("videoUrl") or structured.get("contentUrl") or "",
            "canonicalPath": urlparse(structured.get("url") or "").path,
            "author": {"name": creator["name"],
                       "secUid": creator.get("encryptedCapcutID") or "",
                       "profileUrl": creator.get("profileURL") or ""},
        }
    ids = [str(item.get("templateId")) for item in templates if item.get("templateId")]
    if not ids:
        ids = config.URL_ID.findall(page.replace("\\u002F", "/"))
    return ids, summaries


def landing_template_ids(url):
    _, page = fetch(url, timeout=25)
    return parse_landing_page(page)


def fetch_jp_tiktok_chart():
    """Top 10 song titles of the Oricon Japan TikTok weekly chart."""
    chart_url, page = fetch(config.ORICON_TIKTOK_WEEKLY, timeout=25)
    parser = _Headings()
    parser.feed(page)
    terms = []
    for heading in parser.headings:
        if heading == "音楽ランキング":
            break
        if re.search(r"\d{4}年\d{2}月\d{2}日付", heading):
            continue
        terms.append(heading)
        if len(terms) == 10:
            break
    return chart_url, terms


def feed_api(path, payload):
    """Signed POST to CapCut's public feed API."""
    timestamp = int(time.time())
    signature = hashlib.md5(f"9e2c|{path[-7:]}|0||{timestamp}||11ac".encode()).hexdigest()
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone)",
        "Content-Type": "application/json",
        "appvr": "",
        "device-time": str(timestamp),
        "loc": "BR",
        "pf": "0",
        "sign": signature,
        "sign-ver": "1",
        "app-sdk-version": "1000.0.0",
    }
    req = Request("https://feed-api.capcutapi.com" + path, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=20) as resp:
        result = json.load(resp)
    if result.get("ret") != "0":
        raise ValueError(result.get("errmsg", result))
    return result["data"]


def _public_id_from_share_link(link):
    parsed = urlparse(link.strip())
    if parsed.scheme != "https" or parsed.hostname != "mobile.capcutshare.com":
        raise ValueError("请粘贴 CapCut 主页分享链接")
    if parsed.path.startswith("/sv2/"):
        request = Request(link.strip(), headers={"User-Agent": "Mozilla/5.0 (iPhone)"})
        with urlopen(request, timeout=15) as response:
            parsed = urlparse(response.url)
    if parsed.hostname != "mobile.capcutshare.com" or parsed.path != "/imlv/personal-homepage":
        raise ValueError("这不是 CapCut 作者主页链接")
    public_id = parse_qs(parsed.query).get("publicid", [""])[0]
    if not public_id:
        raise ValueError("主页链接里没有作者标识")
    return public_id


def resolve_profile_link(link):
    """Resolve a creator share link into CC ID, post count and TikTok link."""
    public_id = _public_id_from_share_link(link)
    profile = feed_api("/lv/v1/homepage/profile", {"public_id": public_id})
    user = profile.get("user") or {}
    stats = profile.get("user_statistics") or {}
    if not user.get("unique_id"):
        raise ValueError("CapCut 未返回 CC ID")
    tt = user.get("tiktok_user_info") or {}
    return {"name": user.get("name", ""), "cc_id": str(user["unique_id"]),
            "system_uid": str(user.get("uid") or ""),
            "total_posts": stats.get("template_count"),
            "tt_link": tt.get("link") or tt.get("url") or ""}


def check_profile_templates(link, min_uses=config.HIGH_USE_THRESHOLD):
    """Inspect a creator homepage and list templates with at least ``min_uses``."""
    public_id = _public_id_from_share_link(link)
    profile = feed_api("/lv/v1/homepage/profile", {"public_id": public_id})
    user = profile["user"]
    cursor = "0"
    seen = set()
    qualifying = []
    pages = 0
    while pages < 10 and len(qualifying) < 8:
        data = feed_api("/lv/v1/homepage/templates", {
            "cursor": cursor, "count": 100, "uid": 1,
            "public_id": public_id, "sdk_version": "100.0.0",
        })
        pages += 1
        for item in data.get("templates") or []:
            template_id = item.get("id")
            if template_id in seen:
                continue
            seen.add(template_id)
            if item.get("usage_amount", 0) >= min_uses:
                qualifying.append({
                    "id": template_id,
                    "title": item.get("short_title") or item.get("title", "")[:80],
                    "uses": item["usage_amount"],
                    "clips": item.get("fragment_count"),
                })
        if not data.get("has_more") or not data.get("new_cursor"):
            break
        cursor = data["new_cursor"]
    return {
        "name": user["name"], "id": user["unique_id"], "bio": user.get("description", ""),
        "cc_link": link, "count": profile["user_statistics"]["template_count"],
        "high_use_count_found": len(qualifying), "qualifying": qualifying,
        "pages_checked": pages, "public_id": public_id, "tt": user.get("tiktok_user_info"),
    }
