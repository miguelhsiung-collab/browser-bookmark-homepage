#!/usr/bin/env python3
"""Homepage-only hidden/denylist store. Never touches browser bookmarks or History."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

STORE_VERSION = 1


def normalize_host(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def host_from_url(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        host = (p.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        query = ("?" + p.query) if p.query else ""
        scheme = (p.scheme or "https").lower()
        netloc = host
        if p.port:
            netloc = f"{host}:{p.port}"
        return f"{scheme}://{netloc}{path}{query}"
    except Exception:
        return u.rstrip("/")


def item_key(item: dict) -> tuple[str, str]:
    scope = item.get("scope") or "url"
    if scope == "host":
        host = normalize_host(item.get("host") or host_from_url(item.get("url") or ""))
        return ("host", host)
    return ("url", normalize_url(item.get("url") or ""))


def empty_store() -> dict:
    return {"version": STORE_VERSION, "items": []}


def normalize_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = (raw.get("url") or "").strip()
    host = normalize_host(raw.get("host") or host_from_url(url))
    scope = raw.get("scope") or ("host" if raw.get("cat") in ("高频访问", "Frequent") and not raw.get("scope") else "url")
    if scope == "host" and not host:
        return None
    if scope != "host" and not url:
        return None
    hidden = raw.get("hidden")
    if hidden is None:
        hidden = True
    try:
        updated = int(raw.get("updatedAt") or 0)
    except (TypeError, ValueError):
        updated = 0
    return {
        "url": url,
        "host": host,
        "name": (raw.get("name") or host or url or "").strip(),
        "cat": raw.get("cat") or "",
        "scope": "host" if scope == "host" else "url",
        "hidden": bool(hidden),
        "updatedAt": updated,
    }


def normalize_store(data) -> dict:
    if not data:
        return empty_store()
    if isinstance(data, list):
        items_raw = data
    elif isinstance(data, dict):
        items_raw = data.get("items") or []
    else:
        return empty_store()
    items = []
    seen = {}
    for raw in items_raw:
        it = normalize_item(raw)
        if not it:
            continue
        k = item_key(it)
        prev = seen.get(k)
        if prev is None or it["updatedAt"] >= prev["updatedAt"]:
            seen[k] = it
    items = list(seen.values())
    return {"version": STORE_VERSION, "items": items}


def load_hidden(path: Path | str | None) -> dict:
    if not path:
        return empty_store()
    p = Path(path)
    if not p.is_file():
        return empty_store()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store()
    return normalize_store(data)


def save_hidden(path: Path | str, store: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(normalize_store(store), ensure_ascii=False, indent=2)
    p.write_text(text + "\n", encoding="utf-8")


def merge_stores(*stores) -> dict:
    best: dict[tuple[str, str], dict] = {}
    for store in stores:
        for it in normalize_store(store)["items"]:
            k = item_key(it)
            prev = best.get(k)
            if prev is None or it["updatedAt"] >= prev["updatedAt"]:
                best[k] = it
    return {"version": STORE_VERSION, "items": list(best.values())}


def active_items(store) -> list[dict]:
    return [it for it in normalize_store(store)["items"] if it.get("hidden", True)]


def hidden_host_set(store) -> set[str]:
    out = set()
    for it in active_items(store):
        if it.get("scope") == "host":
            h = normalize_host(it.get("host") or "")
            if h:
                out.add(h)
    return out


def hidden_url_set(store) -> set[str]:
    out = set()
    for it in active_items(store):
        u = normalize_url(it.get("url") or "")
        if u:
            out.add(u)
    return out


def is_item_hidden(item: dict, store, *, frequent: bool = False) -> bool:
    url = normalize_url(item.get("url") or "")
    host = normalize_host(item.get("host") or host_from_url(item.get("url") or ""))
    if url and url in hidden_url_set(store):
        return True
    if frequent and host and host in hidden_host_set(store):
        return True
    return False


def filter_frequent(items: list[dict], store, top: int | None = None) -> list[dict]:
    out = [i for i in items if not is_item_hidden(i, store, frequent=True)]
    if top is not None:
        return out[:top]
    return out


def sidecar_paths(homepage: Path | str) -> list[Path]:
    """hidden.json sits next to each homepage copy."""
    p = Path(homepage)
    return [p.with_name("hidden.json")]
