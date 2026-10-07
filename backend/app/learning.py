"""Aesthetic learning from reviews: preference terms, manual edits, rejected videos.

The preference profile is derived from the ``reviews`` table every time it is
needed; only manual term edits (``term_overrides``) and the revision counter
are stored separately.
"""

import hashlib
import re

from . import config, repository, video
from .db import dumps, get_setting, loads, now, set_setting

LEARNING_POLICY = "通过与审美达标特征累积为正向审美偏好；不通过原因原文累积为反向提示词。"


def learned_terms(text):
    return [word.casefold() for word in config.LEARN_TOKEN.findall(text or "")
            if word.casefold() not in config.LEARN_STOP]


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
    return list(dict.fromkeys(term for term in terms if term and term not in config.LEARN_STOP))


def effective_terms(derived, overrides, deleted):
    deleted = set(deleted)
    terms = {term: int(weight) for term, weight in derived.items() if term not in deleted}
    for term, weight in overrides.items():
        if term:
            terms[term] = max(0, min(10, int(weight)))
    return dict(sorted(terms.items(), key=lambda item: (-item[1], item[0])))


def _ordered_reviews(conn):
    return [repository.review_from_row(row) for row in
            conn.execute("SELECT * FROM reviews ORDER BY created_at, rowid")]


def derive_from_reviews(reviews):
    positive_phrases, negative_prompts = [], []
    positive_terms, negative_terms = {}, {}
    for review in reviews:
        status = review.get("status")
        if status in ("approved", "aesthetic_only"):
            phrase = "；".join(part for part in [
                (review.get("specialty") or "").strip(),
                (review.get("aesthetic_notes") or "").strip(),
            ] if part)
            if phrase:
                positive_phrases.append({"creator_key": review["key"], "status": status, "text": phrase})
                for term in learned_terms(phrase):
                    positive_terms[term] = positive_terms.get(term, 0) + 1
        elif status == "rejected":
            reason = (review.get("rejection_reason") or "").strip()
            if reason:
                negative_prompts.append({"creator_key": review["key"], "text": reason})
                for term in negative_learned_terms(reason):
                    negative_terms[term] = negative_terms.get(term, 0) + 1
    return positive_phrases, negative_prompts, positive_terms, negative_terms


def load_overrides(conn):
    overrides = {"positive": {}, "negative": {}}
    deleted = {"positive": [], "negative": []}
    for row in conn.execute("SELECT polarity, term, weight FROM term_overrides ORDER BY term"):
        if row["weight"] is None:
            deleted[row["polarity"]].append(row["term"])
        else:
            overrides[row["polarity"]][row["term"]] = int(row["weight"])
    return overrides, deleted


def _fingerprint(*parts):
    return hashlib.sha1(dumps(parts).encode("utf-8")).hexdigest()


def preference_profile(conn):
    reviews = _ordered_reviews(conn)
    positive_phrases, negative_prompts, positive_terms, negative_terms = derive_from_reviews(reviews)
    overrides, deleted = load_overrides(conn)
    meta = get_setting(conn, "preference_meta", {})
    history = [{"at": row["created_at"], "summary": row["summary"]} for row in conn.execute(
        "SELECT created_at, summary FROM (SELECT * FROM preference_edits ORDER BY id DESC LIMIT 50) ORDER BY id")]
    return {
        "revision": int(meta.get("revision", 1)),
        "updated_at": meta.get("updated_at", "尚未更新"),
        "approved_count": sum(r["status"] == "approved" for r in reviews),
        "aesthetic_only_count": sum(r["status"] == "aesthetic_only" for r in reviews),
        "rejected_count": sum(r["status"] == "rejected" for r in reviews),
        "learning_policy": LEARNING_POLICY,
        "positive_phrases": positive_phrases,
        "negative_prompts": negative_prompts,
        "derived_positive_terms": positive_terms,
        "derived_negative_terms": negative_terms,
        "positive_terms": effective_terms(positive_terms, overrides["positive"], deleted["positive"]),
        "negative_terms": effective_terms(negative_terms, overrides["negative"], deleted["negative"]),
        "edit_history": history,
    }


def _bump_revision(conn, fingerprint=None):
    meta = get_setting(conn, "preference_meta", {})
    meta["revision"] = int(meta.get("revision", 0)) + 1
    meta["updated_at"] = now()
    if fingerprint is not None:
        meta["fingerprint"] = fingerprint
    set_setting(conn, "preference_meta", meta)


def sync_revision(conn):
    """Advance the profile revision when reviews changed what was learned."""
    positive_phrases, negative_prompts, positive_terms, negative_terms = derive_from_reviews(_ordered_reviews(conn))
    fingerprint = _fingerprint(positive_phrases, negative_prompts, positive_terms, negative_terms)
    meta = get_setting(conn, "preference_meta", {})
    if "fingerprint" not in meta and "revision" in meta:
        # First sync after an import: remember the baseline, nothing changed yet.
        set_setting(conn, "preference_meta", {**meta, "fingerprint": fingerprint})
    elif meta.get("fingerprint") != fingerprint:
        _bump_revision(conn, fingerprint)


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


def _change_summary(old_terms, new_terms, label):
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


def apply_term_edits(conn, positive_terms, negative_terms):
    """Store the submitted effective term lists as overrides of the derived ones."""
    profile = preference_profile(conn)
    changes = (_change_summary(profile["positive_terms"], positive_terms, "正向") +
               _change_summary(profile["negative_terms"], negative_terms, "反向"))
    rows = []
    for polarity, submitted, derived in (
        ("positive", positive_terms, profile["derived_positive_terms"]),
        ("negative", negative_terms, profile["derived_negative_terms"]),
    ):
        rows += [(polarity, term, weight) for term, weight in submitted.items() if derived.get(term) != weight]
        rows += [(polarity, term, None) for term in derived if term not in submitted]
    with conn:
        conn.execute("DELETE FROM term_overrides")
        conn.executemany("INSERT INTO term_overrides(polarity, term, weight) VALUES(?, ?, ?)", rows)
        conn.execute("INSERT INTO preference_edits(created_at, summary) VALUES(?, ?)",
                     (now(), "；".join(changes) if changes else "保存审美规则（内容未变）"))
        _bump_revision(conn)
    return preference_profile(conn)


# --- negative visual learning ------------------------------------------------

def rejected_visual_profiles(conn):
    return [{
        "creator_key": row["creator_key"],
        "reason": row["reason"],
        "affects_visual_score": bool(row["affects_visual_score"]),
        "video_profile": loads(row["video_profile"], {}),
        "updated_at": row["updated_at"],
    } for row in conn.execute("SELECT * FROM rejected_visual_profiles")]


def learn_rejected_creator_video(conn, key, reason):
    """Analyse a rejected creator's videos and keep them as a negative sample."""
    author = repository.load_creator(conn, key)
    if not author:
        return False
    video.analyze_authors(conn, [author], per_author=2)
    profile = author.get("video_content_profile")
    if not profile:
        return False
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO rejected_visual_profiles VALUES(?, ?, ?, ?, ?)",
            (key, reason, int(bool(config.VISUAL_REASON.search(reason or ""))), dumps(profile), now()),
        )
        repository.upsert_creator(conn, author, ["video_content_profile"])
    return True
