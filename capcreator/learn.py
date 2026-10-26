"""Glue between stored category data, Template DNA and the taste model."""

import threading
import time

from . import dna, scoring, store, taste, textlearn
from .textlearn import STYLE_REASON, author_key

_analysis_lock = threading.Lock()


def normalize_candidates(data):
    """Map v2 dance-specific field names onto the category-neutral ones (idempotent)."""
    for author in data.get("candidates", []):
        if "category_non_ai_indexed" not in author and "dance_non_ai_indexed" in author:
            author["category_non_ai_indexed"] = author.get("dance_non_ai_indexed", 0)
            author["explicit_category_indexed"] = author.get("explicit_dance_indexed", 0)
        for work in author.get("works", []):
            if "category_signal" not in work and ("dance_signal" in work or "dance_seed" in work):
                work["category_signal"] = bool(work.get("dance_signal"))
                work["category_seed"] = bool(work.get("dance_seed"))
                work["excluded_signal"] = bool(work.get("non_dance_gimmick"))
    return data


def template_index(category, data=None):
    """key -> display info for every template the category knows about."""
    data = data or normalize_candidates(category.candidates())
    index = {}
    for item in category.read("background.json", []):
        index[item["key"]] = item
    for author in data.get("candidates", []):
        for work in author.get("works", []):
            key = f't{work["template_id"]}'
            index[key] = {"key": key, "template_id": work["template_id"], "title": work.get("title", ""),
                          "video_url": work.get("video_url", ""), "cover_url": work.get("cover_url", ""),
                          "url": work.get("url", ""), "uses": work.get("uses", 0),
                          "author_key": author_key(author), "author_name": author.get("name", "")}
    for example in category.examples():
        index[example["key"]] = {**index.get(example["key"], {}), **example, "is_example": True}
    return index


def records_for(keys):
    out = {}
    for key in keys:
        record = dna.cached(key)
        if record:
            out[key] = record
    return out


def training_labels(category, data=None):
    data = data or normalize_candidates(category.candidates())
    points = []
    for example in category.examples():
        if example.get("label") == "positive":
            points.append({"key": example["key"], "label": 1, "source": "example"})
        elif example.get("label") == "negative":
            points.append({"key": example["key"], "label": 0, "source": "dislike"})
    # Trainer clicks: the latest explicit like/dislike for a key wins over older ones.
    stored = category.labels()
    latest = {}
    for point in stored["points"]:
        latest[point["key"]] = point
    points.extend(latest.values())
    decisions = category.decisions()
    for author in data.get("candidates", []):
        decision = decisions.get(author_key(author), {})
        status = decision.get("status")
        if status not in ("approved", "aesthetic_only", "rejected"):
            continue
        if status == "rejected":
            source = "rejected_style" if STYLE_REASON.search(decision.get("rejection_reason") or "") else "rejected_other"
        else:
            source = "approved"
        for work in author.get("works", []):
            # An approved creator's off-topic templates say nothing about this category's style.
            if status != "rejected" and not scoring.is_category_work(work):
                continue
            points.append({"key": f't{work["template_id"]}', "label": 0 if status == "rejected" else 1,
                           "source": source})
    return points, stored["pairs"]


def retrain(category, data=None):
    data = data or normalize_candidates(category.candidates())
    index = template_index(category, data)
    records = records_for(index)
    points, pairs = training_labels(category, data)
    model = taste.train(records, points, pairs, slug=category.slug, previous=category.model())
    if model:
        category.save_model(model)
    return model


def template_scores(category, data=None, model=None):
    model = model or category.model()
    if not model:
        return {}
    index = template_index(category, data)
    return taste.score_records(model, records_for(index))


def reference_cases(category):
    reference = category.read("reference_positive_cases.json", {})
    return reference if reference.get("videos") and reference.get("common_aesthetic") else {}


def rescore(category, data, relabel=False):
    """Recompute every creator's score with the current text profile and taste model."""
    config = category.config
    normalize_candidates(data)
    scores = template_scores(category, data)
    terms = scoring.category_terms(config, category.examples())
    reference = reference_cases(category) if config.get("reference_cases") else None
    profile = category.text_profile()
    candidates = data.get("candidates", [])
    for author in candidates:
        scoring.score_author(author, config, profile, reference, scores, terms)
        for work in author.get("works", []):
            score = scores.get(f't{work.get("template_id")}')
            work["style_prob"] = None if score is None else round(score, 3)
    candidates.sort(key=lambda a: a.get("score", 0), reverse=True)
    if relabel:
        ranked = min(30, round(len(candidates) * 0.6))
        for i, author in enumerate(candidates, 1):
            author["recommendation_type"] = "高匹配" if i <= ranked else "随机探索"
            author["match_rank"] = i
    model = category.model()
    data["model_code"] = model.get("code") if model else None
    data["reference_case_count"] = len((reference or {}).get("videos", []))
    data["scoring_policy"] = "审美（文字代理 + 视频风格模型）70% + 数据质量 30% + 审核反馈修正"
    return data


def rebuild_text_profile(category, data=None, decisions=None):
    data = data or category.candidates()
    profile = textlearn.rebuild_profile(decisions if decisions is not None else category.decisions(),
                                        data.get("candidates", []), category.text_profile())
    category.save_text_profile(profile)
    return profile


def best_works(author, limit=1):
    works = [w for w in author.get("works", []) if w.get("video_url")]
    works.sort(key=lambda w: (scoring.is_category_work(w), int(w.get("uses") or 0)), reverse=True)
    return works[:limit]


def analyze_works(works, progress=None, workers=3):
    """Download + DNA for CapCut works (skips cached ones). Returns {key: record}."""
    if not dna.available():
        return {}
    from concurrent.futures import ThreadPoolExecutor
    results = {}

    def one(work):
        key = f't{work["template_id"]}'
        cached = dna.cached(key)
        if cached:
            return key, cached
        try:
            return key, dna.analyze_template(work["template_id"], work.get("video_url", ""),
                                             meta={"title": work.get("title", "")})
        except Exception:
            return key, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (key, record) in enumerate(pool.map(one, works), 1):
            if record:
                results[key] = record
            if progress:
                progress(done, len(works))
    return results


def prepare_pool(category, limit=60, per_author=2, progress=None):
    """Analyse not-yet-analysed candidate works so the trainer and model have material."""
    data = normalize_candidates(category.candidates())
    todo = []
    for author in data.get("candidates", []):
        for work in best_works(author, per_author):
            if not dna.cached(f't{work["template_id"]}'):
                todo.append(work)
    with _analysis_lock:
        done = analyze_works(todo[:limit], progress=progress)
    return len(done), len(todo)


def add_background(category, works):
    """Remember analysed templates that never became candidates (PU-learning background)."""
    with store.LOCK:
        current = {item["key"]: item for item in category.read("background.json", [])}
        for work in works:
            key = f't{work["template_id"]}'
            current[key] = {"key": key, "template_id": work["template_id"], "title": work.get("title", ""),
                            "video_url": work.get("video_url", ""), "cover_url": work.get("cover_url", ""),
                            "url": work.get("url", ""), "uses": work.get("uses", 0),
                            "author_key": work.get("sec_uid") or work.get("author_name", ""),
                            "author_name": work.get("author_name", ""), "added_at": time.strftime("%Y-%m-%d")}
        items = list(current.values())[-3000:]
        category.write("background.json", items)
