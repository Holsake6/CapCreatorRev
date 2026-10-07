"""Creator match score: 70% reference aesthetics + 30% data quality + learned feedback."""

import json

from . import config, learning, repository, video

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
        reference = json.loads(config.REFERENCE_CASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return reference if reference.get("videos") and reference.get("common_aesthetic") else {}


def reference_case_score(author, reference):
    """Metadata proxy for the visual rubric extracted from the positive videos."""
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

    # Recognizable packaging, beat-aware changes, a coherent visual system and
    # low-to-medium replacement difficulty.
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


def preference_adjustment(author, profile):
    """Small metadata-only adjustment from learned review terms."""
    text = " ".join([author.get("name", ""), author.get("bio", ""), *[
        f'{work.get("title", "")} {work.get("desc", "")}' for work in author.get("works", [])
    ]]).casefold()
    positive = sum(weight for term, weight in profile.get("positive_terms", {}).items() if term in text)
    negative = sum(weight for term, weight in profile.get("negative_terms", {}).items() if term in text)
    return max(-30, min(30, positive * 2 - negative * 4))


def content_negative_adjustment(author, negatives):
    candidate = author.get("video_content_profile") or {}
    matches = [(video.similarity(candidate, item["video_profile"]), item["reason"])
               for item in negatives if item.get("affects_visual_score")]
    matches = [match for match in matches if match[0]]
    if not matches:
        return 0, ""
    similarity, reason = max(matches)
    # Dance videos naturally share people and motion; only similarity above a
    # conservative 0.65 baseline counts as evidence of a learned negative.
    if similarity <= 0.65:
        return 0, ""
    return round(min(20, (similarity - 0.65) / 0.35 * 20), 1), reason


def scoring_context(conn):
    return {
        "reference": read_reference_cases(),
        "profile": learning.preference_profile(conn),
        "negatives": learning.rejected_visual_profiles(conn),
    }


def score_author(author, context):
    aesthetic, evidence = reference_case_score(author, context["reference"])
    quality = quality_data_score(author)
    learned = preference_adjustment(author, context["profile"])
    penalty, reason = content_negative_adjustment(author, context["negatives"])
    author.update(
        reference_match_score=aesthetic, quality_data_score=quality,
        reference_match_evidence=evidence, preference_adjustment=learned,
        negative_video_penalty=penalty, negative_video_reason=reason,
        score=round(aesthetic * 0.7 + quality * 0.3 + learned - penalty, 1),
    )
    return author["score"]


SCORE_COLUMNS = ("score", "reference_match_score", "quality_data_score", "reference_match_evidence",
                 "preference_adjustment", "negative_video_penalty", "negative_video_reason")


def rescore_queue(conn):
    context = scoring_context(conn)
    authors = repository.queued_creators(conn)
    with conn:
        for author in authors:
            score_author(author, context)
            repository.upsert_creator(conn, author, SCORE_COLUMNS)
    return len(authors)
