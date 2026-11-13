#!/usr/bin/env python3
"""Refresh the 高频访问 section from Chromium/Comet History and optionally serve it."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hidden_store import (  # noqa: E402
    load_hidden,
    merge_stores,
    normalize_store,
    save_hidden,
)
from export_chromium_nav import (  # noqa: E402
    bookmark_home_map,
    bookmark_name_map,
    load_bookmarks,
    load_frequent,
)
from build_homepage import snapshot_payload, write_frequent_sidecar  # noqa: E402

TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
SNAP_RE = re.compile(
    r"<!--NAV_FREQUENT_START-->.*?<!--NAV_FREQUENT_END-->",
    re.S,
)
HIDDEN_RE = re.compile(
    r"<!--NAV_HIDDEN_START-->.*?<!--NAV_HIDDEN_END-->",
    re.S,
)
DEFAULT_PORT = 8765
CANDIDATE_POOL = 80

BROWSER_ROOTS = {
    "comet": {
        "win": ("LOCALAPPDATA", "Perplexity/Comet/User Data"),
        "mac": "Library/Application Support/Perplexity/Comet",
        "linux": None,
    },
    "chrome": {
        "win": ("LOCALAPPDATA", "Google/Chrome/User Data"),
        "mac": "Library/Application Support/Google/Chrome",
        "linux": ".config/google-chrome",
    },
    "edge": {
        "win": ("LOCALAPPDATA", "Microsoft/Edge/User Data"),
        "mac": "Library/Application Support/Microsoft Edge",
        "linux": ".config/microsoft-edge",
    },
    "brave": {
        "win": ("LOCALAPPDATA", "BraveSoftware/Brave-Browser/User Data"),
        "mac": "Library/Application Support/BraveSoftware/Brave-Browser",
        "linux": ".config/BraveSoftware/Brave-Browser",
    },
    "chromium": {
        "win": ("LOCALAPPDATA", "Chromium/User Data"),
        "mac": "Library/Application Support/Chromium",
        "linux": ".config/chromium",
    },
}


def log(msg: str, stream=sys.stderr) -> None:
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts} Asia/Shanghai] {msg}"
    print(line, file=stream, flush=True)
    log_path = os.environ.get("NAV_UPDATER_LOG")
    if log_path:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def default_user_data(browser: str) -> Path | None:
    spec = BROWSER_ROOTS.get(browser.lower())
    if not spec:
        return None
    plat = platform_key()
    info = spec.get(plat)
    if not info:
        return None
    if plat == "win":
        env, rel = info
        root = os.environ.get(env) or os.environ.get("USERPROFILE")
        if not root:
            return None
        return Path(root) / Path(rel)
    return Path.home() / info


def resolve_profile_file(browser: str, profile: str, name: str, explicit: str = "") -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    root = default_user_data(browser)
    if not root:
        return None
    p = root / profile / name
    return p if p.is_file() else None


def load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def as_paths(value) -> list[Path]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [Path(v) for v in value if v]
    return [Path(value)]


def merge_hidden_files(paths: list[Path]) -> dict:
    stores = [load_hidden(p) for p in paths if p]
    return merge_stores(*stores) if stores else {"version": 1, "items": []}


def collect_hidden_paths(homepages: list[Path], extra: str = "") -> list[Path]:
    paths = []
    seen = set()
    for hp in homepages:
        p = hp.with_name("hidden.json")
        key = str(p.resolve()) if p.exists() or True else str(p)
        if key not in seen:
            seen.add(key)
            paths.append(p)
    if extra:
        p = Path(extra)
        key = str(p.resolve()) if p.parent.exists() else str(p)
        if key not in seen:
            paths.append(p)
    return paths


def render_frequent_block(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return (
        "<!--NAV_FREQUENT_START-->\n"
        '<script id="frequent-snapshot">\n'
        f"window.__FREQUENT_SNAPSHOT__ = {body};\n"
        "</script>\n"
        "<!--NAV_FREQUENT_END-->"
    )


def render_hidden_block(store: dict) -> str:
    body = json.dumps(normalize_store(store), ensure_ascii=False)
    return (
        "<!--NAV_HIDDEN_START-->\n"
        '<script id="hidden-seed">\n'
        f"window.__HIDDEN_SEED__ = {body};\n"
        "</script>\n"
        "<!--NAV_HIDDEN_END-->"
    )


def patch_homepage(homepage: Path, payload: dict, hidden: dict) -> bool:
    if not homepage.is_file():
        log(f"homepage not found: {homepage}")
        return False
    html = homepage.read_text(encoding="utf-8")
    original = html
    freq_block = render_frequent_block(payload)
    hidden_block = render_hidden_block(hidden)
    if SNAP_RE.search(html):
        html = SNAP_RE.sub(freq_block, html, count=1)
    else:
        # Old homepage without markers: inject before </body> if possible.
        if "</body>" in html:
            html = html.replace("</body>", freq_block + "\n</body>", 1)
            log(f"injected frequent markers into older HTML: {homepage}")
        else:
            log(f"cannot patch HTML, no markers or </body>: {homepage}")
            return False
    if HIDDEN_RE.search(html):
        html = HIDDEN_RE.sub(hidden_block, html, count=1)
    elif "</body>" in html:
        html = html.replace("</body>", hidden_block + "\n</body>", 1)
    if html != original:
        tmp = homepage.with_suffix(homepage.suffix + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(homepage)
    write_frequent_sidecar(homepage, payload)
    return True


def apply_names(items: list[dict], name_map: dict[str, str]) -> list[dict]:
    for item in items:
        if item["host"] in name_map:
            item["name"] = name_map[item["host"]]
        elif item.get("name") and len(item["name"]) > 40:
            item["name"] = item["host"]
    return items


def compute_frequent(bookmarks: Path, history: Path, top: int, candidate_n: int, hidden) -> tuple[list, list]:
    cats = load_bookmarks(bookmarks)
    home_map = bookmark_home_map(cats)
    name_map = bookmark_name_map(cats)
    cand_n = max(candidate_n, top)
    from hidden_store import hidden_host_set, hidden_url_set

    skip_hosts = hidden_host_set(hidden)
    skip_urls = hidden_url_set(hidden)
    candidates = apply_names(load_frequent(history, cand_n, home_map), name_map)
    frequent = apply_names(load_frequent(history, top, home_map, skip_hosts, skip_urls), name_map)
    return frequent, candidates


class UpdaterState:
    def __init__(self):
        self.lock = threading.Lock()
        self.payload: dict = {}
        self.hidden: dict = {"version": 1, "items": []}
        self.meta: dict = {}
        self.homepages: list[Path] = []
        self.hidden_paths: list[Path] = []


STATE = UpdaterState()


def run_update(args, *, reason: str = "manual") -> dict:
    homepages = as_paths(args.homepage)
    hidden_paths = collect_hidden_paths(homepages, args.hidden)
    hidden = merge_hidden_files(hidden_paths)

    bookmarks = resolve_profile_file(args.browser, args.profile, "Bookmarks", args.bookmarks)
    history = resolve_profile_file(args.browser, args.profile, "History", args.history)
    if not bookmarks:
        raise FileNotFoundError("Bookmarks file not found; pass --bookmarks or check --browser/--profile")
    if not history:
        raise FileNotFoundError("History file not found; pass --history or check --browser/--profile")

    frequent, candidates = compute_frequent(
        bookmarks, history, args.top, args.candidates, hidden
    )
    payload = snapshot_payload(candidates or frequent, args.top, args.frequent_label)
    patched = []
    for hp in homepages:
        if patch_homepage(hp, payload, hidden):
            patched.append(str(hp))
            # Keep hidden.json next to each homepage (create if missing).
            side = hp.with_name("hidden.json")
            if not side.exists():
                save_hidden(side, hidden)
    meta = {
        "reason": reason,
        "generatedAt": payload["generatedAt"],
        "version": payload["version"],
        "frequent_count": len(frequent),
        "candidate_count": len(candidates),
        "top": args.top,
        "patched": patched,
        "bookmarks": str(bookmarks),
        "history": str(history),
    }
    with STATE.lock:
        STATE.payload = payload
        STATE.hidden = hidden
        STATE.meta = meta
        STATE.homepages = homepages
        STATE.hidden_paths = hidden_paths
    log(
        f"updated frequent: top {len(frequent)} / candidates {len(candidates)} "
        f"→ {len(patched)} file(s) ({reason})"
    )
    return meta


def persist_hidden(store: dict, paths: list[Path], homepages: list[Path]) -> None:
    store = normalize_store(store)
    targets = list(paths)
    for hp in homepages:
        side = hp.with_name("hidden.json")
        if side not in targets:
            targets.append(side)
    for p in targets:
        try:
            save_hidden(p, store)
        except OSError as exc:
            log(f"failed to write {p}: {exc}")
    payload = STATE.payload
    if payload:
        for hp in homepages:
            if hp.is_file():
                patch_homepage(hp, payload, store)


class Handler(BaseHTTPRequestHandler):
    server_version = "BookmarkHomepageUpdater/1.0"

    def log_message(self, fmt, *args):
        log("http " + (fmt % args))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _json(self, code: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/frequent":
            with STATE.lock:
                payload = STATE.payload or {}
            self._json(200, payload)
            return
        if path == "/api/hidden":
            with STATE.lock:
                hidden = STATE.hidden
            self._json(200, hidden)
            return
        if path == "/api/status":
            with STATE.lock:
                self._json(200, STATE.meta or {"status": "empty"})
            return
        if path in ("/", "/index.html", "/homepage.html"):
            with STATE.lock:
                homepages = list(STATE.homepages)
            target = next((p for p in homepages if p.is_file()), None)
            if not target:
                self._json(404, {"error": "homepage not found"})
                return
            data = target.read_bytes()
            self._bytes(200, data, "text/html; charset=utf-8")
            return
        if path == "/frequent-data.js":
            with STATE.lock:
                payload = STATE.payload or {}
            body = (
                "window.__FREQUENT_SNAPSHOT__ = "
                + json.dumps(payload, ensure_ascii=False)
                + ";\n"
            ).encode("utf-8")
            self._bytes(200, body, "application/javascript; charset=utf-8")
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        if parsed.path != "/api/hidden":
            self._json(404, {"error": "not found"})
            return
        incoming = normalize_store(data)
        with STATE.lock:
            merged = merge_stores(STATE.hidden, incoming)
            STATE.hidden = merged
            paths = list(STATE.hidden_paths)
            homepages = list(STATE.homepages)
        persist_hidden(merged, paths, homepages)
        self._json(200, merged)


def serve(port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    log(f"local server http://127.0.0.1:{port}/ (localhost only)")
    return httpd


def watch_loop(args) -> None:
    interval = max(1, int(args.interval)) * 60
    while True:
        time.sleep(interval)
        try:
            run_update(args, reason="watch")
        except Exception as exc:
            log(f"watch update failed: {exc}\n{traceback.format_exc()}")


def write_default_config(path: Path, args) -> None:
    cfg = {
        "homepage": [str(p) for p in as_paths(args.homepage)],
        "browser": args.browser,
        "profile": args.profile,
        "top": args.top,
        "candidates": args.candidates,
        "interval": args.interval,
        "port": args.port,
        "frequent_label": args.frequent_label,
        "bookmarks": args.bookmarks or "",
        "history": args.history or "",
        "hidden": args.hidden or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install_windows_task(args) -> int:
    if not sys.platform.startswith("win"):
        log("scheduled task installer is for Windows only")
        return 1
    import subprocess

    script = Path(__file__).resolve()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else Path(sys.executable)
    config = Path(args.config) if args.config else script.parent / "updater-config.json"
    write_default_config(config, args)
    log_path = config.with_name("updater.log")
    wrapper = config.with_name("start_updater.bat")
    wrapper.write_text(
        "\n".join(
            [
                "@echo off",
                "chcp 65001 >nul",
                f'set "NAV_UPDATER_LOG={log_path}"',
                f'"{exe}" "{script}" --config "{config}" --watch --serve --interval {args.interval} --port {args.port}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    task_name = "BookmarkHomepageFrequentUpdate"
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        str(wrapper),
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/F",
    ]
    log("creating scheduled task: " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout or "")
    sys.stderr.write(result.stderr or "")
    if result.returncode != 0:
        log(f"schtasks failed with code {result.returncode}")
        return result.returncode
    log(f"scheduled task installed: {task_name} (ONLOGON) -> {wrapper}")
    env = {**os.environ, "NAV_UPDATER_LOG": str(log_path)}
    subprocess.Popen(
        [str(exe), str(script), "--config", str(config), "--watch", "--serve", "--interval", str(args.interval), "--port", str(args.port)],
        env=env,
        cwd=str(script.parent),
        close_fds=True,
    )
    log("updater started in background for this session")
    print(json.dumps({"task": task_name, "wrapper": str(wrapper), "config": str(config), "log": str(log_path)}, ensure_ascii=False, indent=2))
    return 0


def apply_config(args) -> None:
    cfg = load_config(args.config)
    if not cfg:
        return
    if not args.homepage and cfg.get("homepage"):
        args.homepage = cfg["homepage"]
    for key in ("browser", "profile", "bookmarks", "history", "hidden", "frequent_label"):
        if not getattr(args, key, None) and cfg.get(key):
            setattr(args, key, cfg[key])
    for key in ("top", "candidates", "interval", "port"):
        # Keep argparse defaults unless config sets them and user didn't? We can't
        # distinguish default vs user. Config fills only if still default-ish is messy.
        # Prefer CLI when explicitly passed; simplest: config applies first, then we
        # already overwrote from argparse. So only fill empty/zero-not-set.
        # For these ints, use config if args still equal parser defaults AND config has them,
        # but we don't know. Document: --config values are used when the CLI flag is omitted
        # by applying config then letting argparse... we apply after argparse, so CLI wins
        # only if we skip when the value was provided. Use dest from sys.argv.
        pass
    # CLI wins when the flag is present; otherwise config wins.
    flags = set()
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            flags.add(tok.lstrip("-").replace("-", "_"))
        i += 1
    mapping = {
        "homepage": "homepage",
        "browser": "browser",
        "profile": "profile",
        "bookmarks": "bookmarks",
        "history": "history",
        "hidden": "hidden",
        "frequent_label": "frequent_label",
        "top": "top",
        "candidates": "candidates",
        "interval": "interval",
        "port": "port",
    }
    for flag, attr in mapping.items():
        if flag in flags:
            continue
        if flag.replace("_", "-") in {a.replace("_", "-") for a in flags}:
            continue
        if cfg.get(attr if attr != "frequent_label" else "frequent_label") is not None or cfg.get(flag) is not None:
            val = cfg.get(attr, cfg.get(flag))
            if val is not None:
                setattr(args, attr, val)


def main() -> int:
    ap = argparse.ArgumentParser(description="更新导航主页的高频访问，并可选启动本地服务")
    ap.add_argument("--config", default="", help="JSON config with homepage / browser / interval etc.")
    ap.add_argument("--homepage", action="append", default=[], help="Homepage HTML path (repeatable)")
    ap.add_argument("--bookmarks", default="")
    ap.add_argument("--history", default="")
    ap.add_argument("--hidden", default="", help="Optional extra hidden.json to merge")
    ap.add_argument("--browser", default="comet")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--candidates", type=int, default=CANDIDATE_POOL)
    ap.add_argument("--interval", type=int, default=15, help="Watch interval in minutes")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--frequent-label", default="高频访问")
    ap.add_argument("--install-task", action="store_true", help="Windows: install ONLOGON scheduled task")
    ap.add_argument("--once", action="store_true", help="Run a single update and exit (default unless --watch/--serve)")
    args = ap.parse_args()
    apply_config(args)
    if isinstance(args.homepage, str):
        args.homepage = [args.homepage]
    if not args.homepage:
        log("no --homepage and no config homepage; nothing to patch")
        if not args.install_task:
            return 2

    if args.install_task:
        return install_windows_task(args)

    try:
        meta = run_update(args, reason="startup")
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    except Exception as exc:
        log(f"update failed: {exc}\n{traceback.format_exc()}")
        if not args.serve and not args.watch:
            return 1

    httpd = None
    if args.serve:
        port = int(args.port or DEFAULT_PORT)
        try:
            httpd = serve(port)
        except OSError as exc:
            log(f"port {port} unavailable ({exc}); trying the next ports")
            httpd = None
            for p in range(port + 1, port + 6):
                try:
                    httpd = serve(p)
                    args.port = p
                    break
                except OSError:
                    continue
            if httpd is None:
                log("could not bind any local port; continuing without server")

    if args.watch:
        watch_loop(args)
    elif args.serve and httpd is not None:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
