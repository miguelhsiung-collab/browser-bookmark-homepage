#!/usr/bin/env python3
"""Export Chromium Bookmarks + History into nav JSON for homepage build."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

AUTH_PATH = re.compile(
    r"(login|signin|sign-in|signup|sign-up|oauth|authorize|/auth/|sso|saml|logout|password|accounts/login|session|loginDeepControl|join-team)",
    re.I,
)
AUTH_QUERY = re.compile(
    r"(?:^|[?&])(client_id|redirect_uri|code|state|challenge|returnTo|signInStarted)=",
    re.I,
)

KEYWORD_CATS = [
    ("AI 工具", ("openai", "chatgpt", "claude", "gemini", "grok", "midjourney", "deepseek", "通义", "qwen", "aistudio", "modelscope", "ollama")),
    ("工作采购", ("1688", "srm", "jaggaer", "ariba", "xiekeyun", "采购", "supplier", "geely", "fuyao")),
    ("AGV叉车", ("agv", "forklift", "hikrobot", "叉车", "mobilerobot")),
    ("设计素材", ("canva", "pixabay", "pexels", "gaoding", "looka", "摄图")),
    ("学习文档", ("zhihu.com/p", "runoob", "readthedocs", "feishu.cn/wiki", "360doc", "cookbook")),
    ("搜索工具", ("google.com", "baidu.com", "bing.com", "translate.google")),
    ("社交资讯", ("twitter", "x.com", "zhihu.com", "weixin", "toutiao", "xueqiu", "producthunt")),
    ("购物海淘", ("taobao", "jd.com", "amazon", "shopee")),
    ("影视娱乐", ("bilibili", "iqiyi", "v.qq.com", "douban", "youtube", "cilixiong", "btbt")),
]


def host_key(url: str) -> str:
    try:
        p = urlparse(url)
        h = (p.hostname or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def is_http(url: str) -> bool:
    try:
        return urlparse(url).scheme in ("http", "https")
    except Exception:
        return False


def is_auth_url(url: str) -> bool:
    try:
        p = urlparse(url)
        path = p.path or "/"
        if AUTH_PATH.search(path):
            return True
        if AUTH_QUERY.search(p.query or ""):
            return True
        return False
    except Exception:
        return True


AUTH_HOST_SUFFIXES = (
    "accounts.google.com",
    "login.microsoftonline.com",
    "authenticator.cursor.sh",
    "auth0.com",
)

def is_junk_host(host: str) -> bool:
    if not host:
        return True
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local"):
        return True
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return True
    if host.startswith("accounts.") or host.startswith("login.") or host.startswith("auth."):
        return True
    if host in AUTH_HOST_SUFFIXES or any(host.endswith("." + s) for s in AUTH_HOST_SUFFIXES):
        return True
    if "authenticator." in host:
        return True
    return False


def walk_bookmarks(node, folder_name: str | None, out: list):
    ntype = node.get("type")
    if ntype == "url":
        url = node.get("url") or ""
        if not is_http(url):
            return
        name = (node.get("name") or "").strip() or host_key(url) or url
        out.append({"name": name, "url": url, "host": host_key(url), "folder": folder_name or "其他常用"})
        return
    if ntype == "folder" or "children" in node:
        name = (node.get("name") or "").strip()
        # Skip root-ish wrappers
        next_folder = folder_name
        if name and name not in ("书签栏", "Bookmarks bar", "其他书签", "Other bookmarks", "移动设备书签", "Mobile bookmarks"):
            next_folder = name
        for child in node.get("children") or []:
            walk_bookmarks(child, next_folder, out)


def heuristic_cat(item: dict) -> str:
    blob = f"{item.get('name','')} {item.get('url','')}".lower()
    for cat, keys in KEYWORD_CATS:
        if any(k.lower() in blob for k in keys):
            return cat
    return item.get("folder") or "其他常用"


def load_bookmarks(path: Path) -> dict[str, list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    roots = data.get("roots") or {}
    flat: list[dict] = []
    for key in ("bookmark_bar", "other", "synced"):
        if key in roots:
            walk_bookmarks(roots[key], None, flat)
    # Prefer real folders when most items have distinct folders
    folders = {i["folder"] for i in flat if i.get("folder")}
    use_heuristic = len(folders) <= 1
    cats: dict[str, list] = defaultdict(list)
    seen = set()
    for it in flat:
        key = (it["url"], it["name"])
        if key in seen:
            continue
        seen.add(key)
        cat = heuristic_cat(it) if use_heuristic else (it.get("folder") or "其他常用")
        cats[cat].append({"name": it["name"], "url": it["url"], "host": it["host"]})
    return dict(cats)


def prefer_url(host: str, candidates: list[str], bookmark_urls: dict[str, str]) -> str:
    if host in bookmark_urls:
        return bookmark_urls[host]
    clean = [u for u in candidates if not is_auth_url(u)]
    pool = clean or candidates
    # Prefer shortest path
    def score(u: str):
        p = urlparse(u)
        return (len(p.path or "/"), len(u))
    pool.sort(key=score)
    return pool[0] if pool else f"https://{host}/"


def load_frequent(history_path: Path, top: int, bookmark_by_host: dict[str, str]) -> list[dict]:
    tmp = Path(tempfile.mkdtemp()) / "History"
    shutil.copy2(history_path, tmp)
    conn = sqlite3.connect(str(tmp))
    try:
        rows = conn.execute(
            "SELECT url, title, visit_count FROM urls WHERE visit_count > 0 ORDER BY visit_count DESC LIMIT 5000"
        ).fetchall()
    finally:
        conn.close()
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass

    host_counts: dict[str, int] = defaultdict(int)
    host_urls: dict[str, list[str]] = defaultdict(list)
    host_titles: dict[str, str] = {}
    for url, title, vc in rows:
        if not is_http(url):
            continue
        h = host_key(url)
        if is_junk_host(h):
            continue
        host_counts[h] += int(vc or 0)
        host_urls[h].append(url)
        if title and h not in host_titles:
            host_titles[h] = title.strip()

    ranked = sorted(host_counts.items(), key=lambda x: (-x[1], x[0]))
    out = []
    for h, count in ranked:
        # Skip hosts that only have auth URLs and no bookmark
        urls = host_urls[h]
        if all(is_auth_url(u) for u in urls) and h not in bookmark_by_host:
            continue
        url = prefer_url(h, urls, bookmark_by_host)
        if is_auth_url(url) and h not in bookmark_by_host:
            continue
        name = bookmark_by_host.get(h) and None
        # name from bookmark title if we stored only url — fix below
        display = host_titles.get(h) or h
        out.append({"name": display, "url": url, "host": h, "visit_count": count})
        if len(out) >= top:
            break
    return out


def bookmark_home_map(cats: dict) -> dict[str, str]:
    """host -> best bookmark url; also improve names later via separate map."""
    best: dict[str, str] = {}
    for items in cats.values():
        for it in items:
            h = it.get("host") or ""
            if not h or is_auth_url(it["url"]):
                continue
            prev = best.get(h)
            if prev is None or len(urlparse(it["url"]).path or "/") < len(urlparse(prev).path or "/"):
                best[h] = it["url"]
    return best


def bookmark_name_map(cats: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for items in cats.values():
        for it in items:
            h = it.get("host") or ""
            if h and h not in names and it.get("name"):
                names[h] = it["name"]
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bookmarks", required=True)
    ap.add_argument("--history", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    cats = load_bookmarks(Path(args.bookmarks))
    home_map = bookmark_home_map(cats)
    name_map = bookmark_name_map(cats)

    frequent: list[dict] = []
    if args.history:
        hp = Path(args.history)
        if hp.is_file():
            frequent = load_frequent(hp, args.top, home_map)
            for item in frequent:
                if item["host"] in name_map:
                    item["name"] = name_map[item["host"]]
                elif item["name"] and len(item["name"]) > 40:
                    item["name"] = item["host"]
        else:
            warnings.append(f"History not found: {hp}")
    else:
        warnings.append("No History path provided; frequent section empty")

    (out_dir / "bookmarks.json").write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "frequent.json").write_text(json.dumps(frequent, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "bookmark_categories": len(cats),
        "bookmark_items": sum(len(v) for v in cats.values()),
        "frequent_count": len(frequent),
        "top": args.top,
        "warnings": warnings,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
