"""Bring the client's example templates into a category.

Accepted sources (all end up as example records + Template DNA):

* a local folder or ``.zip`` — videos anywhere inside; text/CSV files are
  scanned for CapCut template links;
* a Google Drive file/folder link, a Dropbox file/folder link, or any direct
  download URL (zip or video);
* CapCut template links / ids pasted as text.

Folder conventions (optional, recommended for the client):

    客户素材/
      舞蹈/        ← one folder per category (name becomes the category)
        xxx.mp4
        反例/      ← "反例" / "negative" / "不要": counter-examples
      旅行vlog/
        links.txt  ← CapCut template links, one per line
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import capcut, category as categories, dna, net, paths

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
TEXT_EXT = {".txt", ".csv", ".md", ".json", ".html", ".htm", ".tsv"}
NEGATIVE_DIR = re.compile(r"(?i)^(反例|负例|不要|不喜欢|negative|negatives|bad|no)$")
SKIP_DIR = re.compile(r"^(__MACOSX|\..*)$")


class IngestError(ValueError):
    pass


def _log(log, message):
    if log:
        log(message)


# ---------------------------------------------------------------- remote sources

def google_drive_id(url):
    parsed = urlparse(url)
    if parsed.hostname not in ("drive.google.com", "docs.google.com", "drive.usercontent.google.com"):
        return None, None
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return "folder", match.group(1)
    match = re.search(r"/d/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return "file", match.group(1)
    file_id = parse_qs(parsed.query).get("id", [None])[0]
    return ("file", file_id) if file_id else (None, None)


def dropbox_direct(url):
    parsed = urlparse(url)
    if not (parsed.hostname or "").endswith("dropbox.com"):
        return None
    query = re.sub(r"(^|&)dl=0", r"\1dl=1", parsed.query)
    if "dl=1" not in query:
        query = (query + "&" if query else "") + "dl=1"
    return parsed._replace(query=query).geturl()


def _filename_from_headers(headers, fallback):
    disposition = (headers or {}).get("Content-Disposition", "") if headers else ""
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", disposition or "")
    if match:
        from urllib.parse import unquote
        return Path(unquote(match.group(1) or match.group(2))).name
    return fallback


def fetch_remote(url, workdir, log=None):
    """Download ``url`` into ``workdir``; returns a local file or directory path."""
    workdir = Path(workdir)
    kind, drive_id = google_drive_id(url)
    if kind == "folder":
        try:
            import gdown
        except ImportError as exc:
            raise IngestError("读取 Google Drive 文件夹需要 gdown：pip install gdown；"
                              "或者让客户把文件夹打包成一个 zip 再分享。") from exc
        _log(log, "正在下载 Google Drive 文件夹…")
        target = workdir / "gdrive"
        files = gdown.download_folder(url=url, output=str(target), quiet=True, remaining_ok=True)
        if not files:
            raise IngestError("Google Drive 文件夹为空或未设置“知道链接的任何人可查看”。")
        return target
    if kind == "file":
        url = f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&confirm=t"
    else:
        url = dropbox_direct(url) or url
    _log(log, f"正在下载 {urlparse(url).hostname} …")
    temp = workdir / "download.bin"
    try:
        final_url, headers = net.download(url, temp, max_bytes=8 * 1024 ** 3, timeout=120)
    except net.NetError as exc:
        raise IngestError(f"下载失败：{exc}。{exc.advice()}") from exc
    name = _filename_from_headers(headers, Path(urlparse(final_url).path).name or "download.bin")
    target = workdir / name
    temp.replace(target)
    with open(target, "rb") as handle:
        head = handle.read(512).lower()
    if b"<html" in head or b"<!doctype html" in head:
        raise IngestError("链接返回的是网页而不是文件：请确认分享权限为“任何人可查看/下载”，"
                          "或换成 Google Drive / Dropbox / 直链 zip。")
    return target


# ---------------------------------------------------------------- local scanning

def safe_extract(archive, target):
    target = Path(target).resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            if member.flag_bits & 0x800 == 0:  # legacy encoding: macOS/Windows Chinese zips are often GBK/cp932
                raw = name.encode("cp437", "replace")
                for codec in ("utf-8", "gbk", "cp932"):
                    try:
                        name = raw.decode(codec)
                        break
                    except UnicodeDecodeError:
                        continue
            dest = (target / name).resolve()
            if not dest.is_relative_to(target):
                continue  # zip-slip
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    return target


def scan(root):
    """Yield (relative_parts, path, kind) for every usable file under ``root``."""
    root = Path(root)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(SKIP_DIR.match(part) for part in rel.parts) or not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in VIDEO_EXT:
            yield rel.parts[:-1], path, "video"
        elif ext in TEXT_EXT:
            yield rel.parts[:-1], path, "text"
        elif ext == ".zip":
            yield rel.parts[:-1], path, "zip"


def label_for(parts):
    return "negative" if any(NEGATIVE_DIR.match(p) for p in parts) else "positive"


def category_for(parts, default, by_folder):
    if not by_folder:
        return default
    for part in parts:
        if not NEGATIVE_DIR.match(part):
            return part
    return default


# ---------------------------------------------------------------- adding examples

def add_video(category, path, label="positive", source="", analyze=True, log=None, title=None):
    key = dna.file_key(path)
    target = paths.media_dir() / "uploads" / f"{key}{Path(path).suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(path, target)
    record = {"key": key, "kind": "upload", "label": label, "title": title or Path(path).stem,
              "file": str(target.relative_to(paths.media_dir())), "source": source or str(path)}
    added = category.add_examples([record])
    if analyze and dna.available():
        try:
            dna.analyze_video(target, key=key, meta={"title": record["title"]})
        except Exception as exc:  # a broken file should not stop a 500-file import
            _log(log, f"  ⚠ 无法分析 {Path(path).name}：{exc}")
    return bool(added)


def add_capcut_templates(category, template_ids, label="positive", analyze=True, log=None):
    """Fetch metadata + preview for CapCut template ids and store them as examples."""
    region = category.config["region"]
    added, failed = 0, []
    for template_id in template_ids:
        page = capcut.template_page(template_id, region=region)
        detail = page.get("detail")
        if not detail:
            failed.append((template_id, page.get("error", "无数据")))
            record = {"key": f"t{template_id}", "kind": "capcut", "template_id": template_id, "label": label,
                      "title": "", "pending_fetch": True, "url": capcut.detail_url(template_id, region)}
            added += bool(category.add_examples([record]))
            continue
        author = detail.get("author") or {}
        record = {"key": f"t{template_id}", "kind": "capcut", "template_id": template_id, "label": label,
                  "title": detail.get("title") or "", "desc": (detail.get("desc") or "")[:350],
                  "video_url": detail.get("videoUrl") or "", "cover_url": detail.get("coverUrl") or "",
                  "url": capcut.detail_url(template_id, region), "uses": detail.get("usageAmount") or 0,
                  "author_name": author.get("name", ""), "author_key": author.get("secUid") or author.get("name", ""),
                  "clips": detail.get("segmentAmount")}
        if not category.add_examples([record]):
            category.update_example(record["key"], **{k: v for k, v in record.items() if k != "label"},
                                    pending_fetch=False)
        else:
            added += 1
        if analyze and dna.available() and record["video_url"]:
            try:
                dna.analyze_template(template_id, record["video_url"], meta={"title": record["title"]})
            except Exception as exc:
                _log(log, f"  ⚠ 预览视频分析失败 {template_id}：{exc}")
    for template_id, error in failed:
        _log(log, f"  ⚠ 模板 {template_id} 暂时无法读取（{error}），已登记，联网后会自动补全")
    return added, failed


def ingest_text(category, text, label="positive", log=None):
    ids, unresolved = capcut.template_ids_from_text(text)
    for link in unresolved:
        _log(log, f"  ⚠ 无法识别模板链接：{link}")
    added, _ = add_capcut_templates(category, ids, label=label, log=log)
    return added, len(ids)


def ingest_path(path, default_slug, by_folder=False, log=None, analyze=True):
    """Import a folder / zip / single file. Returns {slug: added_count}."""
    path = Path(path)
    counts = {}
    with tempfile.TemporaryDirectory(prefix="capcreator-ingest-") as temp:
        if path.is_file() and path.suffix.lower() == ".zip":
            _log(log, f"解压 {path.name} …")
            root = safe_extract(path, Path(temp) / "unzipped")
        elif path.is_file():
            root = Path(temp) / "single"
            root.mkdir()
            shutil.copy2(path, root / path.name)
        elif path.is_dir():
            root = path
        else:
            raise IngestError(f"找不到 {path}")
        items = []
        for parts, file_path, kind in scan(root):
            if kind != "zip":
                items.append((parts, file_path, kind))
                continue
            # Nested archives are unpacked into the temp dir, never next to the user's files.
            unpacked = safe_extract(file_path, Path(temp) / "nested" / f"{len(items)}-{file_path.stem}")
            prefix = parts + (file_path.stem,) if by_folder and not parts else parts
            items.extend((prefix + sub_parts, sub_path, sub_kind)
                         for sub_parts, sub_path, sub_kind in scan(unpacked) if sub_kind != "zip")
        videos = sum(kind == "video" for _, _, kind in items)
        _log(log, f"发现 {videos} 个视频、{sum(kind == 'text' for _, _, kind in items)} 个文本文件")
        done = 0
        for parts, file_path, kind in items:
            slug_name = category_for(parts, default_slug, by_folder)
            cat = resolve_category(slug_name)
            label = label_for(parts)
            if kind == "video":
                done += 1
                _log(log, f"  [{done}/{videos}] {cat.config['name']} · {'反例' if label == 'negative' else '正例'} · {file_path.name}")
                counts[cat.slug] = counts.get(cat.slug, 0) + add_video(cat, file_path, label, analyze=analyze, log=log)
            elif kind == "text":
                text = file_path.read_text(encoding="utf-8", errors="replace")
                if capcut.CAPCUT_LINK.search(text) or capcut.TEMPLATE_ID.search(text):
                    added, _ = ingest_text(cat, text, label=label, log=log)
                    counts[cat.slug] = counts.get(cat.slug, 0) + added
    return counts


def resolve_category(name_or_slug):
    try:
        return categories.get(name_or_slug)
    except (KeyError, ValueError):
        pass
    for existing in categories.list_categories():
        if existing.config["name"] == name_or_slug:
            return existing
    return categories.create(name_or_slug)


def ingest(source, default_slug, by_folder=False, log=None, analyze=True):
    """Entry point for CLI and web: ``source`` is a path, URL or pasted text."""
    source = (source or "").strip()
    if not source:
        raise IngestError("请提供文件夹路径、网盘链接或模板链接")
    if re.match(r"https?://", source) and "\n" not in source and not capcut.CAPCUT_LINK.fullmatch(source):
        with tempfile.TemporaryDirectory(prefix="capcreator-dl-") as temp:
            local = fetch_remote(source, temp, log=log)
            return ingest_path(local, default_slug, by_folder=by_folder, log=log, analyze=analyze)
    if Path(source).expanduser().exists():
        return ingest_path(Path(source).expanduser(), default_slug, by_folder=by_folder, log=log, analyze=analyze)
    cat = resolve_category(default_slug)
    added, total = ingest_text(cat, source, log=log)
    if not total:
        raise IngestError("没有识别到 CapCut 模板链接、文件夹或网盘链接")
    return {cat.slug: added}
