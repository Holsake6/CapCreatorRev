from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse
import hashlib
import json
import re
import sys
import time


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            src = dict(attrs).get("src")
            if src:
                self.scripts.append(src)


def post(path, payload):
    timestamp = int(time.time())
    signature = hashlib.md5(
        f"9e2c|{path[-7:]}|0||{timestamp}||11ac".encode()
    ).hexdigest()
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
    req = Request(
        "https://feed-api.capcutapi.com" + path,
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    with urlopen(req, timeout=20) as resp:
        result = json.load(resp)
    if result.get("ret") != "0":
        raise ValueError(result.get("errmsg", result))
    return result["data"]


def check(short_url):
    request = Request(short_url, headers={"User-Agent": "Mozilla/5.0 (iPhone)"})
    with urlopen(request, timeout=20) as resp:
        resolved_url = resp.url
    public_id = parse_qs(urlparse(resolved_url).query).get("publicid", [None])[0]
    if not public_id:
        raise ValueError("No profile public ID in redirect")
    profile = post("/lv/v1/homepage/profile", {"public_id": public_id})
    user = profile["user"]
    count = profile["user_statistics"]["template_count"]
    cursor = "0"
    seen = set()
    qualifying = []
    pages = 0
    while pages < 10 and len(qualifying) < 8:
        data = post("/lv/v1/homepage/templates", {
            "cursor": cursor, "count": 100, "uid": 1,
            "public_id": public_id, "sdk_version": "100.0.0",
        })
        pages += 1
        templates = data.get("templates") or []
        for item in templates:
            template_id = item.get("id")
            if template_id in seen:
                continue
            seen.add(template_id)
            if item.get("usage_amount", 0) >= 3000:
                qualifying.append({
                    "id": template_id,
                    "title": item.get("short_title") or item.get("title", "")[:80],
                    "uses": item["usage_amount"],
                    "clips": item.get("fragment_count"),
                    "item_type": item.get("item_type"),
                    "functions": item.get("functions"),
                })
        if not data.get("has_more") or not data.get("new_cursor"):
            break
        cursor = data["new_cursor"]
    return {
        "name": user["name"],
        "id": user["unique_id"],
        "bio": user.get("description", ""),
        "cc_link": short_url,
        "count": count,
        "high_use_count_found": len(qualifying),
        "qualifying": qualifying,
        "pages_checked": pages,
        "public_id": public_id,
        "tt": user.get("tiktok_user_info"),
    }


if __name__ == "__main__":
    urls = sys.argv[1:]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(check, url): url for url in urls}
        for future in as_completed(futures):
            try:
                print(json.dumps(future.result(), ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"cc_link": futures[future], "error": str(exc)}, ensure_ascii=False), flush=True)
