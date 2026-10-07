"""Creator discovery: landing pages -> templates -> creators -> review batch."""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from . import capcut, config, learning, repository, scoring, video
from .db import dumps, get_setting, loads, now, set_setting


class RefreshCancelled(Exception):
    """Raised when a refresh is stopped before results are saved."""


def _check_cancel(cancel_event):
    if cancel_event and cancel_event.is_set():
        raise RefreshCancelled("已停止刷新，保留上一次候选结果")


def has_japanese(text):
    # One kana is often decorative kaomoji, including on non-Japanese accounts.
    return len(config.KANA.findall(text or "")) >= 2


def item_record(item):
    """Normalise a CapCut template payload (detail, recommendation or live list)."""
    author = item.get("author") or {}
    template_id = str(item.get("templateId") or item.get("id") or "")
    if not template_id or not author.get("name"):
        return None
    title = item.get("title") or ""
    desc = item.get("desc") or ""
    try:
        created_at = float(item.get("createTime") or item.get("create_time") or 0)
        if created_at > 10_000_000_000:
            created_at /= 1000
    except (TypeError, ValueError):
        created_at = 0
    uses = int(item.get("usageAmount") or item.get("usage_amount") or 0)
    sec_uid = author.get("secUid") or author.get("profileUrl", "").rsplit("/", 1)[-1]
    text = f"{title} {desc}"
    return {
        "template_id": template_id,
        "creator_key": sec_uid or author["name"],
        "title": title,
        "desc": desc[:350],
        "uses": uses,
        "created_at_epoch": int(created_at) if created_at else 0,
        "clips": item.get("segmentAmount") or item.get("fragment_count"),
        "url": "https://www.capcut.com" + (item.get("canonicalPath") or f"/ja-jp/template-detail/{template_id}"),
        "cover_url": item.get("coverUrl") or "",
        "video_url": item.get("videoUrl") or "",
        "author_name": author.get("name", ""),
        "author_bio": author.get("description", ""),
        "sec_uid": sec_uid,
        "japanese_post": has_japanese(text),
        "likely_ai": bool(config.AI.search(text)),
        "dance_signal": bool(config.DANCE.search(text)),
        "non_dance_gimmick": bool(config.NON_DANCE_GIMMICK.search(text)),
    }


# --- discovery inputs ----------------------------------------------------------

def trend_terms(conn, force=False):
    """Current Japan TikTok weekly chart titles, cached for 24 hours."""
    cached = get_setting(conn, "trend_terms", {})
    clean = cached.get("terms") and not any("�" in term for term in cached["terms"])
    if not force and clean and time.time() - float(cached.get("checked_epoch", 0)) < 24 * 3600:
        return cached["terms"][:10]
    source = config.ORICON_TIKTOK_WEEKLY
    try:
        source, terms = capcut.fetch_jp_tiktok_chart()
    except Exception:
        terms = cached.get("terms") or []
    payload = {"checked_at": now(), "checked_epoch": time.time(), "source": source,
               "terms": terms or list(config.FALLBACK_TREND_TERMS)}
    set_setting(conn, "trend_terms", payload)
    conn.commit()
    return payload["terms"][:10]


def landing_urls(conn):
    trend_urls = [f"https://www.capcut.com/ja-jp/explore/{quote(term, safe='')}" for term in trend_terms(conn)]
    return list(dict.fromkeys([*config.DANCE_LANDINGS, *trend_urls]))


def scan_page_numbers(conn, quick=False):
    if quick:
        return [1, 2, 3]
    cursor = max(4, int(get_setting(conn, "scan_state", {}).get("next_archive_page", 4)))
    # Newest pages every time plus five rotating archive pages.
    return sorted({1, 2, 3, *range(cursor, cursor + 5)})


def advance_scan_state(conn):
    state = get_setting(conn, "scan_state", {})
    cursor = max(4, int(state.get("next_archive_page", 4)))
    next_page = cursor + 5
    state.update(next_archive_page=4 if next_page > 200 else next_page,
                 last_completed_at=now(), last_archive_pages=list(range(cursor, cursor + 5)))
    set_setting(conn, "scan_state", state)
    conn.commit()


def cached_dance_template_ids(conn):
    """Every previously cached non-AI dance template is a future entry point."""
    ids = []
    for row in conn.execute("SELECT payload FROM template_cache"):
        cached = loads(row["payload"], {})
        for item in [cached.get("detail"), *(cached.get("recommendations") or [])]:
            if not item:
                continue
            text = f'{item.get("title") or ""} {item.get("desc") or ""}'
            template_id = str(item.get("templateId") or item.get("id") or "")
            if template_id and config.DANCE.search(text) and not config.AI.search(text):
                ids.append(template_id)
    return ids


def seed_ids(conn, quick=False, progress=None, cancel_event=None):
    bundled = []
    if config.SEED_TEMPLATES.exists():
        bundled = [line.strip() for line in config.SEED_TEMPLATES.read_text(encoding="utf-8").splitlines()
                   if line.strip().isdigit()]
    discovered, summaries = [], {}
    ok_pages = failed_pages = 0
    pages = [url if page == 1 else f"{url}?page={page}"
             for url in landing_urls(conn) for page in scan_page_numbers(conn, quick)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {pool.submit(capcut.landing_template_ids, url): url for url in pages}
        for completed, job in enumerate(as_completed(jobs), 1):
            if cancel_event and cancel_event.is_set():
                for pending in jobs:
                    pending.cancel()
                _check_cancel(cancel_event)
            try:
                ids, page_summaries = job.result()
                discovered.extend(ids)
                summaries.update(page_summaries)
                ok_pages += 1
            except Exception as exc:
                failed_pages += 1
                if progress and failed_pages <= 3:
                    progress("入口失败", f"{jobs[job]}：{type(exc).__name__}：{exc}")
                continue
            if progress and (completed == 1 or completed % 5 == 0 or completed == len(jobs)):
                progress("发现入口", f"已检查专题页 {completed}/{len(jobs)}，成功 {ok_pages}、失败 {failed_pages}；当前：{jobs[job]}")
    if progress:
        progress("发现入口", f"实时专题页返回 {len(summaries)} 条含作者资料的模板；成功 {ok_pages} 页、失败 {failed_pages} 页")
    return list(dict.fromkeys(discovered + bundled + cached_dance_template_ids(conn))), summaries


def _fetch_detail(template_id):
    try:
        return capcut.fetch_template_detail(template_id)
    except Exception as exc:
        return {"error": str(exc)}


def _cached_payload(conn, template_id):
    row = conn.execute("SELECT payload, fetched_at FROM template_cache WHERE template_id = ?",
                       (template_id,)).fetchone()
    if not row:
        return None, 0
    return loads(row["payload"], None), float(row["fetched_at"])


# --- creator qualification ---------------------------------------------------

def creator_stats(all_works):
    """Counts the review page and the score use; stale works never count."""
    works = [work for work in all_works if not work.get("stale_low_use")]
    non_ai = [work for work in works if not work.get("likely_ai")]
    # Landing pages mix in unrelated popular templates, so page membership
    # (dance_seed) is discovery evidence only; usage counts need explicit dance.
    explicit_dance = [work for work in non_ai if work.get("dance_signal") and not work.get("non_dance_gimmick")]
    dance_non_ai = [work for work in non_ai
                    if (work.get("dance_seed") or work.get("dance_signal")) and not work.get("non_dance_gimmick")]
    return {
        "works": works,
        "indexed_count": len(works),
        "stale_low_use_excluded_count": len(all_works) - len(works),
        "high_use_non_ai_indexed": sum(int(work["uses"]) >= config.HIGH_USE_THRESHOLD for work in explicit_dance),
        "dance_non_ai_indexed": len(dance_non_ai),
        "explicit_dance_indexed": len(explicit_dance),
        "japanese_post_count": sum(bool(work.get("japanese_post")) for work in works),
        "ai_flagged_count": sum(bool(work.get("likely_ai")) for work in works),
    }


def exclusion_terms(conn):
    return [row["term"].casefold() for row in conn.execute("SELECT term FROM exclusions")]


def is_excluded(author, terms):
    values = [(author.get("name") or "").casefold(), (author.get("cc_id") or "").casefold()]
    return any(term and (term == value or term in value) for term in terms for value in values)


def discover(conn, max_pages=1200, workers=10, force=False, cancel_event=None, progress=None, fresh=False):
    progress = progress or (lambda *_: None)
    _check_cancel(cancel_event)
    progress("发现入口", "正在读取 CapCut 舞蹈专题和热歌页面，寻找模板链接")
    ids, live = seed_ids(conn, quick=max_pages <= 50 or fresh, progress=progress, cancel_event=cancel_event)
    known = repository.known_template_ids(conn)
    if fresh:
        ids = sorted((template_id for template_id in ids if template_id in live),
                     key=lambda template_id: template_id in known)
        progress("发现入口", f"实时列表中有 {sum(t not in known for t in ids)} 条本地未索引模板，优先读取这些新模板")
    if not ids:
        raise RuntimeError("CapCut 页面没有返回模板链接，保留上次扫描结果")
    dance_seed_ids = set(ids)
    progress("发现入口", f"找到 {len(ids)} 个模板入口，开始读取模板详情与作者资料")

    cache_ids = {row[0] for row in conn.execute("SELECT template_id FROM template_cache")}
    queue, queued = list(ids), set(ids)
    chosen, records, errors = [], {}, []
    processed = 0

    def absorb(template_id, result, source):
        nonlocal processed
        processed += 1
        author_name = ((result.get("detail") or {}).get("author") or {}).get("name", "")
        progress("模板抓取", f"{source}：模板 {template_id}{'，作者 ' + author_name if author_name else ''}；已处理 {processed}，上限 {max_pages}")
        if result.get("error"):
            errors.append({"template_id": template_id, "error": result["error"]})
        items = [result.get("detail")] + ([] if fresh else list(result.get("recommendations") or []))
        for item in items:
            record = item_record(item) if item else None
            if not record:
                continue
            live_record = item_record(live[record["template_id"]]) if record["template_id"] in live else None
            if live_record:
                if record["author_name"] == live_record["author_name"]:
                    live_record["author_bio"] = record["author_bio"]
                record = live_record
            record["dance_seed"] = record["template_id"] in dance_seed_ids
            records[record["template_id"]] = record
            if not fresh and record["template_id"] not in queued:
                queue.append(record["template_id"])
                queued.add(record["template_id"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while queue and len(chosen) < max_pages:
            _check_cancel(cancel_event)
            batch = queue[:min(100, max_pages - len(chosen))]
            del queue[:len(batch)]
            chosen.extend(batch)
            jobs = {}
            for template_id in batch:
                if fresh and template_id in live and template_id not in cache_ids:
                    absorb(template_id, {"detail": live[template_id], "recommendations": []}, "实时专题页")
                    continue
                cached, fetched_at = _cached_payload(conn, template_id)
                if cached and not force and time.time() - fetched_at < config.TEMPLATE_CACHE_SECONDS:
                    absorb(template_id, cached, "本地详情缓存")
                else:
                    jobs[pool.submit(_fetch_detail, template_id)] = (template_id, cached)
            for job in as_completed(jobs):
                if cancel_event and cancel_event.is_set():
                    for pending in jobs:
                        pending.cancel()
                    _check_cancel(cancel_event)
                template_id, cached = jobs[job]
                result = job.result()
                if not result.get("error"):
                    # Commit per row: never hold the write lock while waiting on the network.
                    with conn:
                        conn.execute("INSERT OR REPLACE INTO template_cache VALUES(?, ?, ?)",
                                     (template_id, dumps(result), time.time()))
                    cache_ids.add(template_id)
                elif cached:
                    result = cached  # detail page unavailable: keep the older copy
                absorb(template_id, result, "详情页")

    _check_cancel(cancel_event)
    with conn:
        repository.upsert_templates(conn, records.values())

    # Group by creator; works come from every template ever stored for them.
    identities = {}
    for record in records.values():
        identity = identities.setdefault(record["creator_key"], {
            "name": record["author_name"], "bio": record["author_bio"], "sec_uid": record["sec_uid"]})
        if len(record["author_bio"]) > len(identity["bio"]):
            identity["bio"] = record["author_bio"]
    progress("作者筛选", f"已整理 {len(identities)} 位模板作者，开始核对地区、舞蹈与使用量信息")

    terms = exclusion_terms(conn)
    reviews = repository.all_reviews(conn)
    context = scoring.scoring_context(conn)
    candidates, skipped_rejected = [], 0
    for index, (key, identity) in enumerate(identities.items(), 1):
        _check_cancel(cancel_event)
        if index == 1 or index % 10 == 0 or index == len(identities):
            progress("作者筛选", f"正在核对作者 {identity['name']} 的公开模板数据（{index}/{len(identities)}）")
        # Being shown before is not an exclusion; only a human rejection is.
        if repository.review_status(reviews, key) == "rejected":
            skipped_rejected += 1
            continue
        author = repository.load_creator(conn, key, with_works=False) or {
            "key": key, "cc_id": "", "cc_link": "", "tt_link": "", "total_posts": None,
            "profile_verified": False, "profile_link_checked": False, "video_content_profile": {}}
        author.update(identity)
        if is_excluded(author, terms):
            continue
        stats = creator_stats(repository.load_works(conn, key, include_stale=True))
        post_jp, bio_jp, name_jp = stats["japanese_post_count"], has_japanese(author["bio"]), has_japanese(author["name"])
        if not (post_jp or bio_jp or name_jp) or not stats["dance_non_ai_indexed"]:
            continue
        author.update(stats)
        author["japanese_signal"] = "投稿文案" if post_jp else ("自我介绍" if bio_jp else "用户名")
        share = config.PROFILE_LINK.search(author["bio"])
        if share:
            author["profile_link_hint"] = share.group(0)
        scoring.score_author(author, context)
        candidates.append(author)
    candidates.sort(key=lambda a: a["score"], reverse=True)

    # Cheap metadata retrieval first; only the strongest pool is decoded and
    # reranked against rejected video content.
    _check_cancel(cancel_event)
    top = candidates[:80]
    if context["negatives"]:
        progress("视频分析", f"初筛出 {len(candidates)} 位作者，准备分析排名靠前的模板视频")
        video.analyze_authors(conn, top, progress=progress)
        for author in top:
            scoring.score_author(author, context)
    else:
        progress("视频分析", "尚无负面视觉样本，跳过逐帧分析")
    filtered = []
    for author in candidates:
        profile = author.get("video_content_profile") or {}
        author["dance_video_verified"] = video.supports_dance(profile)
        # A decoded video must visibly support the dance claim; metadata-only
        # creators survive only when titles/descriptions explicitly say dance.
        if author["dance_video_verified"] or (not profile and author["explicit_dance_indexed"] > 0):
            filtered.append(author)
    filtered.sort(key=lambda a: a["score"], reverse=True)
    progress("筛选完成", f"得到 {len(filtered)} 位符合条件的候选作者")

    live_ids = sorted(set(records) & set(live))
    new_live_ids = [template_id for template_id in live_ids if template_id not in known]
    progress("实时更新", f"首次索引 {len(new_live_ids)} 条实时模板，历史已知 {len(live_ids) - len(new_live_ids)} 条")
    return {
        "generated_at": now(),
        "indexed_templates": len(records),
        "live_template_ids": live_ids,
        "new_live_templates": len(new_live_ids),
        "errors": errors,
        "skipped_rejected": skipped_rejected,
        "candidates": filtered,
    }


# --- profiles and queue ------------------------------------------------------

PROFILE_COLUMNS = ("cc_id", "cc_link", "total_posts", "tt_link", "profile_verified", "profile_link_checked")


def enrich_profiles(authors, progress=None, cancel_event=None):
    """Fill CC ID / post count from a verified creator homepage link (in place)."""
    checked = []
    for author in authors:
        _check_cancel(cancel_event)
        if author.get("profile_verified") or author.get("profile_link_checked"):
            continue
        link = author.get("profile_link_hint") or author.get("cc_link", "")
        if not link:
            continue
        if progress:
            progress("作者主页", f"正在读取 {author['name']} 的 CapCut 主页：CC ID、投稿总数和 TT 链接")
        try:
            profile = capcut.resolve_profile_link(link)
            if profile["name"].strip().casefold() != author["name"].strip().casefold():
                raise ValueError("链接指向其他作者")
            author.update(cc_id=profile["cc_id"], cc_link=link, total_posts=profile["total_posts"],
                          tt_link=profile["tt_link"], profile_verified=True)
            if progress:
                progress("作者主页", f"已核验 {author['name']} 的主页资料与投稿总数")
        except (ValueError, OSError):
            author["cc_link"] = ""
            if progress:
                progress("作者主页", f"{author['name']} 的主页链接未通过核验")
        author["profile_link_checked"] = True
        checked.append(author)
    if progress and not checked:
        progress("作者主页", "候选作者没有可核验的主页分享链接，本轮仅使用公开模板资料")
    return checked


def pending_count(conn):
    return conn.execute(
        """SELECT COUNT(*) FROM creators c LEFT JOIN reviews r ON r.creator_key = c.creator_key
           WHERE c.in_queue = 1 AND COALESCE(r.status, 'pending') = 'pending'""").fetchone()[0]


def merge_into_queue(conn, new, replace_pending=False, append_batch_size=None):
    """Build a review batch: 60% best matches + 40% random exploration.

    A manual refresh replaces the whole pending batch. Replaced creators are
    not excluded and may come back; only a rejection keeps a creator out.
    """
    reviews = repository.all_reviews(conn)
    queued = [row["creator_key"] for row in conn.execute("SELECT creator_key FROM creators WHERE in_queue = 1")]
    replaced_pending = sum(repository.review_status(reviews, key) == "pending" for key in queued)
    if replace_pending:
        preserved = {key for key in queued if repository.review_status(reviews, key) in ("approved", "aesthetic_only")}
    else:
        preserved = set(queued)
    if append_batch_size is not None:
        slots = max(0, int(append_batch_size))
    elif replace_pending:
        slots = config.MAX_PENDING_CREATORS
    else:
        slots = max(0, config.MAX_PENDING_CREATORS - replaced_pending)
    available = [author for author in new["candidates"]
                 if author["key"] not in preserved and repository.review_status(reviews, author["key"]) != "rejected"]
    ranked = available[:min(len(available), round(slots * config.RANKED_SHARE))]
    remainder = available[len(ranked):]
    random_slots = min(len(remainder), slots - len(ranked))
    exploratory = random.Random(new["generated_at"]).sample(remainder, random_slots) if random_slots else []
    rank_lookup = {author["key"]: index for index, author in enumerate(available, 1)}
    stamp = now()
    with conn:
        if replace_pending:
            conn.executemany("UPDATE creators SET in_queue = 0 WHERE creator_key = ?",
                             [(key,) for key in queued if key not in preserved])
        for kind, group in (("高匹配", ranked), ("随机探索", exploratory)):
            for author in group:
                author.update(recommendation_type=kind, match_rank=rank_lookup[author["key"]],
                              discovered_at=new["generated_at"], in_queue=True, last_shown_at=stamp)
                author["first_shown_at"] = author.get("first_shown_at") or stamp
                repository.upsert_creator(conn, author)
    return {
        "added": len(ranked) + len(exploratory),
        "ranked": len(ranked),
        "random": len(exploratory),
        "deferred": max(0, len(available) - len(ranked) - len(exploratory)),
        "replaced_pending": replaced_pending if replace_pending else 0,
        "pending": pending_count(conn),
    }


def refresh_queue_stats(conn):
    """Re-apply the 7-day / 1,000-use rule to the queue as templates age.

    Pending creators left without any qualifying dance work leave the queue.
    """
    reviews = repository.all_reviews(conn)
    removed = 0
    with conn:
        for author in repository.queued_creators(conn, with_works=False):
            stats = creator_stats(repository.load_works(conn, author["key"], include_stale=True))
            stats.pop("works")
            author.update(stats)
            if not stats["dance_non_ai_indexed"] and repository.review_status(reviews, author["key"]) == "pending":
                author["in_queue"] = False
                removed += 1
            repository.upsert_creator(conn, author, [*stats, "in_queue"])
    return removed


def _start_scan(conn, mode):
    with conn:
        cursor = conn.execute("INSERT INTO scans(mode, status, started_at) VALUES(?, 'running', ?)", (mode, now()))
    return cursor.lastrowid


def _finish_scan(conn, scan_id, status, message, **stats):
    columns = ["status", "message", "finished_at", *stats]
    values = [status, message, now(), *(dumps(v) if isinstance(v, list) else v for v in stats.values())]
    with conn:
        conn.execute(f"UPDATE scans SET {', '.join(c + ' = ?' for c in columns)} WHERE id = ?", (*values, scan_id))


def run_refresh(conn, max_pages=1200, replace_pending=False, append_batch_size=None,
                cancel_event=None, progress=None, mode="cli"):
    """Scan CapCut and update the review queue. Returns (message, changed)."""
    progress = progress or (lambda *_: None)
    pending_before = pending_count(conn)
    if not replace_pending and append_batch_size is None and pending_before >= config.MAX_PENDING_CREATORS:
        return (f"当前已有 {pending_before} 位待审作者。请先审核一部分，"
                f"刷新时再补足到 {config.MAX_PENDING_CREATORS} 位。"), False
    scan_id = _start_scan(conn, mode)
    try:
        new = discover(conn, max_pages=max(1, min(max_pages, 2000)), cancel_event=cancel_event,
                       progress=progress, fresh=replace_pending)
        if not new["indexed_templates"]:
            raise RuntimeError("没有获取到模板，保留上次扫描结果")
        if replace_pending and not new["new_live_templates"]:
            raise RuntimeError("实时专题页未发现可首次索引的新模板，保留上次候选结果")
        if replace_pending and not new["candidates"]:
            raise RuntimeError("实时模板未产生符合条件的作者，保留上次候选结果")
        enrich_profiles(new["candidates"], progress=progress, cancel_event=cancel_event)
        _check_cancel(cancel_event)
        progress("生成候选", "正在按匹配分和随机探索比例整理新一批候选")
        result = merge_into_queue(conn, new, replace_pending=replace_pending, append_batch_size=append_batch_size)
        with conn:
            repository.mark_live_templates_seen(conn, new["live_template_ids"])
        if max_pages > 50:
            advance_scan_state(conn)
        progress("保存结果", f"已保存 {result['added']} 位本批候选")
        if replace_pending:
            message = (f"实时新增索引 {new['new_live_templates']} 条模板；扫描 {new['indexed_templates']} 条模板，"
                       f"已替换 {result['replaced_pending']} 位原待审作者；当前待审 {result['pending']} 位。")
        else:
            message = (f"扫描 {new['indexed_templates']} 条模板，本次补充 {result['added']} 位；"
                       f"当前待审 {result['pending']} 位。")
        _finish_scan(conn, scan_id, "succeeded", message,
                     indexed_templates=new["indexed_templates"], new_live_templates=new["new_live_templates"],
                     new_candidates=result["added"], ranked_candidates=result["ranked"],
                     random_candidates=result["random"], deferred_candidates=result["deferred"],
                     replaced_pending=result["replaced_pending"], skipped_rejected=new["skipped_rejected"],
                     error_count=len(new["errors"]), trend_terms=trend_terms(conn))
        return message, True
    except RefreshCancelled as exc:
        conn.rollback()
        _finish_scan(conn, scan_id, "cancelled", str(exc))
        raise
    except Exception as exc:
        conn.rollback()
        _finish_scan(conn, scan_id, "failed", str(exc))
        raise


def startup_maintenance(conn, log=print):
    """Fast local housekeeping the review page relies on; safe to run every start."""
    removed = refresh_queue_stats(conn)
    if removed:
        log(f"{config.STALE_RULE}：{removed} 位待审作者移出队列。")
    learning.sync_revision(conn)
    conn.commit()
    scoring.rescore_queue(conn)


def enrich_queue_profiles(conn):
    """Network step: verify queued creators' homepage links once."""
    checked = enrich_profiles(repository.queued_creators(conn, with_works=False))
    if checked:
        with conn:
            for author in checked:
                repository.upsert_creator(conn, author, PROFILE_COLUMNS)
    return len(checked)
