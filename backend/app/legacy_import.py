"""One-time import of the JSON files used by the old single-file version.

Runs automatically when the database is empty. State files are read from the
old ``capcut_local_data/`` folder if it still holds them (a newer local copy),
otherwise from the snapshot committed in ``backend/data/legacy/``.
"""

import csv
import json
import time

from . import config, learning, repository
from .category import fingerprint
from .db import dumps, now, set_setting

LEGACY_NAMES = {
    # file name in backend/data/legacy -> path inside the old capcut_local_data
    "candidates.json": "candidates.json",
    "decisions.json": "decisions.json",
    "preference_profile.json": "preference_profile.json",
    "visual_learning.json": "visual_learning.json",
    "scan_state.json": "scan_state.json",
    "scan_history.json": "scan_history.json",
    "seen_creators.json": "seen_creators.json",
    "seen_templates.json": "seen_templates.json",
    "trend_terms.json": "trend_terms.json",
    "new_category_positive_cases.json": "new_category/positive_cases.json",
    "new_category_positive_profile.json": "new_category/positive_profile.json",
}


def _read(name, default):
    for path in (config.OLD_LOCAL_DATA / LEGACY_NAMES[name], config.LEGACY_DIR / name):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return default


def _creators(conn, candidates, seen):
    for author in candidates.get("candidates", []):
        key = repository.creator_key(author)
        if not key:
            continue
        works = []
        for work in author.get("works", []):
            works.append({**work, "creator_key": key})
        repository.upsert_templates(conn, works)
        shown = seen.get(key, {})
        repository.upsert_creator(conn, {
            **author, "key": key, "in_queue": True,
            "first_shown_at": shown.get("first_seen") or author.get("discovered_at"),
            "last_shown_at": shown.get("last_seen") or author.get("discovered_at"),
        })
    for key, shown in seen.items():
        conn.execute(
            "INSERT OR IGNORE INTO creators(creator_key, name, first_shown_at, last_shown_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?)", (key, shown.get("name", ""), shown.get("first_seen"), shown.get("last_seen"), now()))


def _reviews(conn, decisions):
    for key, decision in decisions.items():
        repository.save_review(conn, key, decision)
        conn.execute("INSERT OR IGNORE INTO creators(creator_key, name, updated_at) VALUES(?, ?, ?)",
                     (key, "", now()))


def _preferences(conn, profile):
    overrides = profile.get("term_overrides") or {}
    deleted = profile.get("deleted_terms") or {}
    for polarity in ("positive", "negative"):
        for term, weight in (overrides.get(polarity) or {}).items():
            conn.execute("INSERT OR REPLACE INTO term_overrides VALUES(?, ?, ?)", (polarity, term, int(weight)))
        for term in deleted.get(polarity) or []:
            conn.execute("INSERT OR IGNORE INTO term_overrides VALUES(?, ?, NULL)", (polarity, term))
    for item in profile.get("edit_history") or []:
        conn.execute("INSERT INTO preference_edits(created_at, summary) VALUES(?, ?)",
                     (item.get("at", ""), item.get("summary", "")))
    set_setting(conn, "preference_meta", {
        "revision": int(profile.get("revision", 1) or 1),
        "updated_at": profile.get("updated_at") or now(),
    })


def _scans(conn, history, candidates):
    latest = candidates.get("generated_at")
    for entry in history:
        is_latest = entry.get("generated_at") == latest
        conn.execute(
            """INSERT INTO scans(mode, status, message, started_at, finished_at, indexed_templates,
                   new_live_templates, new_candidates, ranked_candidates, random_candidates,
                   deferred_candidates, replaced_pending, skipped_rejected, trend_terms)
               VALUES('legacy', 'succeeded', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.get("generated_at"), entry.get("generated_at"), entry.get("indexed_templates", 0),
             candidates.get("new_live_templates", 0) if is_latest else 0,
             entry.get("new_candidates", 0),
             candidates.get("latest_ranked_candidates", 0) if is_latest else 0,
             candidates.get("latest_random_candidates", 0) if is_latest else 0,
             entry.get("deferred_new_candidates", 0),
             candidates.get("replaced_pending_candidates", 0) if is_latest else 0,
             entry.get("skipped_seen_creators", 0),
             dumps(candidates.get("trend_terms", []) if is_latest else [])))


def _category(conn, cases, profile):
    for item in cases if isinstance(cases, list) else []:
        conn.execute("INSERT OR IGNORE INTO category_cases(fingerprint, payload, created_at) VALUES(?, ?, ?)",
                     (fingerprint(item), dumps(item), now()))
    if profile:
        set_setting(conn, "category_meta", {
            "name": profile.get("category_name", "新类别（待命名）"),
            "revision": int(profile.get("revision", 0)),
            "updated_at": profile.get("updated_at", "尚未学习"),
        })


def _exclusions(conn):
    terms = list(config.DEFAULT_EXCLUSIONS)
    for path in (config.PROJECT_ROOT / "已归类作者.txt", config.LEGACY_DIR / "excluded_creators.txt"):
        if path.exists():
            terms += [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.startswith("#")]
            break
    csv_path = config.PROJECT_ROOT / "已归类作者.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                terms += [row.get(k, "").strip() for k in ("CC用户名称", "CC ID", "CC主页link") if row.get(k)]
    conn.executemany("INSERT OR IGNORE INTO exclusions(term, created_at) VALUES(?, ?)",
                     [(term, now()) for term in dict.fromkeys(terms)])


def _local_caches(conn):
    """Template-detail and video-analysis caches the old version kept untracked."""
    cache_dir = config.OLD_LOCAL_DATA / "cache"
    for path in cache_dir.glob("*.json") if cache_dir.exists() else []:
        try:
            conn.execute("INSERT OR IGNORE INTO template_cache VALUES(?, ?, ?)",
                         (path.stem, path.read_text(encoding="utf-8"), path.stat().st_mtime))
        except OSError:
            continue
    analysis_dir = config.OLD_LOCAL_DATA / "video_analysis"
    for path in analysis_dir.glob("*.json") if analysis_dir.exists() else []:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        conn.execute("INSERT OR IGNORE INTO video_analyses VALUES(?, ?, ?)",
                     (path.stem, dumps(result), result.get("analyzed_at")))


def run(conn, log=print):
    started = time.time()
    candidates = _read("candidates.json", {})
    with conn:
        _creators(conn, candidates, _read("seen_creators.json", {}))
        _reviews(conn, _read("decisions.json", {}))
        _preferences(conn, _read("preference_profile.json", {}))
        for key, item in (_read("visual_learning.json", {}).get("rejected_profiles") or {}).items():
            conn.execute("INSERT OR REPLACE INTO rejected_visual_profiles VALUES(?, ?, ?, ?, ?)",
                         (key, item.get("reason", ""), int(bool(item.get("affects_visual_score"))),
                          dumps(item.get("video_profile", {})), item.get("updated_at")))
        _scans(conn, _read("scan_history.json", []), candidates)
        repository.mark_live_templates_seen(conn, _read("seen_templates.json", []))
        set_setting(conn, "scan_state", _read("scan_state.json", {}))
        trend = _read("trend_terms.json", {})
        if trend:
            set_setting(conn, "trend_terms", trend)
        _category(conn, _read("new_category_positive_cases.json", []), _read("new_category_positive_profile.json", {}))
        _exclusions(conn)
        _local_caches(conn)
    # Record what is learned now so the imported revision is not bumped.
    learning.sync_revision(conn)
    conn.commit()
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("creators", "templates", "reviews", "rejected_visual_profiles", "exclusions")}
    log(f"已从旧版 JSON 导入数据（{time.time() - started:.1f}s）：{counts}")
    return counts
