"""Local video analysis with the Apple Vision helper (macOS only).

On other platforms analysis is skipped and discovery falls back to
title/description evidence, exactly like a failed download on macOS.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen

from . import config
from .db import dumps, loads, now

MAX_VIDEO_BYTES = 80 * 1024 * 1024


class AnalysisUnavailable(OSError):
    """The platform cannot run the Vision helper."""


def ensure_analyzer():
    if sys.platform != "darwin":
        raise AnalysisUnavailable("视频分析仅支持 macOS")
    target = config.VISUAL_ANALYZER
    if target.exists() and target.stat().st_mtime >= config.VISUAL_ANALYZER_SOURCE.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "/usr/bin/swiftc", "-module-cache-path", "/tmp/capcut-swift-module-cache",
        str(config.VISUAL_ANALYZER_SOURCE), "-o", str(target),
    ], check=True, capture_output=True, text=True, timeout=120)
    return target


def analysis_id(work):
    return str(work.get("template_id") or hashlib.sha1(work.get("video_url", "").encode()).hexdigest())


def run_video_analysis(work):
    """Download one template video and run the Vision helper on it (no DB access)."""
    video_url = work.get("video_url", "")
    if not video_url:
        raise ValueError("模板没有可分析的视频地址")
    analyzer = ensure_analyzer()
    request = Request(video_url, headers={"User-Agent": config.USER_AGENT})
    temp_path = None
    try:
        with urlopen(request, timeout=30) as response, tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False) as target:
            temp_path = Path(target.name)
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise ValueError("视频超过 80MB，跳过本地分析")
                target.write(chunk)
        result = subprocess.run([str(analyzer), str(temp_path)], check=True, capture_output=True,
                                text=True, timeout=90)
        analysis = json.loads(result.stdout)
        analysis.update(template_id=analysis_id(work), title=work.get("title", ""),
                        analyzed_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        return analysis
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def cached_analysis(conn, template_id):
    row = conn.execute("SELECT result FROM video_analyses WHERE template_id = ?", (template_id,)).fetchone()
    return loads(row["result"]) if row else None


def store_analysis(conn, template_id, analysis):
    conn.execute(
        "INSERT OR REPLACE INTO video_analyses(template_id, result, analyzed_at) VALUES(?, ?, ?)",
        (template_id, dumps(analysis), analysis.get("analyzed_at") or now()),
    )
    conn.commit()


def aggregate(analyses):
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


def supports_dance(profile):
    """Conservative video gate for seed items whose titles omit dance."""
    if not profile:
        return False
    human_presence = max(float(profile.get("human_frame_ratio") or 0),
                         float(profile.get("face_frame_ratio") or 0))
    return human_presence >= 0.45 and float(profile.get("mean_frame_distance") or 0) >= 0.35


def similarity(candidate, negative):
    if not candidate or not negative:
        return 0
    candidate_labels = candidate.get("labels", {})
    negative_labels = negative.get("labels", {})
    all_labels = set(candidate_labels) | set(negative_labels)
    union = sum(max(float(candidate_labels.get(label, 0)), float(negative_labels.get(label, 0))) for label in all_labels)
    overlap = (sum(min(float(candidate_labels.get(label, 0)), float(negative_labels.get(label, 0)))
                   for label in all_labels) / union) if union else 0

    def closeness(field, scale=1.0):
        return max(0.0, 1.0 - abs(float(candidate.get(field, 0)) - float(negative.get(field, 0))) / scale)

    motion_scale = max(1.0, float(candidate.get("mean_frame_distance", 0)), float(negative.get("mean_frame_distance", 0)))
    score = (0.45 * overlap + 0.2 * closeness("human_frame_ratio") +
             0.1 * closeness("face_frame_ratio") +
             0.2 * closeness("mean_frame_distance", motion_scale) +
             0.05 * closeness("label_diversity", 20.0))
    return round(max(0, min(1, score)), 3)


def works_to_analyze(author, limit):
    # Analyse the author's dance work first; sorting only by uses frequently
    # inspected an unrelated viral slideshow from the same author.
    works = [work for work in author.get("works", []) if work.get("video_url")]
    works.sort(key=lambda work: (
        bool(work.get("dance_signal") and not work.get("non_dance_gimmick")),
        int(work.get("uses") or 0),
    ), reverse=True)
    return works[:limit]


def analyze_authors(conn, authors, per_author=1, workers=2, progress=None):
    """Attach ``video_content_profile`` to each author, using the DB cache."""
    plan = {id(author): works_to_analyze(author, per_author) for author in authors}
    results = {}
    missing = {}
    for works in plan.values():
        for work in works:
            template_id = analysis_id(work)
            cached = cached_analysis(conn, template_id)
            if cached:
                results[template_id] = cached
            else:
                missing.setdefault(template_id, work)
    if missing:
        try:
            ensure_analyzer()
        except (OSError, subprocess.SubprocessError) as exc:
            if progress:
                progress("视频分析", f"跳过逐帧分析：{exc}")
            missing = {}
    if missing:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = {pool.submit(run_video_analysis, work): template_id for template_id, work in missing.items()}
            for completed, job in enumerate(as_completed(jobs), 1):
                template_id = jobs[job]
                try:
                    analysis = job.result()
                except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
                    continue
                results[template_id] = analysis
                store_analysis(conn, template_id, analysis)
                if progress:
                    progress("视频分析", f"已分析模板 {missing[template_id].get('title') or template_id}（{completed}/{len(jobs)}）")
    for author in authors:
        profile = aggregate([results.get(analysis_id(work)) for work in plan[id(author)]])
        if profile:
            author["video_content_profile"] = profile
    return results
