"""Review decisions, the review queue view and the approved-creator CSV."""

import csv
import io

from . import config, learning, repository
from .db import loads, now
from .scoring import read_reference_cases


def _sort_key(author):
    # The ranked recommendations first, highest score first; exploration after.
    return (1 if author.get("recommendation_type") == "随机探索" else 0,
            -float(author.get("score") or 0), int(author.get("match_rank") or 10**9))


def list_creators(conn, view="pending"):
    reviews = repository.all_reviews(conn)
    authors = sorted(repository.queued_creators(conn), key=_sort_key)
    if view in config.REVIEW_STATUSES:
        authors = [author for author in authors if repository.review_status(reviews, author["key"]) == view]
    items = []
    for author in authors:
        review = reviews.get(author["key"], {})
        items.append({
            **{key: value for key, value in author.items() if key != "works"},
            "works": author["works"][:config.WORKS_PER_CREATOR],
            "review": {
                "status": review.get("status", "pending"),
                "cc_id": review.get("cc_id") or author.get("cc_id") or "",
                "cc_link": review.get("cc_link") or author.get("cc_link") or "",
                "tt_link": review.get("tt_link") or author.get("tt_link") or "",
                "total_posts": review.get("total_posts") if review.get("total_posts") is not None else author.get("total_posts"),
                "high_use_posts": (review.get("high_use_posts") if review.get("high_use_posts") is not None
                                   else author.get("high_use_non_ai_indexed")),
                "non_ai_confirmed": bool(review.get("non_ai_confirmed")),
                "dance_confirmed": bool(review.get("dance_confirmed")),
                "priority": review.get("priority") or "P1",
                "specialty": review.get("specialty") or "",
                "aesthetic_notes": review.get("aesthetic_notes") or "",
                "rejection_reason": review.get("rejection_reason") or "",
            },
        })
    return items


def validate(body):
    status = body.get("status")
    if status not in config.REVIEW_STATUSES:
        raise ValueError("无效的审核状态")
    has_notes = (body.get("specialty") or "").strip() and (body.get("aesthetic_notes") or "").strip()
    if status == "approved":
        if not body.get("non_ai_confirmed"):
            raise ValueError("通过前需确认作者以非AI模板为主")
        if not body.get("dance_confirmed"):
            raise ValueError("通过前需确认作者主要产出优质舞蹈模板")
        if not ((body.get("cc_id") or "").strip() or (body.get("cc_link") or "").strip()) or not has_notes:
            raise ValueError("通过前需填写 CC ID 或主页链接、舞蹈类型，以及包装与节奏评价")
    if status == "aesthetic_only":
        if not body.get("non_ai_confirmed") or not body.get("dance_confirmed"):
            raise ValueError("标记审美达标前，请确认作者以非AI舞蹈模板为主")
        if not has_notes:
            raise ValueError("标记审美达标前，请填写舞蹈类型和包装与节奏评价")
    if status == "rejected" and not (body.get("rejection_reason") or "").strip():
        raise ValueError("排除前请填写不通过原因；它会作为反向提示词")


def save(conn, body):
    """Validate and store a review; returns the creator key."""
    key = body.get("key") or ""
    # Fields the request leaves out keep their saved values.
    review = {**repository.all_reviews(conn).get(key, {}), **body}
    validate(review)
    if not conn.execute("SELECT 1 FROM creators WHERE creator_key = ? AND in_queue = 1", (key,)).fetchone():
        raise ValueError("未知作者")
    with conn:
        repository.save_review(conn, key, review)
    learning.sync_revision(conn)
    conn.commit()
    return key


def approved_csv(conn):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["CC用户名称", "CC ID", "CC主页link", "TT主页link", "作者擅长类型"])
    rows = conn.execute(
        """SELECT COALESCE(c.name, r.creator_key) AS name, r.* FROM reviews r
           LEFT JOIN creators c ON c.creator_key = r.creator_key
           WHERE r.status = 'approved' ORDER BY r.updated_at""")
    for row in rows:
        specialty = "；".join(part for part in [row["specialty"], row["aesthetic_notes"]] if part)
        writer.writerow([row["name"], row["cc_id"], row["cc_link"], row["tt_link"], specialty])
    return stream.getvalue().encode("utf-8-sig")


def overview(conn):
    counts = {status: 0 for status in config.REVIEW_STATUSES}
    for row in conn.execute(
            """SELECT COALESCE(r.status, 'pending') AS status, COUNT(*) AS n FROM creators c
               LEFT JOIN reviews r ON r.creator_key = c.creator_key
               WHERE c.in_queue = 1 GROUP BY 1"""):
        counts[row["status"]] = row["n"]
    scan = conn.execute("SELECT * FROM scans WHERE status = 'succeeded' ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "counts": counts,
        "total_in_queue": sum(counts.values()),
        "reference_case_count": len(read_reference_cases().get("videos", [])),
        "scoring_policy": config.SCORING_POLICY,
        "stale_rule": config.STALE_RULE,
        "max_pending": config.MAX_PENDING_CREATORS,
        "latest_scan": None if not scan else {
            "finished_at": scan["finished_at"],
            "message": scan["message"],
            "indexed_templates": scan["indexed_templates"],
            "new_live_templates": scan["new_live_templates"],
            "new_candidates": scan["new_candidates"],
            "ranked_candidates": scan["ranked_candidates"],
            "random_candidates": scan["random_candidates"],
            "skipped_rejected": scan["skipped_rejected"],
            "trend_terms": loads(scan["trend_terms"], []),
        },
    }


def exclusions(conn):
    return [row["term"] for row in conn.execute("SELECT term FROM exclusions ORDER BY created_at, term")]


def replace_exclusions(conn, terms):
    cleaned = list(dict.fromkeys(term.strip() for term in terms if term and term.strip() and not term.startswith("#")))
    with conn:
        conn.execute("DELETE FROM exclusions")
        conn.executemany("INSERT INTO exclusions(term, created_at) VALUES(?, ?)", [(term, now()) for term in cleaned])
    return cleaned
