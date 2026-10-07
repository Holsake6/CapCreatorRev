"""SQLite storage: schema, connections and small JSON helpers.

Each thread opens its own connection with ``connect()``. Network work runs
outside transactions so writes stay short and concurrent scans do not block
the review API for long.
"""

import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    creator_key TEXT PRIMARY KEY,           -- sec_uid, or name when CapCut gives none
    name TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    sec_uid TEXT NOT NULL DEFAULT '',
    cc_id TEXT NOT NULL DEFAULT '',
    cc_link TEXT NOT NULL DEFAULT '',
    tt_link TEXT NOT NULL DEFAULT '',
    total_posts INTEGER,
    profile_link_hint TEXT NOT NULL DEFAULT '',
    profile_verified INTEGER NOT NULL DEFAULT 0,
    profile_link_checked INTEGER NOT NULL DEFAULT 0,
    japanese_signal TEXT NOT NULL DEFAULT '',
    japanese_post_count INTEGER NOT NULL DEFAULT 0,
    ai_flagged_count INTEGER NOT NULL DEFAULT 0,
    indexed_count INTEGER NOT NULL DEFAULT 0,
    dance_non_ai_indexed INTEGER NOT NULL DEFAULT 0,
    explicit_dance_indexed INTEGER NOT NULL DEFAULT 0,
    high_use_non_ai_indexed INTEGER NOT NULL DEFAULT 0,
    stale_low_use_excluded_count INTEGER NOT NULL DEFAULT 0,
    dance_video_verified INTEGER NOT NULL DEFAULT 0,
    video_content_profile TEXT,             -- JSON aggregate of analysed videos
    score REAL NOT NULL DEFAULT 0,
    reference_match_score REAL NOT NULL DEFAULT 0,
    quality_data_score REAL NOT NULL DEFAULT 0,
    reference_match_evidence TEXT NOT NULL DEFAULT '[]',
    preference_adjustment REAL NOT NULL DEFAULT 0,
    negative_video_penalty REAL NOT NULL DEFAULT 0,
    negative_video_reason TEXT NOT NULL DEFAULT '',
    in_queue INTEGER NOT NULL DEFAULT 0,    -- shown on the review page
    recommendation_type TEXT NOT NULL DEFAULT '',
    match_rank INTEGER,
    discovered_at TEXT,
    first_shown_at TEXT,
    last_shown_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_creators_queue ON creators(in_queue);

CREATE TABLE IF NOT EXISTS templates (
    template_id TEXT PRIMARY KEY,
    creator_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    uses INTEGER NOT NULL DEFAULT 0,
    clips INTEGER,
    url TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    video_url TEXT NOT NULL DEFAULT '',
    created_at_epoch INTEGER NOT NULL DEFAULT 0,
    japanese_post INTEGER NOT NULL DEFAULT 0,
    likely_ai INTEGER NOT NULL DEFAULT 0,
    dance_signal INTEGER NOT NULL DEFAULT 0,
    dance_seed INTEGER NOT NULL DEFAULT 0,
    non_dance_gimmick INTEGER NOT NULL DEFAULT 0,
    first_indexed_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_templates_creator ON templates(creator_key);

-- Template ids already returned by a live landing list ("首次索引" bookkeeping).
CREATE TABLE IF NOT EXISTS seen_live_templates (
    template_id TEXT PRIMARY KEY,
    first_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS template_cache (
    template_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,                  -- {"detail": ..., "recommendations": [...]}
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS video_analyses (
    template_id TEXT PRIMARY KEY,
    result TEXT NOT NULL,
    analyzed_at TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    creator_key TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'aesthetic_only', 'rejected')),
    cc_id TEXT NOT NULL DEFAULT '',
    cc_link TEXT NOT NULL DEFAULT '',
    tt_link TEXT NOT NULL DEFAULT '',
    total_posts INTEGER,
    high_use_posts INTEGER,
    non_ai_confirmed INTEGER NOT NULL DEFAULT 0,
    dance_confirmed INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'P1',
    specialty TEXT NOT NULL DEFAULT '',
    aesthetic_notes TEXT NOT NULL DEFAULT '',
    rejection_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);

CREATE TABLE IF NOT EXISTS rejected_visual_profiles (
    creator_key TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    affects_visual_score INTEGER NOT NULL DEFAULT 0,
    video_profile TEXT NOT NULL,
    updated_at TEXT
);

-- Manual edits on top of the terms derived from reviews. weight NULL = deleted.
CREATE TABLE IF NOT EXISTS term_overrides (
    polarity TEXT NOT NULL CHECK (polarity IN ('positive', 'negative')),
    term TEXT NOT NULL,
    weight INTEGER,
    PRIMARY KEY (polarity, term)
);

CREATE TABLE IF NOT EXISTS preference_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,                     -- manual | cli
    status TEXT NOT NULL,                   -- running | succeeded | failed | cancelled
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    indexed_templates INTEGER NOT NULL DEFAULT 0,
    new_live_templates INTEGER NOT NULL DEFAULT 0,
    new_candidates INTEGER NOT NULL DEFAULT 0,
    ranked_candidates INTEGER NOT NULL DEFAULT 0,
    random_candidates INTEGER NOT NULL DEFAULT 0,
    deferred_candidates INTEGER NOT NULL DEFAULT 0,
    replaced_pending INTEGER NOT NULL DEFAULT 0,
    skipped_rejected INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    trend_terms TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS exclusions (
    term TEXT PRIMARY KEY,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS category_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_at TEXT
);

-- Small singletons: scan cursor, trend chart cache, profile revisions.
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None):
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def is_empty(conn):
    tables = ("creators", "reviews", "settings", "templates")
    return all(conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is None for table in tables)


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def loads(text, default=None):
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return loads(row["value"], default) if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, dumps(value)),
    )
