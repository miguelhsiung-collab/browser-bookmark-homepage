#!/usr/bin/env python3
"""Inject bookmark + frequent JSON into homepage-template.html."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hidden_store import load_hidden, normalize_store

DEFAULT_ICONS = {
    "高频访问": "🔥",
    "Frequent": "🔥",
    "AI 工具": "✨",
    "工作采购": "🏭",
    "AGV叉车": "🚛",
    "设计素材": "🎨",
    "学习文档": "📚",
    "搜索工具": "🔎",
    "社交资讯": "💬",
    "购物海淘": "🛒",
    "影视娱乐": "🎬",
    "其他常用": "⭐",
    "Other": "⭐",
}

TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def short_brand(title: str) -> str:
    t = (title or "").strip()
    for sep in (" · ", " — ", " - ", "｜", "|"):
        if sep in t:
            left = t.split(sep, 1)[0].strip()
            if left:
                return left
    return t or "我的导航"


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def load_json_list(path: str) -> list:
    if path and Path(path).is_file():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    return []


def snapshot_payload(items: list, top: int, label: str) -> dict:
    visits = {i["host"]: i.get("visit_count", 0) for i in items if i.get("host")}
    return {
        "generatedAt": now_iso(),
        "version": int(time.time()),
        "top": top,
        "frequentLabel": label,
        "items": [
            {
                "name": i.get("name") or i.get("host") or "",
                "url": i.get("url") or "",
                "host": i.get("host") or "",
                "visit_count": i.get("visit_count", 0),
            }
            for i in items
        ],
        "visits": visits,
    }


def write_frequent_sidecar(homepage: Path, payload: dict) -> Path:
    sidecar = homepage.with_name("frequent-data.js")
    body = (
        "window.__FREQUENT_SNAPSHOT__ = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n"
    )
    sidecar.write_text(body, encoding="utf-8")
    return sidecar


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bookmarks", required=True)
    ap.add_argument("--frequent", default="")
    ap.add_argument("--candidates", default="", help="Optional frequent_candidates.json (larger pool)")
    ap.add_argument("--hidden", default="", help="Optional hidden.json seed (homepage-only denylist)")
    ap.add_argument("--template", required=True)
    ap.add_argument("--title", default="我的导航")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frequent-label", default="高频访问")
    ap.add_argument("--frequent-tip", default="按浏览器访问次数自动收录")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--api-port", type=int, default=8765)
    ap.add_argument("--brand", default="", help="Short sidebar label; default is the title before ·")
    args = ap.parse_args()

    cats = json.loads(Path(args.bookmarks).read_text(encoding="utf-8"))
    frequent = load_json_list(args.frequent)
    candidates = load_json_list(args.candidates) or frequent
    hidden = load_hidden(args.hidden) if args.hidden else {"version": 1, "items": []}

    data = {}
    visits = {}
    if candidates or frequent:
        label = args.frequent_label
        pool = candidates or frequent
        data[label] = [{"name": i["name"], "url": i["url"], "host": i["host"]} for i in pool]
        for i in pool:
            visits[i["host"]] = i.get("visit_count", 0)

    for k, v in cats.items():
        if k in data:
            continue
        data[k] = v

    icons = {k: DEFAULT_ICONS.get(k, "•") for k in data}
    bm_count = sum(len(v) for k, v in data.items() if k not in (args.frequent_label, "Frequent"))
    freq_n = min(args.top, len(frequent) or len(candidates))
    stats = f"书签 {bm_count} · 高频站点 {freq_n} · {len(data)} 个分类"

    payload = snapshot_payload(candidates or frequent, args.top, args.frequent_label)

    html = Path(args.template).read_text(encoding="utf-8")
    html = html.replace("__TITLE__", args.title)
    html = html.replace("__BRAND__", args.brand or short_brand(args.title))
    html = html.replace("__STATS_LINE__", stats)
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__VISITS_JSON__", json.dumps(visits, ensure_ascii=False))
    html = html.replace("__ICONS_JSON__", json.dumps(icons, ensure_ascii=False))
    html = html.replace("__FREQUENT_LABEL__", args.frequent_label)
    html = html.replace("__FREQUENT_TIP__", args.frequent_tip)
    html = html.replace("__FREQUENT_SNAPSHOT_JSON__", json.dumps(payload, ensure_ascii=False))
    html = html.replace("__HIDDEN_SEED_JSON__", json.dumps(normalize_store(hidden), ensure_ascii=False))
    html = html.replace("__API_PORT__", str(int(args.api_port or 0)))
    html = html.replace("__DISPLAY_TOP__", str(int(args.top)))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    sidecar = write_frequent_sidecar(out, payload)
    if args.hidden:
        # Keep a copy next to the HTML so later updater runs can merge it.
        dest = out.with_name("hidden.json")
        if Path(args.hidden).resolve() != dest.resolve() and Path(args.hidden).is_file():
            dest.write_text(Path(args.hidden).read_text(encoding="utf-8"), encoding="utf-8")
        elif not dest.exists():
            dest.write_text(
                json.dumps(normalize_store(hidden), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    print(out)
    print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
