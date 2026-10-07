"""Independent "new category" workspace: positive-only learning, no negative prompts."""

import json
import re

from .db import dumps, get_setting, loads, now, set_setting
from .learning import learned_terms

DEFAULT_NAME = "新类别（待命名）"
LEARNING_POLICY = "只从用户提供和审核通过的正面案例自动学习；不建立反向提示词。"


def case_records(payload):
    """Accept common JSON layouts while keeping the supplied data as evidence."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("videos", "cases", "examples", "items", "data", "positive_cases"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    raise ValueError("正面案例必须是 JSON 对象或数组")


def nested_strings(value):
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        return [text] if text else []
    if isinstance(value, list):
        return [text for item in value for text in nested_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in nested_strings(item)]
    return []


def fingerprint(item):
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def state(conn):
    meta = get_setting(conn, "category_meta", {})
    cases = [loads(row["payload"]) for row in conn.execute("SELECT payload FROM category_cases ORDER BY id")]
    terms, fields, summaries = {}, {}, []
    for index, item in enumerate(cases, 1):
        if isinstance(item, dict):
            for field in item:
                fields[str(field)] = fields.get(str(field), 0) + 1
        combined = "；".join(nested_strings(item))
        for term in learned_terms(combined):
            terms[term] = terms.get(term, 0) + 1
        if combined:
            summaries.append({"index": index, "text": combined[:280]})
    return {
        "category_name": meta.get("name", DEFAULT_NAME),
        "revision": int(meta.get("revision", 0)),
        "updated_at": meta.get("updated_at", "尚未学习"),
        "learning_policy": LEARNING_POLICY,
        "case_count": len(cases),
        "positive_terms": dict(sorted(terms.items(), key=lambda pair: (-pair[1], pair[0]))),
        "source_fields": dict(sorted(fields.items(), key=lambda pair: (-pair[1], pair[0]))),
        "case_summaries": summaries,
    }


def add_cases(conn, payload, category_name=""):
    """Append positive examples; exact duplicates are ignored. Returns count added."""
    incoming = case_records(payload)
    if not incoming:
        raise ValueError("没有读取到正面案例")
    meta = get_setting(conn, "category_meta", {})
    name = (category_name or meta.get("name") or DEFAULT_NAME).strip()
    added = 0
    stamp = now()
    with conn:
        for item in incoming:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO category_cases(fingerprint, payload, created_at) VALUES(?, ?, ?)",
                (fingerprint(item), dumps(item), stamp))
            added += cursor.rowcount
        changed = added or name != meta.get("name", DEFAULT_NAME)
        set_setting(conn, "category_meta", {
            "name": name,
            "revision": int(meta.get("revision", 0)) + (1 if changed else 0),
            "updated_at": stamp if changed else meta.get("updated_at", "尚未学习"),
        })
    return added
