---
name: browser-bookmark-homepage
description: >-
  When the user wants a personal start/nav homepage built from Chromium or Comet
  bookmarks, or an auto Top-N frequent-sites section from browser History visit
  counts. Also when they want to hide/remove site cards on that homepage,
  restore hidden cards, or auto-refresh the frequent section from History. Not
  for Firefox-only workflows, writing browser extensions, or deploying
  self-hosted OneNav.
---
# Browser bookmark homepage

Build a self-contained HTML navigation homepage from Chromium-family browser data (Chrome, Edge, Brave, Perplexity Comet, and similar). Default visual style follows littleheli / OneNav (aside categories, gradient search banner, favicon cards). The user may name another public reference site; if that site needs a logged-in app or heavy server UI, fall back to the default card grid.

User-facing UI strings and the docs in `references/delete-and-auto-update.md` are Chinese by default.

## Invariants

1. Prefer local, static HTML the user can open with `file://` or set as the browser homepage. A tiny optional `127.0.0.1` helper server makes frequent-section auto-refresh and hidden-list file sync smoother, but `file://` + a watcher that patches the HTML must still work.
2. Aggregate History by **registrable-ish host** (strip leading `www.`), not by raw URL. Prefer a clean bookmark URL for that host when one exists.
3. Filter authentication noise: skip login / OAuth / SSO path patterns listed in `references/host-filters.md`.
4. Never bake the user's real bookmarks, History, names, or company URLs into this skill's `assets/` or published repos. Use only synthetic sample data in tests.
5. Do not change browser policies, registry, or enterprise homepage settings unless the user explicitly asks; otherwise deliver the file and tell them how to set it.
6. Card "deletion" is homepage-only hide. Never delete or edit the browser's Bookmarks or History files. Persist hides in `localStorage` and in a sibling `hidden.json` denylist so a later frequent rebuild cannot bring the same item back. Always provide a restore UI.

## When to ask

Ask only if you cannot decide from context:

- Which browser / profile (Comet vs Chrome vs Edge; Default vs another Profile).
- Output path and page title language.
- Top N (default **20**) and whether to include a frequent section when History is missing.
- Alternate reference site URL (optional).

If the user wants automatic frequent-section updates, do not ask them to approve a new export every 15 minutes. Prefer a local watcher or Windows scheduled task (see below). Check whether Python 3 exists on their machine first.

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
  --top 20 \
  --hidden /path/to/hidden.json
```

`--hidden` is optional. When present, hidden hosts/URLs are skipped while filling Top N so the next site can take the empty slot.

Outputs:

- `bookmarks.json` — categories → `[{name,url,host}, …]`
- `frequent.json` — Top N hosts with `visit_count` and preferred `url` (denylist applied)
- `frequent_candidates.json` — a larger pool (default 80) so the page can refill Top N after local hides
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
  --candidates /workspace/nav-export/frequent_candidates.json \
  --hidden /path/to/hidden.json \
  --template assets/homepage-template.html \
  --title "我的导航" \
  --out /workspace/bookmark-homepage.html
```

Default template matches littleheli-style layout and includes card hide/restore plus frequent-section refresh hooks. If the user supplies another reference, adapt colors/structure in a copy of the template for that run only; do not overwrite the skill asset unless they ask to update the skill.

The builder also writes `frequent-data.js` next to the HTML.

### 5. Deliver

Copy the HTML (and, when present, `frequent-data.js` / `hidden.json`) to the path the user wants (Desktop, Documents, OneDrive, etc.). Open it once to verify. Tell them:

- Cards can be removed from the homepage with × (or 「编辑主页」). This does **not** delete browser bookmarks. Use 「已删除」 to restore. Accidental hides can be undone from the toast.
- The frequent section can refresh automatically; see `references/delete-and-auto-update.md`.
- How to set the file as homepage in their browser (settings UI), without automating policy changes.

### 6. Auto-update the frequent section

A static `file://` page cannot read History itself (`fetch()` of local files is blocked). Use the updater:

```bash
python3 scripts/update_frequent.py \
  --homepage /path/to/bookmark-homepage.html \
  --browser comet \
  --profile Default \
  --watch --interval 15 \
  --serve
```

- Default interval is **15 minutes**. History is copied before querying.
- The updater patches the `<!--NAV_FREQUENT_START-->` block in place and rewrites `frequent-data.js`. Multiple `--homepage` values (or a `homepage` list in config) can be patched together.
- `--serve` starts a localhost-only server (default `http://127.0.0.1:8765/`) exposing `/api/frequent` and `/api/hidden`. This is the smoother mode: an open tab can refresh the frequent block in place, and hides are written back to `hidden.json`. Bind only `127.0.0.1` and do not serve unrelated files.
- `file://` + watcher still works without the server: the page tries the local API, then reloads `frequent-data.js` on window focus and on a 15-minute timer. It skips refresh while the edit mode or restore dialog is open. If a cached `file://` tab cannot see the sidecar, reopening the HTML is enough.
- Windows: copy `scripts/` to a tools folder next to the homepage, fill in `updater-config.json` from `updater-config.example.json`, then use `watch_frequent.bat` or `install_scheduled_task.bat` (login-time task `BookmarkHomepageFrequentUpdate`). Confirm Python 3 is installed (`python --version`). If Python is missing, say so clearly and fall back to an agent-run update on the user's machine (may need approval) instead of failing silently.

Read `references/delete-and-auto-update.md` for the user-facing explanation.

## Stop conditions

- Required Bookmarks file not found after checking documented paths → report paths tried; stop.
- User asks for Firefox-only or a browser extension → out of scope; say so and stop.
- User asks to push private bookmark dumps to a public GitHub repo → refuse; only publish the skill/template with sample data.

## Scripts and references

| Path | When |
| --- | --- |
| `references/chromium-paths.md` | Locating Bookmarks / History |
| `references/host-filters.md` | Filtering auth / junk hosts |
| `references/delete-and-auto-update.md` | Hide/restore cards and frequent auto-update (user-facing, Chinese) |
| `scripts/export_chromium_nav.py` | Parse + aggregate |
| `scripts/build_homepage.py` | Inject data into template |
| `scripts/hidden_store.py` | Homepage-only denylist load / merge |
| `scripts/update_frequent.py` | Patch frequent section; `--watch` / `--serve` / `--install-task` |
| `scripts/watch_frequent.bat` | Windows helper to run the watcher + local server |
| `scripts/install_scheduled_task.bat` | Windows logon scheduled task |
| `scripts/updater-config.example.json` | Config template |
| `assets/homepage-template.html` | Default UI shell (`__TITLE__`, `__DATA_JSON__`, `__VISITS_JSON__`, `__ICONS_JSON__`, `__STATS_LINE__`, `__FREQUENT_LABEL__`, `__FREQUENT_TIP__`, `__FREQUENT_SNAPSHOT_JSON__`, `__HIDDEN_SEED_JSON__`, `__API_PORT__`, `__DISPLAY_TOP__`) |
