"""Row <-> dict mapping for creators, templates and reviews.

Services work with plain dicts (``author`` with a ``works`` list, the same
shape the scoring logic has always used); this module is the only place that
knows the table layout.
"""

import time

from . import config
from .db import dumps, loads, now

CREATOR_COLUMNS = (
    "name", "bio", "sec_uid", "cc_id", "cc_link", "tt_link", "total_posts",
    "profile_link_hint", "profile_verified", "profile_link_checked",
    "japanese_signal", "japanese_post_count", "ai_flagged_count", "indexed_count",
    "dance_non_ai_indexed", "explicit_dance_indexed", "high_use_non_ai_indexed",
    "stale_low_use_excluded_count", "dance_video_verified", "video_content_profile",
    "score", "reference_match_score", "quality_data_score", "reference_match_evidence",
    "preference_adjustment", "negative_video_penalty", "negative_video_reason",
    "in_queue", "recommendation_type", "match_rank", "discovered_at",
    "first_shown_at", "last_shown_at",
)
CREATOR_JSON = {"video_content_profile", "reference_match_evidence"}
CREATOR_BOOL = {"profile_verified", "profile_link_checked", "dance_video_verified", "in_queue"}
CREATOR_TEXT = {
    "name", "bio", "sec_uid", "cc_id", "cc_link", "tt_link", "profile_link_hint",
    "japanese_signal", "negative_video_reason", "recommendation_type",
}

TEMPLATE_COLUMNS = (
    "creator_key", "title", "description", "uses", "clips", "url", "cover_url",
    "video_url", "created_at_epoch", "japanese_post", "likely_ai", "dance_signal",
    "dance_seed", "non_dance_gimmick",
)
TEMPLATE_BOOL = ("japanese_post", "likely_ai", "dance_signal", "dance_seed", "non_dance_gimmick")

REVIEW_COLUMNS = (
    "status", "cc_id", "cc_link", "tt_link", "total_posts", "high_use_posts",
    "non_ai_confirmed", "dance_confirmed", "priority", "specialty",
    "aesthetic_notes", "rejection_reason",
)
REVIEW_BOOL = {"non_ai_confirmed", "dance_confirmed"}
REVIEW_INT = {"total_posts", "high_use_posts"}


def creator_key(item):
    return item.get("sec_uid") or item.get("name") or ""


# --- templates ---------------------------------------------------------------

def work_age(created_at, uses, now_ts=None):
    """Return (age_days, stale_low_use) for the 7-day / 1,000-use hard gate."""
    if not created_at:
        return None, False
    age = max(0, int(((now_ts or time.time()) - created_at) // 86400))
    return age, age >= config.STALE_DAYS and int(uses or 0) < config.STALE_MIN_USES


def work_from_row(row, now_ts=None):
    created = int(row["created_at_epoch"] or 0)
    age, stale = work_age(created, row["uses"], now_ts)
    work = {
        "template_id": row["template_id"],
        "creator_key": row["creator_key"],
        "title": row["title"],
        "desc": row["description"],
        "uses": int(row["uses"] or 0),
        "clips": row["clips"],
        "url": row["url"],
        "cover_url": row["cover_url"],
        "video_url": row["video_url"],
        "created_at_epoch": created,
        "published_at": time.strftime("%Y-%m-%d", time.localtime(created)) if created else "",
        "age_days": age,
        "stale_low_use": stale,
    }
    for column in TEMPLATE_BOOL:
        work[column] = bool(row[column])
    return work


def upsert_templates(conn, records):
    """Store discovered templates. ``dance_seed`` is sticky once observed."""
    stamp = now()
    rows = []
    for record in records:
        rows.append((
            record["template_id"], record["creator_key"], record.get("title", ""),
            record.get("desc", ""), int(record.get("uses") or 0), record.get("clips"),
            record.get("url", ""), record.get("cover_url", ""), record.get("video_url", ""),
            int(record.get("created_at_epoch") or 0),
            *(int(bool(record.get(column))) for column in TEMPLATE_BOOL),
            stamp, stamp,
        ))
    conn.executemany(
        f"""INSERT INTO templates(template_id, {", ".join(TEMPLATE_COLUMNS)}, first_indexed_at, updated_at)
            VALUES({", ".join("?" * (len(TEMPLATE_COLUMNS) + 3))})
            ON CONFLICT(template_id) DO UPDATE SET
              creator_key = excluded.creator_key, title = excluded.title,
              description = excluded.description, uses = excluded.uses,
              clips = COALESCE(excluded.clips, templates.clips), url = excluded.url,
              cover_url = CASE WHEN excluded.cover_url != '' THEN excluded.cover_url ELSE templates.cover_url END,
              video_url = CASE WHEN excluded.video_url != '' THEN excluded.video_url ELSE templates.video_url END,
              created_at_epoch = CASE WHEN excluded.created_at_epoch > 0 THEN excluded.created_at_epoch ELSE templates.created_at_epoch END,
              japanese_post = excluded.japanese_post, likely_ai = excluded.likely_ai,
              dance_signal = excluded.dance_signal, non_dance_gimmick = excluded.non_dance_gimmick,
              dance_seed = MAX(templates.dance_seed, excluded.dance_seed),
              updated_at = excluded.updated_at""",
        rows,
    )


def sort_works(works):
    return sorted(
        works,
        key=lambda w: (bool(w.get("dance_seed") or w.get("dance_signal")), int(w.get("uses") or 0)),
        reverse=True,
    )


def load_works(conn, key, include_stale=False):
    now_ts = time.time()
    works = [work_from_row(row, now_ts) for row in
             conn.execute("SELECT * FROM templates WHERE creator_key = ?", (key,))]
    if not include_stale:
        works = [work for work in works if not work["stale_low_use"]]
    return sort_works(works)


def known_template_ids(conn):
    ids = set()
    for table in ("templates", "seen_live_templates", "template_cache"):
        ids.update(row[0] for row in conn.execute(f"SELECT template_id FROM {table}"))
    return ids


def mark_live_templates_seen(conn, template_ids):
    stamp = now()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_live_templates(template_id, first_seen_at) VALUES(?, ?)",
        [(template_id, stamp) for template_id in template_ids],
    )


# --- creators ----------------------------------------------------------------

def creator_from_row(row):
    author = {"key": row["creator_key"]}
    for column in CREATOR_COLUMNS:
        value = row[column]
        if column in CREATOR_JSON:
            value = loads(value, [] if column == "reference_match_evidence" else None)
        elif column in CREATOR_BOOL:
            value = bool(value)
        author[column] = value
    if author["video_content_profile"] is None:
        author["video_content_profile"] = {}
    return author


def load_creator(conn, key, with_works=True):
    row = conn.execute("SELECT * FROM creators WHERE creator_key = ?", (key,)).fetchone()
    if not row:
        return None
    author = creator_from_row(row)
    if with_works:
        author["works"] = load_works(conn, key)
    return author


def queued_creators(conn, with_works=True):
    rows = conn.execute("SELECT * FROM creators WHERE in_queue = 1").fetchall()
    authors = [creator_from_row(row) for row in rows]
    if with_works:
        for author in authors:
            author["works"] = load_works(conn, author["key"])
    return authors


def _creator_value(author, column):
    value = author.get(column)
    if column in CREATOR_JSON:
        return dumps(value if value is not None else ([] if column == "reference_match_evidence" else {}))
    if column in CREATOR_BOOL:
        return int(bool(value))
    if column in CREATOR_TEXT:
        return value or ""
    if column == "total_posts":
        return to_int(value)
    if column in {"first_shown_at", "last_shown_at", "discovered_at", "match_rank"}:
        return value
    return value or 0


def upsert_creator(conn, author, columns=None):
    """Insert or update a creator. ``columns`` limits which fields are written."""
    key = creator_key(author) if "key" not in author else author["key"]
    columns = [column for column in (columns or CREATOR_COLUMNS) if column in author]
    values = [_creator_value(author, column) for column in columns]
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns)
    conn.execute(
        f"""INSERT INTO creators(creator_key, {", ".join(columns)}, updated_at)
            VALUES(?, {", ".join("?" * len(columns))}, ?)
            ON CONFLICT(creator_key) DO UPDATE SET {assignments + ", " if assignments else ""}
              updated_at = excluded.updated_at""",
        (key, *values, now()),
    )
    return key


def to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


# --- reviews -----------------------------------------------------------------

def review_from_row(row):
    review = {"key": row["creator_key"]}
    for column in REVIEW_COLUMNS:
        value = row[column]
        review[column] = bool(value) if column in REVIEW_BOOL else value
    review["updated_at"] = row["updated_at"]
    return review


def all_reviews(conn):
    return {row["creator_key"]: review_from_row(row) for row in conn.execute("SELECT * FROM reviews")}


def review_status(reviews, key):
    return reviews.get(key, {}).get("status", "pending")


def save_review(conn, key, review):
    stamp = now()
    values = []
    for column in REVIEW_COLUMNS:
        value = review.get(column)
        if column in REVIEW_BOOL:
            value = int(bool(value))
        elif column in REVIEW_INT:
            value = to_int(value)
        elif column == "priority":
            value = value if value in ("P0", "P1") else "P1"
        else:
            value = (value or "").strip() if isinstance(value, str) or value is None else str(value)
        values.append(value)
    assignments = ", ".join(f"{column} = excluded.{column}" for column in REVIEW_COLUMNS)
    conn.execute(
        f"""INSERT INTO reviews(creator_key, {", ".join(REVIEW_COLUMNS)}, created_at, updated_at)
            VALUES(?, {", ".join("?" * len(REVIEW_COLUMNS))}, ?, ?)
            ON CONFLICT(creator_key) DO UPDATE SET {assignments}, updated_at = excluded.updated_at""",
        (key, *values, stamp, stamp),
    )
