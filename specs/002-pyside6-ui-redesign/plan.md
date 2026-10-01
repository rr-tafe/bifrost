# Plan: PySide6 UI Redesign

**Created**: 2026-10-01 | **Status**: Steps 1–2 done; step 3 next
**Requirements baseline**: [001 spec.md](../001-sql-permissions-manager/spec.md) (user stories, FRs and success criteria still apply except where this plan says otherwise)
**Mockups**: https://claude.ai/artifact/9oe2fFwTwa5kzJ9AeGzZyL (private; share from the page if others need it)
**Rollback point**: commit `2c8b54d` (working tree snapshot before the redesign)

## Why

At work, Bifrost will run against a SQL Server database with hundreds of principals and
thousands of objects. The current Tkinter matrix does not hold up at that size:

- It opens empty. You must pick at most 10 users and 10 objects in a modal before anything shows.
- Every object takes 8 columns, so 10 objects is 80 narrow cells with rotated headers.
- Two pagers (users, objects) appear twice each, above and below the grid.
- Each click changes one cell. There is no bulk edit.
- `_redraw_visible` walks every column for every visible row, and `get_assignment` creates a
  new object for every empty cell, so scrolling slows down as the object count grows.

## Decisions (made 2026-10-01)

| Decision | Choice |
|---|---|
| Main matrix layout | **Split view** (mockup option A): a searchable principal list on the left; on the right, the selected principal's objects grouped by schema, with the 8 permissions as fixed columns. A toggle flips it to "by object" (pick an object, see every principal). |
| Secondary views | **Compare mode** (option B): heatmap of principals × objects, one permission at a time, drag-select ranges, limited to the current filter. **Grants tab** (option C): filterable list of explicit GRANT/DENY rows plus a quick-add bar. |
| UI toolkit | **PySide6** (Qt 6), replacing Tkinter. `db/`, `models/` and `services/` stay; `src/ui/` (Tk) is replaced by a new `src/qt/` package. |
| Typical workflow | A mix of per-principal requests, per-object requests and audits, so all three views are worth building. |

### Changes to the 001 requirements

- **FR-001** (three view modes with dropdown selectors) is replaced by the split view (both
  directions) and Compare mode.
- **FR-028** (Compare-view pagination and pinning) is dropped. Scrolling plus search and filters
  replace pagination. Pinning may come back as "favourites" in the principal list (step 3, optional).
- **FR-003** (cross-query highlight) is replaced by the "Only with access" filter in the split view
  and by Compare mode, which shows the same pattern directly.
- Every other FR still applies, in particular FR-002/002a (staging), FR-017a (privilege check),
  FR-024/025 (accessibility), FR-026 (commit preview), FR-029 (undo/redo), FR-030 (confirm
  ≥5-cell bulk changes) and FR-031 (range selection, max 1,000 cells).

## Scale targets (used by every step)

Reference dataset: **1,000 principals × 20,000 objects × 200,000 explicit permissions**
(about 5× the expected work database, as headroom).

| Measure | Target |
|---|---|
| Window visible after launch | ≤ 0.5 s, before any DB work |
| Full load (DB fetch + index build) | ≤ 5 s on the reference dataset over LAN; UI stays responsive throughout |
| Search / filter keystroke → updated list | ≤ 50 ms |
| Scroll frame | ≤ 16 ms (60 fps) |
| Stage 1,000 cells in one bulk action | ≤ 100 ms including repaint |
| Memory for the loaded matrix | ≤ 200 MB RSS for the whole app |

## Steps

Each step ends with the app in a working state and its tests passing.

### Step 1 — Data layer and speed
Spec: [spec-01-data-layer.md](spec-01-data-layer.md)

- Integer-indexed permission store with each (principal, object) row packed into one int
  (8 grant bits + 8 deny bits). No object created per cell lookup.
- Load split into a DB-only fetch (safe to run on a worker thread) and an in-memory index build.
- Indexes for search, filters, tags, per-row counts and schema grouping.
- Bulk staging with grouped undo, and change events that name the rows that changed.
- Commit split into prepare (UI thread), execute (worker) and apply results (UI thread).
- Fixes: staged changes lost on refresh, tags never applied to filters, unescaped identifiers
  in T-SQL, one privilege-check round trip per cell.
- Large synthetic dataset for dev and perf tests.

### Step 2 — PySide6 app shell
Spec: [spec-02-app-shell.md](spec-02-app-shell.md)

- New `src/qt/` package: main window, menus, shortcuts, tab bar, theme (light/dark).
- `Session` controller (UI-free) that owns the config, connection, matrix and tag store.
- One serial DB worker thread. The UI thread never touches pyodbc.
- Status bar with the pending-changes tray, Undo, Discard, Review and Commit.
- Ported dialogs: Settings, Tag manager, Commit preview, Commit results, Connection lost.
- Audit log view ported to Qt.
- The Matrix tab shows a load summary placeholder until step 3.
- The Tk app stays runnable with `python main.py --legacy-tk` until step 6.

### Step 3 — Split view (main matrix screen)
Spec: [spec-03-split-view.md](spec-03-split-view.md)

- Principal list (`QListView` + proxy model): search, type chips (Users / Groups / SQL users),
  tag chips, "Has pending", counts per principal, pending dot.
- Object grid (`QTreeView` or `QTableView` + custom delegate): schema groups with counts,
  8 fixed permission columns, hatched cells for permissions that don't apply, ✓/✕/· glyphs,
  staged outline and dot.
- "By principal ↔ By object" toggle keeps the selection and scroll position.
- Filter chips: schema, object type, tag, "All objects / Only with access", "Only pending".
- Editing: click to cycle; keys G grant, D deny, R/Delete revoke, Space cycle; Shift+arrows and
  drag to select; actions apply to the whole selection; confirm at ≥5 cells (FR-030).
- Bulk actions: row/column header selection; context menu "Set selection to…",
  "Make like <principal>…" (copy from another principal), and per-schema "Grant <perm> on all".
- Ctrl+K jump box searching principals, objects and tags.
- Pending tray "reveal" jumps to the cell.

### Step 4 — Grants tab
- `QTableView` over the explicit GRANT/DENY rows plus staged rows.
- Facets with counts: schema, permission, state, principal type, tag.
- Quick-add bar: action × permissions × objects × principals, staged in one undo group.
- Revoke from a row; multi-select revoke.
- Export of the current filtered list.

### Step 5 — Compare mode
- Heatmap grid of principals × objects for one permission, plus a Summary mode
  (strongest permission per cell).
- Limited to the current filter. Shows a "narrow your filter" prompt above a cell budget
  (default 250,000 visible-range cells).
- Drag-select ranges with a popover offering Grant / Deny / Revoke for the range.
- Angled object headers, frozen principal column, schema bands.

### Step 6 — Cleanup and verification
- Delete `src/ui/` (Tk) and its tests; remove `--legacy-tk`.
- Update README, `quickstart.md` and `data-model.md`; move superseded 001 sections to the archive.
- Packaging notes for Windows (PySide6 wheel, ODBC driver).
- Run the full scale validation against `dev/seed_large.sql` (500 × 5,000) and record results.
- Keyboard-only and screen-reader pass (NVDA) against FR-021/024/025.

## Status

| Step | Status | Notes |
|---|---|---|
| 1 Data layer and speed | Done (2026-10-01) | Branch `002-step1-data-layer`. Tk click-through still to do. Results in spec |
| 2 App shell | Done (2026-10-01) | Branch `002-step2-app-shell`. Desktop checks (dark mode, connection loss, quit) and accessibility checks on the work machine still to do. Results in spec |
| 3 Split view | Spec drafted (2026-10-01) | 4 open questions in spec section 19; branch `002-step3-split-view` |
| 4 Grants tab | Not started | |
| 5 Compare mode | Not started | |
| 6 Cleanup | Not started | |

## Open questions

1. **Python version on the work machine.** Resolved 2026-10-01: Python 3.14, same as the dev
   venv.
2. **Installing PySide6 at work.** Resolved 2026-10-01: PySide6 is a plain `pip install` from
   PyPI (no installer or MSI). `PySide6-Essentials` 6.11.2 (`cp310-abi3-win_amd64`) installed
   and ran a test window on the work machine with Python 3.14. It bundles the Qt and Visual C++
   runtime DLLs; about 78 MB download, 210 MB installed.
3. **Escape key and discarding.** Resolved 2026-10-01: only the status bar Discard button
   discards staged changes. No keyboard shortcut, no menu item; Escape never discards.
