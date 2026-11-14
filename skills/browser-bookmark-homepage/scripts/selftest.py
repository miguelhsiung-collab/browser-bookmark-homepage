#!/usr/bin/env python3
"""Synthetic smoke tests for hide denylist + frequent patching. No real user data."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from hidden_store import (  # noqa: E402
    hidden_host_set,
    load_hidden,
    merge_stores,
    save_hidden,
)
from export_chromium_nav import load_frequent, pick_display_name  # noqa: E402
from build_homepage import main as build_main  # noqa: E402
import build_homepage  # noqa: E402
import update_frequent  # noqa: E402


def write_bookmarks(path: Path) -> None:
    data = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "书签栏",
                "children": [
                    {
                        "type": "folder",
                        "name": "示例",
                        "children": [
                            {"type": "url", "name": "Alpha", "url": "https://alpha.example/"},
                            {"type": "url", "name": "Beta", "url": "https://beta.example/path"},
                            {"type": "url", "name": "Gamma", "url": "https://gamma.example/"},
                        ],
                    }
                ],
            },
            "other": {"type": "folder", "name": "其他书签", "children": []},
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def write_history(path: Path, rows: list[tuple[str, str, int]]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE urls (url TEXT, title TEXT, visit_count INTEGER)"
    )
    conn.executemany("INSERT INTO urls(url, title, visit_count) VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()


def test_display_names() -> None:
    assert pick_display_name("x.com", "", "(1) X上的 huangserv...", frequent=True) == "X"
    assert pick_display_name("baidu.com", "", "百度一下，你就知道", frequent=True) == "百度"
    assert pick_display_name("iqiyi.com", "", "爱奇艺-在线视频网站-海量", frequent=True) == "爱奇艺"
    assert pick_display_name("github.com", "", "GitHub - TanShilong/foo", frequent=True) == "GitHub"
    assert pick_display_name("youmind.com", "", "Chaos · YouMind", frequent=True) == "YouMind"
    assert pick_display_name("pan.baidu.com", "", "English说文解字", frequent=True) == "百度网盘"
    assert pick_display_name("zhihu.com", "如何学习Python", "", frequent=False) == "如何学习Python"


def test_denylist_and_build(tmp: Path) -> None:
    bookmarks = tmp / "Bookmarks"
    history = tmp / "History"
    write_bookmarks(bookmarks)
    # 25 hosts so Top20 can refill after a hide. Include auth noise that must be skipped.
    rows = []
    for i in range(1, 26):
        host = f"site{i:02d}.example"
        rows.append((f"https://{host}/", host, 1000 - i))
    rows.append(("https://accounts.google.com/signin", "Sign in", 9999))
    rows.append(("https://login.microsoftonline.com/oauth", "OAuth", 9998))
    rows.append(("https://alpha.example/login", "Alpha login", 50))
    write_history(history, rows)

    hidden = tmp / "hidden.json"
    save_hidden(
        hidden,
        {
            "items": [
                {
                    "url": "https://site01.example/",
                    "host": "site01.example",
                    "name": "site01",
                    "cat": "高频访问",
                    "scope": "host",
                    "hidden": True,
                    "updatedAt": 1,
                }
            ]
        },
    )

    out = tmp / "export"
    os.system(
        f"{sys.executable} {ROOT / 'export_chromium_nav.py'} "
        f"--bookmarks {bookmarks} --history {history} --out-dir {out} --top 20 --hidden {hidden}"
    )
    frequent = json.loads((out / "frequent.json").read_text(encoding="utf-8"))
    hosts = [i["host"] for i in frequent]
    assert "site01.example" not in hosts, hosts
    assert "accounts.google.com" not in hosts, hosts
    assert "login.microsoftonline.com" not in hosts, hosts
    assert "site02.example" in hosts
    assert "site21.example" in hosts  # filled the empty slot
    assert len(frequent) == 20, len(frequent)

    # Candidates should still include the hidden host so a later restore can show it
    # after the next client-side filter — actually export candidates ignore denylist.
    cands = json.loads((out / "frequent_candidates.json").read_text(encoding="utf-8"))
    cand_hosts = [i["host"] for i in cands]
    assert "site01.example" in cand_hosts

    html_out = tmp / "homepage.html"
    sys.argv = [
        "build_homepage.py",
        "--bookmarks",
        str(out / "bookmarks.json"),
        "--frequent",
        str(out / "frequent.json"),
        "--candidates",
        str(out / "frequent_candidates.json"),
        "--hidden",
        str(hidden),
        "--template",
        str(ROOT.parent / "assets" / "homepage-template.html"),
        "--title",
        "测试导航",
        "--out",
        str(html_out),
    ]
    assert build_main() == 0
    html = html_out.read_text(encoding="utf-8")
    assert "NAV_FREQUENT_START" in html
    assert "从主页移除" in html
    assert "高频访问已自动更新" not in html
    assert "__BRAND__" not in html
    assert "brand-text" in html
    assert "setRefreshLabel" in html
    assert "已从主页移除" in html
    assert (tmp / "frequent-data.js").is_file()
    # hidden seed contains the denylist
    assert "site01.example" in html
    # layout tokens still present
    assert "aside-nav" in html and "hot-section" in html

    # Patch in place should change version / items
    payload = {
        "generatedAt": "2026-11-13T20:00:00+08:00",
        "version": 42,
        "top": 20,
        "frequentLabel": "高频访问",
        "items": [{"name": "Zed", "url": "https://zed.example/", "host": "zed.example", "visit_count": 3}],
        "visits": {"zed.example": 3},
    }
    store = load_hidden(hidden)
    assert update_frequent.patch_homepage(html_out, payload, store)
    html2 = html_out.read_text(encoding="utf-8")
    assert "zed.example" in html2
    assert "window.__FREQUENT_SNAPSHOT__" in html2
    assert '"version": 42' in html2
    sidecar = json.loads((tmp / "frequent-data.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    assert sidecar["version"] == 42

    # Restore tombstone should win when newer
    restored = merge_stores(
        store,
        {
            "items": [
                {
                    "host": "site01.example",
                    "url": "https://site01.example/",
                    "scope": "host",
                    "hidden": False,
                    "updatedAt": 99,
                }
            ]
        },
    )
    assert "site01.example" not in hidden_host_set(restored)


def test_local_server(tmp: Path) -> None:
    update_frequent.STATE.payload = {
        "generatedAt": "2026-11-13T20:00:00+08:00",
        "version": 7,
        "items": [{"name": "Zed", "url": "https://zed.example/", "host": "zed.example"}],
        "visits": {"zed.example": 1},
        "top": 20,
    }
    update_frequent.STATE.hidden = {"version": 1, "items": []}
    update_frequent.STATE.homepages = [tmp / "homepage.html"]
    (tmp / "homepage.html").write_text("<html>ok</html>", encoding="utf-8")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), update_frequent.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/frequent") as r:
            data = json.loads(r.read().decode("utf-8"))
        assert data["version"] == 7
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/hidden",
            data=json.dumps(
                {
                    "items": [
                        {
                            "url": "https://hide.example/",
                            "host": "hide.example",
                            "scope": "host",
                            "name": "Hide",
                            "hidden": True,
                            "updatedAt": 1,
                        }
                    ]
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            saved = json.loads(r.read().decode("utf-8"))
        assert any(it["host"] == "hide.example" for it in saved["items"])
        assert (tmp / "hidden.json").is_file()
    finally:
        httpd.shutdown()


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_display_names()
        test_denylist_and_build(tmp)
        test_local_server(tmp)
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
