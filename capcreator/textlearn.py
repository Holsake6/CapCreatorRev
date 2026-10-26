"""Keyword learning from review notes (unchanged behaviour from the dance tool).

Approval notes become positive terms, rejection reasons negative terms. They
adjust a creator's score by matching template titles/descriptions. Reviewers
can edit the resulting terms on the profile page.
"""

import re
import time

LEARN_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}|[぀-ヿ]{2,}|[一-鿿]{2,}")
LEARN_STOP = {"作者", "模板", "视频", "比较", "感觉", "这个", "那个", "不是", "没有", "可以", "作品"}
# A rejection reason that talks about the look/edit (not e.g. "已合作") is
# allowed to teach the video model, not just the keyword list.
STYLE_REASON = re.compile(r"(?i)(AI|动画|节奏|包装|舞蹈|画面|构图|剪辑|内容|模板|特效|简单|审美|卡点|镜头|滤镜|风格|色|字|贴纸|转场|质感|土|丑|low|普通)")


def learned_terms(text):
    return [word.casefold() for word in LEARN_TOKEN.findall(text or "") if word.casefold() not in LEARN_STOP]


def negative_learned_terms(text):
    """Keep each rejection reason whole while also extracting matchable clauses/tokens."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().casefold())
    if not normalized:
        return []
    terms = [normalized]
    terms.extend(part.strip(" -_/\t") for part in re.split(r"[，。；！？、（）()\[\]{}:：]+", normalized)
                 if len(part.strip(" -_/\t")) >= 2 and not part.strip().isdigit())
    terms.extend(learned_terms(normalized))
    return list(dict.fromkeys(term for term in terms if term and term not in LEARN_STOP))


def effective_terms(derived, overrides, deleted):
    terms = {term: int(weight) for term, weight in derived.items() if term not in set(deleted)}
    for term, weight in overrides.items():
        if term:
            terms[term] = max(0, min(10, int(weight)))
    return dict(sorted(terms.items(), key=lambda item: (-item[1], item[0])))


def author_text(author):
    return " ".join([author.get("name", ""), author.get("bio", ""), *[
        f'{work.get("title", "")} {work.get("desc", "")}' for work in author.get("works", [])
    ]]).casefold()


def preference_adjustment(author, profile):
    """Bounded keyword adjustment in [-30, 30]."""
    text = author_text(author)
    positive = sum(weight for term, weight in profile.get("positive_terms", {}).items() if term in text)
    negative = sum(weight for term, weight in profile.get("negative_terms", {}).items() if term in text)
    return max(-30, min(30, positive * 2 - negative * 4))


def rebuild_profile(decisions, candidates, previous):
    by_key = {author_key(a): a for a in candidates}
    positive_phrases, negative_prompts = [], []
    positive_terms, negative_terms = {}, {}
    approved_features = []
    for key, decision in decisions.items():
        status = decision.get("status")
        if status in ("approved", "aesthetic_only"):
            phrase = "；".join(x for x in [(decision.get("specialty") or "").strip(),
                                           (decision.get("aesthetic_notes") or "").strip()] if x)
            if phrase:
                positive_phrases.append({"creator_key": key, "status": status, "text": phrase})
                for term in learned_terms(phrase):
                    positive_terms[term] = positive_terms.get(term, 0) + 1
            author = by_key.get(key)
            if author and status == "approved":
                uses = [int(w.get("uses") or 0) for w in author.get("works", [])]
                approved_features.append({
                    "creator_key": key, "indexed_count": author.get("indexed_count", len(uses)),
                    "high_use_non_ai_indexed": author.get("high_use_non_ai_indexed", 0),
                    "japanese_signal": author.get("japanese_signal", ""), "max_uses": max(uses, default=0),
                })
        elif status == "rejected":
            reason = (decision.get("rejection_reason") or "").strip()
            if reason:
                negative_prompts.append({"creator_key": key, "text": reason})
                for term in negative_learned_terms(reason):
                    negative_terms[term] = negative_terms.get(term, 0) + 1
    overrides = previous.get("term_overrides", {"positive": {}, "negative": {}})
    deleted = previous.get("deleted_terms", {"positive": [], "negative": []})
    changed = (positive_phrases != previous.get("positive_phrases", []) or
               negative_prompts != previous.get("negative_prompts", []) or
               positive_terms != previous.get("derived_positive_terms", previous.get("positive_terms", {})) or
               negative_terms != previous.get("derived_negative_terms", previous.get("negative_terms", {})))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "version": 2,
        "revision": max(1, int(previous.get("revision", 0)) + (1 if changed else 0)),
        "updated_at": now if changed else previous.get("updated_at", now),
        "approved_count": sum(d.get("status") == "approved" for d in decisions.values()),
        "aesthetic_only_count": sum(d.get("status") == "aesthetic_only" for d in decisions.values()),
        "rejected_count": sum(d.get("status") == "rejected" for d in decisions.values()),
        "learning_policy": "通过与审美达标特征累积为正向偏好；不通过原因原文累积为反向提示词。",
        "positive_phrases": positive_phrases, "negative_prompts": negative_prompts,
        "derived_positive_terms": positive_terms, "derived_negative_terms": negative_terms,
        "term_overrides": overrides, "deleted_terms": deleted,
        "positive_terms": effective_terms(positive_terms, overrides.get("positive", {}), deleted.get("positive", [])),
        "negative_terms": effective_terms(negative_terms, overrides.get("negative", {}), deleted.get("negative", [])),
        "approved_creator_features": approved_features,
        "edit_history": previous.get("edit_history", [])[-50:],
    }


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


def apply_edits(profile, positive_terms, negative_terms):
    derived_positive = profile.get("derived_positive_terms", profile.get("positive_terms", {}))
    derived_negative = profile.get("derived_negative_terms", profile.get("negative_terms", {}))
    old_positive, old_negative = profile.get("positive_terms", {}), profile.get("negative_terms", {})

    def diff(submitted, derived):
        return ({t: w for t, w in submitted.items() if derived.get(t) != w}, sorted(set(derived) - set(submitted)))

    def summary(old, new, label):
        parts = []
        added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
        changed = sorted(t for t in set(old) & set(new) if old[t] != new[t])
        if added:
            parts.append(f"{label}新增：" + "、".join(added))
        if removed:
            parts.append(f"{label}删除：" + "、".join(removed))
        if changed:
            parts.append(f"{label}调权：" + "、".join(f"{t} {old[t]}→{new[t]}" for t in changed))
        return parts

    pos_overrides, pos_deleted = diff(positive_terms, derived_positive)
    neg_overrides, neg_deleted = diff(negative_terms, derived_negative)
    changes = summary(old_positive, positive_terms, "正向") + summary(old_negative, negative_terms, "反向")
    profile["term_overrides"] = {"positive": pos_overrides, "negative": neg_overrides}
    profile["deleted_terms"] = {"positive": pos_deleted, "negative": neg_deleted}
    profile["positive_terms"] = dict(sorted(positive_terms.items(), key=lambda i: (-i[1], i[0])))
    profile["negative_terms"] = dict(sorted(negative_terms.items(), key=lambda i: (-i[1], i[0])))
    profile["revision"] = int(profile.get("revision", 0)) + 1
    profile["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    history = profile.get("edit_history", [])
    history.append({"at": profile["updated_at"], "summary": "；".join(changes) or "保存规则（内容未变）"})
    profile["edit_history"] = history[-50:]
    return profile


def author_key(author):
    return author.get("sec_uid") or author.get("name")
