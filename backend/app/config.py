"""Paths, ports and domain constants shared by the backend."""

import os
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
RESOURCES = BACKEND_ROOT / "resources"
DATA_DIR = Path(os.environ.get("CAPCUT_DATA_DIR") or BACKEND_ROOT / "data")
DB_PATH = DATA_DIR / "capcut.db"
LEGACY_DIR = DATA_DIR / "legacy"
# Gitignored caches that the previous single-file version left in the project
# root. They are imported once when the database is first created.
OLD_LOCAL_DATA = PROJECT_ROOT / "capcut_local_data"
TOOLS_DIR = DATA_DIR / "tools"

REFERENCE_CASES = RESOURCES / "reference_positive_cases.json"
SEED_TEMPLATES = RESOURCES / "seed_templates.txt"
VISUAL_ANALYZER_SOURCE = RESOURCES / "video_visual_analyzer.swift"
VISUAL_ANALYZER = TOOLS_DIR / "video_visual_analyzer"

HOST = os.environ.get("CAPCUT_HOST", "127.0.0.1")
PORT = int(os.environ.get("BACKEND_PORT", "8765"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))
# Only the local frontend may call the API from a browser.
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "CAPCUT_ALLOWED_ORIGINS",
        f"http://127.0.0.1:{FRONTEND_PORT},http://localhost:{FRONTEND_PORT}",
    ).split(",")
    if origin.strip()
}

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36"
KANA = re.compile(r"[぀-ヿ]")
AI = re.compile(r"(?i)(?:\bAI\b|生成AI|AI生成|AI加工|AI写真|AI顔|AI変身|AIエフェクト|人工知能|seedance|dreamina)")
DANCE = re.compile(r"(?i)(?:dance|dancing|choreo|ダンス|踊|振り?付け|手振り|手ぶり|アイドル|パフォーマンス)")
NON_DANCE_GIMMICK = re.compile(r"(?i)(?:顔ハメ|顔入れ替え|face\s*swap|head\s*swap|pet\s*dance|baby\s*dance|dancing\s*baby|cat\s*dance|dog\s*dance|踊る(?:犬|猫|動物))")
URL_ID = re.compile(r"/template-detail/(?:[^\"<>\s]*/)?(\d{18,20})")
PROFILE_LINK = re.compile(r"https?://mobile\.capcutshare\.com/sv2/[A-Za-z0-9]+/?")

DANCE_LANDINGS = (
    "https://www.capcut.com/ja-jp/template/record/dance",
    "https://www.capcut.com/ja-jp/explore/dance-template",
    "https://www.capcut.com/ja-jp/explore/popular-tiktok-dance",
    "https://www.capcut.com/ja-jp/explore/7512880651008559105",
    "https://www.capcut.com/ja-jp/explore/ダンス編集",
    "https://www.capcut.com/ja-jp/explore/CapCut-ダンス動画",
    "https://www.capcut.com/ja-jp/explore/ビデオダンスエディタ",
    "https://www.capcut.com/ja-jp/explore/Dance-Editing-Template",
    "https://www.capcut.com/ja-jp/explore/ダンス編集者",
    "https://www.capcut.com/ja-jp/explore/ダンス動画",
    "https://www.capcut.com/ja-jp/explore/ダンスミュージック",
    "https://www.capcut.com/ja-jp/explore/ダンス-エフェクト",
    "https://www.capcut.com/ja-jp/explore/ダンスエフェクト",
    "https://www.capcut.com/ja-jp/explore/CapCut-ワンダンス編集/7513481238256371728",
    "https://www.capcut.com/ja-jp/explore/Dance-Editing-Template/7497640620559779857",
    "https://www.capcut.com/ja-jp/explore/ダンス編集/7512965054573938704",
    "https://www.capcut.com/ja-jp/explore/ビデオダンスエディタ/7512990501697374209",
    "https://www.capcut.com/ja-jp/explore/ダンス編集者/7513008290424670209",
    "https://www.capcut.com/ja-jp/explore/CapCut-ダンス動画/7513481238256355344",
    "https://www.capcut.com/ja-jp/explore/ナルト-踊ってみた/7513342350833223696",
    "https://www.capcut.com/ja-jp/explore/踊ってみた",
    "https://www.capcut.com/ja-jp/explore/TikTokダンス",
    "https://www.capcut.com/ja-jp/explore/TikTok流行りのダンス",
    "https://www.capcut.com/ja-jp/explore/流行りダンス",
    "https://www.capcut.com/ja-jp/explore/ダンスチャレンジ",
    "https://www.capcut.com/ja-jp/explore/ダンス動画編集",
    "https://www.capcut.com/ja-jp/explore/踊るテンプレート",
    "https://www.capcut.com/ja-jp/explore/ダンス用テンプレート",
    "https://www.capcut.com/ja-jp/explore/KPOPダンス",
    "https://www.capcut.com/ja-jp/explore/アイドルダンス",
    # Related dance collections linked by CapCut itself from the Japanese
    # TikTok dance page.  Exact IDs are more stable than guessed slugs.
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
)
ORICON_TIKTOK_WEEKLY = "https://www.oricon.co.jp/rank/tt/w/"
FALLBACK_TREND_TERMS = (
    "ピンク", "BALI", "きゃわぽっぴんどぅー", "Sunshine Girl",
    "分かっちゃいないね", "Hug feat. kojikoji", "恋、はじめました。",
    "愛のレンタル", "マル・マル・モリ・モリ！", "エアロピクルス",
)
DEFAULT_EXCLUSIONS = ("rin_go.x", "s.n_so_", "カーラ", "てぃーすけ", "りあな", "みるくぱんだ")

LEARN_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}|[぀-ヿ]{2,}|[一-鿿]{2,}")
LEARN_STOP = {"作者", "模板", "视频", "比较", "感觉", "这个", "那个", "不是", "没有", "可以", "作品"}
VISUAL_REASON = re.compile(r"(?i)(AI|动画|节奏|包装|舞蹈|画面|构图|剪辑|内容|模板|特效|简单|审美|卡点|镜头|滤镜)")

MAX_PENDING_CREATORS = 50
RANKED_SHARE = 0.6
STALE_DAYS = 7
STALE_MIN_USES = 1000
HIGH_USE_THRESHOLD = 3000
TEMPLATE_CACHE_SECONDS = 12 * 3600
WORKS_PER_CREATOR = 12

REVIEW_STATUSES = ("pending", "approved", "aesthetic_only", "rejected")
SCORING_POLICY = "正面案例审美70% + 数据质量30% + 审核反馈修正"
STALE_RULE = f"发布满{STALE_DAYS}天且 uses<{STALE_MIN_USES} 的模板直接排除"
