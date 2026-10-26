"""Categories: each one is an independent "creator search" with its own taste.

Layout of ``capcut_local_data/categories/<slug>/``::

    config.json          what to crawl and which hard rules apply
    examples.json        example templates/videos supplied by the client
    labels.json          trainer clicks (points + pairwise comparisons)
    taste_model.json     latest trained style model (with its profile code)
    candidates.json      creators found by discovery (same schema as v2)
    decisions.json       reviewer decisions per creator
    preference_profile.json  keyword learning from review notes
    background.json      analysed, unlabelled templates seen while crawling
    seen_creators.json / scan_state.json / scan_history.json
"""

import re
import shutil
import time
import unicodedata

from . import paths, store
from .textlearn import author_key

AI_PATTERN = r"(?i)(?:\bAI\b|生成AI|AI生成|AI加工|AI写真|AI顔|AI変身|AIエフェクト|人工知能|seedance|dreamina)"
DANCE_PATTERN = r"(?i)(?:dance|dancing|choreo|ダンス|踊|振り?付け|手振り|手ぶり|アイドル|パフォーマンス)"
DANCE_EXCLUDE = (r"(?i)(?:顔ハメ|顔入れ替え|face\s*swap|head\s*swap|pet\s*dance|baby\s*dance|dancing\s*baby|"
                 r"cat\s*dance|dog\s*dance|踊る(?:犬|猫|動物))")
DANCE_LANDINGS = [
    "https://www.capcut.com/ja-jp/template/record/dance",
    "https://www.capcut.com/ja-jp/explore/dance-template",
    "https://www.capcut.com/ja-jp/explore/popular-tiktok-dance",
    "https://www.capcut.com/ja-jp/explore/7512880651008559105",
    "https://www.capcut.com/ja-jp/explore/CapCut-ワンダンス編集/7513481238256371728",
    "https://www.capcut.com/ja-jp/explore/Dance-Editing-Template/7497640620559779857",
    "https://www.capcut.com/ja-jp/explore/ダンス編集/7512965054573938704",
    "https://www.capcut.com/ja-jp/explore/ビデオダンスエディタ/7512990501697374209",
    "https://www.capcut.com/ja-jp/explore/ダンス編集者/7513008290424670209",
    "https://www.capcut.com/ja-jp/explore/CapCut-ダンス動画/7513481238256355344",
    "https://www.capcut.com/ja-jp/explore/ナルト-踊ってみた/7513342350833223696",
    "https://www.capcut.com/ja-jp/explore/dancing-template",
    "https://www.capcut.com/ja-jp/explore/energetic-dance",
    "https://www.capcut.com/ja-jp/explore/tiktok-cute-poppin-do-dance",
    "https://www.capcut.com/ja-jp/explore/popular-tiktok-dances",
    "https://www.capcut.com/ja-jp/explore/TikTokダンスソング/7512978747810809857",
    "https://www.capcut.com/ja-jp/explore/TikTokダンス曲/7512978747810891777",
    "https://www.capcut.com/ja-jp/explore/ダンス動画/7512983683641772049",
    "https://www.capcut.com/ja-jp/explore/あなたに踊る/7512967238586222593",
    "https://www.capcut.com/ja-jp/explore/ホットベリーダンス/7513004558294927376",
    "https://www.capcut.com/ja-jp/explore/ダンスビデオ/7512945605816797201",
    "https://www.capcut.com/ja-jp/explore/ダンスビデオエディター/7512968614363564033",
    "https://www.capcut.com/ja-jp/explore/バチャータ-動画/7512965377309247505",
    "https://www.capcut.com/ja-jp/explore/ダンスソング/7512972489519466512",
    "https://www.capcut.com/ja-jp/explore/7557563389263235088",
]
DANCE_KEYWORDS = [
    "ダンス編集", "CapCut-ダンス動画", "ビデオダンスエディタ", "Dance-Editing-Template", "ダンス編集者",
    "ダンス動画", "ダンスミュージック", "ダンス-エフェクト", "ダンスエフェクト", "踊ってみた", "TikTokダンス",
    "TikTok流行りのダンス", "流行りダンス", "ダンスチャレンジ", "ダンス動画編集", "踊るテンプレート",
    "ダンス用テンプレート", "KPOPダンス", "アイドルダンス",
]

BASE_CONFIG = {
    "name": "", "slug": "", "description": "", "created_at": "",
    "region": "ja-jp",
    "language": "ja",            # "ja": creator must post in Japanese; "any": no language rule
    "keywords": [],              # CapCut explore keywords used as crawl entry points
    "landing_urls": [],          # extra CapCut list pages
    "seed_template_ids": [],     # extra template ids to start the crawl from
    "include_regex": "",         # if set, title/desc must match to count as category evidence
    "exclude_regex": "",
    "exclude_ai": True,
    "ai_regex": AI_PATTERN,
    "trend_source": "",          # "oricon_tiktok_jp" adds this week's JP TikTok songs as keywords
    "visual_gate": "",           # "people_motion": analysed video must show people and movement
    "reference_cases": False,    # dance only: 26 hand-analysed positive cases
    "max_pending": 50,
    "stale_days": 7, "stale_min_uses": 1000,
    "high_use_threshold": 3000,
    "scan_pages": 1200,
    "analyze_top": 80,           # creators whose videos are analysed per scan
    "style_strength": 60,        # 0–100: weight of the learned video taste in the final ranking
    "labels": {"category": "该类别", "confirm": "已确认主要产出优质该类别模板",
               "specialty": "擅长类型与素材", "notes": "包装、节奏、构图和做得好的 case"},
}

DANCE_CONFIG = {
    "name": "日本区舞蹈模板", "slug": "dance",
    "description": "日本区、非 AI、舞蹈模板创作者（v2 审核流程迁移而来）",
    "include_regex": DANCE_PATTERN, "exclude_regex": DANCE_EXCLUDE,
    "keywords": DANCE_KEYWORDS, "landing_urls": DANCE_LANDINGS,
    "trend_source": "oricon_tiktok_jp", "visual_gate": "people_motion", "reference_cases": True,
    "style_strength": 40,
    "labels": {"category": "舞蹈", "confirm": "已确认主要产出优质舞蹈模板",
               "specialty": "舞蹈类型与素材：单人/双人/群舞、手势舞、偶像舞等",
               "notes": "包装、节奏、构图、替换性和做得好的 case"},
}

LEGACY_FILES = ("candidates.json", "decisions.json", "preference_profile.json", "seen_creators.json",
                "scan_state.json", "scan_history.json", "trend_terms.json", "visual_learning.json")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def slugify(name):
    text = unicodedata.normalize("NFKC", name or "").strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if ascii_part and len(ascii_part) >= 3:
        return ascii_part[:40]
    import hashlib
    return "c-" + hashlib.sha1(text.encode()).hexdigest()[:8]


def merged_config(raw):
    config = {**BASE_CONFIG, **(raw or {})}
    config["labels"] = {**BASE_CONFIG["labels"], **((raw or {}).get("labels") or {})}
    return config


class Category:
    def __init__(self, slug):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug or ""):
            raise ValueError("类别标识只能包含小写字母、数字和连字符")
        self.slug = slug
        self.dir = paths.category_dir(slug)

    def path(self, name):
        return self.dir / name

    def exists(self):
        return self.path("config.json").exists()

    # -- config
    @property
    def config(self):
        return merged_config(store.read_json(self.path("config.json"), {}))

    def save_config(self, config):
        stored = {k: v for k, v in config.items() if k in BASE_CONFIG}
        stored["slug"] = self.slug
        store.write_json(self.path("config.json"), stored)

    def update_config(self, **changes):
        with store.LOCK:
            config = self.config
            config.update(changes)
            self.save_config(config)
            return config

    # -- review data (schemas unchanged from v2)
    def candidates(self):
        return store.read_json(self.path("candidates.json"), {"candidates": []})

    def save_candidates(self, data):
        store.write_json(self.path("candidates.json"), data)

    def decisions(self):
        return store.read_json(self.path("decisions.json"), {})

    def save_decisions(self, decisions):
        store.write_json(self.path("decisions.json"), decisions)

    def text_profile(self):
        return store.read_json(self.path("preference_profile.json"), {})

    def save_text_profile(self, profile):
        store.write_json(self.path("preference_profile.json"), profile)

    def read(self, name, default):
        return store.read_json(self.path(name), default)

    def write(self, name, value):
        store.write_json(self.path(name), value)

    # -- examples
    def examples(self):
        return store.read_json(self.path("examples.json"), [])

    def add_examples(self, items):
        with store.LOCK:
            current = self.examples()
            known = {item["key"] for item in current}
            added = []
            for item in items:
                if item["key"] in known:
                    continue
                item.setdefault("added_at", now())
                item.setdefault("label", "positive")
                current.append(item)
                known.add(item["key"])
                added.append(item)
            store.write_json(self.path("examples.json"), current)
            return added

    def update_example(self, key, **changes):
        with store.LOCK:
            current = self.examples()
            for item in current:
                if item["key"] == key:
                    item.update(changes)
            store.write_json(self.path("examples.json"), current)

    def remove_example(self, key):
        with store.LOCK:
            store.write_json(self.path("examples.json"), [e for e in self.examples() if e["key"] != key])

    # -- trainer labels
    def labels(self):
        data = store.read_json(self.path("labels.json"), {})
        return {"points": data.get("points", []), "pairs": data.get("pairs", []),
                "rounds": data.get("rounds", 0)}

    def add_labels(self, points=(), pairs=(), round_done=False):
        with store.LOCK:
            data = self.labels()
            data["points"].extend(points)
            data["pairs"].extend(pairs)
            data["rounds"] += 1 if round_done else 0
            store.write_json(self.path("labels.json"), data)
            return data

    def undo_last_round(self):
        with store.LOCK:
            data = self.labels()
            if not data["points"]:
                return data
            last_at = data["points"][-1].get("at")
            data["points"] = [p for p in data["points"] if p.get("at") != last_at]
            data["pairs"] = [p for p in data["pairs"] if p.get("at") != last_at]
            data["rounds"] = max(0, data["rounds"] - 1)
            store.write_json(self.path("labels.json"), data)
            return data

    def model(self):
        return store.read_json(self.path("taste_model.json"), None)

    def save_model(self, model):
        history = store.read_json(self.path("taste_history.json"), [])
        history.append({"code": model["code"], "trained_at": model["trained_at"],
                        "counts": model["counts"], "confidence": model["confidence"]})
        store.write_json(self.path("taste_history.json"), history[-100:])
        store.write_json(self.path("taste_model.json"), model)

    def summary(self):
        config = self.config
        data = self.candidates()
        decisions = self.decisions()
        statuses = [decisions.get(author_key(a), {}).get("status", "pending") for a in data.get("candidates", [])]
        model = self.model() or {}
        labels = self.labels()
        examples = self.examples()
        return {"slug": self.slug, "name": config["name"], "description": config["description"],
                "examples": len(examples),
                "positive_examples": sum(e.get("label") == "positive" for e in examples),
                "creators": len(statuses), "pending": statuses.count("pending"),
                "approved": statuses.count("approved"), "rejected": statuses.count("rejected"),
                "rounds": labels["rounds"], "model_code": model.get("code"),
                "confidence": model.get("confidence", 0), "last_scan": data.get("generated_at")}


def list_categories():
    root = paths.categories_dir()
    if not root.exists():
        return []
    return [Category(p.name) for p in sorted(root.iterdir()) if (p / "config.json").exists()]


def get(slug):
    category = Category(slug)
    if not category.exists():
        raise KeyError(slug)
    return category


def create(name, slug=None, **overrides):
    slug = slug or slugify(name)
    category = Category(slug)
    if category.exists():
        raise ValueError(f"类别 {slug} 已存在")
    config = merged_config({**overrides, "name": name.strip() or slug, "slug": slug, "created_at": now()})
    category.save_config(config)
    return category


def _legacy_is_newer(data_root, dance):
    """v2 files left at the data root win when they hold newer review state than categories/dance.

    This happens when a Mac that kept running v2 daily scans copies its old
    files back after pulling v3 (whose repo copy of dance is older).
    """
    old = store.read_json(data_root / "candidates.json", {})
    new = store.read_json(dance.path("candidates.json"), {})
    old_decisions = store.read_json(data_root / "decisions.json", {})
    new_decisions = store.read_json(dance.path("decisions.json"), {})
    return (str(old.get("generated_at") or "") > str(new.get("generated_at") or "")
            or len(old_decisions) > len(new_decisions))


def migrate_legacy():
    """Move the v2 single-category (dance) layout into ``categories/dance``. Idempotent."""
    data = paths.data_root()
    dance = Category("dance")
    legacy = [name for name in LEGACY_FILES if (data / name).exists()]
    moved = []
    if legacy and dance.path("candidates.json").exists():
        if _legacy_is_newer(data, dance):
            backup = dance.dir / f"before-v3-migration-{time.strftime('%Y%m%d-%H%M%S')}"
            backup.mkdir(parents=True, exist_ok=True)
            for name in legacy:
                if dance.path(name).exists():
                    shutil.move(str(dance.path(name)), str(backup / name))
        else:
            backup = data / f"v2-superseded-{time.strftime('%Y%m%d-%H%M%S')}"
            backup.mkdir(parents=True, exist_ok=True)
            for name in legacy:
                shutil.move(str(data / name), str(backup / name))
            legacy = []
    if legacy:
        dance.dir.mkdir(parents=True, exist_ok=True)
        for name in legacy:
            shutil.move(str(data / name), str(dance.path(name)))
            moved.append(name)
    for reference in (data / "reference_positive_cases.json", paths.ROOT / "reference_positive_cases.json"):
        if reference.exists() and not dance.path("reference_positive_cases.json").exists() and (moved or dance.exists()):
            dance.dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reference, dance.path("reference_positive_cases.json"))
            moved.append("reference_positive_cases.json")
    if not dance.exists() and (moved or dance.path("candidates.json").exists()):
        config = merged_config({**DANCE_CONFIG, "created_at": now()})
        seeds = paths.ROOT / "seed_templates.txt"
        if seeds.exists():
            config["seed_template_ids"] = [line.strip() for line in seeds.read_text(encoding="utf-8").splitlines()
                                           if line.strip().isdigit()]
        dance.save_config(config)
        moved.append("config.json")
    empty_new_category = data / "new_category"
    if empty_new_category.exists():
        cases = store.read_json(empty_new_category / "positive_cases.json", [])
        if not cases:
            shutil.rmtree(empty_new_category, ignore_errors=True)
    old_video_analysis = data / "video_analysis"
    if old_video_analysis.exists():  # Apple Vision results are superseded by Template DNA
        shutil.rmtree(old_video_analysis, ignore_errors=True)
    return moved


def ensure_default():
    moved = migrate_legacy()
    if not list_categories():
        category = Category("dance")
        category.save_config(merged_config({**DANCE_CONFIG, "created_at": now()}))
    return moved
