"""Filesystem layout. Everything lives under ``capcut_local_data`` next to the code.

Override the data root with ``CAPCREATOR_DATA`` (used by tests and for running
several isolated workspaces on one machine).
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_root():
    override = os.environ.get("CAPCREATOR_DATA")
    return Path(override).resolve() if override else ROOT / "capcut_local_data"


def categories_dir():
    return data_root() / "categories"


def category_dir(slug):
    return categories_dir() / slug


def template_cache_dir():
    """Raw CapCut template pages, shared by every category (network derived)."""
    return data_root() / "cache"


def features_dir():
    """Per-video Template DNA, shared by every category (expensive to rebuild)."""
    return data_root() / "features"


def media_dir():
    """Uploaded / ingested example videos."""
    return data_root() / "media"


def exclusions_txt():
    return ROOT / "已归类作者.txt"


def exclusions_csv():
    return ROOT / "已归类作者.csv"
