#!/usr/bin/env python3
"""Export Chromium Bookmarks + History into nav JSON for homepage build."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hidden_store import load_hidden, hidden_host_set, hidden_url_set, normalize_host, normalize_url

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



# Short official names for well-known hosts (frequent section aggregates by host).
SHORT_HOST_NAMES = {
    "x.com": "X",
    "twitter.com": "X",
    "baidu.com": "百度",
    "pan.baidu.com": "百度网盘",
    "yun.baidu.com": "百度网盘",
    "youmind.com": "YouMind",
    "google.com": "Google",
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "youtube.com": "YouTube",
    "bilibili.com": "哔哩哔哩",
    "iqiyi.com": "爱奇艺",
    "youku.com": "优酷",
    "v.qq.com": "腾讯视频",
    "douban.com": "豆瓣",
    "movie.douban.com": "豆瓣电影",
    "zhihu.com": "知乎",
    "weixin.qq.com": "微信",
    "mp.weixin.qq.com": "微信公众号",
    "work.weixin.qq.com": "企业微信",
    "mail.qq.com": "QQ邮箱",
    "exmail.qq.com": "企业邮箱",
    "es.mail.qq.com": "企业邮箱",
    "cursor.com": "Cursor",
    "grok.com": "Grok",
    "x.ai": "Grok",
    "openai.com": "OpenAI",
    "chatgpt.com": "ChatGPT",
    "claude.ai": "Claude",
    "taobao.com": "淘宝",
    "tmall.com": "天猫",
    "jd.com": "京东",
    "amazon.com": "Amazon",
    "amazon.cn": "Amazon",
}


def lookup_short_host_name(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    # Exact host only: pan.baidu.com must not inherit "百度".
    return SHORT_HOST_NAMES.get(h, "")


def clean_page_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(r"^\(\d+\)\s*", "", t)
    t = re.sub(r"^【.*?】\s*", "", t)
    if not t:
        return ""
    parts = [p.strip() for p in re.split(r"\s*[-–—|｜·•]\s*", t) if p.strip()]
    if len(parts) >= 2:
        first = parts[0]
        rest_len = len(" ".join(parts[1:]))
        # Keep short two-part brands only when joined by a mid-dot (Chaos · YouMind).
        # Hyphen / dash is usually "品牌 - 口号", so take the first short part.
        mid_dot = ("·" in t or "•" in t) and "-" not in t and "—" not in t and "–" not in t
        if mid_dot and len(parts) == 2 and len(t) <= 16 and len(parts[1]) <= 12:
            return t
        if 2 <= len(first) <= 16 and (rest_len >= 4 or len(t) > 12):
            return first
    if "-" in t and not re.search(r"\s-\s", t):
        first = t.split("-", 1)[0].strip()
        if 2 <= len(first) <= 16:
            return first
    return t


def is_good_short_name(name: str) -> bool:
    n = (name or "").strip()
    if not n or len(n) > 16:
        return False
    if re.match(r"^https?://", n, re.I):
        return False
    if re.match(r"^\(\d+\)\s*", n):
        return False
    return True


def pick_display_name(host: str, bookmark_name: str = "", page_title: str = "", *, frequent: bool = True) -> str:
    """Prefer a short site/bookmark name over a raw browser tab title."""
    known = lookup_short_host_name(host)
    if frequent and known:
        return known
    bm = (bookmark_name or "").strip()
    bm_clean = clean_page_title(bm) if bm else ""
    if is_good_short_name(bm_clean):
        return bm_clean
    if is_good_short_name(bm):
        return bm
    if known:
        return known
    cleaned = clean_page_title(page_title)
    if cleaned:
        return cleaned
    if bm_clean:
        return bm_clean
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h or host or page_title or "未命名"


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
    # Prefer real folders when they actually organize most items.
    # If the tree is flat, or a large share sits in 其他常用, use keyword heuristics.
    folders = {i["folder"] for i in flat if i.get("folder")}
    catch_names = {"其他常用", "Other"}
    catch_n = sum(1 for i in flat if (i.get("folder") or "其他常用") in catch_names)
    use_heuristic = len(folders) <= 1 or (flat and catch_n / len(flat) >= 0.4)
    only_classify_catch = use_heuristic and len(folders) > 1
    cats: dict[str, list] = defaultdict(list)
    seen = set()
    for it in flat:
        key = (it["url"], it["name"])
        if key in seen:
            continue
        seen.add(key)
        folder = it.get("folder") or "其他常用"
        if use_heuristic:
            if only_classify_catch and folder not in catch_names:
                cat = folder
            else:
                cat = heuristic_cat(it)
        else:
            cat = folder
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


def load_frequent(
    history_path: Path,
    top: int,
    bookmark_by_host: dict[str, str],
    hidden_hosts: set[str] | None = None,
    hidden_urls: set[str] | None = None,
) -> list[dict]:
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
    skip_hosts = {normalize_host(h) for h in (hidden_hosts or set()) if h}
    skip_urls = {normalize_url(u) for u in (hidden_urls or set()) if u}
    out = []
    for h, count in ranked:
        # Skip hosts that only have auth URLs and no bookmark
        urls = host_urls[h]
        if all(is_auth_url(u) for u in urls) and h not in bookmark_by_host:
            continue
        url = prefer_url(h, urls, bookmark_by_host)
        if is_auth_url(url) and h not in bookmark_by_host:
            continue
        # Homepage-only denylist: skip so the next host can fill Top N
        if normalize_host(h) in skip_hosts or normalize_url(url) in skip_urls:
            continue
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
            n = (it.get("name") or "").strip()
            if not h or not n:
                continue
            prev = names.get(h)
            if prev is None or len(n) < len(prev):
                names[h] = n
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bookmarks", required=True)
    ap.add_argument("--history", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--candidates", type=int, default=80, help="Candidate pool size written to frequent_candidates.json")
    ap.add_argument("--hidden", default="", help="Optional hidden.json denylist (homepage-only)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    cats = load_bookmarks(Path(args.bookmarks))
    home_map = bookmark_home_map(cats)
    name_map = bookmark_name_map(cats)

    hidden_store = load_hidden(args.hidden) if args.hidden else None
    skip_hosts = hidden_host_set(hidden_store) if hidden_store else set()
    skip_urls = hidden_url_set(hidden_store) if hidden_store else set()

    frequent: list[dict] = []
    candidates: list[dict] = []
    if args.history:
        hp = Path(args.history)
        if hp.is_file():
            cand_n = max(args.candidates, args.top)
            # Candidates ignore the denylist so the page can refill Top N after local hides.
            candidates = load_frequent(hp, cand_n, home_map)
            frequent = load_frequent(hp, args.top, home_map, skip_hosts, skip_urls)
            for lst in (candidates, frequent):
                for item in lst:
                    item["name"] = pick_display_name(
                        item["host"],
                        name_map.get(item["host"]) or "",
                        item.get("name") or "",
                        frequent=True,
                    )
        else:
            warnings.append(f"History not found: {hp}")
    else:
        warnings.append("No History path provided; frequent section empty")

    (out_dir / "bookmarks.json").write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "frequent.json").write_text(json.dumps(frequent, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "frequent_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "bookmark_categories": len(cats),
        "bookmark_items": sum(len(v) for v in cats.values()),
        "frequent_count": len(frequent),
        "candidate_count": len(candidates),
        "top": args.top,
        "warnings": warnings,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
