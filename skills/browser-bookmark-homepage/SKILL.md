---
name: browser-bookmark-homepage
description: When the user wants a personal start/nav homepage built from Chromium or Comet bookmarks, or an auto Top-N frequent-sites section from browser History visit counts. Not for Firefox-only workflows, writing browser extensions, or deploying self-hosted OneNav.
---

# Browser bookmark homepage

Build a self-contained HTML navigation homepage from Chromium-family browser data (Chrome, Edge, Brave, Perplexity Comet, and similar). Default visual style follows littleheli / OneNav (aside categories, gradient search banner, favicon cards). The user may name another public reference site; if that site needs a logged-in app or heavy server UI, fall back to the default card grid.

## Invariants

1. Prefer local, static HTML the user can open with `file://` or set as the browser homepage. Do not require a server unless the user asks for OneNav-style hosting (out of scope for this skill).
2. Aggregate History by **registrable-ish host** (strip leading `www.`), not by raw URL. Prefer a clean bookmark URL for that host when one exists.
3. Filter authentication noise: skip login / OAuth / SSO path patterns listed in `references/host-filters.md`.
4. Never bake the user's real bookmarks, History, names, or company URLs into this skill's `assets/` or published repos. Use only synthetic sample data in tests.
5. Do not change browser policies, registry, or enterprise homepage settings unless the user explicitly asks; otherwise deliver the file and tell them how to set it.

## When to ask

Ask only if you cannot decide from context:

- Which browser / profile (Comet vs Chrome vs Edge; Default vs another Profile).
- Output path and page title language.
- Top N (default **20**) and whether to include a frequent section when History is missing.
- Alternate reference site URL (optional).

## Workflow

### 1. Locate profile data

Read `references/chromium-paths.md`. On the user's machine, resolve:

- `Bookmarks` (JSON)
- `History` (SQLite)

Copy both onto the agent box (or a temp folder the agent can read). If History is locked, copy the file first, then open the copy.

### 2. Export structured data

Run:

```bash
python3 scripts/export_chromium_nav.py \
  --bookmarks /path/to/Bookmarks \
  --history /path/to/History-copy \
  --out-dir /workspace/nav-export \
  --top 20
```

Outputs:

- `bookmarks.json` — categories → `[{name,url,host}, …]`
- `frequent.json` — Top N hosts with `visit_count` and preferred `url`
- `meta.json` — counts and warnings

If History is absent, still emit bookmarks and set `frequent` empty with a warning.

### 3. Categorize

- If the bookmark tree has folders, use folder names as categories (skip empty "书签栏" wrappers that only hold folders).
- If mostly flat, apply light heuristics in the export script (keyword → category); put leftovers in `其他常用` / `Other`.
- Insert **高频访问** / **Frequent** as the first nav section when frequent data exists.

### 4. Build HTML

```bash
python3 scripts/build_homepage.py \
  --bookmarks /workspace/nav-export/bookmarks.json \
  --frequent /workspace/nav-export/frequent.json \
  --template assets/homepage-template.html \
  --title "我的导航" \
  --out /workspace/bookmark-homepage.html
```

Default template matches littleheli-style layout. If the user supplies another reference, adapt colors/structure in a copy of the template for that run only; do not overwrite the skill asset unless they ask to update the skill.

### 5. Deliver

Copy the HTML to the path the user wants (Desktop, Documents, OneDrive, etc.). Open it once to verify. Tell them:

- This is a **static snapshot**; refreshing Top N needs a new export.
- How to set it as homepage in their browser (settings UI), without automating policy changes.

## Stop conditions

- Required Bookmarks file not found after checking documented paths → report paths tried; stop.
- User asks for Firefox-only or a browser extension → out of scope; say so and stop.
- User asks to push private bookmark dumps to a public GitHub repo → refuse; only publish the skill/template with sample data.

## Scripts and references

| Path | When |
| --- | --- |
| `references/chromium-paths.md` | Locating Bookmarks / History |
| `references/host-filters.md` | Filtering auth / junk hosts |
| `scripts/export_chromium_nav.py` | Parse + aggregate |
| `scripts/build_homepage.py` | Inject data into template |
| `assets/homepage-template.html` | Default UI shell (`__TITLE__`, `__DATA_JSON__`, `__VISITS_JSON__`, `__ICONS_JSON__`, `__STATS_LINE__`) |
