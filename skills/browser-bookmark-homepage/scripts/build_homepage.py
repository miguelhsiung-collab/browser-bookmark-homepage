#!/usr/bin/env python3
"""Inject bookmark + frequent JSON into homepage-template.html."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bookmarks", required=True)
    ap.add_argument("--frequent", default="")
    ap.add_argument("--template", required=True)
    ap.add_argument("--title", default="我的导航")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frequent-label", default="高频访问")
    args = ap.parse_args()

    cats = json.loads(Path(args.bookmarks).read_text(encoding="utf-8"))
    frequent = []
    if args.frequent and Path(args.frequent).is_file():
        frequent = json.loads(Path(args.frequent).read_text(encoding="utf-8"))

    data = {}
    visits = {}
    if frequent:
        label = args.frequent_label
        data[label] = [{"name": i["name"], "url": i["url"], "host": i["host"]} for i in frequent]
        for i in frequent:
            visits[i["host"]] = i.get("visit_count", 0)

    for k, v in cats.items():
        if k in data:
            continue
        data[k] = v

    icons = {k: DEFAULT_ICONS.get(k, "•") for k in data}
    bm_count = sum(len(v) for k, v in data.items() if k not in (args.frequent_label, "Frequent"))
    freq_n = len(frequent)
    stats = f"书签 {bm_count} · 高频站点 {freq_n} · {len(data)} 个分类"

    html = Path(args.template).read_text(encoding="utf-8")
    html = html.replace("__TITLE__", args.title)
    html = html.replace("__STATS_LINE__", stats)
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__VISITS_JSON__", json.dumps(visits, ensure_ascii=False))
    html = html.replace("__ICONS_JSON__", json.dumps(icons, ensure_ascii=False))
    html = html.replace("__FREQUENT_LABEL__", args.frequent_label)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
