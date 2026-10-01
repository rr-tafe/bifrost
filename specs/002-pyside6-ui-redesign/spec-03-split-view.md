# Spec — Step 3: Split View (Main Matrix Screen)

**Plan**: [plan.md](plan.md) | **Created**: 2026-10-01 | **Status**: Ready to implement (decisions in section 19)
**Depends on**: [step 1](spec-01-data-layer.md), [step 2](spec-02-app-shell.md) | **Blocks**: steps 4–6
**Mockups**: https://claude.ai/artifact/9oe2fFwTwa5kzJ9AeGzZyL (option A)

## 1. Goal

Replace the Matrix tab placeholder with the split view chosen on 2026-10-01: a searchable list
on the left, and on the right a grid of the selected entity's permissions with the 8 permissions
as fixed columns. It must make the common jobs fast at work-database scale:

- "What can CORP\jsmith do?" and "Give the new analyst read access to the sales schema."
- "Who can touch sales.Orders?" and "Remove DELETE on this table from everyone but the ETL
  accounts."

When this step is done, the Qt app replaces the Tk app for day-to-day work. `--legacy-tk` stays
until step 6 in case something is missing.

## 2. Scope

**In scope**

- `MatrixView` with two modes, **By principal** and **By object**, sharing one layout.
- Left list: search, filter chips, sort, counts and pending markers.
- Right grid: grouped rows, 8 permission columns, cell rendering, selection, keyboard and mouse
  editing, context menu, bulk actions, presets, "Make like…".
- Confirmation for bulk changes (FR-030) and the FR-017a privilege check at staging time.
- Object descriptions (FR-023) in the object header, including the fix for views, procedures
  and functions.
- Ctrl+K jump box.
- Pending tray "reveal" (jump to the staged cell).
- Removing the dev "stage sample changes" action and the summary placeholder.
- View state remembered between launches.

**Out of scope**

- Grants tab (step 4) and Compare mode (step 5). A disabled **Compare** button shows where
  Compare mode will go.
- Effective permissions through Windows group membership.
- Column-level permissions.
- Deleting the Tk app (step 6).

## 3. Requirements this step meets or changes

| Requirement | How |
|---|---|
| FR-001 (perspective modes) | Replaced by By principal / By object, per [plan.md](plan.md) |
| FR-001a (only applicable permissions) | Cells that don't apply are hatched, skipped by keyboard focus, never staged. In By object mode, columns that don't apply to the object are hidden. |
| FR-002, FR-002a (staging, visible pending) | Staged cells have an outline and a dot; commit/discard as in step 2 |
| FR-009/010/011 (search, filter, sort) | Left list and grid header filters (sections 6, 7) |
| FR-017a (no granting what you don't hold) | Checked when staging, before the cell changes (section 9.6) |
| FR-020 (permission icons) | Column headers show short names (SEL, INS…) with the full name in the tooltip and accessible name. No pictograms: abbreviations scan faster and need no legend. **Deviation; see open question 4.** |
| FR-021, FR-024, FR-025 (keyboard, non-colour states, accessibility) | Sections 9, 12 |
| FR-023 (object descriptions) | Object header in By object mode (section 8.3) |
| FR-027 (press-and-hold preview) | Replaced by a hover tooltip that names the next state and the keys. Click selects and never changes a cell (section 9.1). |
| FR-029 (undo) | Every action is one undo step (from step 1) |
| FR-030 (confirm ≥ 5 cells) | Section 9.5 |
| FR-031 (range selection) | Shift/drag/Ctrl selection; limit raised from 1,000 to 20,000 cells (section 9.4; open question 2) |

## 4. Layout

```
┌ Matrix tab ──────────────────────────────────────────────────────────────────────────────────┐
│ [ By principal | By object ]  [Compare (soon)]                                               │
├──────────────────────────────┬───────────────────────────────────────────────────────────────┤
│ 🔍 Search 412 principals…    │ CORP\jsmith   Windows user   finance  reporting               │
│ [Users][Groups][SQL users]   │ 38 grants · 2 denies · 3 pending                              │
│ [Has pending] [Tags ▾]       │ 🔍 Filter objects…  [Schema ▾] [Type ▾] [Tags ▾]               │
│ Sort: Name ▾                 │ ( All objects | Only with access | Only pending )   [Make like…]│
│──────────────────────────────│───────────────────────────────────────────────────────────────│
│ G  CORP\finance-analysts 124 │ Object                     SEL INS UPD DEL EXE ALT REF VDEF    │
│ U  CORP\jdoe              12 │ ▾ sales   86 objects · 9 with access                          │
│▌U  CORP\jsmith         ●  40 │   T  sales.Customers        ✓   ✓   ·   ·  ░░   ·   ·   ✓      │
│ U  CORP\kpatel             9 │   T  sales.Orders          [✓]  ✓   ✓  [·] ░░   ·   ·   ✓      │
│ …                            │   V  sales.vw_DailyRevenue  ✓  ░░  ░░  ░░  ░░   ·  ░░   ✓      │
│                              │   P  sales.usp_CloseMonth  ░░  ░░  ░░  ░░   ✓   ·  ░░   ·      │
│                              │ ▸ dbo     1,204 objects · 21 with access                      │
│ 412 principals               │ ▸ finance   977 objects · 8 with access                       │
└──────────────────────────────┴───────────────────────────────────────────────────────────────┘
  ✓ GRANT  ✕ DENY  · none  ░░ doesn't apply  [ ] staged (outline + corner dot)
```

- A `QSplitter` divides the two panes; the left pane starts at 300 px, min 220 px. Sizes are
  remembered.
- Mode switch: segmented buttons **By principal** / **By object**. **Compare** is shown
  disabled with the tooltip "Compare mode arrives in a later update".
- In **By object** mode the panes swap content: left lists objects grouped by schema, right
  grid lists principals grouped by type (Windows groups, Windows users, SQL users) with only the
  permissions that apply to the selected object as columns.
- The Matrix tab shows the step 2 placeholder pages for every state except `READY`,
  `COMMITTING` and `OFFLINE`. In those three states it shows `MatrixView`. In `COMMITTING` and
  `OFFLINE` the grid is read-only and a banner says why ("Committing… editing resumes when it
  finishes" / "Offline. Reconnect to make changes."). The loaded-data summary moves to
  **Help → Database summary**.

## 5. Package layout

```
src/qt/views/matrix/
├── __init__.py
├── matrix_view.py        # MatrixView: mode switch, splitter, wiring, state persistence
├── entity_list.py        # EntityListPane + PrincipalListModel / ObjectListModel + delegate
├── grid.py               # PermissionGrid (QTreeView subclass): keys, mouse, context menu
├── grid_model.py         # GridModel base + PrincipalGridModel / ObjectGridModel
├── cell_delegate.py      # Paints cells, group headers and the name column
├── grid_header.py        # Entity header: title, chips, counts, filters, description
├── chips.py              # ChipButton, ChipGroup, MultiSelectChip (dropdown with checkboxes)
├── bulk.py               # Presets, "Make like…", bulk-change summaries for confirmation
├── jump_dialog.py        # Ctrl+K jump box
└── view_state.py         # Saved filters/mode/selection (QSettings)
src/qt/dialogs/
└── confirm_bulk.py       # FR-030 confirmation
```

Rules from step 2 still apply: views call `Session`, never `src.db`; no QObject in worker jobs.

## 6. Left pane: entity list

### 6.1 Principals (By principal mode)

| Element | Behavior |
|---|---|
| Search | `SearchField` ("Search 412 principals…"). Debounced 150 ms. Matches `PrincipalQuery.text` (whitespace tokens, AND, case-insensitive). |
| Type chips | **Users** (U), **Groups** (G), **SQL users** (S). None selected = all. Multi-select. |
| Has pending | Toggle chip → `PrincipalQuery.has_pending` |
| Tags ▾ | Multi-select dropdown of all tags with counts; principal must have all selected (AND). |
| Sort ▾ | Name (default), Type, Most grants |
| Rows | `QListView` with `setUniformItemSizes(True)` over `PrincipalListModel`. Row = type badge (U/G/S, with tooltip "Windows user"), login (elided in the middle so the domain and the end of the name stay visible), pending dot when `pending > 0`, effective grant count right-aligned. Tooltip: full name, type, tags, "38 grants · 2 denies · 3 pending". |
| Footer | "412 principals" or "12 of 412 principals" when filtered. |
| Empty | "No principals match. [Clear filters]" |

The list keeps its selection across filtering when the selected principal still matches;
otherwise the first row is selected.

### 6.2 Objects (By object mode)

Same pane with:

- Search over `schema.name`.
- Chips: **Tables**, **Views**, **Procedures**, **Functions**; **Has pending** (objects with any
  pending cell); **Tags ▾**; **Schema ▾** (multi-select).
- Rows grouped by schema with a non-selectable header row per schema ("sales · 86"). Headers
  collapse with a click or Left/Right arrow.
- Row = type badge (T/V/P/F), name without schema (the header shows it), pending dot, count of
  principals with access.

### 6.3 Models

`PrincipalListModel(QAbstractListModel)` holds `list[int]` from `index.query_principals(...)`.
`ObjectListModel` holds a flat list of entries `("header", schema, start, end)` or
`("object", o)` built from `query_objects` + `group_by_schema`, minus collapsed groups.

- `data()` returns display text, tooltip, and custom roles `IndexRole` (p or o),
  `PendingRole`, `CountRole`, `TypeRole`.
- On `MatrixChange` the models update in place: only rows for affected p/o get `dataChanged`
  (counts, pending dot). If the change affects filter membership (`has_pending` on), refilter
  with the 150 ms debounce.
- On `reason="reload"` or `"tags"`: rebuild the query and keep the selection by login or
  `schema.name`.

## 7. Right pane: grid

### 7.1 Header (`grid_header.py`)

**By principal:**

- Title: login (selectable text), type chip, tag chips (click a tag = add it to the left list's
  tag filter), counts "38 grants · 2 denies · 3 pending" (from `principal_counts`).
- Filters: object search, **Schema ▾**, **Type ▾**, **Tags ▾**, and a segmented
  **All objects / Only with access / Only pending**.
- **Make like…** button (section 9.8).

**By object:**

- Title: `schema.name`, type chip, tags, "Granted to 14 principals · 1 deny · 2 pending".
- Description (FR-023): read-only text (max 3 lines, "More" expands), **Edit description…**
  opens a small dialog. Saving runs `save_object_description` on the DB worker. "No
  description" placeholder when empty. Loaded on demand when the object is selected
  (`load_object_description`, worker job, coalesced), cached per object for the session.
- Filters: principal search, type chips (Users / Groups / SQL users), **Tags ▾**,
  **All principals / Only with access / Only pending**.

Filter choices are remembered per mode (section 13). The default segment is **All objects**
(decision 3), so new access can be granted without changing filters first; the schema groups
keep thousands of rows navigable. When **Only with access** gives no rows, the grid shows
"CORP\nwong has no explicit permissions. [Show all objects]".

### 7.2 Rows and columns

`PermissionGrid` is a `QTreeView` over a two-level `GridModel`:

- **Top level**: group rows. By principal → one per schema (`group_by_schema`). By object → up to
  three groups by principal type: Windows groups, Windows users, SQL users. Groups with no
  visible rows are omitted. A group row spans all columns (`setFirstColumnSpanned`) and reads
  "▾ sales  86 objects · 9 with access · 2 pending".
- **Second level**: one row per object (By principal) or principal (By object).
- **Column 0**: name with type badge. By principal: `schema.name` is shown as just the name
  (the group shows the schema); tooltip shows the full name and description if cached.
- **Columns 1–8**: SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW
  DEFINITION, in `PERMS` order. Headers show SEL, INS, UPD, DEL, EXEC, ALTER, REF, VDEF; full name
  in tooltip and accessible name. Fixed width (fits the widest of 52 px or the header text).
- By object mode hides permission columns that don't apply to the selected object
  (`setColumnHidden`), so a procedure shows only EXEC, ALTER, VDEF.
- `uniformRowHeights=True`, compact rows (font height + 8 px), alternating row colours off
  (cells carry the colour).
- All groups expanded by default; collapse state remembered per mode for the session.

### 7.3 Cell rendering (`cell_delegate.py`)

| State | Fill | Glyph | Extra |
|---|---|---|---|
| GRANT | `grant_bg` | ✓ in `grant` | |
| DENY | `deny_bg` | ✕ in `deny` | |
| none | surface | · in `muted` | |
| Doesn't apply | diagonal hatch (`na` / surface) | none | Not focusable, never selected |
| Staged (any state above) | as state | as state | 2 px `staged` inset outline + 6 px dot top-right |
| Selected | as state | as state | 2 px `accent` outline (drawn over staged outline, inset 3 px) |
| Focused (keyboard) | as state | as state | dashed `fg` outline 1 px |
| Read-only (offline/committing) | as state, 60% opacity | | |

- Painting reads `row_state(p, o)` once per row per paint pass (the model caches the packed
  int per visible row during `data()` calls for that row), then `cell_code`.
- Colours, pens, brushes and the hatch brush are created once per theme (`apply_theme`), never
  per paint.
- Glyph font is the UI font in bold at the same size; glyphs are text, so screen-reader text
  is separate (section 12).

### 7.4 Model (`grid_model.py`)

```python
class GridModel(QAbstractItemModel):
    # Built from Session + current entity + filters
    def set_entity(self, entity: int | None) -> None      # p (By principal) or o (By object)
    def set_filters(self, filters: GridFilters) -> None
    def cell_at(self, index: QModelIndex) -> CellRef | None
    def index_for_cell(self, cell: CellRef) -> QModelIndex   # for reveal and mode switch
    def on_matrix_change(self, change: MatrixChange) -> None
```

- Internal structure: `groups: list[Group]` where `Group = (label, key, rows: list[int])`;
  `rows` are o (By principal) or p (By object). A reverse map `row_of: dict[int, (g, r)]` gives
  the position of any visible o/p in O(1).
- `index(row, col, parent)`: parent invalid → group; parent = group → item. `internalId` =
  group number + 1 for items, 0 for groups.
- Custom roles: `StateRole` (effective code), `CommittedRole`, `PendingRole` (bool),
  `ApplicableRole` (bool), `CellRole` (CellRef), plus `AccessibleTextRole` and `ToolTipRole`.
- `flags()`: name column selectable only; applicable cells `ItemIsSelectable | ItemIsEnabled`;
  non-applicable cells `ItemIsEnabled` only (not selectable). Group rows are enabled, not
  selectable.
- `on_matrix_change`: if `rows` is given, map each (p, o) in this grid's entity to a model row
  and emit one `dataChanged` per contiguous run; group header counts update with one
  `dataChanged` per touched group. `rows=None` (reload/tags) → rebuild, keeping entity,
  scroll position and current cell by natural key.
- If a change affects which rows pass the filter ("Only pending", "Only with access"), the row
  stays visible until the user changes filters or entity, so cells never jump away while being
  edited. A small "Filter out of date — Refresh list" link appears in the header.

## 8. Entity header details

### 8.1 Counts

Counts come from `index.principal_counts(p)` / `object_counts(o)` and update on every
`MatrixChange` for that entity (O(1)).

### 8.2 Tags

Tag chips are read-only here; editing stays in the Tag manager. A **Tags…** link next to the
chips opens the Tag manager with this entity's tag selected.

### 8.3 Object descriptions (FR-023)

- `src/db/objects.py`: fix `save_object_description` to pass the right `@level1type` for the
  object's type (TABLE, VIEW, PROCEDURE, FUNCTION) instead of always `TABLE`. Add the object type
  as a parameter; callers pass `obj.object_type`. Regression test with a mock cursor for each
  type.
- Validate with `validation.validate_description` (max 7,500 characters).
- Session gains `load_description(schema, name, callback)` and
  `save_description(obj, text, callback)` (worker jobs; save commits immediately and is not
  part of staged permission changes). The UI states this clearly: "Descriptions save
  immediately. They aren't staged or audited."

## 9. Editing

### 9.1 Mouse

| Action | Result |
|---|---|
| Click a cell | Select it (focus moves to it). Never changes state. |
| Double-click a cell | Cycle it: none → GRANT → DENY → none |
| Click-drag | Select a rectangle of applicable cells |
| Shift-click / Ctrl-click | Extend / toggle selection (Cmd on macOS) |
| Click a permission column header | Select that column for all visible rows (applicable cells) |
| Click a row's name cell | Select that row's applicable cells |
| Click a group row | Collapse/expand. Shift-click selects every applicable cell in the group. |
| Right-click | Context menu for the selection (or the cell under the pointer if outside it) |
| Hover a cell | Tooltip: "SELECT on sales.Orders for CORP\jsmith — GRANT (staged; was none). Double-click or Space: change to DENY. G grant · D deny · R revoke." |

### 9.2 Keyboard (grid focused)

| Key | Action |
|---|---|
| Arrows | Move focus between applicable cells (skip hatched cells and group rows) |
| Shift+Arrows | Extend selection |
| Home / End | First / last applicable cell in the row |
| Ctrl+Home / Ctrl+End | First / last row |
| Page Up / Page Down | Move by a screen |
| Ctrl+A | Select all applicable cells in visible rows |
| Space | One cell selected: cycle it (none → GRANT → DENY → none). Several cells selected: open the context menu, so the result is always explicit. |
| G | Set selection to GRANT |
| D | Set selection to DENY |
| R or Delete or Backspace | Set selection to none (REVOKE) |
| U | Revert selection to committed (undo staged changes on just these cells) |
| Enter on a group row | Collapse/expand |
| Menu key / Shift+F10 | Context menu |
| Escape | Clear selection (never discards anything) |
| F6 / Shift+F6 | Move focus: left list → grid header filters → grid → pending tray |
| Ctrl+F | Focus the left list's search; Ctrl+Shift+F focuses the grid's filter |

Keys act only when `session.can_edit`; otherwise the status bar says "Offline. Reconnect to
make changes." (or "Committing…") and nothing changes.

Left list keys: Up/Down move and immediately show that entity in the grid (debounced 50 ms so
holding the arrow key doesn't rebuild the grid on every row); Enter or Right moves focus to the
grid; typing a printable character moves focus to the search box and types it.

### 9.3 Context menu

On a selection of N applicable cells:

```
Grant (G)                           — "Grant SELECT on 12 objects"
Deny (D)
Revoke (R)
Revert to committed (U)             — only if any selected cell is staged
─────────────
Apply preset ▸   Read · Read/write · Execute · Full DML · View definition only
─────────────
Select row · Select column · Select group
Copy                                — tab-separated: name, then states
```

On a group row: **Grant ▸ / Deny ▸ / Revoke ▸ <permission> on all <n> objects in sales**
(applicable rows only, respecting the current filter), **Collapse/Expand**, **Select group**.

On the left list (By principal): **Make like…**, **Show only this principal's pending
changes**, **Tags…**.

### 9.4 Selection

- Selection is per cell (`SelectItems`, `ExtendedSelection`). Non-applicable cells and group
  rows can't be selected.
- Limit: 20,000 cells per action (step 1 stages 20,000 cells in 26 ms). Above that, actions are
  disabled and the status bar says "Select at most 20,000 cells, or use a group action".
  FR-031's 1,000-cell limit was a Tk performance limit (open question 2).
- Selection clears on mode change, entity change, commit, discard and Escape (FR-031).
- Status bar shows "12 cells selected" while more than one cell is selected.

### 9.5 Confirmation (FR-030)

Any action that would change **5 or more cells** shows `ConfirmBulkDialog` first:

```
┌ Stage 247 changes? ────────────────────────────────────────────┐
│ Grant SELECT on 247 objects in sales for CORP\jsmith.          │
│                                                                │
│ 231 will change · 16 already GRANT · 3 don't apply (skipped)   │
│ You can undo this with Ctrl+Z before committing.               │
│                                                                │
│ ☐ Don't ask again until Bifrost restarts                       │
│                                [ Cancel ]  [ Stage 231 changes ]│
└────────────────────────────────────────────────────────────────┘
```

- The summary is computed without staging: changed / unchanged / not applicable counts, plus
  a one-line scope from `bulk.describe_scope(cells, state)` ("on 247 objects in sales for
  CORP\jsmith", "for 38 principals on sales.Orders", "on 12 cells").
- Counts only cells that would actually change; "5 or more" means 5 or more **changes**.
- The checkbox (open question 1) suppresses the dialog for the rest of the session. Staging is
  undoable and nothing reaches the database until Commit, which still has its own preview.
- Default button is Cancel. Escape cancels.

### 9.6 Privilege check at staging (FR-017a)

When an action would set any cell to GRANT:

1. If `matrix.privileged`, skip the check.
2. Cells whose privilege is cached (`known_grant_privilege`) are sorted into allowed/denied.
3. Unknown ones are checked in one `check_grant_privileges` worker job (Session method
   `check_then_stage(cells, state, label)`); the grid shows a busy cursor and ignores further
   edits until the answer arrives (typically < 100 ms).
4. Allowed cells are staged as one undo step. If any were denied: message "You can't grant
   SELECT on 3 objects because you don't hold those permissions yourself. Contact a database
   owner or sysadmin." with **Details** listing them. Denied cells are not staged.
5. The commit-time check from step 2 stays as a safety net.

The Tk app's behavior (silently cycling to DENY when GRANT isn't allowed) is not carried over;
the user is told and nothing is changed for those cells.

### 9.7 Presets (`bulk.py`)

```python
PRESETS = {
    "Read":                 {"TABLE": {SELECT}, "VIEW": {SELECT}, "FUNCTION": {EXECUTE}, "PROCEDURE": set()},
    "Read/write":           {"TABLE": {SELECT, INSERT, UPDATE, DELETE}, "VIEW": {SELECT, INSERT, UPDATE, DELETE}, ...},
    "Execute":              {"PROCEDURE": {EXECUTE}, "FUNCTION": {EXECUTE}},
    "Full DML":             {... SELECT, INSERT, UPDATE, DELETE, REFERENCES ...},
    "View definition only": {all types: {VIEW_DEFINITION}},
}
```

Applying a preset to selected **rows** (the rows of any selected cell) sets the preset's
permissions to GRANT and leaves other permissions alone. It never sets DENY or revokes. Presets
are a fixed list in this step; editing them is out of scope.

### 9.8 Make like… (By principal mode)

"Make CORP\newanalyst have the same permissions as CORP\jsmith":

1. Picker (searchable list of principals, excluding the current one).
2. Scope: **All objects** or **Only objects shown by the current filter** (default: current
   filter if any filter is active, else all).
3. For every object in scope, set each applicable cell of the target to the source's
   **effective** state (GRANT, DENY or none). This can revoke and deny, so the confirmation
   shows the split: "52 grants, 1 deny, 4 revokes".
4. One undo step.

Needs a new matrix API (step 1 code):

```python
def stage_states(self, items: Iterable[tuple[CellRef, PermissionState]], label: str | None = None) -> StageResult
```

Mixed target states in one call and one undo group. `stage()` becomes a thin wrapper over
it. Tests: mixed states, undo restores all, one `MatrixChange`.

## 10. Mode switch, reveal and jump

### 10.1 Switching modes

- By principal → By object: the focused cell's object becomes the left selection; the grid
  focuses the same principal row and permission column.
- By object → By principal: the reverse.
- If the target row is hidden by the other mode's filters, those filters stay as they are and
  the grid shows the "not shown by the current filter — [Show it]" link; **Show it** clears the
  filters that hide it.
- Shortcuts: **Ctrl+Shift+1** By principal, **Ctrl+Shift+2** By object (added to the action
  registry, View menu).

### 10.2 Reveal (pending tray double-click / Enter)

1. Switch to the Matrix tab and By principal mode.
2. Select the principal in the left list, clearing left-list filters only if they hide it.
3. Switch the grid segment to **All objects** if the current segment hides the cell, expand
   its group, scroll to it, select and focus it, and flash its outline twice (skipped when the
   OS asks for reduced motion).

### 10.3 Jump box (Ctrl+K)

- Popup anchored under the toolbar: one search field and a result list.
- Sources: principals, objects (`schema.name`), tags. Results grouped with headers, at most 8
  per group, with "Show all N" to expand a group.
- Matching: same token rules as the lists; ranking puts prefix matches first, then shorter
  names.
- Enter on a principal → By principal mode, select it. On an object → By object mode, select
  it. On a tag → add the tag filter to the left list in the current mode.
- Must answer within 30 ms per keystroke on the reference dataset (it reuses the index's
  search keys).

## 11. Session and matrix changes

| Change | Where |
|---|---|
| `stage_states()` (section 9.8) | `src/services/matrix.py` |
| `check_then_stage(cells_or_items, label)` with FR-017a flow, emitting `stagingDenied(list[StagedChange])` | `src/qt/session.py` |
| `load_description`, `save_description` | `src/qt/session.py` |
| `save_object_description(conn, schema, name, description, object_type)` | `src/db/objects.py` |
| Remove `dev_stage_sample` and its Help action | session, actions |
| `revealRequested` handled by `MatrixView` | main window wiring |
| Move the index build off the UI thread if a load logs a stall at work (step 2 note): `PermissionIndex.build` in the worker job, then a cheap swap on the UI thread. Do it in this step only if measurements on the reference dataset show a stall over 100 ms. | `session.py`, `matrix.py` |

## 12. Accessibility

- Each cell's accessible text: "SELECT on sales.Orders: granted, staged, was none" /
  "DELETE on sales.Orders: not applicable". Provided via `AccessibleTextRole` and
  `AccessibleDescriptionRole`.
- Group rows: "sales group, 86 objects, 9 with access, expanded".
- After each staging action, announce the undo label ("Granted SELECT on 12 objects for
  CORP\jsmith"); after mode or entity change, announce "Showing CORP\jsmith, 2,847 objects,
  38 with access".
- Every chip is a checkable button with an accessible name including its state ("Users filter,
  on").
- Focus is always visible (dashed outline in the grid, platform focus elsewhere).
- No information by colour alone: glyphs for states, dot plus outline for staged, hatch for
  not applicable.
- Reduced motion: no reveal flash.

## 13. Remembered view state (`view_state.py`)

Stored in `QSettings` under `matrix/`:

- Mode, splitter sizes, last selected principal login and object `schema.name`.
- Per mode: left-list chips, tags, sort; grid segment, schema/type/tag filters.
- Search text is **not** remembered (it surprises people on the next launch).
- Collapsed groups are remembered for the session only.

On load, saved entities that no longer exist are ignored.

## 14. Performance budgets

Measured on the 1,000 × 20,000 × 200,000 synthetic snapshot through a real `MatrixView`
(offscreen), best of 3. Tests assert 3× the budget, like step 1.

| Operation | Budget |
|---|---|
| Select a principal → grid model built and first paint (All objects, 20,000 rows) | 80 ms |
| Select a principal with Only with access (busiest principal, ~2,400 rows) | 30 ms |
| Grid filter keystroke (objects) | 50 ms |
| Left list search keystroke (principals) | 20 ms |
| Paint one screen of grid (40 rows × 9 columns) | 16 ms |
| Stage 1,000 cells and repaint affected rows | 100 ms |
| Mode switch with reveal of focused cell | 80 ms |
| Jump box keystroke | 30 ms |
| Memory added by the view on top of step 2 | ≤ 50 MB |

`tests/perf/test_matrix_view_perf.py`, marked `slow`.

## 15. Tests

Unit (headless, `tests/unit/qt/matrix/`):

- `test_grid_model.py`: grouping per mode; `cell_at`/`index_for_cell` round trip; flags for
  non-applicable cells; roles; By object hides non-applicable columns; `on_matrix_change` emits
  `dataChanged` only for affected rows (spy on the signal); rebuild keeps current cell by
  natural key; rows stay visible after a change that would filter them out.
- `test_entity_list.py`: filters, chips, sort, tags (AND), has-pending updates, selection kept
  across refilter, schema headers and collapse.
- `test_grid_editing.py` (qtbot keys/mouse): G/D/R/U on a selection; Space and double-click
  cycle; click never changes state; Escape clears selection only; keys ignored when offline;
  selection skips hatched cells; column-header and row-name selection; 20,000-cell limit.
- `test_bulk.py`: confirmation shown at 5 changes not 4; counts (changed/unchanged/skipped);
  "don't ask again"; presets per object type; Make like (mixed states, scope, one undo step);
  `stage_states`.
- `test_privileges.py`: privileged skip; cached; one worker check for unknown cells; denied
  cells not staged and reported; allowed ones staged as one undo step.
- `test_mode_switch_reveal_jump.py`: mode switch keeps the cell; reveal clears only the filters
  that hide the cell; jump to principal/object/tag; ranking.
- `test_descriptions.py`: level1type per object type (mock cursor); load/save via Session;
  validation of length.
- `test_view_state.py`: round trip through a temp `QSettings`; missing entities ignored; search
  text not restored.

Existing tests: remove the dev-action tests; update placeholder tests for the new state
mapping.

## 16. Manual test script (BifrostDev with `--large`)

1. Launch. Matrix tab opens in By principal mode with the first principal selected.
2. Type "0101" in the left search; select `lg_user_0101`; grid shows all objects grouped by schema.
3. Collapse `lg01`; scroll to the end; scrolling stays smooth. Switch to Only with access; the list shrinks to their objects.
4. Select 3 cells with Shift+arrows, press G → three staged cells; Ctrl+Z → gone.
5. Click the SEL column header → whole column selected → G → confirmation shows counts →
   Stage → pending pill shows the number; Undo once restores everything.
6. Right-click a group row → Grant SELECT on all in `lg02` → confirm → staged.
7. Make like `lg_user_0001` (a heavy principal) → confirmation shows grants/denies/revokes.
8. Switch to By object with a cell focused → same cell focused in object mode.
9. Edit the description of a view and a procedure; reload; descriptions still there.
10. Ctrl+K "Table0042" → Enter → By object mode on that table.
11. Pending tray → double-click a change → the cell is revealed and focused.
12. Stop the container → grid becomes read-only with the offline banner; keys do nothing;
    reconnect → editable again, staged changes intact.
13. Commit everything (preview, results) and confirm in the Audit tab.
14. Keyboard only: steps 2, 4, 5, 8 and 10 without the mouse.
15. Quit and relaunch → mode, splitter, filters and last selection restored; search text empty.

## 17. Acceptance criteria

- [ ] `MatrixView` replaces the placeholder in READY / COMMITTING / OFFLINE states.
- [ ] Sections 6–10 implemented as decided in section 19.
- [ ] Budgets in section 14 met on the dev Mac; numbers recorded in Results.
- [ ] All tests pass headless; `ruff check` clean for new code; new modules ≥ 80% covered
      (models, bulk, view state) and the view/grid modules covered by qtbot tests.
- [ ] Manual script (section 16) done on the Mac; steps 12–14 also on the work machine.
- [ ] `save_object_description` fixed for views, procedures and functions.
- [ ] Dev "stage sample changes" action removed; README updated (it's no longer needed).
- [ ] Plan status updated; step 2 follow-up about index build on the UI thread resolved or
      re-deferred with measurements.

## 18. Results

_Fill in when step 3 is done._

## 19. Decisions (2026-10-01)

1. **Bulk confirmation offers "Don't ask again until Bifrost restarts"**, off by default.
   Staging is undoable and Commit has its own preview. (Deviation from FR-030 as written.)
2. **Selection limit is 20,000 cells** per action, instead of FR-031's 1,000. Group actions
   aren't limited.
3. **Default grid filter is All objects** (By principal) / **All principals** (By object). The
   last choice is remembered per mode.
4. **Permission column headers use abbreviations** (SEL, INS, UPD, DEL, EXEC, ALTER, REF, VDEF)
   with the full name in the tooltip and accessible name, instead of icons (FR-020). Proposed
   and not objected to.
5. **Click selects; double-click or Space changes a cell**, and G/D/R/U set the selection. A
   stray click never changes a permission, in line with the Discard decision.
