#!/usr/bin/env python3
"""Local CapCut Japan creator discovery and review. No OpenAI calls."""

import argparse
import csv
import hashlib
import html
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import random
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, quote, urlparse, urlunparse
from urllib.request import Request, urlopen
import webbrowser
from capcut_batch import post as capcut_post

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "capcut_local_data"
CACHE = DATA / "cache"
RESULTS = DATA / "candidates.json"
DECISIONS = DATA / "decisions.json"
PREFERENCES = DATA / "preference_profile.json"
REFERENCE_CASES = ROOT / "reference_positive_cases.json"
SEEN_CREATORS = DATA / "seen_creators.json"
SCAN_STATE = DATA / "scan_state.json"
SCAN_HISTORY = DATA / "scan_history.json"
SEEN_TEMPLATES = DATA / "seen_templates.json"
TREND_TERMS = DATA / "trend_terms.json"
VIDEO_ANALYSIS = DATA / "video_analysis"
VISUAL_LEARNING = DATA / "visual_learning.json"
NEW_CATEGORY_DATA = DATA / "new_category"
NEW_CATEGORY_CASES = NEW_CATEGORY_DATA / "positive_cases.json"
NEW_CATEGORY_PROFILE = NEW_CATEGORY_DATA / "positive_profile.json"
VISUAL_ANALYZER_SOURCE = ROOT / "video_visual_analyzer.swift"
VISUAL_ANALYZER = DATA / "tools" / "video_visual_analyzer"
EXCLUSIONS = ROOT / "已归类作者.txt"
EXCLUSIONS_CSV = ROOT / "已归类作者.csv"
SEED_TEMPLATES = ROOT / "seed_templates.txt"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36"
KANA = re.compile(r"[\u3040-\u30ff]")
AI = re.compile(r"(?i)(?:\bAI\b|生成AI|AI生成|AI加工|AI写真|AI顔|AI変身|AIエフェクト|人工知能|seedance|dreamina)")
DANCE = re.compile(r"(?i)(?:dance|dancing|choreo|ダンス|踊|振り?付け|手振り|手ぶり|アイドル|パフォーマンス)")
NON_DANCE_GIMMICK = re.compile(r"(?i)(?:顔ハメ|顔入れ替え|face\s*swap|head\s*swap|pet\s*dance|baby\s*dance|dancing\s*baby|cat\s*dance|dog\s*dance|踊る(?:犬|猫|動物))")
URL_ID = re.compile(r"/template-detail/(?:[^\"<>\s]*/)?(\d{18,20})")
PROFILE_LINK = re.compile(r"https?://mobile\.capcutshare\.com/sv2/[A-Za-z0-9]+/?")
DANCE_LANDINGS = (
    "https://www.capcut.com/ja-jp/template/record/dance",
    "https://www.capcut.com/ja-jp/explore/dance-template",
    "https://www.capcut.com/ja-jp/explore/popular-tiktok-dance",
    "https://www.capcut.com/ja-jp/explore/7512880651008559105",
    "https://www.capcut.com/ja-jp/explore/ダンス編集",
    "https://www.capcut.com/ja-jp/explore/CapCut-ダンス動画",
    "https://www.capcut.com/ja-jp/explore/ビデオダンスエディタ",
    "https://www.capcut.com/ja-jp/explore/Dance-Editing-Template",
    "https://www.capcut.com/ja-jp/explore/ダンス編集者",
    "https://www.capcut.com/ja-jp/explore/ダンス動画",
    "https://www.capcut.com/ja-jp/explore/ダンスミュージック",
    "https://www.capcut.com/ja-jp/explore/ダンス-エフェクト",
    "https://www.capcut.com/ja-jp/explore/ダンスエフェクト",
    "https://www.capcut.com/ja-jp/explore/CapCut-ワンダンス編集/7513481238256371728",
    "https://www.capcut.com/ja-jp/explore/Dance-Editing-Template/7497640620559779857",
    "https://www.capcut.com/ja-jp/explore/ダンス編集/7512965054573938704",
    "https://www.capcut.com/ja-jp/explore/ビデオダンスエディタ/7512990501697374209",
    "https://www.capcut.com/ja-jp/explore/ダンス編集者/7513008290424670209",
    "https://www.capcut.com/ja-jp/explore/CapCut-ダンス動画/7513481238256355344",
    "https://www.capcut.com/ja-jp/explore/ナルト-踊ってみた/7513342350833223696",
    "https://www.capcut.com/ja-jp/explore/踊ってみた",
    "https://www.capcut.com/ja-jp/explore/TikTokダンス",
    "https://www.capcut.com/ja-jp/explore/TikTok流行りのダンス",
    "https://www.capcut.com/ja-jp/explore/流行りダンス",
    "https://www.capcut.com/ja-jp/explore/ダンスチャレンジ",
    "https://www.capcut.com/ja-jp/explore/ダンス動画編集",
    "https://www.capcut.com/ja-jp/explore/踊るテンプレート",
    "https://www.capcut.com/ja-jp/explore/ダンス用テンプレート",
    "https://www.capcut.com/ja-jp/explore/KPOPダンス",
    "https://www.capcut.com/ja-jp/explore/アイドルダンス",
    # Related dance collections linked by CapCut itself from the Japanese
    # TikTok dance page.  Exact IDs are more stable than guessed slugs.
    "https://www.capcut.com/ja-jp/explore/dancing-template",
    "https://www.capcut.com/ja-jp/explore/energetic-dance",
    "https://www.capcut.com/ja-jp/explore/tiktok-cute-poppin-do-dance",
    "https://www.capcut.com/ja-jp/explore/popular-tiktok-dances",
    "https://www.capcut.com/ja-jp/explore/TikTokダンスソング/7512978747810809857",
    "https://www.capcut.com/ja-jp/explore/TikTokダンス曲/7512978747810891777",
    "https://www.capcut.com/ja-jp/explore/ダンス動画/7512983683641772049",
    "https://www.capcut.com/ja-jp/explore/あなたに踊る/7512967238586222593",
    "https://www.capcut.com/ja-jp/explore/ホットベリーダンス/7513004558294927376",
    "https://www.capcut.com/ja-jp/explore/ダンスビデオ/7512945605816797201",
    "https://www.capcut.com/ja-jp/explore/ダンスビデオエディター/7512968614363564033",
    "https://www.capcut.com/ja-jp/explore/バチャータ-動画/7512965377309247505",
    "https://www.capcut.com/ja-jp/explore/ダンスソング/7512972489519466512",
    "https://www.capcut.com/ja-jp/explore/7557563389263235088",
)
LEARN_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}|[\u3040-\u30ff]{2,}|[\u4e00-\u9fff]{2,}")
LEARN_STOP = {"作者", "模板", "视频", "比较", "感觉", "这个", "那个", "不是", "没有", "可以", "作品"}
VISUAL_REASON = re.compile(r"(?i)(AI|动画|节奏|包装|舞蹈|画面|构图|剪辑|内容|模板|特效|简单|审美|卡点|镜头|滤镜)")
MAX_PENDING_CREATORS = 50
ORICON_TIKTOK_WEEKLY = "https://www.oricon.co.jp/rank/tt/w/"
FALLBACK_TREND_TERMS = (
    "ピンク", "BALI", "きゃわぽっぴんどぅー", "Sunshine Girl",
    "分かっちゃいないね", "Hug feat. kojikoji", "恋、はじめました。",
    "愛のレンタル", "マル・マル・モリ・モリ！", "エアロピクルス",
)


class RefreshCancelled(Exception):
    """Raised when a manual refresh is stopped before results are saved."""


class ScriptData(HTMLParser):
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


class HeadingData(HTMLParser):
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
    # urllib requires ASCII request targets. Without this conversion, the most
    # relevant Japanese dance landing pages were silently skipped.
    safe_url = urlunparse(parsed._replace(path=quote(parsed.path, safe="/%")))
    req = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja-JP,ja;q=0.9"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
        if not charset and urlparse(response.url).hostname == "www.oricon.co.jp":
            charset = "cp932"
        return response.url, raw.decode(charset or "utf-8", "replace")


def has_japanese(text):
    # One kana is often decorative kaomoji, including on non-Japanese accounts.
    return len(KANA.findall(text or "")) >= 2


def cached_template(template_id, force=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{template_id}.json"
    if not force and path.exists() and time.time() - path.stat().st_mtime < 12 * 3600:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        _, page = fetch(f"https://www.capcut.com/ja-jp/template-detail/{template_id}")
        parser = ScriptData()
        parser.feed(page)
        router = json.loads("".join(parser.parts))
        data = router["loaderData"]["template-detail_$"]
        result = {"detail": data["templateDetail"], "recommendations": data["recommendList"]}
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result
    except Exception as exc:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"error": str(exc), "detail": None, "recommendations": []}


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


def landing_template_ids(url):
    _, page = fetch(url, timeout=25)
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
        ids = URL_ID.findall(page.replace("\\u002F", "/"))
    return ids, summaries


def read_json_file(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def current_jp_tiktok_songs(force=False):
    """Read the current Japan TikTok weekly chart without an API token."""
    cached = read_json_file(TREND_TERMS, {})
    cache_is_clean = cached.get("terms") and not any("�" in term for term in cached["terms"])
    if (not force and cache_is_clean and
            time.time() - float(cached.get("checked_epoch", 0)) < 24 * 3600):
        return cached["terms"][:10]
    terms = []
    chart_url = ORICON_TIKTOK_WEEKLY
    try:
        chart_url, page = fetch(ORICON_TIKTOK_WEEKLY, timeout=25)
        parser = HeadingData()
        parser.feed(page)
        for heading in parser.headings:
            if heading == "音楽ランキング":
                break
            if re.search(r"\d{4}年\d{2}月\d{2}日付", heading):
                continue
            terms.append(heading)
            if len(terms) == 10:
                break
    except Exception:
        terms = cached.get("terms") or list(FALLBACK_TREND_TERMS)
    payload = {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_epoch": time.time(),
        "source": chart_url,
        "terms": terms or list(FALLBACK_TREND_TERMS),
    }
    DATA.mkdir(exist_ok=True)
    TREND_TERMS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload["terms"][:10]


def discovery_landing_urls():
    trend_urls = [f"https://www.capcut.com/ja-jp/explore/{quote(term, safe='')}"
                  for term in current_jp_tiktok_songs()]
    return list(dict.fromkeys([*DANCE_LANDINGS, *trend_urls]))


def ensure_visual_analyzer():
    if VISUAL_ANALYZER.exists() and VISUAL_ANALYZER.stat().st_mtime >= VISUAL_ANALYZER_SOURCE.stat().st_mtime:
        return VISUAL_ANALYZER
    VISUAL_ANALYZER.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "/usr/bin/swiftc", "-module-cache-path", "/tmp/capcut-swift-module-cache",
        str(VISUAL_ANALYZER_SOURCE), "-o", str(VISUAL_ANALYZER),
    ], check=True, capture_output=True, text=True, timeout=120)
    return VISUAL_ANALYZER


def analyze_work_video(work):
    template_id = str(work.get("template_id") or hashlib.sha1(work.get("video_url", "").encode()).hexdigest())
    VIDEO_ANALYSIS.mkdir(parents=True, exist_ok=True)
    cached = VIDEO_ANALYSIS / f"{template_id}.json"
    previous = read_json_file(cached, None)
    if previous:
        return previous
    video_url = work.get("video_url", "")
    if not video_url:
        raise ValueError("模板没有可分析的视频地址")
    analyzer = ensure_visual_analyzer()
    request = Request(video_url, headers={"User-Agent": USER_AGENT})
    temp_path = None
    try:
        with urlopen(request, timeout=30) as response, tempfile.NamedTemporaryFile(
                suffix=".mp4", dir=str(DATA), delete=False) as target:
            temp_path = Path(target.name)
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 80 * 1024 * 1024:
                    raise ValueError("视频超过 80MB，跳过本地分析")
                target.write(chunk)
        result = subprocess.run([str(analyzer), str(temp_path)], check=True, capture_output=True,
                                text=True, timeout=90)
        analysis = json.loads(result.stdout)
        analysis.update(template_id=template_id, title=work.get("title", ""), analyzed_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        cached.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return analysis
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def aggregate_video_analyses(analyses):
    analyses = [item for item in analyses if item]
    if not analyses:
        return {}
    labels = {}
    for item in analyses:
        for label, confidence in item.get("labels", {}).items():
            labels[label] = max(labels.get(label, 0), float(confidence))
    def average(field):
        return round(sum(float(item.get(field, 0)) for item in analyses) / len(analyses), 3)
    return {
        "video_count": len(analyses),
        "human_frame_ratio": average("human_frame_ratio"),
        "face_frame_ratio": average("face_frame_ratio"),
        "mean_frame_distance": average("mean_frame_distance"),
        "label_diversity": round(sum(int(item.get("label_diversity", 0)) for item in analyses) / len(analyses), 1),
        "labels": dict(sorted(labels.items(), key=lambda pair: -pair[1])[:30]),
        "template_ids": [item.get("template_id") for item in analyses],
    }


def video_supports_dance(profile):
    """Conservative local-video gate for seed items whose titles omit dance."""
    if not profile:
        return False
    human_presence = max(
        float(profile.get("human_frame_ratio") or 0),
        float(profile.get("face_frame_ratio") or 0),
    )
    motion = float(profile.get("mean_frame_distance") or 0)
    return human_presence >= 0.45 and motion >= 0.35


def analyze_author_video_content(author, limit=1):
    works = [work for work in author.get("works", []) if work.get("video_url")]
    # Analyse the author's dance work first.  Sorting only by uses frequently
    # inspected an unrelated viral slideshow from the same author.
    works.sort(key=lambda work: (
        bool(work.get("dance_signal") and not work.get("non_dance_gimmick")),
        int(work.get("uses") or 0),
    ), reverse=True)
    analyses = []
    for work in works[:limit]:
        try:
            analyses.append(analyze_work_video(work))
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            continue
    profile = aggregate_video_analyses(analyses)
    if profile:
        author["video_content_profile"] = profile
    return profile


def visual_profile_similarity(candidate, negative):
    if not candidate or not negative:
        return 0
    candidate_labels = candidate.get("labels", {})
    negative_labels = negative.get("labels", {})
    all_labels = set(candidate_labels) | set(negative_labels)
    label_union = sum(max(float(candidate_labels.get(label, 0)), float(negative_labels.get(label, 0))) for label in all_labels)
    label_overlap = (sum(min(float(candidate_labels.get(label, 0)), float(negative_labels.get(label, 0))) for label in all_labels) /
                     label_union) if label_union else 0
    def closeness(field, scale=1.0):
        return max(0.0, 1.0 - abs(float(candidate.get(field, 0)) - float(negative.get(field, 0))) / scale)
    motion_scale = max(1.0, float(candidate.get("mean_frame_distance", 0)), float(negative.get("mean_frame_distance", 0)))
    score = (0.45 * label_overlap + 0.2 * closeness("human_frame_ratio") +
             0.1 * closeness("face_frame_ratio") +
             0.2 * closeness("mean_frame_distance", motion_scale) +
             0.05 * closeness("label_diversity", 20.0))
    return round(max(0, min(1, score)), 3)


def content_negative_adjustment(author):
    candidate = author.get("video_content_profile") or {}
    learned = read_json_file(VISUAL_LEARNING, {}).get("rejected_profiles", {})
    matches = []
    for item in learned.values():
        if not item.get("affects_visual_score"):
            continue
        similarity = visual_profile_similarity(candidate, item.get("video_profile", {}))
        if similarity:
            matches.append((similarity, item.get("reason", "")))
    if not matches:
        return 0, ""
    similarity, reason = max(matches)
    # Dance videos naturally share people and motion. Only similarity above a
    # conservative 0.65 baseline is treated as evidence of a learned negative.
    if similarity <= 0.65:
        return 0, ""
    penalty = min(20, (similarity - 0.65) / 0.35 * 20)
    return round(penalty, 1), reason


def learn_rejected_creator_video(author_key, reason, data):
    author = next((item for item in data.get("candidates", [])
                   if (item.get("sec_uid") or item.get("name")) == author_key), None)
    if not author:
        return False
    profile = analyze_author_video_content(author, limit=2)
    if not profile:
        return False
    learning = read_json_file(VISUAL_LEARNING, {"rejected_profiles": {}})
    learning.setdefault("rejected_profiles", {})[author_key] = {
        "reason": reason,
        "affects_visual_score": bool(VISUAL_REASON.search(reason or "")),
        "video_profile": profile,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    learning["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    temp = VISUAL_LEARNING.with_suffix(".tmp")
    temp.write_text(json.dumps(learning, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(VISUAL_LEARNING)
    return True


def analyze_retrieved_candidates(candidates, limit=60, progress=None):
    learning = read_json_file(VISUAL_LEARNING, {}).get("rejected_profiles", {})
    if not learning:
        if progress:
            progress("视频分析", "尚无负面视觉样本，跳过逐帧分析")
        return
    selected = candidates[:min(limit, len(candidates))]

    def analyze(author):
        if progress:
            progress("视频分析", f"正在分析作者 {author['name']} 的模板视频")
        return analyze_author_video_content(author)

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(analyze, author): author for author in selected}
        for completed, job in enumerate(as_completed(jobs), 1):
            job.result()
            if progress:
                progress("视频分析", f"已分析作者 {jobs[job]['name']} 的模板视频（{completed}/{len(selected)}）")


def scan_page_numbers(quick=False):
    if quick:
        return [1, 2, 3]
    state = read_json_file(SCAN_STATE, {})
    cursor = max(4, int(state.get("next_archive_page", 4)))
    # Cover the newest pages every time and rotate through five archive pages.
    # With many focused landing pages this is broader and substantially cheaper
    # than requesting ten mostly empty archive pages from every source.
    return sorted(set([1, 2, 3, *range(cursor, cursor + 5)]))


def get_seed_ids(quick=False, progress=None, cancel_event=None):
    bundled = []
    if SEED_TEMPLATES.exists():
        bundled = [line.strip() for line in SEED_TEMPLATES.read_text(encoding="utf-8").splitlines()
                   if line.strip().isdigit()]
    discovered = []
    summaries = {}
    successful_pages = 0
    failed_pages = 0
    page_numbers = scan_page_numbers(quick)
    landing_pages = [url if page == 1 else f"{url}?page={page}"
                     for url in discovery_landing_urls() for page in page_numbers]
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {pool.submit(landing_template_ids, url): url for url in landing_pages}
        for completed, job in enumerate(as_completed(jobs), 1):
            if cancel_event and cancel_event.is_set():
                for pending_job in jobs:
                    pending_job.cancel()
                raise RefreshCancelled("已停止刷新，保留上一次候选结果")
            try:
                ids, page_summaries = job.result()
                discovered.extend(ids)
                summaries.update(page_summaries)
                successful_pages += 1
            except Exception as exc:
                failed_pages += 1
                if progress and failed_pages <= 3:
                    progress("入口失败", f"{jobs[job]}：{type(exc).__name__}：{exc}")
                continue
            if progress and (completed == 1 or completed % 5 == 0 or completed == len(jobs)):
                progress("发现入口", f"已检查专题页 {completed}/{len(jobs)}，成功 {successful_pages}、失败 {failed_pages}；当前：{jobs[job]}")
    # Keep every previously seen non-AI dance template as a future entry point.
    # This makes the graph grow over successive daily scans instead of restarting
    # from a small fixed list each day.
    cached_dance = []
    for path in CACHE.glob("*.json"):
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in [cached.get("detail"), *(cached.get("recommendations") or [])]:
            if not item:
                continue
            text = f'{item.get("title") or ""} {item.get("desc") or ""}'
            template_id = str(item.get("templateId") or item.get("id") or "")
            if template_id and DANCE.search(text) and not AI.search(text):
                cached_dance.append(template_id)
    if progress:
        progress("发现入口", f"实时专题页返回 {len(summaries)} 条含作者资料的模板；成功 {successful_pages} 页、失败 {failed_pages} 页")
    return list(dict.fromkeys(discovered + bundled + cached_dance)), summaries


def item_record(item):
    author = item.get("author") or {}
    template_id = str(item.get("templateId") or item.get("id") or "")
    if not template_id or not author.get("name"):
        return None
    title = item.get("title") or ""
    desc = item.get("desc") or ""
    try:
        created_at = float(item.get("createTime") or item.get("create_time") or 0)
        if created_at > 10_000_000_000:
            created_at /= 1000
    except (TypeError, ValueError):
        created_at = 0
    age_days = max(0, int((time.time() - created_at) // 86400)) if created_at else None
    uses = int(item.get("usageAmount") or item.get("usage_amount") or 0)
    return {
        "template_id": template_id,
        "title": title,
        "desc": desc[:350],
        "uses": uses,
        "created_at_epoch": int(created_at) if created_at else 0,
        "published_at": time.strftime("%Y-%m-%d", time.localtime(created_at)) if created_at else "",
        "age_days": age_days,
        "stale_low_use": bool(created_at and age_days >= 7 and uses < 1000),
        "clips": item.get("segmentAmount") or item.get("fragment_count"),
        "url": "https://www.capcut.com" + (item.get("canonicalPath") or f"/ja-jp/template-detail/{template_id}"),
        "cover_url": item.get("coverUrl") or "",
        "video_url": item.get("videoUrl") or "",
        "author_name": author.get("name", ""),
        "author_bio": author.get("description", ""),
        "sec_uid": author.get("secUid") or author.get("profileUrl", "").rsplit("/", 1)[-1],
        "japanese_post": has_japanese(title + " " + desc),
        "likely_ai": bool(AI.search(title + " " + desc)),
        "dance_signal": bool(DANCE.search(title + " " + desc)),
        "non_dance_gimmick": bool(NON_DANCE_GIMMICK.search(title + " " + desc)),
    }


def apply_stale_low_use_rule(data, decisions=None):
    """Apply the 7-day/1,000-use hard gate to saved and newly found work."""
    decisions = decisions if decisions is not None else read_decisions()
    create_times = {}
    for path in CACHE.glob("*.json"):
        cached = read_json_file(path, {})
        for item in [cached.get("detail"), *(cached.get("recommendations") or [])]:
            if not item:
                continue
            template_id = str(item.get("templateId") or item.get("id") or "")
            if template_id and (item.get("createTime") or item.get("create_time")):
                create_times[template_id] = item.get("createTime") or item.get("create_time")

    kept_authors = []
    removed_authors = 0
    removed_templates = 0
    now = time.time()
    for author in data.get("candidates", []):
        eligible = []
        newly_excluded = 0
        for work in author.get("works", []):
            raw_created = work.get("created_at_epoch") or create_times.get(str(work.get("template_id") or ""))
            try:
                created_at = float(raw_created or 0)
                if created_at > 10_000_000_000:
                    created_at /= 1000
            except (TypeError, ValueError):
                created_at = 0
            age_days = max(0, int((now - created_at) // 86400)) if created_at else None
            work["created_at_epoch"] = int(created_at) if created_at else 0
            work["published_at"] = time.strftime("%Y-%m-%d", time.localtime(created_at)) if created_at else ""
            work["age_days"] = age_days
            work["stale_low_use"] = bool(created_at and age_days >= 7 and int(work.get("uses") or 0) < 1000)
            if work["stale_low_use"]:
                newly_excluded += 1
            else:
                eligible.append(work)
        removed_templates += newly_excluded
        author["stale_low_use_excluded_count"] = int(author.get("stale_low_use_excluded_count", 0)) + newly_excluded
        author["works"] = eligible
        non_ai = [work for work in eligible if not work.get("likely_ai")]
        explicit_dance = [work for work in non_ai if work.get("dance_signal") and not work.get("non_dance_gimmick")]
        dance_non_ai = [work for work in non_ai
                        if (work.get("dance_seed") or work.get("dance_signal")) and not work.get("non_dance_gimmick")]
        author["indexed_count"] = len(eligible)
        author["high_use_non_ai_indexed"] = sum(int(work.get("uses") or 0) >= 3000 for work in explicit_dance)
        author["dance_non_ai_indexed"] = len(dance_non_ai)
        author["explicit_dance_indexed"] = len(explicit_dance)
        key = author.get("sec_uid") or author.get("name")
        status = decisions.get(key, {}).get("status", "pending")
        if dance_non_ai or status != "pending":
            kept_authors.append(author)
        else:
            removed_authors += 1
    data["candidates"] = kept_authors
    data["stale_low_use_rule"] = "发布满7天且 uses<1000 的模板直接排除"
    data["stale_low_use_removed_templates"] = int(data.get("stale_low_use_removed_templates", 0)) + removed_templates
    data["stale_low_use_removed_pending_authors"] = int(data.get("stale_low_use_removed_pending_authors", 0)) + removed_authors
    return removed_authors, removed_templates


def exclusion_terms():
    defaults = ["rin_go.x", "s.n_so_", "カーラ", "てぃーすけ", "りあな", "みるくぱんだ"]
    if EXCLUSIONS.exists():
        defaults += [line.strip() for line in EXCLUSIONS.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
    if EXCLUSIONS_CSV.exists():
        with EXCLUSIONS_CSV.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                defaults += [row.get(k, "").strip() for k in ("CC用户名称", "CC ID", "CC主页link") if row.get(k)]
    return [x.casefold() for x in defaults]


def is_excluded(candidate, terms):
    values = [candidate.get("name", "").casefold(), candidate.get("cc_id", "").casefold()]
    return any(term == value or (term and term in value) for term in terms for value in values)


def learned_terms(text):
    return [word.casefold() for word in LEARN_TOKEN.findall(text or "")
            if word.casefold() not in LEARN_STOP]


def negative_learned_terms(text):
    """Keep every rejection reason complete while also extracting matchable clauses/tokens."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().casefold())
    if not normalized:
        return []
    terms = [normalized]
    terms.extend(
        part.strip(" -_/\t")
        for part in re.split(r"[，。；！？、（）()\[\]{}:：]+", normalized)
        if len(part.strip(" -_/\t")) >= 2 and not part.strip().isdigit()
    )
    terms.extend(learned_terms(normalized))
    # Preserve order so the dashboard reads from complete reasons down to details.
    return list(dict.fromkeys(term for term in terms if term and term not in LEARN_STOP))


def read_preferences():
    if not PREFERENCES.exists():
        return {}
    try:
        return json.loads(PREFERENCES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_preferences(profile):
    DATA.mkdir(exist_ok=True)
    temp = PREFERENCES.with_suffix(".tmp")
    temp.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(PREFERENCES)


def new_category_state():
    """Read the isolated, positive-only learning workspace."""
    profile = read_json_file(NEW_CATEGORY_PROFILE, {})
    cases = read_json_file(NEW_CATEGORY_CASES, [])
    return {
        "category_name": profile.get("category_name", "新类别（待命名）"),
        "revision": int(profile.get("revision", 0)),
        "updated_at": profile.get("updated_at", "尚未学习"),
        "case_count": len(cases) if isinstance(cases, list) else 0,
        "positive_terms": profile.get("positive_terms", {}),
        "case_summaries": profile.get("case_summaries", []),
        "source_fields": profile.get("source_fields", {}),
    }


def positive_case_records(payload):
    """Accept common JSON layouts while keeping the supplied data as evidence."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("videos", "cases", "examples", "items", "data", "positive_cases"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    raise ValueError("正面案例必须是 JSON 对象或数组")


def nested_strings(value):
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        return [text] if text else []
    if isinstance(value, list):
        return [text for item in value for text in nested_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in nested_strings(item)]
    return []


def learn_new_category_positive_cases(payload, category_name=""):
    """Append positive examples and rebuild a positive-only profile."""
    NEW_CATEGORY_DATA.mkdir(parents=True, exist_ok=True)
    incoming = positive_case_records(payload)
    if not incoming:
        raise ValueError("没有读取到正面案例")
    existing = read_json_file(NEW_CATEGORY_CASES, [])
    if not isinstance(existing, list):
        existing = []
    # Exact JSON identity prevents accidental duplicate imports.
    known = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in existing}
    added = 0
    for item in incoming:
        identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if identity not in known:
            existing.append(item)
            known.add(identity)
            added += 1

    previous = read_json_file(NEW_CATEGORY_PROFILE, {})
    name = (category_name or previous.get("category_name") or "新类别（待命名）").strip()
    terms = {}
    fields = {}
    summaries = []
    for index, item in enumerate(existing, 1):
        if isinstance(item, dict):
            for field in item:
                fields[str(field)] = fields.get(str(field), 0) + 1
        texts = nested_strings(item)
        combined = "；".join(texts)
        for term in learned_terms(combined):
            terms[term] = terms.get(term, 0) + 1
        if combined:
            summaries.append({"index": index, "text": combined[:280]})
    profile = {
        "version": 1,
        "revision": int(previous.get("revision", 0)) + (1 if added or name != previous.get("category_name") else 0),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "category_name": name,
        "learning_policy": "只从用户提供和审核通过的正面案例自动学习；不建立反向提示词。",
        "positive_terms": dict(sorted(terms.items(), key=lambda pair: (-pair[1], pair[0]))),
        "source_fields": dict(sorted(fields.items(), key=lambda pair: (-pair[1], pair[0]))),
        "case_summaries": summaries,
    }
    NEW_CATEGORY_CASES.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    NEW_CATEGORY_PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return added, profile


def effective_terms(derived, overrides, deleted):
    terms = {term: int(weight) for term, weight in derived.items() if term not in set(deleted)}
    for term, weight in overrides.items():
        if term:
            terms[term] = max(0, min(10, int(weight)))
    return dict(sorted(terms.items(), key=lambda item: (-item[1], item[0])))


def preference_adjustment(author, profile):
    """Small metadata-only adjustment. Full video judgments stay in the saved prompt profile."""
    text = " ".join([author.get("name", ""), author.get("bio", ""), *[
        f'{work.get("title", "")} {work.get("desc", "")}' for work in author.get("works", [])
    ]]).casefold()
    positive = sum(weight for term, weight in profile.get("positive_terms", {}).items() if term in text)
    negative = sum(weight for term, weight in profile.get("negative_terms", {}).items() if term in text)
    return max(-30, min(30, positive * 2 - negative * 4))


REFERENCE_STYLE_TERMS = {
    "手写涂鸦/歌词包装": ("落書き", "手書き", "歌詞", "lyrics", "lyric", "graffiti", "doodle", "scribble", "typography"),
    "可爱贴纸/少女感": ("かわいい", "可愛い", "cute", "kawaii", "ステッカー", "sticker", "キラキラ", "星", "pink", "ピンク", "pastel"),
    "极简人物/舞蹈驱动": ("シンプル", "minimal", "全身", "full body", "固定", "one take", "ワンカット"),
    "拼贴/抠像/版式": ("コラージュ", "collage", "切り抜き", "ポスター", "poster", "magazine", "雑誌", "frame", "layout", "split"),
    "群舞/偶像舞蹈": ("群舞", "アイドル", "idol", "kpop", "k-pop", "group dance", "3人", "4人", "5人", "6人"),
    "场景与镜头语言": ("魚眼", "フィッシュアイ", "fisheye", "wide angle", "超広角", "夜景", "night", "street", "ストリート", "camera"),
}
REFERENCE_RHYTHM_TERMS = ("音ハメ", "ビート", "beat", "sync", "リズム", "rhythm", "テンポ", "tempo")
REFERENCE_THEME_TERMS = ("世界観", "aesthetic", "テーマ", "theme", "デザイン", "design")


def read_reference_cases():
    try:
        reference = json.loads(REFERENCE_CASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return reference if reference.get("videos") and reference.get("common_aesthetic") else {}


def reference_case_score(author, reference):
    """Metadata proxy for the visual rubric extracted from the 26 positive videos."""
    if not reference:
        return 0, []
    texts = [
        f'{work.get("title", "")} {work.get("desc", "")}'.casefold()
        for work in author.get("works", [])
        if not work.get("likely_ai") and (work.get("dance_seed") or work.get("dance_signal"))
    ]
    combined = " ".join(texts)
    active_groups = reference.get("common_aesthetic", {}).get("style_groups", [])
    matched_groups = []
    for label, terms in REFERENCE_STYLE_TERMS.items():
        if active_groups and not any(label.split("/")[0] in group for group in active_groups):
            continue
        if any(term.casefold() in combined for term in terms):
            matched_groups.append(label)

    rhythm_hits = sum(term.casefold() in combined for term in REFERENCE_RHYTHM_TERMS)
    theme_hits = sum(term.casefold() in combined for term in REFERENCE_THEME_TERMS)
    styled_works = sum(
        any(term.casefold() in text for terms in REFERENCE_STYLE_TERMS.values() for term in terms)
        for text in texts
    )
    simple_works = sum(1 <= int(work.get("clips") or 0) <= 3 for work in author.get("works", []))
    work_count = max(1, len(author.get("works", [])))

    # The reference cases emphasize recognizable packaging, beat-aware changes,
    # a coherent visual system, and low-to-medium replacement difficulty.
    score = min(48, len(matched_groups) * 12)
    score += min(16, rhythm_hits * 6)
    score += min(12, theme_hits * 6)
    score += min(12, round(12 * styled_works / max(1, len(texts))))
    score += min(12, round(12 * simple_works / work_count))
    evidence = matched_groups[:]
    if rhythm_hits:
        evidence.append("节奏/卡点信号")
    if theme_hits:
        evidence.append("主题化包装信号")
    if simple_works / work_count >= 0.6:
        evidence.append("低至中等替换门槛")
    return min(100, score), evidence


def quality_data_score(author):
    high = int(author.get("high_use_non_ai_indexed", 0))
    dance = int(author.get("dance_non_ai_indexed", 0))
    jp_posts = int(author.get("japanese_post_count", 0))
    max_uses = max((int(work.get("uses") or 0) for work in author.get("works", [])), default=0)
    return min(100, 10 * min(high, 5) + 5 * min(dance, 5) + 3 * min(jp_posts, 5) + min(10, max_uses // 100000))


def score_author(author, preference_profile=None, reference=None):
    reference = reference if reference is not None else read_reference_cases()
    preference_profile = preference_profile if preference_profile is not None else read_preferences()
    aesthetic, evidence = reference_case_score(author, reference)
    quality = quality_data_score(author)
    learned = preference_adjustment(author, preference_profile)
    content_penalty, content_reason = content_negative_adjustment(author)
    author["reference_match_score"] = aesthetic
    author["quality_data_score"] = quality
    author["reference_match_evidence"] = evidence
    author["preference_adjustment"] = learned
    author["negative_video_penalty"] = content_penalty
    author["negative_video_reason"] = content_reason
    # Positive-case aesthetics drive 70% of the score. Data quality supplies
    # 30%; later approvals/rejections add a bounded learned adjustment.
    author["score"] = round(aesthetic * 0.7 + quality * 0.3 + learned - content_penalty, 1)
    return author["score"]


def rescore_candidates(data, relabel=False):
    reference = read_reference_cases()
    preferences = read_preferences()
    candidates = data.get("candidates", [])
    for author in candidates:
        score_author(author, preferences, reference)
    candidates.sort(key=lambda author: author.get("score", 0), reverse=True)
    if relabel:
        ranked_count = min(30, round(len(candidates) * 0.6))
        for index, author in enumerate(candidates, 1):
            author["recommendation_type"] = "高匹配" if index <= ranked_count else "随机探索"
            author["match_rank"] = index
        data["latest_ranked_candidates"] = ranked_count
        data["latest_random_candidates"] = len(candidates) - ranked_count
    data["reference_case_count"] = len(reference.get("videos", []))
    data["scoring_policy"] = "正面案例审美70% + 数据质量30% + 审核反馈修正"
    return data


def rebuild_preference_profile(decisions=None, data=None):
    decisions = decisions if decisions is not None else read_decisions()
    if data is None:
        data = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {"candidates": []}
    by_key = {a.get("sec_uid") or a.get("name"): a for a in data.get("candidates", [])}
    positive_phrases, negative_prompts = [], []
    positive_terms, negative_terms = {}, {}
    approved_features = []
    for key, decision in decisions.items():
        status = decision.get("status")
        if status in ("approved", "aesthetic_only"):
            phrase = "；".join(x for x in [
                (decision.get("specialty") or "").strip(),
                (decision.get("aesthetic_notes") or "").strip(),
            ] if x)
            if phrase:
                positive_phrases.append({"creator_key": key, "status": status, "text": phrase})
                for term in learned_terms(phrase):
                    positive_terms[term] = positive_terms.get(term, 0) + 1
            author = by_key.get(key)
            if author and status == "approved":
                uses = [int(w.get("uses") or 0) for w in author.get("works", [])]
                approved_features.append({
                    "creator_key": key,
                    "indexed_count": author.get("indexed_count", len(uses)),
                    "high_use_non_ai_indexed": author.get("high_use_non_ai_indexed", 0),
                    "japanese_signal": author.get("japanese_signal", ""),
                    "max_uses": max(uses, default=0),
                })
        elif status == "rejected":
            reason = (decision.get("rejection_reason") or "").strip()
            if reason:
                negative_prompts.append({"creator_key": key, "text": reason})
                for term in negative_learned_terms(reason):
                    negative_terms[term] = negative_terms.get(term, 0) + 1
    previous = read_preferences()
    overrides = previous.get("term_overrides", {"positive": {}, "negative": {}})
    deleted = previous.get("deleted_terms", {"positive": [], "negative": []})
    learning_changed = (
        positive_phrases != previous.get("positive_phrases", []) or
        negative_prompts != previous.get("negative_prompts", []) or
        positive_terms != previous.get("derived_positive_terms", previous.get("positive_terms", {})) or
        negative_terms != previous.get("derived_negative_terms", previous.get("negative_terms", {}))
    )
    revision = max(1, int(previous.get("revision", 0)) + (1 if learning_changed else 0))
    updated_at = time.strftime("%Y-%m-%d %H:%M:%S") if learning_changed else previous.get("updated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    profile = {
        "version": 2,
        "revision": revision,
        "updated_at": updated_at,
        "approved_count": sum(d.get("status") == "approved" for d in decisions.values()),
        "aesthetic_only_count": sum(d.get("status") == "aesthetic_only" for d in decisions.values()),
        "rejected_count": sum(d.get("status") == "rejected" for d in decisions.values()),
        "learning_policy": "通过与审美达标特征累积为正向审美偏好；只有正式通过作者用于数据质量特征；不通过原因原文累积为反向提示词。",
        "positive_phrases": positive_phrases,
        "negative_prompts": negative_prompts,
        "derived_positive_terms": positive_terms,
        "derived_negative_terms": negative_terms,
        "term_overrides": overrides,
        "deleted_terms": deleted,
        "positive_terms": effective_terms(positive_terms, overrides.get("positive", {}), deleted.get("positive", [])),
        "negative_terms": effective_terms(negative_terms, overrides.get("negative", {}), deleted.get("negative", [])),
        "approved_creator_features": approved_features,
        "edit_history": previous.get("edit_history", [])[-50:],
    }
    write_preferences(profile)
    return profile


def read_seen_creators():
    return read_json_file(SEEN_CREATORS, {})


def record_seen_candidates(data):
    seen = read_seen_creators()
    timestamp = data.get("generated_at") or time.strftime("%Y-%m-%d %H:%M:%S")
    for author in data.get("candidates", []):
        key = author.get("sec_uid") or author.get("name")
        if not key:
            continue
        previous = seen.get(key, {})
        seen[key] = {
            "name": author.get("name", previous.get("name", "")),
            "first_seen": previous.get("first_seen", timestamp),
            "last_seen": timestamp,
        }
    SEEN_CREATORS.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def advance_scan_state(data):
    state = read_json_file(SCAN_STATE, {})
    cursor = max(4, int(state.get("next_archive_page", 4)))
    next_page = cursor + 5
    if next_page > 200:
        next_page = 4
    state.update({
        "next_archive_page": next_page,
        "last_completed_at": data.get("generated_at"),
        "last_archive_pages": list(range(cursor, cursor + 5)),
    })
    SCAN_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_results(previous, new, append_batch_size=None, replace_pending=False):
    """Build a new review batch while retaining completed, non-rejected work.

    The manual refresh intentionally replaces the current pending batch.
    Pending creators are not added to a permanent exclusion list, so they may
    appear in a later batch. Rejections are the sole review decision that
    prevents a creator from being offered again.
    """
    decisions = read_decisions()
    existing = list((previous or {}).get("candidates", []))
    preserved = (
        [
            author for author in existing
            if decisions.get(author.get("sec_uid") or author.get("name"), {}).get("status")
            in {"approved", "aesthetic_only"}
        ]
        if replace_pending else existing
    )
    preserved_keys = {author.get("sec_uid") or author.get("name") for author in preserved}
    replaced_pending = sum(
        decisions.get(author.get("sec_uid") or author.get("name"), {}).get("status", "pending")
        == "pending" for author in existing
    )
    # The button builds a complete, independent review batch. Scheduled and
    # command-line incremental scans retain their queue-refill behavior.
    available_slots = (max(0, int(append_batch_size)) if append_batch_size is not None
                       else (MAX_PENDING_CREATORS if replace_pending
                             else max(0, MAX_PENDING_CREATORS - replaced_pending)))
    available = [
        author for author in new.get("candidates", [])
        if (author.get("sec_uid") or author.get("name")) not in preserved_keys
        and decisions.get(author.get("sec_uid") or author.get("name"), {}).get("status") != "rejected"
    ]
    # Keep a 60/40 exploitation/exploration split. A full batch is exactly
    # 30 highest-match creators plus 20 random creators from the remainder.
    ranked_slots = min(len(available), round(available_slots * 0.6))
    ranked = available[:ranked_slots]
    remainder = available[ranked_slots:]
    random_slots = min(len(remainder), available_slots - len(ranked))
    rng = random.Random(new.get("generated_at", ""))
    exploratory = rng.sample(remainder, random_slots) if random_slots else []
    added = ranked + exploratory
    rank_lookup = {id(author): index for index, author in enumerate(available, 1)}
    for author in ranked:
        author["recommendation_type"] = "高匹配"
        author["match_rank"] = rank_lookup[id(author)]
    for author in exploratory:
        author["recommendation_type"] = "随机探索"
        author["match_rank"] = rank_lookup[id(author)]
    for author in added:
        author["discovered_at"] = new.get("generated_at")
        preserved.append(author)
    eligible_new = len(available)
    merged = {**new, "candidates": preserved,
              "latest_batch_candidates": len(added),
              "latest_batch_keys": [a.get("sec_uid") or a.get("name") for a in added],
              "latest_ranked_candidates": len(ranked),
              "latest_random_candidates": len(exploratory),
              "deferred_new_candidates": max(0, eligible_new - len(added)),
              "pending_queue": len(added),
              "replaced_pending_candidates": replaced_pending,
              "total_candidates": len(preserved)}
    history = read_json_file(SCAN_HISTORY, [])
    history.append({
        "generated_at": new.get("generated_at"),
        "indexed_templates": new.get("indexed_templates", 0),
        "new_candidates": len(added),
        "deferred_new_candidates": merged["deferred_new_candidates"],
        "skipped_seen_creators": new.get("skipped_seen_creators", 0),
    })
    SCAN_HISTORY.write_text(json.dumps(history[-365:], ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def pending_creator_count(data, decisions=None):
    decisions = decisions if decisions is not None else read_decisions()
    return sum(
        decisions.get(a.get("sec_uid") or a.get("name"), {}).get("status", "pending") == "pending"
        for a in data.get("candidates", [])
    )


def run_incremental_refresh(max_pages=1200, append_batch_size=None, replace_pending=False,
                            cancel_event=None, progress=None):
    previous = read_json_file(RESULTS, {"candidates": []})
    pending_before = pending_creator_count(previous)
    if (not replace_pending and append_batch_size is None and RESULTS.exists()
            and pending_before >= MAX_PENDING_CREATORS):
        return previous, (f"当前已有 {pending_before} 位待审作者。请先审核一部分，"
                          f"刷新时再补足到 {MAX_PENDING_CREATORS} 位。"), False
    new_data = discover(max_pages=max(1, min(max_pages, 2000)), cancel_event=cancel_event,
                        progress=progress, fresh=replace_pending)
    if not new_data["indexed_templates"]:
        raise RuntimeError("没有获取到模板，保留上次扫描结果")
    if replace_pending and not new_data.get("new_live_templates"):
        raise RuntimeError("实时专题页未发现可首次索引的新模板，保留上次候选结果")
    if replace_pending and not new_data["candidates"]:
        raise RuntimeError("实时模板未产生符合条件的作者，保留上次候选结果")
    enrich_profiles(new_data, progress=progress, cancel_event=cancel_event)
    if cancel_event and cancel_event.is_set():
        raise RefreshCancelled("已停止刷新，保留上一次候选结果")
    if progress:
        progress("生成候选", "正在按匹配分和随机探索比例整理新一批候选")
    data = merge_results(previous, new_data, append_batch_size=append_batch_size,
                         replace_pending=replace_pending)
    temp = RESULTS.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(RESULTS)
    if new_data.get("live_template_ids"):
        seen_templates = set(read_json_file(SEEN_TEMPLATES, []))
        seen_templates.update(new_data["live_template_ids"])
        seen_temp = SEEN_TEMPLATES.with_suffix(".tmp")
        seen_temp.write_text(json.dumps(sorted(seen_templates), ensure_ascii=False), encoding="utf-8")
        seen_temp.replace(SEEN_TEMPLATES)
    if progress:
        progress("保存结果", f"已保存 {data['latest_batch_candidates']} 位本批候选")
    added_keys = set(data.get("latest_batch_keys", []))
    record_seen_candidates({
        "generated_at": new_data.get("generated_at"),
        "candidates": [a for a in new_data.get("candidates", [])
                       if (a.get("sec_uid") or a.get("name")) in added_keys],
    })
    if max_pages > 50:
        advance_scan_state(new_data)
    rebuild_preference_profile(data=data)
    if replace_pending:
        message = (f"实时新增索引 {data.get('new_live_templates', 0)} 条模板；扫描 {data['indexed_templates']} 条模板，已替换 "
                   f"{data.get('replaced_pending_candidates', 0)} 位原待审作者；"
                   f"当前待审 {data['pending_queue']} 位。")
    else:
        message = (f"扫描 {data['indexed_templates']} 条模板，本次补充 "
                   f"{data['latest_batch_candidates']} 位；当前待审 {data['pending_queue']} 位。")
    return data, message, True


def discover(max_pages=1200, workers=10, force=False, cancel_event=None, progress=None,
             fresh=False):
    def raise_if_cancelled():
        if cancel_event and cancel_event.is_set():
            raise RefreshCancelled("已停止刷新，保留上一次候选结果")

    raise_if_cancelled()
    if progress:
        progress("发现入口", "正在读取 CapCut 舞蹈专题和热歌页面，寻找模板链接")
    seed_ids, live_summaries = get_seed_ids(quick=max_pages <= 50 or fresh,
                                            progress=progress, cancel_event=cancel_event)
    known_template_ids = set(read_json_file(SEEN_TEMPLATES, []))
    known_template_ids.update(path.stem for path in CACHE.glob("*.json"))
    for previous_author in read_json_file(RESULTS, {}).get("candidates", []):
        known_template_ids.update(str(work.get("template_id")) for work in previous_author.get("works", []))
    if fresh:
        seed_ids = [template_id for template_id in seed_ids if template_id in live_summaries]
        seed_ids.sort(key=lambda template_id: template_id in known_template_ids)
        if progress:
            unseen = sum(template_id not in known_template_ids for template_id in seed_ids)
            progress("发现入口", f"实时列表中有 {unseen} 条本地未索引模板，优先读取这些新模板")
    dance_seed_ids = set(seed_ids)
    if not seed_ids:
        raise RuntimeError("CapCut 页面没有返回模板链接，保留上次扫描结果")
    if progress:
        progress("发现入口", f"找到 {len(seed_ids)} 个模板入口，开始读取模板详情与作者资料")
    queue = list(seed_ids)
    queued = set(queue)
    chosen = []
    records = {}
    errors = []
    processed_templates = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while queue and len(chosen) < max_pages:
            raise_if_cancelled()
            batch = queue[:min(100, max_pages - len(chosen))]
            del queue[:len(batch)]
            chosen.extend(batch)
            jobs = {pool.submit(cached_template, template_id, force)
                    if not (fresh and template_id in live_summaries and
                            not (CACHE / f"{template_id}.json").exists())
                    else pool.submit(lambda item: {"detail": item, "recommendations": [],
                                                   "source": "live-list"}, live_summaries[template_id]): template_id
                    for template_id in batch}
            for job in as_completed(jobs):
                if cancel_event and cancel_event.is_set():
                    for pending_job in jobs:
                        pending_job.cancel()
                    raise_if_cancelled()
                result = job.result()
                processed_templates += 1
                template_id = jobs[job]
                author_name = ((result.get("detail") or {}).get("author") or {}).get("name", "")
                if progress:
                    label = f"，作者 {author_name}" if author_name else ""
                    source = "实时专题页" if template_id in live_summaries else ("本地详情缓存" if (CACHE / f"{template_id}.json").exists() else "详情页")
                    progress("模板抓取", f"{source}：模板 {template_id}{label}；已处理 {processed_templates}，上限 {max_pages}")
                if result.get("error"):
                    errors.append({"template_id": jobs[job], "error": result["error"]})
                items = [result.get("detail")]
                if not fresh:
                    items.extend(result.get("recommendations") or [])
                for item in items:
                    if not item:
                        continue
                    record = item_record(item)
                    if record:
                        live_item = live_summaries.get(record["template_id"])
                        if live_item:
                            live_record = item_record(live_item)
                            if live_record:
                                if record.get("author_name") == live_record["author_name"]:
                                    live_record["author_bio"] = record.get("author_bio", "")
                                record = live_record
                        record["dance_seed"] = record["template_id"] in dance_seed_ids
                        records[record["template_id"]] = record
                        if not fresh and record["template_id"] not in queued:
                            queue.append(record["template_id"])
                            queued.add(record["template_id"])

    raise_if_cancelled()
    authors = {}
    for record in records.values():
        key = record["sec_uid"] or record["author_name"]
        author = authors.setdefault(key, {
            "name": record["author_name"], "bio": record["author_bio"],
            "sec_uid": record["sec_uid"], "works": [], "cc_id": "", "cc_link": "",
            "total_posts": None, "tt_link": "", "profile_verified": False,
        })
        if len(record["author_bio"]) > len(author["bio"]):
            author["bio"] = record["author_bio"]
        author["works"].append(record)
    if progress:
        progress("作者筛选", f"已整理 {len(authors)} 位模板作者，开始核对地区、舞蹈与使用量信息")

    terms = exclusion_terms()
    candidates = []
    decisions = read_decisions()
    skipped_rejected = 0
    preference_profile = read_preferences()
    for author_index, author in enumerate(authors.values(), 1):
        raise_if_cancelled()
        if progress and (author_index == 1 or author_index % 10 == 0 or author_index == len(authors)):
            progress("作者筛选", f"正在核对作者 {author['name']} 的公开模板数据（{author_index}/{len(authors)}）")
        author_key = author.get("sec_uid") or author.get("name")
        # Being displayed before is not an exclusion: pending creators are
        # eligible for every new refresh. A human rejection is the only
        # decision that permanently removes a creator from the queue.
        if decisions.get(author_key, {}).get("status") == "rejected":
            skipped_rejected += 1
            continue
        if is_excluded(author, terms):
            continue
        all_works = sorted(author["works"], key=lambda w: (w.get("dance_seed") or w.get("dance_signal"), w["uses"]), reverse=True)
        # A template gets one week to accumulate usage. After day 7, fewer
        # than 1,000 uses is a hard exclusion from creator qualification.
        # The rule applies per template, so one old weak post does not erase a
        # creator who also has other qualifying dance work.
        works = [w for w in all_works if not w.get("stale_low_use")]
        stale_low_use_count = len(all_works) - len(works)
        non_ai = [w for w in works if not w["likely_ai"]]
        # A landing page is only a retrieval source.  CapCut mixes unrelated
        # popular templates into those pages, so page membership alone is not
        # evidence that a template actually contains dance content.
        explicit_dance = [w for w in non_ai
                          if w.get("dance_signal") and not w.get("non_dance_gimmick")]
        dance_non_ai = [w for w in non_ai
                        if (w.get("dance_seed") or w.get("dance_signal")) and not w.get("non_dance_gimmick")]
        # Usage evidence is only counted from explicitly identified dance
        # templates.  Visual seed matches remain discovery evidence until the
        # reviewer verifies the creator's full homepage.
        high = [w for w in explicit_dance if w["uses"] >= 3000]
        post_jp = sum(w["japanese_post"] for w in works)
        bio_jp = has_japanese(author["bio"])
        name_jp = has_japanese(author["name"])
        if not (post_jp or bio_jp or name_jp):
            continue
        if not dance_non_ai:
            continue
        author["works"] = works
        author["stale_low_use_excluded_count"] = stale_low_use_count
        author["indexed_count"] = len(works)
        author["high_use_non_ai_indexed"] = len(high)
        author["dance_non_ai_indexed"] = len(dance_non_ai)
        author["explicit_dance_indexed"] = len(explicit_dance)
        author["japanese_signal"] = "投稿文案" if post_jp else ("自我介绍" if bio_jp else "用户名")
        author["japanese_post_count"] = post_jp
        author["ai_flagged_count"] = sum(w["likely_ai"] for w in works)
        share = PROFILE_LINK.search(author["bio"])
        if share:
            author["profile_link_hint"] = share.group(0)
        score_author(author, preference_profile)
        candidates.append(author)
    candidates.sort(key=lambda a: a["score"], reverse=True)
    raise_if_cancelled()
    # Cheap metadata retrieval runs first. Only the strongest retrieval pool is
    # decoded with Apple Vision, then reranked against rejected video content.
    if progress:
        progress("视频分析", f"初筛出 {len(candidates)} 位作者，准备分析排名靠前的模板视频")
    analyze_retrieved_candidates(candidates, limit=80, progress=progress)
    raise_if_cancelled()
    for author in candidates[:min(80, len(candidates))]:
        raise_if_cancelled()
        score_author(author, preference_profile)
    # Keep explicit dance metadata.  For title-less music trends and other
    # landing-page seeds, require local video evidence of both people and
    # motion before the creator reaches the review queue.
    filtered = []
    for author in candidates:
        raise_if_cancelled()
        profile = author.get("video_content_profile", {})
        verified = video_supports_dance(profile)
        author["dance_video_verified"] = verified
        # If a video was decoded successfully, it must visibly support the
        # dance claim.  Metadata-only candidates survive only when decoding
        # failed and the title/description itself explicitly says dance.
        if verified or (not profile and author.get("explicit_dance_indexed", 0) > 0):
            filtered.append(author)
    candidates = filtered
    candidates.sort(key=lambda a: a["score"], reverse=True)
    if progress:
        progress("筛选完成", f"得到 {len(candidates)} 位符合条件的候选作者")
    live_template_ids = sorted(set(records).intersection(live_summaries))
    new_live_template_ids = [template_id for template_id in live_template_ids
                             if template_id not in known_template_ids]
    if progress:
        progress("实时更新", f"首次索引 {len(new_live_template_ids)} 条实时模板，历史已知 {len(live_template_ids) - len(new_live_template_ids)} 条")
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed_pages": len(chosen), "indexed_templates": len(records),
            "live_template_ids": live_template_ids,
            "new_live_template_ids": new_live_template_ids,
            "new_live_templates": len(new_live_template_ids),
            "errors": errors, "skipped_seen_creators": skipped_rejected,
            "reference_case_count": len(read_reference_cases().get("videos", [])),
            "scoring_policy": "正面案例审美70% + 数据质量30% + 审核反馈修正",
            "scoring_version": 2,
            "trend_terms": current_jp_tiktok_songs(),
            "candidates": candidates}


def read_decisions():
    return json.loads(DECISIONS.read_text(encoding="utf-8")) if DECISIONS.exists() else {}


def resolve_profile_link(link):
    parsed = urlparse(link.strip())
    if parsed.scheme != "https" or parsed.hostname != "mobile.capcutshare.com":
        raise ValueError("请粘贴 CapCut 主页分享链接")
    if parsed.path.startswith("/sv2/"):
        request = Request(link, headers={"User-Agent": "Mozilla/5.0 (iPhone)"})
        with urlopen(request, timeout=15) as response:
            parsed = urlparse(response.url)
    if parsed.hostname != "mobile.capcutshare.com" or parsed.path != "/imlv/personal-homepage":
        raise ValueError("这不是 CapCut 作者主页链接")
    public_id = parse_qs(parsed.query).get("publicid", [""])[0]
    if not public_id:
        raise ValueError("主页链接里没有作者标识")
    profile = capcut_post("/lv/v1/homepage/profile", {"public_id": public_id})
    user = profile.get("user") or {}
    stats = profile.get("user_statistics") or {}
    if not user.get("unique_id"):
        raise ValueError("CapCut 未返回 CC ID")
    tt = user.get("tiktok_user_info") or {}
    return {"name": user.get("name", ""), "cc_id": str(user["unique_id"]),
            "system_uid": str(user.get("uid") or ""),
            "total_posts": stats.get("template_count"),
            "tt_link": tt.get("link") or tt.get("url") or ""}


def enrich_profiles(data, progress=None, cancel_event=None):
    """Use only a verified creator homepage, never a generic CapCut short link."""
    changed = False
    checked = 0
    for author in data.get("candidates", []):
        if cancel_event and cancel_event.is_set():
            raise RefreshCancelled("已停止刷新，保留上一次候选结果")
        if author.get("profile_verified") or author.get("profile_link_checked"):
            continue
        link = author.get("profile_link_hint") or author.get("cc_link", "")
        if not link:
            continue
        checked += 1
        if progress:
            progress("作者主页", f"正在读取 {author['name']} 的 CapCut 主页：CC ID、投稿总数和 TT 链接")
        try:
            profile = resolve_profile_link(link)
            if profile["name"].strip().casefold() != author["name"].strip().casefold():
                raise ValueError("链接指向其他作者")
            author.update(cc_id=profile["cc_id"], cc_link=link,
                          total_posts=profile["total_posts"],
                          tt_link=profile["tt_link"], profile_verified=True)
            if progress:
                progress("作者主页", f"已核验 {author['name']} 的主页资料与投稿总数")
        except (ValueError, OSError):
            author["cc_link"] = ""
            if progress:
                progress("作者主页", f"{author['name']} 的主页链接未通过核验")
        author["profile_link_checked"] = True
        changed = True
    if progress and not checked:
        progress("作者主页", "候选作者没有可核验的主页分享链接，本轮仅使用公开模板资料")
    return changed


def terms_editor_text(terms):
    return "\n".join(f"{term} = {weight}" for term, weight in terms.items())


def parse_terms_editor(text):
    terms = {}
    for line_number, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"第 {line_number} 行需要使用：关键词 = 权重")
        term, weight = (part.strip() for part in line.rsplit("=", 1))
        if not term:
            raise ValueError(f"第 {line_number} 行缺少关键词")
        try:
            value = int(weight)
        except ValueError as exc:
            raise ValueError(f"第 {line_number} 行的权重必须是 0–10 的整数") from exc
        if not 0 <= value <= 10:
            raise ValueError(f"第 {line_number} 行的权重必须在 0–10 之间")
        terms[term.casefold()] = value
    return terms


def preference_change_summary(old_terms, new_terms, label):
    added = sorted(set(new_terms) - set(old_terms))
    removed = sorted(set(old_terms) - set(new_terms))
    changed = sorted(term for term in set(old_terms) & set(new_terms) if old_terms[term] != new_terms[term])
    parts = []
    if added:
        parts.append(f"{label}新增：" + "、".join(added))
    if removed:
        parts.append(f"{label}删除：" + "、".join(removed))
    if changed:
        parts.append(f"{label}调权：" + "、".join(f"{term} {old_terms[term]}→{new_terms[term]}" for term in changed))
    return parts


def apply_preference_edits(positive_terms, negative_terms, data):
    profile = read_preferences()
    derived_positive = profile.get("derived_positive_terms", profile.get("positive_terms", {}))
    derived_negative = profile.get("derived_negative_terms", profile.get("negative_terms", {}))
    old_positive = profile.get("positive_terms", {})
    old_negative = profile.get("negative_terms", {})

    def diff_from_derived(submitted, derived):
        overrides = {term: weight for term, weight in submitted.items() if derived.get(term) != weight}
        deleted = sorted(set(derived) - set(submitted))
        return overrides, deleted

    pos_overrides, pos_deleted = diff_from_derived(positive_terms, derived_positive)
    neg_overrides, neg_deleted = diff_from_derived(negative_terms, derived_negative)
    changes = (preference_change_summary(old_positive, positive_terms, "正向") +
               preference_change_summary(old_negative, negative_terms, "反向"))
    profile["term_overrides"] = {"positive": pos_overrides, "negative": neg_overrides}
    profile["deleted_terms"] = {"positive": pos_deleted, "negative": neg_deleted}
    profile["positive_terms"] = dict(sorted(positive_terms.items(), key=lambda item: (-item[1], item[0])))
    profile["negative_terms"] = dict(sorted(negative_terms.items(), key=lambda item: (-item[1], item[0])))
    profile["revision"] = int(profile.get("revision", 0)) + 1
    profile["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    history = profile.get("edit_history", [])
    history.append({"at": profile["updated_at"], "summary": "；".join(changes) if changes else "保存审美规则（内容未变）"})
    profile["edit_history"] = history[-50:]
    write_preferences(profile)
    rescore_candidates(data, relabel=False)
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def new_category_html(saved=False, error="", added=0):
    state = new_category_state()
    terms = list(state["positive_terms"].items())[:40]
    term_html = "".join(
        f'<span class="tag">{html.escape(term)} <b>{weight}</b></span>' for term, weight in terms
    ) or '<div class="empty">等待你导入第一批正面案例后开始学习。</div>'
    field_html = "".join(
        f'<span class="field">{html.escape(field)} · {count}</span>'
        for field, count in list(state["source_fields"].items())[:20]
    ) or '<span class="muted">暂无结构字段</span>'
    summary_html = "".join(
        f'<li><b>案例 {item.get("index", "")}</b><span>{html.escape(item.get("text", ""))}</span></li>'
        for item in state["case_summaries"][-12:]
    ) or '<li class="empty">尚未导入案例</li>'
    notice = (f'<div class="notice ok">已加入 {added} 条新正面案例，并完成自动解析。</div>' if saved else
              f'<div class="notice bad">{html.escape(error)}</div>' if error else '')
    return f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>新类别正面学习</title>
<style>
:root{{--ink:#172033;--muted:#687086;--line:#e4e8f0;--blue:#635bff;--green:#15815b;--shadow:0 16px 40px rgba(31,38,67,.08)}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;background:linear-gradient(135deg,#f6f4ff,#f5fbff 48%,#fafbfc);min-height:100vh}}main{{max-width:1180px;margin:auto;padding:28px}}.hero{{padding:30px 34px;border-radius:24px;color:#fff;background:linear-gradient(125deg,#1d2850,#5b59de 56%,#8b5cf6);box-shadow:var(--shadow)}}.eyebrow{{font-size:12px;letter-spacing:.13em;opacity:.75}}h1{{margin:5px 0 8px;font-size:30px}}.hero p{{margin:0;color:rgba(255,255,255,.84)}}.nav{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}.btn{{display:inline-flex;align-items:center;justify-content:center;padding:10px 15px;border:0;border-radius:11px;font:700 14px inherit;text-decoration:none;cursor:pointer}}.primary{{color:#fff;background:var(--blue)}}.subtle{{color:#4c5267;background:#fff;border:1px solid var(--line)}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.card,.section{{background:#fff;border:1px solid var(--line);border-radius:17px;box-shadow:var(--shadow)}}.card{{padding:20px}}.card b{{display:block;margin:4px 0;font-size:26px}}.muted,.card span{{color:var(--muted)}}.section{{margin-top:16px;padding:22px}}.section h2{{margin:0 0 7px;font-size:19px}}label{{display:block;margin:12px 0 6px;font-weight:700}}input[type=text],textarea{{width:100%;padding:11px 12px;border:1px solid #d7dce8;border-radius:10px;font:inherit;outline:none}}textarea{{min-height:210px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}input:focus,textarea:focus{{border-color:#7770f0;box-shadow:0 0 0 3px rgba(99,91,255,.12)}}input[type=file]{{display:block;margin:8px 0 12px}}.tag,.field{{display:inline-block;margin:5px 6px 0 0;padding:6px 9px;border-radius:999px;background:#f0efff;color:#5049c6}}.field{{background:#f1f5f9;color:#4d5870}}.tag b{{color:#252166}}.empty{{padding:14px;border-radius:10px;background:#f7f8fb;color:var(--muted)}}.notice{{margin:16px 0;padding:12px 14px;border-radius:11px}}.ok{{color:#116c4c;background:#e9f8f1}}.bad{{color:#a33243;background:#fff0f2}}ul{{margin:10px 0 0;padding:0;list-style:none}}li{{display:grid;grid-template-columns:85px 1fr;gap:12px;padding:11px 0;border-top:1px solid #edf0f5}}li span{{color:#555f75}}@media(max-width:720px){{main{{padding:14px}}.grid{{grid-template-columns:1fr}}.hero{{padding:24px}}li{{grid-template-columns:1fr}}}}
</style><body><main>
<section class="hero"><div class="eyebrow">CAPCUT · NEW CATEGORY · POSITIVE LEARNING</div><h1>{html.escape(state["category_name"])}</h1><p>这是独立的新类别工作区。当前只学习正面案例，不继承舞蹈审美，也不建立反向提示词。</p></section>
<nav class="nav"><a class="btn subtle" href="/">返回舞蹈创作者界面</a><a class="btn primary" href="#feed">导入正面案例</a></nav>{notice}
<section class="grid"><div class="card"><span>已吸收正面案例</span><b>{state["case_count"]}</b><span>条</span></div><div class="card"><span>正面审美档案</span><b>v{state["revision"]}</b><span>{html.escape(state["updated_at"])}</span></div><div class="card"><span>反向提示词</span><b>0</b><span>此类别不启用</span></div></section>
<section class="section"><h2>当前学到的正面特征</h2><p class="muted">系统从你提供的结构化案例中自动汇总重复出现的风格、包装、节奏、内容和制作特征。</p><div>{term_html}</div></section>
<section class="section"><h2>已识别的数据维度</h2><div>{field_html}</div></section>
<form id="feed" method="post" action="/new-category/positive-cases"><section class="section"><h2>喂入正面案例</h2><p class="muted">支持 JSON 数组，或包含 videos、cases、examples、items、data、positive_cases 数组的 JSON 对象。重复案例不会再次加入。</p><label>类别名称</label><input name="category_name" type="text" value="{html.escape(state["category_name"])}" placeholder="例如：旅行模板创作者"><label>选择 JSON 文件</label><input id="jsonFile" type="file" accept=".json,application/json"><label>或粘贴 JSON</label><textarea id="jsonPayload" name="json_payload" placeholder='[{{"style":"……","rhythm":"……"}}]'></textarea><button class="btn primary" type="submit">导入并自动学习</button></section></form>
<section class="section"><h2>最近吸收的案例内容</h2><ul>{summary_html}</ul></section>
<script>document.querySelector('#jsonFile').addEventListener('change',async e=>{{const file=e.target.files[0];if(file)document.querySelector('#jsonPayload').value=await file.text();}});</script>
</main></body></html>'''


def aesthetic_html(data, saved=False, error=""):
    profile = read_preferences()
    visual_learning = read_json_file(VISUAL_LEARNING, {}).get("rejected_profiles", {})
    visual_items = list(visual_learning.values())
    visual_video_count = sum(int(item.get("video_profile", {}).get("video_count", 0)) for item in visual_items)
    visual_scoring_count = sum(bool(item.get("affects_visual_score")) for item in visual_items)
    visual_labels = {}
    for item in visual_items:
        for label, confidence in item.get("video_profile", {}).get("labels", {}).items():
            visual_labels[label] = visual_labels.get(label, 0) + float(confidence)
    top_visual_labels = sorted(visual_labels.items(), key=lambda pair: -pair[1])[:12]
    visual_label_html = "".join(f'<span class="tag">{html.escape(label)}</span>' for label, _ in top_visual_labels) or "尚未完成视频内容分析"
    reference_count = len(read_reference_cases().get("videos", []))
    positive_terms = profile.get("positive_terms", {})
    negative_terms = profile.get("negative_terms", {})
    positive_feedback = [item.get("text", "") for item in profile.get("positive_phrases", []) if item.get("text")]
    negative_feedback = [item.get("text", "") for item in profile.get("negative_prompts", []) if item.get("text")]
    absorbed = len(positive_feedback) + len(negative_feedback)
    learned_content = "".join(f"<li>{html.escape(text)}</li>" for text in positive_feedback) or "<li>暂无有效正向描述</li>"
    rejected_content = "".join(f"<li>{html.escape(text)}</li>" for text in negative_feedback) or "<li>暂无反向原因</li>"
    history = "".join(
        f'<li><time>{html.escape(item.get("at", ""))}</time>{html.escape(item.get("summary", ""))}</li>'
        for item in reversed(profile.get("edit_history", [])[-12:])
    ) or "<li>尚无手动修改记录</li>"
    notice = ("<div class='notice ok'>已保存，所有候选人匹配度已重新计算。</div>" if saved else
              f"<div class='notice bad'>{html.escape(error)}</div>" if error else "")
    return f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>审美学习机制</title>
<style>
:root{{--ink:#172033;--muted:#687086;--line:#e4e8f0;--panel:#fff;--blue:#635bff;--purple:#8b5cf6;--green:#15945c;--red:#bd4052;--amber:#9a6700;--shadow:0 16px 40px rgba(31,38,67,.08)}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;background:linear-gradient(135deg,#f5f3ff,#f7fbff 42%,#f8fafc);min-height:100vh}}main{{max-width:1280px;margin:auto;padding:28px}}a{{color:#5148d8}}.hero{{color:#fff;padding:28px 32px;border-radius:22px;background:linear-gradient(125deg,#27215f,#635bff 54%,#a855f7);box-shadow:var(--shadow)}}.hero h1{{margin:4px 0 7px;font-size:28px}}.hero p{{margin:0;color:rgba(255,255,255,.84)}}.top{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}}.btn{{display:inline-flex;align-items:center;border:0;border-radius:10px;padding:9px 13px;color:#4d5265;background:#eef0f6;font:inherit;font-weight:650;text-decoration:none;cursor:pointer}}.primary{{color:#fff;background:linear-gradient(120deg,var(--blue),var(--purple))}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card,.section{{border:1px solid var(--line);border-radius:18px;background:var(--panel);box-shadow:var(--shadow)}}.card{{padding:18px}}.card b{{display:block;margin-top:5px;font-size:24px}}.muted{{color:var(--muted)}}.formula{{display:grid;grid-template-columns:7fr 3fr;overflow:hidden;height:18px;margin:12px 0;border-radius:999px;background:#eef0f6}}.formula span:first-child{{background:#7067f5}}.formula span:last-child{{background:#52b788}}.legend{{display:flex;justify-content:space-between;gap:14px;color:var(--muted)}}.section{{margin-top:16px;padding:22px}}.section h2{{margin:0 0 4px}}.edit-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}textarea{{width:100%;min-height:240px;margin-top:8px;padding:12px;border:1px solid #d9deea;border-radius:12px;font:14px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical}}textarea:focus{{outline:0;border-color:#827af7;box-shadow:0 0 0 3px rgba(99,91,255,.12)}}.help{{color:var(--muted);font-size:12px}}.feedback{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.tag{{display:inline-block;margin:5px 6px 0 0;padding:4px 9px;border-radius:999px;color:#5148d8;background:#eeecff}}ul{{margin:10px 0 0;padding-left:20px}}li{{margin:6px 0}}time{{display:inline-block;min-width:145px;color:var(--muted)}}.notice{{padding:12px 14px;border-radius:12px;margin:12px 0}}.ok{{color:#087142;background:#dff7ea}}.bad{{color:#9f2639;background:#ffe4e8}}@media(max-width:800px){{main{{padding:14px}}.grid{{grid-template-columns:1fr 1fr}}.edit-grid,.feedback{{grid-template-columns:1fr}}}}@media(max-width:480px){{.grid{{grid-template-columns:1fr}}}}
</style><body><main>
<section class="hero"><div>CAPCUT · AESTHETIC LEARNING</div><h1>审美学习机制</h1><p>只展示学习进度、具体内容和计分影响，不展示作者名单。</p></section>
<div class="top"><a class="btn" href="/">← 返回作者审核</a><span class="muted">最近更新：{html.escape(profile.get("updated_at", "尚未更新"))}</span></div>{notice}
<section class="grid"><div class="card"><span class="muted">正面案例</span><b>{reference_count}/26</b><span>已载入</span></div><div class="card"><span class="muted">已吸收审核反馈</span><b>{absorbed}</b><span>{len(positive_feedback)} 条正向 · {len(negative_feedback)} 条反向原文完整保留</span></div><div class="card"><span class="muted">当前有效规则</span><b>{len(positive_terms)+len(negative_terms)}</b><span>{len(positive_terms)} 条加分 · {len(negative_terms)} 条扣分</span></div><div class="card"><span class="muted">审美档案版本</span><b>v{profile.get("revision", profile.get("version", 1))}</b><span>持续学习中</span></div></section>
<section class="section"><h2>当前计分逻辑</h2><div class="formula"><span></span><span></span></div><div class="legend"><span>正面案例审美 70%</span><span>数据质量 30%</span></div><p class="muted">审核学习额外修正：每 1 点正向权重 +2 分，每 1 点反向权重 -4 分，最终修正限制在 -30 至 +30 分。</p></section>
<section class="section"><h2>反向视频内容学习</h2><p><b>{len(visual_items)}</b> 份负面视觉档案 · <b>{visual_video_count}</b> 条模板视频 · <b>{visual_scoring_count}</b> 条理由会影响视频内容扣分</p><p class="muted">本地 Apple Vision 会对模板视频抽帧，学习人物出现、面部比例、镜头变化和画面标签。新候选只有高于舞蹈视频的共性基线时才扣分。</p><div>{visual_label_html}</div></section>
<form method="post" action="/preferences"><section class="section"><h2>修改当前审美规则</h2><p class="muted">每行一条，格式为“关键词 = 权重”。权重范围 0–10；删掉整行即删除该规则。</p><div class="edit-grid"><label><b>正向加分内容</b><textarea name="positive_terms">{html.escape(terms_editor_text(positive_terms))}</textarea><span class="help">用于“喜欢什么”，命中后加分。</span></label><label><b>反向扣分内容</b><textarea name="negative_terms">{html.escape(terms_editor_text(negative_terms))}</textarea><span class="help">每条不通过原因完整保留，同时拆出语义片段和可匹配关键词。</span></label></div><div class="top"><button class="btn primary" type="submit">保存并重新计算匹配度</button></div></section></form>
<section class="section"><h2>已学到的具体内容</h2><div class="feedback"><div><b>正向审美描述</b><ul>{learned_content}</ul></div><div><b>反向原因</b><ul>{rejected_content}</ul></div></div></section>
<section class="section"><h2>手动修改记录</h2><ul>{history}</ul></section>
</main></body></html>'''


def review_html(data, decisions, view="pending"):
    rows = []
    # Always show the 30 ranked recommendations first, ordered from the
    # highest score to the lowest. Exploration samples follow afterwards.
    ordered_candidates = sorted(
        data["candidates"],
        key=lambda c: (
            1 if c.get("recommendation_type") == "随机探索" else 0,
            -float(c.get("score", 0)),
            int(c.get("match_rank", 10**9)),
        ),
    )
    if view in {"pending", "approved", "aesthetic_only", "rejected"}:
        ordered_candidates = [
            c for c in ordered_candidates
            if decisions.get(c["sec_uid"] or c["name"], {}).get("status", "pending") == view
        ]
    for i, c in enumerate(ordered_candidates):
        key = c["sec_uid"] or c["name"]
        decision = decisions.get(key, {})
        works = c["works"][:12]
        links = "".join(
            '<div class="preview-item">'
            + (f'<video class="preview-video" src="{html.escape(w["video_url"], quote=True)}" '
               f'poster="{html.escape(w.get("cover_url", ""), quote=True)}" muted playsinline '
               'preload="none" tabindex="0" role="button" aria-label="播放或暂停作品预览"></video>'
               if w.get("video_url") else
               (f'<img class="preview-image" src="{html.escape(w.get("cover_url", ""), quote=True)}" '
                'loading="lazy" alt="作品封面">' if w.get("cover_url") else ""))
            + '<div class="preview-caption">'
            + f'<a target="_blank" rel="noopener noreferrer" href="{html.escape(w["url"], quote=True)}">'
            + f'{html.escape(w["title"][:45]) or w["template_id"]}</a>'
            + f' — {w["uses"]:,} uses' + (" 💃舞蹈" if w.get("dance_seed") or w.get("dance_signal") else "")
            + (" ⚠AI?" if w["likely_ai"] else "") + '</div></div>' for w in works
        )
        checked = "checked" if decision.get("non_ai_confirmed") else ""
        dance_checked = "checked" if decision.get("dance_confirmed") else ""
        priority = decision.get("priority", "P1")
        recommendation = c.get("recommendation_type", "高匹配")
        badge_class = "explore" if recommendation == "随机探索" else "match"
        video_profile = c.get("video_content_profile", {})
        video_evidence = ""
        if video_profile:
            penalty = c.get("negative_video_penalty", 0)
            reason = c.get("negative_video_reason", "")
            video_evidence = (f'<br><small>视频内容复核：已分析 {video_profile.get("video_count", 0)} 条'
                              f'；负面视觉相似扣分 {penalty}'
                              + (f'；对应提示：{html.escape(reason)}' if penalty and reason else '') + '</small>')
        rows.append(f'''<tr data-status="{html.escape(decision.get("status", "pending"))}" data-key="{html.escape(key, quote=True)}">
          <td><span class="rank">{i+1}</span></td><td><strong class="creator-name">{html.escape(c["name"])}</strong><br><span class="badge {badge_class}">{html.escape(recommendation)}</span><span class="score">综合 {c.get("score", 0)} · 审美 {c.get("reference_match_score", 0)} · 数据 {c.get("quality_data_score", 0)}</span><br><small>正面案例依据：{html.escape("、".join(c.get("reference_match_evidence", [])) or "仅结构代理，待人工审核")}</small>{video_evidence}<br><small>{html.escape(c["bio"][:180])}</small></td>
          <td>{html.escape(c["japanese_signal"])}<br>已索引舞蹈：{c.get("dance_non_ai_indexed", 0)} 条；舞蹈/非AI且≥3k：{c["high_use_non_ai_indexed"]} 条<br>满7天且 uses&lt;1000 已排除：{c.get("stale_low_use_excluded_count", 0)} 条<br>主页总投稿：{c["total_posts"] or "待核"}</td>
          <td>{links}</td>
          <td><input aria-label="CC ID" placeholder="主页显示的 CapCut ID（不是昵称）" value="{html.escape(decision.get("cc_id", c["cc_id"]), quote=True)}"><br>
              <input aria-label="CC主页" placeholder="粘贴主页分享链接，自动提取ID" value="{html.escape(decision.get("cc_link", c["cc_link"]), quote=True)}"><br>
              <button class="btn subtle" onclick="lookup(this)">从主页链接读取 ID 和投稿数</button><br>
              <input aria-label="TT主页" placeholder="TT主页链接（可空）" value="{html.escape(decision.get("tt_link", c.get("tt_link", "")), quote=True)}"><br>
              <label>主页投稿总数（仅供参考） <input aria-label="投稿总数" type="number" min="0" value="{html.escape(str(decision.get("total_posts", c.get("total_posts") if c.get("total_posts") is not None else "")), quote=True)}"></label>
              <label>≥3000 uses 的非AI舞蹈模板数（仅供排序参考） <input aria-label="达标投稿数" type="number" min="0" value="{html.escape(str(decision.get("high_use_posts", c["high_use_non_ai_indexed"])), quote=True)}"></label>
              <label><input aria-label="确认非AI" type="checkbox" {checked}> 已确认以非AI模板为主</label><br>
              <label><input aria-label="确认舞蹈" type="checkbox" {dance_checked}> 已确认主要产出优质舞蹈模板</label><br>
              <label>内部优先级 <select aria-label="优先级"><option value="P0" {"selected" if priority == "P0" else ""}>P0 高审美/稳定舞蹈型</option><option value="P1" {"selected" if priority == "P1" else ""}>P1 热点/专长舞蹈型</option></select></label><br>
              <textarea aria-label="舞蹈类型" placeholder="舞蹈类型与素材：单人/双人/群舞、手势舞、偶像舞等">{html.escape(decision.get("specialty", ""))}</textarea><br>
              <textarea aria-label="包装与节奏" placeholder="包装、节奏、构图、替换性和做得好的case">{html.escape(decision.get("aesthetic_notes", ""))}</textarea><br>
              <textarea aria-label="不通过原因" placeholder="不通过原因（会自动加入反向提示词）">{html.escape(decision.get("rejection_reason", ""))}</textarea><br>
              <div class="review-actions"><button class="btn approve" onclick="save(this,'approved')">通过</button>
              <button class="btn potential" onclick="save(this,'aesthetic_only')">审美达标·数据不足</button>
              <button class="btn reject" onclick="save(this,'rejected')">排除</button>
              <button class="btn subtle" onclick="save(this,'pending')">待审</button></div></td></tr>''')
    trend_summary = '、'.join(data.get("trend_terms", [])[:5])
    summary = (f'每次刷新都会替换整批待审作者；未审核作者可能再次出现，只有人工排除的作者不会再次进入队列。发布满7天且 uses 仍低于1000的模板会自动排除。已完成审核记录会保留。'
               f'匹配度已结合 {data.get("reference_case_count", 0)} 条正面案例，按审美70%和数据质量30%计算。'
               + (f'本轮日本 TikTok 热歌入口：{html.escape(trend_summary)}。' if trend_summary else '') +
               f'本次从实时专题页首次索引 {data.get("new_live_templates", 0)} 条模板。'
               f'本批待审 {data.get("latest_batch_candidates", len(data.get("candidates", [])))} 位，'
               f'其中高匹配 {data.get("latest_ranked_candidates", 30)} 位、随机探索 {data.get("latest_random_candidates", 20)} 位。'
               f'累计保留 {len(data.get("candidates", []))} 位，扫描时跳过已排除作者 '
               f'{data.get("skipped_seen_creators", 0)} 位。')
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>舞蹈创作者审核</title>
<style>
.refresh-log-panel{margin:0 0 16px;padding:14px 16px;border:1px solid #dce2ef;border-radius:16px;background:#fff;box-shadow:0 8px 24px rgba(31,38,67,.06)}.refresh-log-panel[hidden]{display:none}.refresh-log-panel h2{margin:0 0 9px;font-size:15px}.refresh-log-entries{max-height:250px;overflow-y:auto;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}.refresh-log-entry{display:grid;grid-template-columns:64px 84px minmax(0,1fr);gap:8px;padding:5px 0;border-top:1px solid #edf0f6;overflow-wrap:anywhere}.refresh-log-entry time{color:#777f91}.refresh-log-entry strong{color:#5751c3}@media(max-width:700px){.refresh-log-entry{grid-template-columns:56px minmax(0,1fr)}.refresh-log-entry span{grid-column:1/-1}}
body{overflow-x:hidden}main,.table-wrap{min-width:0}.table-wrap{overflow-x:hidden!important;overflow-y:visible!important}table{width:100%;min-width:0!important;table-layout:fixed}th:nth-child(1){width:4%}th:nth-child(2){width:17%}th:nth-child(3){width:18%}th:nth-child(4){width:32%}th:nth-child(5){width:29%}td,th{min-width:0!important;overflow-wrap:anywhere}td input,td textarea,td select{max-width:100%}.preview-item{margin:0 0 14px}.preview-video,.preview-image{display:block;width:104px;height:148px;max-width:100%;margin:0 0 7px;object-fit:contain;cursor:pointer}.preview-video.expanded{width:100%;height:auto;max-height:70vh;aspect-ratio:9/16;background:#111}.preview-caption{line-height:1.5;overflow-wrap:anywhere}@media(max-width:760px){table,tbody,tr{width:100%}td:nth-child(n){width:auto;min-width:0!important}.preview-video.expanded{max-height:65vh}}
:root{--ink:#172033;--muted:#687086;--line:#e4e8f0;--panel:#fff;--blue:#635bff;--blue2:#8b5cf6;--green:#15945c;--red:#d34b5d;--shadow:0 16px 40px rgba(31,38,67,.08)}*{box-sizing:border-box}body{margin:0;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;background:linear-gradient(135deg,#f5f3ff 0,#f7fbff 40%,#f8fafc 100%);min-height:100vh}main{max-width:1800px;margin:auto;padding:28px}.hero{position:relative;overflow:hidden;color:#fff;padding:28px 32px;border-radius:22px;background:linear-gradient(125deg,#27215f,#635bff 54%,#a855f7);box-shadow:var(--shadow)}.hero:after{content:"";position:absolute;width:320px;height:320px;border-radius:50%;right:-80px;top:-160px;background:rgba(255,255,255,.13)}.eyebrow{font-size:12px;letter-spacing:.16em;text-transform:uppercase;opacity:.72}.hero h1{font-size:28px;margin:5px 0 8px}.hero p{max-width:1050px;margin:0;color:rgba(255,255,255,.84)}.toolbar{position:sticky;top:0;z-index:8;display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:18px 0 14px;padding:12px 14px;border:1px solid rgba(228,232,240,.9);border-radius:16px;background:rgba(255,255,255,.92);backdrop-filter:blur(14px);box-shadow:0 8px 24px rgba(31,38,67,.06)}.btn,.download{appearance:none;border:0;border-radius:10px;padding:9px 13px;font-weight:650;cursor:pointer;text-decoration:none;transition:.15s ease}.btn:hover,.download:hover{transform:translateY(-1px)}.btn:disabled{opacity:.55;cursor:wait;transform:none}.primary{color:#fff;background:linear-gradient(120deg,var(--blue),var(--blue2));box-shadow:0 6px 16px rgba(99,91,255,.25)}.subtle,.download{color:#4d5265;background:#eef0f6}.approve{color:#087142;background:#dff7ea}.potential{color:#765800;background:#fff0b8}.reject{color:#a62f42;background:#ffe4e8}.refresh-status{color:var(--muted);margin-left:auto}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:18px;background:var(--panel);box-shadow:var(--shadow)}table{border-collapse:separate;border-spacing:0;width:100%;min-width:1260px}td,th{border-bottom:1px solid var(--line);padding:14px 12px;vertical-align:top;text-align:left}th{position:sticky;top:0;z-index:5;color:#596176;background:#f5f7fb;font-size:12px;letter-spacing:.04em}tr:last-child td{border-bottom:0}tbody tr{transition:.18s background}tbody tr:hover{background:#fafbff}td:nth-child(2){min-width:180px}td:nth-child(3){min-width:190px}td:nth-child(4){min-width:390px}td:nth-child(5){min-width:270px}.rank{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:9px;color:#5f59d9;background:#eeecff;font-weight:750}.creator-name{font-size:16px}.badge{display:inline-block;margin:7px 7px 7px 0;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:700}.badge.match{color:#5148d8;background:#eae8ff}.badge.explore{color:#9a5b00;background:#fff1ce}.score,small{color:var(--muted)}input,textarea,select{width:100%;margin:4px 0;padding:9px 10px;border:1px solid #d9deea;border-radius:9px;background:#fff;color:var(--ink);font:inherit;outline:none}input:focus,textarea:focus,select:focus{border-color:#827af7;box-shadow:0 0 0 3px rgba(99,91,255,.12)}input[type=checkbox]{width:auto;accent-color:var(--blue)}textarea{height:72px;resize:vertical}.review-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}a{color:#5148d8}img,video{width:100px;height:142px;object-fit:cover;vertical-align:middle;margin:6px 9px 6px 0;border-radius:11px;background:#111;box-shadow:0 4px 12px rgba(20,25,45,.12)}tr[data-status=approved]{background:#f0fbf5}tr[data-status=aesthetic_only]{background:#fffaf0}tr[data-status=rejected]{background:#fff6f7;opacity:.62}#msg{color:#3f4660;font-weight:600}@media(max-width:700px){main{padding:14px}.hero{padding:22px}.hero h1{font-size:22px}.refresh-status{width:100%;margin-left:0}}
@media(max-width:1050px){.toolbar{top:6px}.table-wrap{overflow:visible;border:0;background:transparent;box-shadow:none}table{display:block;min-width:0}thead{display:none}tbody{display:grid;gap:14px}tr{display:block;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:#fff;box-shadow:0 10px 26px rgba(31,38,67,.07)}td{display:block;min-width:0!important;padding:12px 14px;border-bottom:1px solid #edf0f6}td:last-child{border-bottom:0}td:nth-child(1){float:left;width:54px;border:0;padding-top:16px}td:nth-child(2){margin-left:54px;padding-left:0}td:nth-child(n+3):before{display:block;margin-bottom:7px;color:#858ca0;font-size:11px;font-weight:750;letter-spacing:.08em}td:nth-child(3):before{content:"筛选证据"}td:nth-child(4):before{content:"作品预览"}td:nth-child(5):before{content:"审核信息"}img,video{width:88px;height:125px}.review-actions{position:sticky;bottom:8px;padding:8px;border-radius:12px;background:rgba(255,255,255,.94);box-shadow:0 5px 18px rgba(31,38,67,.1)}}
</style><body><main>
<section class="hero"><div class="eyebrow">CAPCUT · JAPAN · DANCE</div><h1>舞蹈模板创作者审核</h1><p>''' + summary + '''</p></section>
<nav class="toolbar"><button id="refreshBtn" class="btn primary" onclick="manualRefresh()">↻ 手动刷新候选</button><a class="btn subtle" href="/?view=pending">只看待审</a><a class="btn approve" href="/?view=approved">只看通过</a><a class="btn subtle" href="/?view=all">查看全部</a><a class="btn potential" href="/aesthetic">舞蹈审美机制</a><a class="btn subtle" href="/new-category">新类别工作区</a><a class="download" href="/export.csv">下载已通过表格</a><span id="msg"></span><span id="refreshStatus" class="refresh-status">准备就绪</span></nav>
<section id="refreshLogPanel" class="refresh-log-panel" hidden><h2>刷新日志</h2><div id="refreshLogEntries" class="refresh-log-entries" role="log" aria-live="polite"></div></section>
<div class="table-wrap"><table><thead><tr><th>#</th><th>作者</th><th>日文和数量证据</th><th>作品预览</th><th>审核</th></tr></thead><tbody>''' + "\n".join(rows) + '''</tbody></table></div>
<script>
async function save(button,status){const row=button.closest('tr'),td=button.closest('td'), inputs=td.querySelectorAll('input'),areas=td.querySelectorAll('textarea'),body={key:row.dataset.key,status,cc_id:inputs[0].value,cc_link:inputs[1].value,tt_link:inputs[2].value,total_posts:inputs[3].value,high_use_posts:inputs[4].value,non_ai_confirmed:inputs[5].checked,dance_confirmed:inputs[6].checked,priority:td.querySelector('select').value,specialty:areas[0].value,aesthetic_notes:areas[1].value,rejection_reason:areas[2].value};const r=await fetch('/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(r.ok){row.dataset.status=status;document.querySelector('#msg').textContent=status==='rejected'?'已保存，原因已加入反向提示词':status==='aesthetic_only'?'已保存为审美达标、数据不足，并更新审美档案':'已保存并更新舞蹈审美档案';return true;}alert(await r.text());return false;}
async function lookup(button){const td=button.closest('td'),inputs=td.querySelectorAll('input'),link=inputs[1].value.trim();if(!link){alert('先粘贴主页分享链接');return;}button.disabled=true;button.textContent='正在读取…';try{const r=await fetch('/resolve-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({link})});if(!r.ok)throw Error(await r.text());const p=await r.json();if(!inputs[0].value.trim())inputs[0].value=p.cc_id||'';inputs[2].value=inputs[2].value||p.tt_link||'';inputs[3].value=p.total_posts||'';await save(button,button.closest('tr').dataset.status);document.querySelector('#msg').textContent='主页：'+p.name+'；投稿数已保存。已有 CC ID 保持原值。';}catch(e){alert('读取失败：'+e.message);}finally{button.disabled=false;button.textContent='从主页链接读取 ID 和投稿数';}}
function closePreview(video){video.pause();video.classList.remove('expanded');video.setAttribute('aria-label','播放或暂停作品预览');}
async function togglePreview(video){if(video.paused){document.querySelectorAll('.preview-video.expanded').forEach(other=>{if(other!==video)closePreview(other)});video.classList.add('expanded');video.setAttribute('aria-label','暂停作品预览');try{await video.play()}catch(e){closePreview(video)}}else{video.pause();video.setAttribute('aria-label','播放作品预览')}}
document.addEventListener('click',event=>{const video=event.target.closest('.preview-video');if(video){togglePreview(video);return}document.querySelectorAll('.preview-video.expanded').forEach(closePreview)});
document.addEventListener('keydown',event=>{if(event.target.matches('.preview-video')&&(event.key==='Enter'||event.key===' ')){event.preventDefault();togglePreview(event.target)}});
function filter(which){document.querySelectorAll('tbody tr').forEach(r=>r.style.display=which==='all'||r.dataset.status===which?'':'none');}
let refreshTimer=null;
function renderRefreshLog(state){const panel=document.querySelector('#refreshLogPanel'),entries=document.querySelector('#refreshLogEntries'),logs=state.logs||[];panel.hidden=logs.length===0;if(!logs.length)return;const atBottom=entries.scrollTop+entries.clientHeight>=entries.scrollHeight-20;entries.replaceChildren(...logs.map(item=>{const line=document.createElement('div');line.className='refresh-log-entry';const time=document.createElement('time');time.textContent=item.time;const stage=document.createElement('strong');stage.textContent=item.stage;const detail=document.createElement('span');detail.textContent=item.message;line.append(time,stage,detail);return line}));if(atBottom)entries.scrollTop=entries.scrollHeight;}
function setRefreshButton(running,stopping=false){const b=document.querySelector('#refreshBtn');b.disabled=stopping;b.textContent=running?(stopping?'正在停止…':'■ 停止刷新'):'↻ 手动刷新候选';}
async function manualRefresh(){const b=document.querySelector('#refreshBtn'),s=document.querySelector('#refreshStatus');if(b.dataset.running==='true'){b.disabled=true;s.textContent='正在请求停止刷新…';try{const r=await fetch('/refresh/cancel',{method:'POST'});if(!r.ok)throw Error(await r.text());pollRefresh(false);}catch(e){b.disabled=false;s.textContent='停止失败：'+e.message;}return;}b.disabled=true;s.textContent='正在启动大范围扫描…';try{const r=await fetch('/refresh',{method:'POST'});if(!r.ok)throw Error(await r.text());b.dataset.running='true';setRefreshButton(true);pollRefresh();}catch(e){b.disabled=false;s.textContent='启动失败：'+e.message;}}
async function pollRefresh(reloadOnFinish=true){const b=document.querySelector('#refreshBtn'),s=document.querySelector('#refreshStatus');if(refreshTimer)clearTimeout(refreshTimer);try{const r=await fetch('/refresh-status');const state=await r.json();renderRefreshLog(state);s.textContent=state.message+(state.running&&state.elapsed_seconds!==undefined?' · '+state.elapsed_seconds+' 秒':'');if(state.running){b.dataset.running='true';setRefreshButton(true,Boolean(state.cancel_requested));refreshTimer=setTimeout(()=>pollRefresh(true),1000);return;}b.dataset.running='false';setRefreshButton(false);if(state.finished&&reloadOnFinish){s.textContent=state.message+' 正在载入…';setTimeout(()=>location.reload(),900);}}catch(e){b.dataset.running='false';setRefreshButton(false);s.textContent='状态读取失败：'+e.message;}}
pollRefresh(false);
</script></main></body></html>'''


def serve(data, port=8765, open_browser=True):
    DATA.mkdir(exist_ok=True)
    lock = threading.Lock()
    refresh_lock = threading.Lock()
    refresh_state = {"running": False, "message": "可以刷新", "logs": [], "finished": False,
                     "error": False, "cancel_requested": False, "started_at": 0,
                     "cancel_event": None}

    def push_progress(stage, message):
        with refresh_lock:
            if not refresh_state["cancel_requested"] or stage in {"已停止", "失败", "完成"}:
                refresh_state["message"] = message
            refresh_state["logs"].append({
                "time": time.strftime("%H:%M:%S"), "stage": stage, "message": message,
            })
            refresh_state["logs"] = refresh_state["logs"][-200:]

    def refresh_worker(cancel_event):
        try:
            _, message, changed = run_incremental_refresh(
                1200, replace_pending=True, cancel_event=cancel_event,
                progress=push_progress)
            push_progress("完成", message)
            with refresh_lock:
                refresh_state.update(running=False, message=message, finished=changed, error=False)
        except RefreshCancelled as exc:
            push_progress("已停止", str(exc))
            with refresh_lock:
                refresh_state.update(running=False, message=str(exc), finished=False, error=False)
        except Exception as exc:
            push_progress("失败", f"刷新失败：{exc}")
            with refresh_lock:
                refresh_state.update(running=False, message=f"刷新失败：{exc}", finished=False, error=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            current = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else data
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/health":
                payload = f"CapCutCreatorReview:{ROOT}".encode("utf-8")
                self.send_response(200);self.send_header("Content-Type", "text/plain; charset=utf-8")
            elif path == "/refresh-status":
                with refresh_lock:
                    state = {key: value for key, value in refresh_state.items() if key != "cancel_event"}
                    if state["running"] and state.get("started_at"):
                        state["elapsed_seconds"] = int(time.time() - state["started_at"])
                    payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
                self.send_response(200);self.send_header("Content-Type", "application/json; charset=utf-8")
            elif path == "/export.csv":
                import io
                stream = io.StringIO()
                writer = csv.writer(stream)
                writer.writerow(["CC用户名称", "CC ID", "CC主页link", "TT主页link", "作者擅长类型"])
                decisions = read_decisions()
                for c in current["candidates"]:
                    d = decisions.get(c["sec_uid"] or c["name"], {})
                    if d.get("status") == "approved":
                        specialty = "；".join(x for x in [d.get("specialty", ""), d.get("aesthetic_notes", "")] if x)
                        writer.writerow([c["name"], d.get("cc_id", ""), d.get("cc_link", ""), d.get("tt_link", ""), specialty])
                payload = stream.getvalue().encode("utf-8-sig")
                self.send_response(200);self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="capcut-approved.csv"')
            elif path == "/aesthetic":
                query = parse_qs(parsed.query)
                payload = aesthetic_html(current, saved=query.get("saved") == ["1"],
                                          error=query.get("error", [""])[0]).encode("utf-8")
                self.send_response(200);self.send_header("Content-Type", "text/html; charset=utf-8")
            elif path == "/new-category":
                query = parse_qs(parsed.query)
                try:
                    added = int(query.get("added", ["0"])[0])
                except ValueError:
                    added = 0
                payload = new_category_html(saved=query.get("saved") == ["1"],
                                            error=query.get("error", [""])[0],
                                            added=added).encode("utf-8")
                self.send_response(200);self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                view = parse_qs(parsed.query).get("view", ["pending"])[0]
                if view not in {"pending", "approved", "aesthetic_only", "rejected", "all"}:
                    view = "pending"
                payload = review_html(current, read_decisions(), view).encode("utf-8")
                self.send_response(200);self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)));self.end_headers();self.wfile.write(payload)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/new-category/positive-cases":
                try:
                    size = min(int(self.headers.get("Content-Length", "0")), 10_000_000)
                    form = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
                    raw = form.get("json_payload", [""])[0].strip()
                    if not raw:
                        raise ValueError("请先选择 JSON 文件或粘贴正面案例 JSON")
                    added, _ = learn_new_category_positive_cases(
                        json.loads(raw), form.get("category_name", [""])[0]
                    )
                    self.send_response(303)
                    self.send_header("Location", f"/new-category?saved=1&added={added}")
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    self.send_response(303)
                    self.send_header("Location", "/new-category?error=" + quote(str(exc)))
                self.end_headers()
                return
            if path == "/preferences":
                try:
                    size = min(int(self.headers.get("Content-Length", "0")), 100000)
                    form = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
                    positive = parse_terms_editor(form.get("positive_terms", [""])[0])
                    negative = parse_terms_editor(form.get("negative_terms", [""])[0])
                    current = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else data
                    apply_preference_edits(positive, negative, current)
                    self.send_response(303);self.send_header("Location", "/aesthetic?saved=1")
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    self.send_response(303);self.send_header("Location", "/aesthetic?error=" + quote(str(exc)))
                self.end_headers()
                return
            if path == "/refresh":
                with refresh_lock:
                    if refresh_state["running"]:
                        payload = json.dumps({key: value for key, value in refresh_state.items() if key != "cancel_event"}, ensure_ascii=False).encode("utf-8")
                        self.send_response(202)
                    else:
                        cancel_event = threading.Event()
                        refresh_state.update(running=True, message="正在启动扫描…",
                                             finished=False, error=False, cancel_requested=False,
                                             cancel_event=cancel_event, started_at=time.time(),
                                             logs=[{"time": time.strftime("%H:%M:%S"),
                                                    "stage": "启动", "message": "正在启动扫描…"}])
                        threading.Thread(target=refresh_worker, args=(cancel_event,), daemon=True).start()
                        payload = json.dumps({key: value for key, value in refresh_state.items() if key != "cancel_event"}, ensure_ascii=False).encode("utf-8")
                        self.send_response(202)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers();self.wfile.write(payload)
                return
            if path == "/refresh/cancel":
                with refresh_lock:
                    if refresh_state["running"]:
                        refresh_state["cancel_requested"] = True
                        refresh_state["message"] = "已请求停止，正在结束当前扫描批次…"
                        refresh_state["logs"].append({
                            "time": time.strftime("%H:%M:%S"), "stage": "停止请求",
                            "message": "已请求停止，正在结束当前扫描批次…",
                        })
                        refresh_state["cancel_event"].set()
                        self.send_response(202)
                    else:
                        self.send_response(409)
                    payload = json.dumps({key: value for key, value in refresh_state.items() if key != "cancel_event"}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers();self.wfile.write(payload)
                return
            if path not in ("/decision", "/resolve-profile"):
                self.send_error(404);return
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 10000)))
                if path == "/resolve-profile":
                    payload = json.dumps(resolve_profile_link(body.get("link", "")), ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers();self.wfile.write(payload)
                    return
                if body.get("status") not in ("approved", "aesthetic_only", "rejected", "pending"):
                    raise ValueError("invalid status")
                current = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else data
                if body.get("key") not in {a["sec_uid"] or a["name"] for a in current["candidates"]}:
                    raise ValueError("unknown author")
                if body["status"] == "approved":
                    if not body.get("non_ai_confirmed"):
                        raise ValueError("通过前需确认作者以非AI模板为主")
                    if not body.get("dance_confirmed"):
                        raise ValueError("通过前需确认作者主要产出优质舞蹈模板")
                    if not (body.get("cc_id") or body.get("cc_link")) or not body.get("specialty") or not body.get("aesthetic_notes"):
                        raise ValueError("通过前需填写 CC ID 或主页链接、舞蹈类型，以及包装与节奏评价")
                if body["status"] == "aesthetic_only":
                    if not body.get("non_ai_confirmed") or not body.get("dance_confirmed"):
                        raise ValueError("标记审美达标前，请确认作者以非AI舞蹈模板为主")
                    if not body.get("specialty") or not body.get("aesthetic_notes"):
                        raise ValueError("标记审美达标前，请填写舞蹈类型和包装与节奏评价")
                if body["status"] == "rejected" and not (body.get("rejection_reason") or "").strip():
                    raise ValueError("排除前请填写不通过原因；它会作为反向提示词")
                with lock:
                    decisions = read_decisions()
                    previous = decisions.get(body["key"], {})
                    updated = {**previous, **body}
                    if body.get("cc_id") != previous.get("cc_id"):
                        updated.pop("cc_id_source", None)
                    decisions[body["key"]] = updated
                    DECISIONS.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
                    rebuild_preference_profile(decisions, current)
                if body["status"] == "rejected":
                    threading.Thread(
                        target=learn_rejected_creator_video,
                        args=(body["key"], body.get("rejection_reason", ""), current),
                        daemon=True,
                    ).start()
                self.send_response(204);self.end_headers()
            except Exception as exc:
                payload = str(exc).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"审核页：http://127.0.0.1:{port}/", flush=True)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="自动发现 CapCut 日本区模板作者并生成本地审核页，不调用 OpenAI")
    parser.add_argument("--pages", type=int, default=1200, help="每次扫描的官方模板页面数，默认1200")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--refresh", action="store_true", help="重新扫描（默认直接打开上次结果）")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--scan-only", action="store_true", help="只扫描并保存数据，适合本机定时任务")
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    if args.refresh or not RESULTS.exists():
        print(f"正在执行增量扫描，最多 {args.pages} 页…", flush=True)
        data, message, _ = run_incremental_refresh(args.pages)
        print(message, flush=True)
    else:
        data = json.loads(RESULTS.read_text(encoding="utf-8"))
        print("已加载上次扫描结果。要更新请使用 --refresh。", flush=True)
        record_seen_candidates(data)
    removed_authors, removed_templates = apply_stale_low_use_rule(data)
    if removed_templates:
        print(f"7天低量规则：排除 {removed_templates} 条模板、{removed_authors} 位待审作者。", flush=True)
    decisions = read_decisions()
    data["pending_queue"] = sum(
        decisions.get(author.get("sec_uid") or author.get("name"), {}).get("status", "pending") == "pending"
        for author in data.get("candidates", [])
    )
    if enrich_profiles(data):
        temp = RESULTS.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(RESULTS)
    rebuild_preference_profile(data=data)
    data = rescore_candidates(data, relabel=data.get("scoring_version") != 2)
    data["scoring_version"] = 2
    temp = RESULTS.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(RESULTS)
    if not args.scan_only:
        serve(data, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
