"""Connectivity and dependency self-check (``python capcut_local.py doctor``)."""

import importlib
import json
import shutil
import sys
import time
from urllib.parse import urlparse

from . import capcut, net

CHECKS = (
    ("CapCut 网页（模板详情/专题）", "https://www.capcut.com/ja-jp/explore/dance-template", "GET", True),
    ("CapCut 应用接口（作者主页）", capcut.API_HOST + "/lv/v1/homepage/profile", "POST", True),
    ("CapCut 分享短链", "https://mobile.capcutshare.com/", "GET", True),
    ("CapCut 预览视频 CDN", "https://v16-vod.capcutvod.com/", "GET", True),
    ("CapCut 封面图片 CDN", "https://p16-capcut-sign-sg.ibyteimg.com/", "GET", False),
    ("ORICON 日本 TikTok 热歌榜", "https://www.oricon.co.jp/rank/tt/w/", "GET", False),
    ("Google Drive（客户素材）", "https://drive.google.com/", "GET", False),
    ("Dropbox（客户素材）", "https://www.dropbox.com/", "GET", False),
)

DEPENDENCIES = (
    ("numpy", "视频特征与学习模型", True),
    ("cv2", "视频解码与画面分析 (opencv-python-headless)", True),
    ("imageio_ffmpeg", "音频节拍分析用的 ffmpeg", False),
    ("certifi", "HTTPS 证书（macOS python.org 版本必需）", False),
    ("gdown", "下载 Google Drive 文件夹", False),
    ("open_clip", "可选：CLIP 语义向量（更懂画面内容）", False),
)


def check_dependencies():
    rows = []
    for module, purpose, required in DEPENDENCIES:
        try:
            importlib.import_module(module)
            rows.append({"module": module, "purpose": purpose, "ok": True, "required": required})
        except Exception:
            ok = module == "imageio_ffmpeg" and bool(shutil.which("ffmpeg"))
            rows.append({"module": module, "purpose": purpose, "ok": ok, "required": required})
    return rows


def check_network(timeout=12):
    rows = []
    for label, url, method, required in CHECKS:
        data = json.dumps({"public_id": "0"}).encode() if method == "POST" else None
        headers = {"Content-Type": "application/json"} if data else None
        result = net.probe(url, timeout=timeout, method=method, data=data, headers=headers)
        result.update(label=label, host=urlparse(url).hostname, required=required)
        rows.append(result)
    return rows


def report():
    deps = check_dependencies()
    network = check_network()
    blocked = [row["host"] for row in network if not row["ok"]]
    return {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
            "dependencies": deps, "network": network, "blocked_hosts": blocked,
            "capcut_ok": all(row["ok"] for row in network if row["required"])}


def print_report(result=None):
    result = result or report()
    print(f"Python {result['python']}  ·  检查时间 {result['checked_at']}")
    print("\n依赖：")
    for row in result["dependencies"]:
        mark = "✅" if row["ok"] else ("❌" if row["required"] else "⚪")
        print(f"  {mark} {row['module']:<15} {row['purpose']}")
    print("\n网络：")
    for row in result["network"]:
        mark = "✅" if row["ok"] else ("❌" if row["required"] else "⚠️")
        extra = f"{row.get('ms', 0)}ms" if row["ok"] else f"{row.get('kind')}: {row.get('advice') or row.get('detail')}"
        print(f"  {mark} {row['label']:<22} {row['host']:<34} {extra}")
    if result["blocked_hosts"]:
        print("\n无法访问的域名（如在云端/公司网络运行，请把它们加入放行名单）：")
        for host in result["blocked_hosts"]:
            print("   -", host)
    print("\n结论：" + ("CapCut 连接正常。" if result["capcut_ok"] else
                      "CapCut 关键域名无法访问，扫描会使用本地缓存，无法获取新作者。"))
    return result
