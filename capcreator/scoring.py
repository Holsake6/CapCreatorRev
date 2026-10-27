"""Creator scoring: style (text proxy + learned video taste) 70% + data quality 30% + feedback."""

import re

from . import textlearn

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
KANA = re.compile(r"[぀-ヿ]")


def has_japanese(text):
    # One kana is often decorative kaomoji, including on non-Japanese accounts.
    return len(KANA.findall(text or "")) >= 2


def is_category_work(work):
    return bool((work.get("category_seed") or work.get("category_signal")) and not work.get("excluded_signal"))


def reference_case_score(author, reference):
    """Metadata proxy for the hand-written rubric of the 26 dance reference videos."""
    if not reference:
        return 0, []
    texts = [f'{w.get("title", "")} {w.get("desc", "")}'.casefold()
             for w in author.get("works", []) if not w.get("likely_ai") and is_category_work(w)]
    combined = " ".join(texts)
    active = reference.get("common_aesthetic", {}).get("style_groups", [])
    matched = [label for label, terms in REFERENCE_STYLE_TERMS.items()
               if (not active or any(label.split("/")[0] in g for g in active))
               and any(t.casefold() in combined for t in terms)]
    rhythm = sum(t.casefold() in combined for t in REFERENCE_RHYTHM_TERMS)
    theme = sum(t.casefold() in combined for t in REFERENCE_THEME_TERMS)
    styled = sum(any(t.casefold() in text for terms in REFERENCE_STYLE_TERMS.values() for t in terms) for text in texts)
    works = author.get("works", [])
    simple = sum(1 <= int(w.get("clips") or 0) <= 3 for w in works)
    count = max(1, len(works))
    score = min(48, len(matched) * 12) + min(16, rhythm * 6) + min(12, theme * 6)
    score += min(12, round(12 * styled / max(1, len(texts)))) + min(12, round(12 * simple / count))
    evidence = matched[:]
    if rhythm:
        evidence.append("节奏/卡点信号")
    if theme:
        evidence.append("主题化包装信号")
    if simple / count >= 0.6:
        evidence.append("低至中等替换门槛")
    return min(100, score), evidence


def category_terms(config, examples):
    terms = [k.casefold().replace("-", " ") for k in config.get("keywords", []) if len(k) >= 2]
    for example in examples:
        if example.get("label", "positive") == "positive":
            terms += textlearn.learned_terms(f'{example.get("title", "")} {example.get("desc", "")}')
    return [t for t in dict.fromkeys(terms) if len(t) >= 2]


def keyword_relevance(author, terms):
    """Generic categories without a hand-written rubric: share of works matching category words."""
    if not terms:
        return 0, []
    works = [w for w in author.get("works", []) if not w.get("likely_ai")]
    hits, matched = 0, []
    for work in works:
        text = f'{work.get("title", "")} {work.get("desc", "")}'.casefold()
        found = [t for t in terms if t in text]
        if found:
            hits += 1
            matched.extend(found)
    if not works:
        return 0, []
    score = round(60 * hits / len(works) + 40 * min(1, hits / 3))
    common = [t for t, _ in sorted(((t, matched.count(t)) for t in set(matched)), key=lambda x: -x[1])[:4]]
    return score, [f"关键词：{t}" for t in common]


def quality_data_score(author):
    high = int(author.get("high_use_non_ai_indexed", 0))
    relevant = int(author.get("category_non_ai_indexed", 0))
    jp_posts = int(author.get("japanese_post_count", 0))
    max_uses = max((int(w.get("uses") or 0) for w in author.get("works", [])), default=0)
    return min(100, 10 * min(high, 5) + 5 * min(relevant, 5) + 3 * min(jp_posts, 5) + min(10, max_uses // 100000))


def creator_style(author, template_scores):
    """Aggregate per-template taste probabilities into a 0–100 creator style score.

    Top-3 mean rewards a creator's best work; the share above 0.5 rewards
    consistency. With few analysed videos the score shrinks toward 50.
    """
    probs = sorted((template_scores[f't{w["template_id"]}'] for w in author.get("works", [])
                    if f't{w.get("template_id")}' in template_scores), reverse=True)
    if not probs:
        return None, 0
    top = sum(probs[:3]) / len(probs[:3])
    share = sum(p >= 0.5 for p in probs) / len(probs)
    raw = 100 * (0.65 * top + 0.35 * share)
    shrink = len(probs) / (len(probs) + 1)
    return round(50 + (raw - 50) * shrink, 1), len(probs)


def score_author(author, config, text_profile, reference=None, template_scores=None, terms=None):
    if config.get("reference_cases"):
        proxy, evidence = reference_case_score(author, reference)
    else:
        proxy, evidence = keyword_relevance(author, terms or [])
    style, analysed = creator_style(author, template_scores or {})
    strength = max(0.0, min(1.0, float(config.get("style_strength", 60)) / 100))
    if not config.get("reference_cases") and not config.get("keywords"):
        # No keywords: the "text" proxy is only example file names (noisy), so the examples' look decides.
        strength = max(strength, 0.85)
    aesthetic = proxy if style is None else round((1 - strength) * proxy + strength * style, 1)
    quality = quality_data_score(author)
    learned = textlearn.preference_adjustment(author, text_profile or {})
    author.update(reference_match_score=proxy, reference_match_evidence=evidence,
                  style_score=style, style_analysed=analysed, aesthetic_score=aesthetic,
                  quality_data_score=quality, preference_adjustment=learned)
    author["score"] = round(aesthetic * 0.7 + quality * 0.3 + learned, 1)
    return author["score"]
