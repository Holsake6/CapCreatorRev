"""Find creators for a category by crawling CapCut's related-template graph.

Entry points, strongest first:

1. the category's own example templates (CapCut's "related" list of a liked
   template is the best similarity search available without an API);
2. explore pages for the category keywords (plus this week's JP TikTok songs
   for dance) and configured landing pages;
3. previously seen templates that matched the category (the graph grows daily).

Cheap metadata rules run on everything; only the best creators get their
preview videos downloaded and scored by the learned taste model.
"""

import csv
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import capcut, dna, learn, net, paths, scoring, store
from .scoring import has_japanese
from .textlearn import author_key

ORICON_TIKTOK_WEEKLY = "https://www.oricon.co.jp/rank/tt/w/"
FALLBACK_TREND_TERMS = ("ピンク", "BALI", "きゃわぽっぴんどぅー", "Sunshine Girl", "分かっちゃいないね",
                        "Hug feat. kojikoji", "恋、はじめました。", "愛のレンタル", "マル・マル・モリ・モリ！", "エアロピクルス")
BUILTIN_EXCLUSIONS = ["rin_go.x", "s.n_so_", "カーラ", "てぃーすけ", "りあな", "みるくぱんだ"]


class Rules:
    def __init__(self, config):
        self.config = config
        self.include = re.compile(config["include_regex"]) if config.get("include_regex") else None
        self.exclude = re.compile(config["exclude_regex"]) if config.get("exclude_regex") else None
        self.ai = re.compile(config["ai_regex"]) if config.get("exclude_ai") and config.get("ai_regex") else None

    def signal(self, text, terms):
        if self.include is not None:
            return bool(self.include.search(text))
        lowered = text.casefold()
        return any(term in lowered for term in terms)


def current_jp_tiktok_songs(category, force=False):
    """This week's Japan TikTok chart from ORICON (no API token needed)."""
    cached = category.read("trend_terms.json", {})
    clean = cached.get("terms") and not any("�" in t for t in cached["terms"])
    if not force and clean and time.time() - float(cached.get("checked_epoch", 0)) < 24 * 3600:
        return cached["terms"][:10]
    from html.parser import HTMLParser

    class Headings(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.current, self.items = 0, [], []

        def handle_starttag(self, tag, attrs):
            if tag == "h2":
                self.depth, self.current = 1, []
            elif self.depth:
                self.depth += 1

        def handle_endtag(self, tag):
            if self.depth:
                self.depth -= 1
                if tag == "h2" and self.depth == 0:
                    text = re.sub(r"\s+", " ", "".join(self.current)).strip()
                    if text:
                        self.items.append(text)

        def handle_data(self, data):
            if self.depth:
                self.current.append(data)

    terms, source = [], ORICON_TIKTOK_WEEKLY
    try:
        source, page = net.fetch_text(ORICON_TIKTOK_WEEKLY, timeout=25)
        parser = Headings()
        parser.feed(page)
        for heading in parser.items:
            if heading == "音楽ランキング":
                break
            if re.search(r"\d{4}年\d{2}月\d{2}日付", heading):
                continue
            terms.append(heading)
            if len(terms) == 10:
                break
    except (OSError, ValueError):
        terms = cached.get("terms") or list(FALLBACK_TREND_TERMS)
    payload = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "checked_epoch": time.time(),
               "source": source, "terms": terms or list(FALLBACK_TREND_TERMS)}
    category.write("trend_terms.json", payload)
    return payload["terms"][:10]


def exclusion_terms():
    terms = list(BUILTIN_EXCLUSIONS)
    if paths.exclusions_txt().exists():
        terms += [line.strip() for line in paths.exclusions_txt().read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
    if paths.exclusions_csv().exists():
        with paths.exclusions_csv().open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                terms += [row.get(k, "").strip() for k in ("CC用户名称", "CC ID", "CC主页link") if row.get(k)]
    return [t.casefold() for t in terms if t]


def is_excluded(author, terms):
    values = [author.get("name", "").casefold(), author.get("cc_id", "").casefold()]
    return any(term == value or (term and term in value) for term in terms for value in values)


def scan_pages(category, quick=False):
    if quick:
        return [1, 2, 3]
    cursor = max(4, int(category.read("scan_state.json", {}).get("next_archive_page", 4)))
    return sorted({1, 2, 3, *range(cursor, cursor + 5)})


def advance_scan_state(category, generated_at):
    state = category.read("scan_state.json", {})
    cursor = max(4, int(state.get("next_archive_page", 4)))
    state.update(next_archive_page=cursor + 5 if cursor + 5 <= 200 else 4,
                 last_completed_at=generated_at, last_archive_pages=list(range(cursor, cursor + 5)))
    category.write("scan_state.json", state)


def landing_urls(category):
    config = category.config
    keywords = list(config.get("keywords", []))
    if config.get("trend_source") == "oricon_tiktok_jp":
        keywords += current_jp_tiktok_songs(category)
    urls = [*config.get("landing_urls", []), *(capcut.explore_url(k, config["region"]) for k in keywords)]
    return list(dict.fromkeys(urls))


def seed_ids(category, rules, terms, quick=False, log=print):
    config = category.config
    examples = [e["template_id"] for e in category.examples()
                if e.get("template_id") and e.get("label", "positive") == "positive"]
    pages = scan_pages(category, quick)
    urls = [u if p == 1 else f"{u}{'&' if '?' in u else '?'}page={p}" for u in landing_urls(category) for p in pages]
    discovered, failures = [], []
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {pool.submit(capcut.landing_template_ids, url): url for url in urls}
        for job in as_completed(jobs):
            try:
                discovered.extend(job.result())
            except (OSError, ValueError) as exc:
                failures.append(exc)
    if failures and not discovered:
        first = failures[0]
        advice = first.advice() if isinstance(first, net.NetError) else ""
        log(f"⚠ 专题页全部读取失败（{len(failures)} 个）：{first} {advice}")
    grown = []
    for page in capcut.cached_pages():
        for item in capcut.page_items(page):
            text = f'{item.get("title") or ""} {item.get("desc") or ""}'
            if rules.signal(text, terms) and not (rules.ai and rules.ai.search(text)):
                grown.append(capcut.item_id(item))
    ordered = [*examples, *config.get("seed_template_ids", []), *discovered, *grown]
    return list(dict.fromkeys(i for i in ordered if i)), set(examples) | set(discovered), len(failures)


def item_record(item, rules, terms, config):
    author = item.get("author") or {}
    template_id = capcut.item_id(item)
    if not template_id or not author.get("name"):
        return None
    title, desc = item.get("title") or "", item.get("desc") or ""
    text = f"{title} {desc}"
    try:
        created = float(item.get("createTime") or item.get("create_time") or 0)
        created = created / 1000 if created > 10_000_000_000 else created
    except (TypeError, ValueError):
        created = 0
    age = max(0, int((time.time() - created) // 86400)) if created else None
    uses = int(item.get("usageAmount") or item.get("usage_amount") or 0)
    return {
        "template_id": template_id, "title": title, "desc": desc[:350], "uses": uses,
        "created_at_epoch": int(created) if created else 0,
        "published_at": time.strftime("%Y-%m-%d", time.localtime(created)) if created else "",
        "age_days": age,
        "stale_low_use": bool(created and age >= config["stale_days"] and uses < config["stale_min_uses"]),
        "clips": item.get("segmentAmount") or item.get("fragment_count"),
        "url": "https://www.capcut.com" + (item.get("canonicalPath") or f'/{config["region"]}/template-detail/{template_id}'),
        "cover_url": item.get("coverUrl") or "", "video_url": item.get("videoUrl") or "",
        "author_name": author.get("name", ""), "author_bio": author.get("description", ""),
        "sec_uid": author.get("secUid") or (author.get("profileUrl") or "").rsplit("/", 1)[-1],
        "japanese_post": has_japanese(text),
        "likely_ai": bool(rules.ai and rules.ai.search(text)),
        "category_signal": rules.signal(text, terms),
        "excluded_signal": bool(rules.exclude and rules.exclude.search(text)),
    }


def qualify(author, config, terms_excl, seen, rules):
    """Apply hard rules; returns the author dict (mutated) or None."""
    key = author_key(author)
    if key in seen or is_excluded(author, terms_excl):
        return None
    works = sorted(author["works"], key=lambda w: (scoring.is_category_work(w), w["uses"]), reverse=True)
    eligible = [w for w in works if not w.get("stale_low_use")]
    non_ai = [w for w in eligible if not w["likely_ai"]]
    explicit = [w for w in non_ai if w.get("category_signal") and not w.get("excluded_signal")]
    relevant = [w for w in non_ai if scoring.is_category_work(w)]
    high = [w for w in explicit if w["uses"] >= config["high_use_threshold"]]
    post_jp = sum(w["japanese_post"] for w in eligible)
    if config.get("language") == "ja" and not (post_jp or has_japanese(author["bio"]) or has_japanese(author["name"])):
        return None
    if not relevant:
        return None
    author.update(
        works=eligible, stale_low_use_excluded_count=len(works) - len(eligible), indexed_count=len(eligible),
        high_use_non_ai_indexed=len(high), category_non_ai_indexed=len(relevant),
        explicit_category_indexed=len(explicit),
        japanese_signal="投稿文案" if post_jp else ("自我介绍" if has_japanese(author["bio"]) else
                                                   ("用户名" if has_japanese(author["name"]) else "不限语言")),
        japanese_post_count=post_jp, ai_flagged_count=sum(w["likely_ai"] for w in eligible))
    share = capcut.PROFILE_SHARE.search(author["bio"])
    if share:
        author["profile_link_hint"] = share.group(0)
    return author


def visual_gate_passes(config, author, records):
    if config.get("visual_gate") != "people_motion":
        return True
    analysed = [records[f't{w["template_id"]}'] for w in author.get("works", []) if f't{w["template_id"]}' in records]
    if not analysed:
        return author.get("explicit_category_indexed", 0) > 0
    verified = any(max(r["scalars"]["person_ratio"], r["scalars"]["face_ratio"]) >= 0.3
                   and r["scalars"]["motion_mean"] >= 0.006 for r in analysed)
    author["category_video_verified"] = verified
    # The detector is uncalibrated for edits, so explicit text evidence still wins.
    return verified or author.get("explicit_category_indexed", 0) > 0


def discover(category, max_pages=None, workers=10, log=print):
    config = category.config
    max_pages = max_pages or config["scan_pages"]
    rules = Rules(config)
    terms = scoring.category_terms(config, category.examples())
    seeds, seed_set, failed_pages = seed_ids(category, rules, terms, quick=max_pages <= 50, log=log)
    if not seeds:
        raise RuntimeError("没有入口模板：CapCut 专题页无法访问，且本类别还没有 CapCut 示例模板。"
                           "请运行 doctor 检查网络，或先添加示例模板链接。")
    log(f"入口模板 {len(seeds)} 个，开始沿 CapCut 相关推荐扩展（最多 {max_pages} 页）…")
    queue, queued, chosen, records, errors = list(seeds), set(seeds), [], {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while queue and len(chosen) < max_pages:
            batch = queue[:min(100, max_pages - len(chosen))]
            del queue[:len(batch)]
            chosen.extend(batch)
            jobs = {pool.submit(capcut.template_page, tid, False, config["region"]): tid for tid in batch}
            for job in as_completed(jobs):
                result = job.result()
                if result.get("error"):
                    errors.append({"template_id": jobs[job], "error": result["error"]})
                for item in capcut.page_items(result):
                    record = item_record(item, rules, terms, config)
                    if not record:
                        continue
                    record["category_seed"] = record["template_id"] in seed_set
                    records[record["template_id"]] = record
                    if record["template_id"] not in queued:
                        queue.append(record["template_id"])
                        queued.add(record["template_id"])
            log(f"  已读取 {len(chosen)} 页，索引 {len(records)} 条模板")
    if errors and not records:
        log(f"⚠ 模板详情页全部失败，例如：{errors[0]['error']}")

    authors = {}
    for record in records.values():
        key = record["sec_uid"] or record["author_name"]
        author = authors.setdefault(key, {
            "name": record["author_name"], "bio": record["author_bio"], "sec_uid": record["sec_uid"],
            "works": [], "cc_id": "", "cc_link": "", "total_posts": None, "tt_link": "", "profile_verified": False})
        if len(record["author_bio"]) > len(author["bio"]):
            author["bio"] = record["author_bio"]
        author["works"].append(record)

    seen = category.read("seen_creators.json", {})
    excl = exclusion_terms()
    candidates = [a for a in (qualify(a, config, excl, seen, rules) for a in authors.values()) if a]
    skipped_seen = sum(author_key(a) in seen for a in authors.values())

    # Cheap ranking first, then video analysis for the strongest pool only.
    profile = category.text_profile()
    reference = learn.reference_cases(category) if config.get("reference_cases") else None
    model = category.model()
    for author in candidates:
        scoring.score_author(author, config, profile, reference, {}, terms)
    candidates.sort(key=lambda a: a["score"], reverse=True)
    analysed = {}
    if dna.available() and config["analyze_top"] > 0:
        top = candidates[:config["analyze_top"]]
        works = [w for a in top for w in learn.best_works(a, 2 if a in top[:20] else 1)]
        log(f"下载并分析 {len(works)} 条预览视频（Template DNA）…")
        analysed = learn.analyze_works(works, progress=lambda d, n: d % 10 == 0 and log(f"  视频分析 {d}/{n}"))
        candidate_ids = {w["template_id"] for a in candidates for w in a["works"]}
        learn.add_background(category, [r for r in records.values()
                                        if f't{r["template_id"]}' in analysed and r["template_id"] not in candidate_ids])
    from . import taste
    scores = taste.score_records(model, learn.records_for({f't{w["template_id"]}' for a in candidates for w in a["works"]})) if model else {}
    for author in candidates:
        scoring.score_author(author, config, profile, reference, scores, terms)
    records_by_key = learn.records_for({f't{w["template_id"]}' for a in candidates for w in a["works"]})
    candidates = [a for a in candidates if visual_gate_passes(config, a, records_by_key)]
    candidates.sort(key=lambda a: a["score"], reverse=True)
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seed_pages": len(chosen),
            "indexed_templates": len(records), "errors": errors[:50], "failed_landing_pages": failed_pages,
            "skipped_seen_creators": skipped_seen, "analysed_videos": len(analysed),
            "model_code": model.get("code") if model else None,
            "trend_terms": category.read("trend_terms.json", {}).get("terms", []),
            "candidates": candidates}


def merge_results(category, previous, new, append_batch_size=None):
    """Append unseen creators: 60% best matches + 40% random exploration, up to the queue limit."""
    config = category.config
    existing = list((previous or {}).get("candidates", []))
    keys = {author_key(a) for a in existing}
    decisions = category.decisions()
    pending = sum(decisions.get(author_key(a), {}).get("status", "pending") == "pending" for a in existing)
    slots = (max(0, int(append_batch_size)) if append_batch_size is not None
             else max(0, config["max_pending"] - pending))
    available = [a for a in new.get("candidates", []) if author_key(a) not in keys]
    ranked = available[:min(len(available), round(slots * 0.6))]
    remainder = available[len(ranked):]
    rng = random.Random(new.get("generated_at", ""))
    exploratory = rng.sample(remainder, min(len(remainder), slots - len(ranked))) if slots > len(ranked) else []
    rank_of = {id(a): i for i, a in enumerate(available, 1)}
    for author in ranked:
        author.update(recommendation_type="高匹配", match_rank=rank_of[id(author)])
    for author in exploratory:
        author.update(recommendation_type="随机探索", match_rank=rank_of[id(author)])
    added = ranked + exploratory
    for author in added:
        author["discovered_at"] = new.get("generated_at")
        existing.append(author)
    merged = {**(previous or {}), **{k: v for k, v in new.items() if k != "candidates"},
              "candidates": existing, "latest_batch_candidates": len(added),
              "latest_batch_keys": [author_key(a) for a in added],
              "latest_ranked_candidates": len(ranked), "latest_random_candidates": len(exploratory),
              "deferred_new_candidates": max(0, len(available) - len(added)),
              "pending_queue": pending + len(added), "total_candidates": len(existing)}
    history = category.read("scan_history.json", [])
    history.append({"generated_at": new.get("generated_at"), "indexed_templates": new.get("indexed_templates", 0),
                    "new_candidates": len(added), "deferred_new_candidates": merged["deferred_new_candidates"],
                    "skipped_seen_creators": new.get("skipped_seen_creators", 0),
                    "analysed_videos": new.get("analysed_videos", 0), "model_code": new.get("model_code")})
    category.write("scan_history.json", history[-365:])
    return merged


def record_seen(category, authors, timestamp):
    seen = category.read("seen_creators.json", {})
    for author in authors:
        key = author_key(author)
        if key:
            previous = seen.get(key, {})
            seen[key] = {"name": author.get("name", previous.get("name", "")),
                         "first_seen": previous.get("first_seen", timestamp), "last_seen": timestamp}
    category.write("seen_creators.json", seen)


def pending_count(category, data):
    decisions = category.decisions()
    return sum(decisions.get(author_key(a), {}).get("status", "pending") == "pending" for a in data.get("candidates", []))


def refresh(category, max_pages=None, append_batch_size=None, log=print):
    """Incremental scan + merge. Returns ``(data, message, changed)``."""
    config = category.config
    max_pages = max_pages or config["scan_pages"]
    previous = learn.normalize_candidates(category.candidates())
    pending = pending_count(category, previous)
    if append_batch_size is None and previous.get("candidates") and pending >= config["max_pending"]:
        return previous, f"当前已有 {pending} 位待审作者。请先审核一部分，刷新时再补足到 {config['max_pending']} 位。", False
    new = discover(category, max_pages=max(1, min(max_pages, 3000)), log=log)
    if not new["indexed_templates"]:
        raise RuntimeError("没有获取到模板，保留上次扫描结果。请运行 doctor 检查 CapCut 连接。")
    with store.LOCK:
        data = merge_results(category, previous, new, append_batch_size)
        apply_stale_rule(category, data)
        if dna.available():
            learn.retrain(category, data)  # new analysed videos widen the pool / background
        learn.rescore(category, data)
        category.save_candidates(data)
    added = set(data.get("latest_batch_keys", []))
    record_seen(category, [a for a in new["candidates"] if author_key(a) in added], new["generated_at"])
    if max_pages > 50:
        advance_scan_state(category, new["generated_at"])
    learn.rebuild_text_profile(category, data)
    message = (f"扫描 {data['indexed_templates']} 条模板，分析 {new.get('analysed_videos', 0)} 条视频，"
               f"本次补充 {data['latest_batch_candidates']} 位；当前待审 {data['pending_queue']} 位。")
    return data, message, True


def apply_stale_rule(category, data):
    """Re-apply the N-day / M-use hard rule to saved work (templates age every day)."""
    config = category.config
    decisions = category.decisions()
    now = time.time()
    kept, removed_authors, removed_templates = [], 0, 0
    for author in data.get("candidates", []):
        eligible = []
        for work in author.get("works", []):
            created = float(work.get("created_at_epoch") or 0)
            age = max(0, int((now - created) // 86400)) if created else None
            work["age_days"] = age
            work["stale_low_use"] = bool(created and age >= config["stale_days"]
                                         and int(work.get("uses") or 0) < config["stale_min_uses"])
            (eligible if not work["stale_low_use"] else []).append(work)
        dropped = len(author.get("works", [])) - len(eligible)
        removed_templates += dropped
        author["stale_low_use_excluded_count"] = int(author.get("stale_low_use_excluded_count", 0)) + dropped
        author["works"] = eligible
        relevant = [w for w in eligible if not w.get("likely_ai") and scoring.is_category_work(w)]
        explicit = [w for w in relevant if w.get("category_signal")]
        author.update(indexed_count=len(eligible), category_non_ai_indexed=len(relevant),
                      explicit_category_indexed=len(explicit),
                      high_use_non_ai_indexed=sum(int(w.get("uses") or 0) >= config["high_use_threshold"] for w in explicit))
        status = decisions.get(author_key(author), {}).get("status", "pending")
        if relevant or status != "pending":
            kept.append(author)
        else:
            removed_authors += 1
    data["candidates"] = kept
    data["stale_low_use_rule"] = f"发布满{config['stale_days']}天且 uses<{config['stale_min_uses']} 的模板直接排除"
    return removed_authors, removed_templates


def enrich_profiles(category, data):
    """Resolve homepage share links found in bios (only verified matches are kept)."""
    changed = False
    for author in data.get("candidates", []):
        if author.get("profile_verified") or author.get("profile_link_checked"):
            continue
        link = author.get("profile_link_hint") or author.get("cc_link", "")
        if not link:
            continue
        try:
            profile = capcut.resolve_profile_link(link)
            if profile["name"].strip().casefold() != author["name"].strip().casefold():
                raise ValueError("链接指向其他作者")
            author.update(cc_id=profile["cc_id"], cc_link=link, total_posts=profile["total_posts"],
                          tt_link=profile["tt_link"], public_id=profile["public_id"], profile_verified=True)
        except (ValueError, OSError):
            author["cc_link"] = ""
        author["profile_link_checked"] = True
        changed = True
    return changed


def deep_check(category, key, public_id, limit_analyse=3):
    """Pull a creator's full homepage catalogue, add it to their works and score it.

    This is how "this creator mostly makes <category>" gets verified instead
    of being inferred from the few templates the crawl happened to meet.
    """
    config = category.config
    rules = Rules(config)
    terms = scoring.category_terms(config, category.examples())
    items = capcut.creator_templates(public_id)
    with store.LOCK:
        data = learn.normalize_candidates(category.candidates())
        author = next((a for a in data["candidates"] if author_key(a) == key), None)
        if not author:
            raise ValueError("unknown author")
        known = {w["template_id"] for w in author.get("works", [])}
        for item in items:
            record = item_record(item, rules, terms, config)
            if record and record["template_id"] not in known:
                record["sec_uid"] = author.get("sec_uid", "")
                record["from_homepage"] = True
                author["works"].append(record)
                known.add(record["template_id"])
        relevant = [w for w in author["works"] if scoring.is_category_work(w) and not w.get("likely_ai")]
        author["homepage_checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        author["homepage_template_count"] = len(items)
        author["homepage_category_share"] = round(
            sum(1 for w in author["works"] if w.get("from_homepage") and scoring.is_category_work(w))
            / max(1, sum(1 for w in author["works"] if w.get("from_homepage"))), 3)
        category.save_candidates(data)
    learn.analyze_works(learn.best_works(author, limit_analyse))
    with store.LOCK:
        data = learn.normalize_candidates(category.candidates())
        learn.rescore(category, data)
        category.save_candidates(data)
    return {"templates": len(items), "category_share": author["homepage_category_share"],
            "relevant": len(relevant)}
