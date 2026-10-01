# Spec — Step 2: PySide6 App Shell

**Plan**: [plan.md](plan.md) | **Created**: 2026-10-01 | **Status**: Ready to implement after step 1
**Depends on**: [step 1](spec-01-data-layer.md) | **Blocks**: steps 3–5 (all views live inside this shell)
**Mockups**: https://claude.ai/artifact/9oe2fFwTwa5kzJ9AeGzZyL (title bar, status bar and pending pill are drawn there)

## 1. Goal

Replace the Tkinter application shell with PySide6, keeping every non-matrix feature working:
connecting, loading, refreshing, committing, cancelling, undo/redo, connection-loss recovery,
settings, tags, audit log and export. The matrix itself is built in step 3. Until then, the
Matrix tab shows a load summary.

When this step is done:

- `python main.py` opens the Qt app. The window appears in ≤ 0.5 s, before any DB work.
- All DB work runs on one worker thread. The UI never freezes during connect, load, refresh,
  commit, audit fetch or export.
- Staged changes are visible and manageable from the status bar and pending tray in every tab.
- `python main.py --legacy-tk` still opens the old Tk app (removed in step 6).

## 2. Scope

**In scope**

- New package `src/qt/` (layout in section 3).
- `Session` controller, `DbWorker`, main window, menus, shortcuts, tab bar, status bar,
  pending tray, theme, logging, crash handler.
- Dialogs: Settings, Tag manager (with member pickers), Commit preview, Commit result,
  Partial-failure, Connection lost, Discard confirm, Quit with pending changes, Keyboard
  shortcuts, About.
- Audit log view.
- Matrix tab placeholder (loading, error and summary states).
- Export of permissions and audit log off the UI thread.
- Dependencies, `main.py` switch, tests.

**Out of scope**

- The split view, editing cells, selection, jump box (step 3). The pending tray's "reveal"
  signal is emitted here but nothing handles it until step 3.
- Grants tab (step 4), Compare mode (step 5).
- Removing `src/ui/` (step 6).
- Object descriptions UI (FR-023). The Tk app has no UI for it either; it lands with the
  object detail panel in step 3.

## 3. Package layout

```
src/qt/
├── __init__.py
├── app.py                  # main(): QApplication setup, logging, excepthook, MainWindow
├── session.py              # Session(QObject): app state + flows; no widgets
├── worker.py               # DbWorker(QObject): serial DB job queue on one thread
├── theme.py                # colour tokens (light/dark), palette, fonts, metrics
├── actions.py              # ActionRegistry: every QAction, its shortcut and handler
├── main_window.py          # MainWindow(QMainWindow): menus, toolbar, tabs, status bar, docks
├── widgets/
│   ├── __init__.py
│   ├── status_bar.py       # BifrostStatusBar
│   ├── pending_tray.py     # PendingTray (QDockWidget) + StagedChangesModel
│   ├── pills.py            # ConnectionPill, PendingPill (custom-painted labels)
│   └── search_field.py     # QLineEdit with debounce + clear button (reused in step 3)
├── views/
│   ├── __init__.py
│   ├── matrix_placeholder.py
│   └── audit_view.py       # AuditView + AuditLogModel
└── dialogs/
    ├── __init__.py
    ├── settings_dialog.py
    ├── tag_manager.py      # TagManagerDialog + MemberPickerDialog
    ├── commit_preview.py
    ├── commit_result.py    # success summary + partial failure
    ├── connection_lost.py
    └── messages.py         # confirm_discard, confirm_quit, info/error helpers
```

Rules:

- `session.py` and `worker.py` import only `PySide6.QtCore` (no widgets), so they can be tested
  without a display and reused by every view.
- Views and dialogs never call `src.db.*` directly. They call `Session` methods and react to
  `Session` signals.
- Nothing in `src/qt/` imports `src/ui/` and vice versa.

## 4. Dependencies

| Package | Where | Notes |
|---|---|---|
| `PySide6-Essentials` | `requirements.txt`, `pyproject.toml` `dependencies` | QtCore, QtGui, QtWidgets only (smaller than full `PySide6`). Pin an exact version that has wheels for both the dev Python (3.14 on the Mac) and the work machine's Python on Windows. Minimum Qt 6.8 (needed for `QAccessibleAnnouncementEvent` and `QStyleHints.colorScheme` change signal). |
| `pytest-qt` | `requirements-dev.txt`, `pyproject.toml` `dev` extra | Pin exact version. |

Update `requirements.txt` header comments to justify PySide6 the same way pyodbc is justified
(the old plan required each dependency to be justified).

## 5. Startup

```
main.py
 ├─ "--legacy-tk" in argv → src.ui.app.main()  (unchanged Tk app)
 └─ otherwise            → src.qt.app.main()
```

`src.qt.app.main(argv) -> int`:

1. Configure logging (section 15).
2. Install `sys.excepthook` (section 15).
3. Create `QApplication`: application name "Bifrost", organization "Bifrost" (for `QSettings`),
   high-DPI is on by default in Qt 6. Use the platform's default style.
4. Apply theme (section 13).
5. Create `Session`, then `MainWindow(session)`, restore geometry from `QSettings`, `show()`.
6. `QTimer.singleShot(0, session.start)` so the window paints before any work starts.
7. `return app.exec()`.

`Session.start()`:

1. Load tags (`TagStore.load()`); on error, log it, use an empty store, and show a status message.
2. `load_config()`. If it returns an error (missing or corrupt, spec edge case) → state
   `NEEDS_SETTINGS`, emit `settingsRequested(reason)`; the window opens the Settings dialog with
   the reason shown at the top.
3. Otherwise → `connect(config)`.

## 6. Session (`src/qt/session.py`)

`Session` owns all application state and all flows. Widgets are thin.

### 6.1 State

```python
class SessionState(Enum):
    NEEDS_SETTINGS = auto()   # no usable config
    CONNECTING = auto()
    LOADING = auto()          # connected, fetching snapshot
    READY = auto()
    COMMITTING = auto()
    OFFLINE = auto()          # connection lost or user disconnected; staged changes kept
    FAILED = auto()           # connect or load failed; see last_error
```

| Attribute | Type |
|---|---|
| `state` | `SessionState` |
| `config` | `Configuration | None` |
| `matrix` | `PermissionMatrix | None` (created on first successful load, kept across reconnects) |
| `tag_store` | `TagStore` |
| `current_user` | `str | None` (from the snapshot) |
| `last_error` | `str | None` |
| `last_load` | `LoadSummary | None` (counts, timings, loaded_at) |

Derived properties: `connected`, `can_edit` (`READY` only; used by step 3), `can_commit`
(`READY` and staged count > 0), `busy` (`CONNECTING`, `LOADING`, `COMMITTING`).

### 6.2 Signals

| Signal | Payload | When |
|---|---|---|
| `stateChanged` | `SessionState` | every transition |
| `loadProgress` | `LoadProgress` | during load/refresh |
| `dataLoaded` | `LoadSummary` | after a snapshot is applied |
| `matrixChanged` | `MatrixChange` | re-emitted from `matrix.subscribe` |
| `stagedCountChanged` | `int` | when the staged count changes (also from `matrixChanged`) |
| `undoStateChanged` | `bool, bool` | `can_undo`, `can_redo` |
| `statusMessage` | `str, int` | text, timeout ms (0 = sticky) |
| `announce` | `str` | text for screen readers (FR-025 live region) |
| `settingsRequested` | `str` | reason to show at the top of Settings ("" if user-initiated) |
| `connectionLost` | `str, int` | error, staged count |
| `commitPreviewRequested` | `CommitPlan` | ≥5 changes (see 9.3) |
| `commitFinished` | `CommitReport` | after results are applied |
| `restageReport` | `RestageReport` | after a refresh/reconnect that dropped or auto-resolved changes |
| `tagsChanged` | — | after tag edits are saved |
| `revealRequested` | `CellRef` | pending tray item activated (handled in step 3) |

Signals are the only way views learn about changes. A view must render correctly from
`Session` state alone when it is created late (for example the Audit tab opened after load).

### 6.3 Methods (all called on the UI thread)

| Method | Summary |
|---|---|
| `start()` | section 5 |
| `connect(config)` | section 9.1 |
| `refresh()` | section 9.2 |
| `disconnect()` | close the connection on the worker; state `OFFLINE`; staged kept |
| `request_commit()` | section 9.3 |
| `confirm_commit(plan)` | called by the preview dialog's Commit button |
| `discard_all(confirmed: bool)` | section 9.4 |
| `undo()` / `redo()` | section 9.5 |
| `revert_change(change: StagedChange)` | revert one cell (pending tray); one undo group |
| `save_settings(config) -> str | None` | `save_config`; returns error; on success `connect(config)` |
| `test_connection(config, callback)` | runs `db.connection.test_connection` on a detached thread (not the DB worker, so it never waits behind a load); `callback(success, message)` on the UI thread |
| `fetch_audit(filters, callback)` | DB worker job wrapping `fetch_audit_entries` + `get_audit_entry_count` |
| `export_permissions(path, include_none, callback)` | section 11 |
| `export_audit(path, entries, callback)` | section 11 |
| `save_tags() -> str | None` | `tag_store.save()`; `matrix.set_tag_store(...)`; emit `tagsChanged` |
| `shutdown(callback)` | section 9.7 |

### 6.4 Connection ownership

- Exactly one `pyodbc.Connection`, created, used and closed **only on the DB worker thread**.
  The UI thread never holds a reference it uses. `Session` stores it opaquely for passing back
  into worker jobs.
- `test_connection` opens and closes its own short-lived connection on a detached thread.

## 7. DB worker (`src/qt/worker.py`)

```python
@dataclass
class JobHandle:
    name: str
    cancel_event: threading.Event
    def cancel(self) -> None

class DbWorker(QObject):
    def submit(self, name: str, fn: Callable[[JobContext], T],
               on_done: Callable[[T], None] | None = None,
               on_error: Callable[[BaseException], None] | None = None,
               on_progress: Callable[[object], None] | None = None,
               coalesce: bool = False) -> JobHandle
    def is_idle(self) -> bool
    def shutdown(self, wait_ms: int = 5000) -> None

@dataclass(frozen=True)
class JobContext:
    cancel_event: threading.Event
    report: Callable[[object], None]    # thread-safe; delivers to on_progress on the UI thread
```

- Backed by a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` (one thread, jobs run in
  submission order). Results, errors and progress are delivered to the UI thread through a Qt
  signal with a queued connection. Callbacks always run on the UI thread.
- `coalesce=True`: if a job with the same `name` is already queued (not running), the new one
  replaces it. Used for audit fetches while the user types in filters.
- Exceptions raised in `fn` go to `on_error`. If `on_error` is `None`, the error is logged and
  forwarded to `Session._on_job_error`, which checks for connection loss (section 9.6).
- A job never touches `PermissionMatrix`, `PermissionIndex` or widgets. Code review rule; add a
  docstring warning.
- `shutdown` cancels queued jobs, sets running jobs' cancel events, waits up to `wait_ms`.
- `run_detached(fn, on_done, on_error)`: module-level helper using `QThreadPool` for work that
  does not need the shared connection (connection tests, CSV writing).

## 8. Main window (`src/qt/main_window.py`)

### 8.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ File  Edit  View  Help                                                    (menu bar) │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ [ Matrix ][ Audit log ]                    [⌘K Jump to… (disabled until step 3)]     │
│                                                     [⟳ Refresh] [🏷 Tags] [⚙ Settings]│
├──────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│                          active tab (QStackedWidget)                                 │
│                                                                                      │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Pending changes tray (QDockWidget, bottom, hidden by default, ~200 px)               │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ● sql01/FinanceDW as CORP\aadmin │ Committed 3 changes │ [3 pending] Undo Discard     │
│                                                          Review…  [Commit 3]          │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- Window title: `Bifrost — <database>[*]` using Qt's `windowModified` marker, set when staged
  count > 0. Before connecting: `Bifrost`.
- Minimum size 1024 × 680. Default 1280 × 860, centred on first run; afterwards restored from
  `QSettings` (`geometry`, `windowState`, last tab, tray visibility).
- Tabs: a `QTabBar` in the toolbar drives a `QStackedWidget`. Tabs in this step: **Matrix**,
  **Audit log**. Step 4 inserts **Grants** between them.
- Toolbar buttons are also `QAction`s from the registry (section 12), so they share
  shortcuts, enabled state and accessible names with the menus.

### 8.2 Enabled states

| Control | Enabled when |
|---|---|
| Refresh | `connected` and not `busy` |
| Commit / Review… | `can_commit` |
| Discard | staged count > 0 and state ≠ `COMMITTING` |
| Undo / Redo | `can_undo` / `can_redo` and state ≠ `COMMITTING` |
| Export permissions | `matrix` loaded |
| Export audit / Audit tab content | `connected` |
| Disconnect | `connected` |
| Tags | always (tag store is local); member pickers need a loaded matrix |

## 9. Flows

### 9.1 Connect

1. State `CONNECTING`; status "Connecting to `<server>/<db>`…" with a busy indicator.
2. Worker job `connect`: close any old connection; `create_connection(config)`;
   `ensure_audit_log_table(conn, config.schema)`.
3. On error: state `FAILED`, `last_error` set, status message with the friendly error from
   `DatabaseConnectionError`. If the error is a login or server-not-found error, also emit
   `settingsRequested(error)`. The Matrix placeholder shows the error with Retry and Settings
   buttons.
4. On success: start the heartbeat (9.6) and go to Load (9.2).

### 9.2 Load and refresh

1. State `LOADING`. Status bar shows the stage message and a determinate 4-step progress
   indicator. The Matrix placeholder shows the same with a **Cancel** button.
2. Worker job `load`: `fetch_snapshot(conn, progress=ctx.report, cancel=ctx.cancel_event)`.
3. On done (UI thread):
   - First load: `matrix = PermissionMatrix(conn=None, schema, tag_store)`, then
     `matrix.apply_snapshot(snapshot)`, subscribe to `matrix`.
   - Later loads (refresh, reconnect): `matrix.apply_snapshot(snapshot)` (keeps staged changes,
     returns `RestageReport`). If the report has dropped or already-applied changes, emit
     `restageReport` and show a non-modal message: "3 staged changes were removed because the
     principal or object no longer exists. 1 change was already made by someone else." with a
     Details button listing them.
   - State `READY`; emit `dataLoaded`; status "Loaded 412 principals, 2,847 objects" (8 s).
4. On `LoadCancelledError`: first load → state `FAILED` with "Loading cancelled" and a Retry
   button; refresh → stay `READY` with the old data.
5. Other errors → section 9.6 classification, else state `FAILED` (first load) or `READY` with an
   error message (refresh).

Staging stays allowed during a refresh (changes are re-applied by natural key).

`PermissionMatrix` is created with `conn=None` because the Qt app never lets it touch the
connection directly; all DB access goes through worker jobs that receive the connection. Step 1's
legacy wrappers that use `self.conn` are only for the Tk app.

### 9.3 Commit

1. `request_commit()`: if not `can_commit`, show status "Nothing to commit" or
   "Not connected" and stop.
2. `plan = matrix.prepare_commit()`.
3. If `len(plan.changes) < 5` → `confirm_commit(plan)` directly (express path, FR-026).
   Otherwise emit `commitPreviewRequested(plan)`; the window opens the Commit preview dialog
   (section 10.3), whose Commit button calls `confirm_commit(plan)`.
4. `confirm_commit(plan)`: privilege check first (FR-017a):
   - Collect the GRANT targets whose privilege isn't cached (`matrix.known_grant_privilege`).
     If the snapshot says `privileged`, skip.
   - Otherwise one worker job `check_grant_privileges`; cache the results. If any target fails,
     show the FR-017a message listing up to 10 failing changes ("You cannot grant SELECT on
     dbo.Orders because you do not have this permission yourself. Contact a database owner or
     sysadmin."), un-stage those cells as one undo group, and stop. The user can then commit
     the rest.

   Step 3 will move this check earlier, to staging time, as FR-017a asks. Doing it at commit in
   this step keeps the rule enforced before any cell editor exists.
5. State `COMMITTING` (editing disabled). Worker job `commit`:
   `PermissionMatrix.execute_commit(conn, plan, current_user)`.
6. On done: `matrix.apply_commit_results(plan, outcome)`; state `READY`; build `CommitReport`
   (succeeded, failed with reasons, rolled_back, error); emit `commitFinished`.
   - All succeeded, < 5: status "Committed 3 changes" (8 s), announce the same.
   - All succeeded, ≥ 5: Commit result dialog (10.4) with "View audit log" and "Close".
   - Some failed: Partial-failure dialog (10.4). Failed changes stay staged.
   - `rolled_back` with a connection error → connection-lost flow (9.6). Other rollback →
     error dialog: "Nothing was committed. <error>. Your N staged changes are still here."
7. Commit is never retried automatically.

### 9.4 Discard

- `discard_all(confirmed=False)`: if staged ≥ 5 and not confirmed → window shows
  `confirm_discard(n)` ("Discard 12 staged changes? This can't be undone." [Discard] [Keep
  editing], default Keep editing); on Discard calls `discard_all(True)`.
- `matrix.cancel()`; status "Discarded 12 changes".

### 9.5 Undo and redo

- `matrix.undo()` / `redo()`; if a group comes back, announce "Undone: <label>" /
  "Redone: <label>" and show it in the status bar for 5 s (FR-029). If nothing, status
  "Nothing to undo".
- Emit `undoStateChanged` after every matrix change.

### 9.6 Connection health

- **Heartbeat**: `QTimer` every 30 s (FR-022). If the worker is idle, submit `SELECT 1`
  (job name `heartbeat`, coalesced). If the worker is busy, skip this tick; a running job proves
  the connection or will fail on its own.
- **Lazy detection**: every job error goes through `is_connection_error(exc)` (new function in
  `src/db/connection.py`): `pyodbc.Error` whose SQLSTATE (`exc.args[0]`) is one of `08S01`,
  `08001`, `08003`, `08004`, `08007`, `HYT00`, `HYT01`, or whose message contains
  "Communication link failure" or "TCP Provider". Unit-test with sample error tuples.
- On connection loss: state `OFFLINE`; stop heartbeat; emit `connectionLost(error, staged)`.
  The window shows the Connection lost dialog (10.5) once per loss (no stacking).
  - **Reconnect now** → `connect(config)` (staged changes kept, re-applied by 9.2).
  - **Open settings** → Settings dialog.
  - **Stay offline** → status "Offline. 3 staged changes kept." Matrix data stays visible
    (read-only until reconnected, `can_edit` is false). A **Reconnect** button appears in the
    connection pill.
- SC-008 (detect within 5 s) is met by lazy detection on the next action; the heartbeat covers
  idle sessions within 30 s as the old spec allows.

### 9.7 Quit

1. Window `closeEvent` → `session.shutdown(callback)` unless already shutting down; ignore the
   event until the callback says quit.
2. If staged > 0: `confirm_quit(n)` → [Commit and quit] [Quit without committing] [Cancel]
   (default Cancel).
   - Commit and quit → commit flow (9.3); quit only if every change succeeded. Any failure
     shows the normal result dialog and the app stays open. (The Tk app quits even when the
     commit fails; this fixes that.)
   - Quit without committing → continue.
   - Cancel → stop, app stays open.
3. If a commit is running: "A commit is in progress. Wait for it to finish?" [Wait] and the
   app closes when it completes. Never kill a running commit.
4. Save tags (log errors; show a warning dialog only if saving fails), save window state to
   `QSettings`, stop the heartbeat, submit a `close_connection` job, `DbWorker.shutdown(5000)`,
   then `QApplication.quit()`.

## 10. Dialogs

All dialogs: modal unless stated; keyboard-operable; default and cancel buttons set
(Enter/Escape); first focus on the most likely action; accessible names on every control;
content wraps at any width; sizes saved in `QSettings` for resizable ones.

### 10.1 Settings (`dialogs/settings_dialog.py`)

Port of `src/ui/views/settings.py` with the same fields, validation and test-result memory.

```
┌ Settings ─────────────────────────────────────────────────────────┐
│ ⚠ <reason banner, only when opened by the app: "Couldn't read the │
│    config file: …" / "Login failed for …">                       │
│                                                                    │
│ Connection                                                         │
│   Server    [ sql01.corp.local          ]  Hostname or IP          │
│   Port      [ 1433 ]                       Default 1433            │
│   Database  [ FinanceDW                 ]                          │
│   Schema    [ dbo  ]                       For Bifrost's audit log │
│                                                                    │
│ Authentication                                                     │
│   Windows Authentication (your current Windows sign-in)            │
│   <dev note when BIFROST_DEV_SQL_USER is set: "Using dev SQL login │
│    from environment">                                              │
│                                                                    │
│ ✓ Connected to sql01/FinanceDW            [ Test connection ]      │
│                                                                    │
│                               [ Cancel ]  [ Save and connect ]     │
└────────────────────────────────────────────────────────────────────┘
```

- Field errors appear under the field they belong to (FR-017, FR-025 error association: set the
  error label as the field's `accessibleDescription` and give the field a red border).
  Validation uses `Configuration.validate()` and `validation.validate_port` /
  `validate_schema_name`. Port must be 1–65535 (no silent fallback to 1433 as the Tk code does).
- **Test connection** runs `Session.test_connection` (detached thread). Button shows
  "Testing…" and is disabled until the result arrives. Result shown with ✓ / ✗ and colour.
- The last test result is shown only while the fields still match what was tested (same rule as
  `_refresh_status` in the Tk view). Editing any field resets it to "Not tested".
- **Save and connect**: validate; `Session.save_settings(config)`; on error show it in the
  dialog; on success close the dialog (no "Saved" message box; the status bar shows progress).
- **Cancel** closes without saving. If opened because there is no usable config, Cancel leaves
  the app in `NEEDS_SETTINGS` with the Matrix placeholder showing "Set up a connection to get
  started" and an **Open settings** button.

### 10.2 Tag manager (`dialogs/tag_manager.py`)

Non-modal. Port of `src/ui/views/tags.py` with the same capabilities.

```
┌ Tags ──────────────────────────────────────────────────────────────────────┐
│ [🔍 Filter tags… ]           │  finance                                    │
│ finance        12 · 340      │  [ Principals (12) ][ Objects (340) ]       │
│ readonly        4 · 0        │  [🔍 Filter members…]                        │
│ reporting      30 · 1,201    │  CORP\jsmith                                │
│ tier1           0 · 18       │  CORP\finance-analysts                      │
│                              │  …                                          │
│ [New] [Rename] [Delete]      │  [ Add… ] [ Remove selected ]               │
└────────────────────────────────────────────────────────────────────────────┘
```

- Tag list shows principal and object counts. Member lists use `QListView` + filter proxy (they
  can hold thousands of rows).
- **New**: inline name entry validated with `validate_tag`. A new tag has no members yet;
  `tags.json` cannot store an empty tag, so the tag lives only in the dialog (shown in italics,
  "not saved until it has members") until something is added.
- **Rename**: validated; `TagStore.rename_tag`; renaming onto an existing tag name merges (ask
  first: "Merge 'Finance' into 'finance'?").
- **Delete**: confirm with member counts, as today.
- **Add…** opens `MemberPickerDialog`: search field, checkable virtualized list of all principals
  (with type) or all objects (with type and schema), "Select all shown", count of checked items.
  Needs a loaded matrix; disabled with a tooltip otherwise.
- Every change calls `Session.save_tags()` immediately (same as the Tk view) and the matrix tag
  indexes update via `matrix.set_tag_store`.
- Shortcut: Ctrl+T. If already open, raise and focus it.

### 10.3 Commit preview (`dialogs/commit_preview.py`)

Shown for ≥ 5 changes (FR-026).

```
┌ Review 12 changes ─────────────────────────────────────────────────────────┐
│ These changes will be applied to FinanceDW and written to the audit log.   │
│ [🔍 Filter…]                        8 grants · 1 deny · 3 revokes          │
│ ┌──────────┬─────────────────┬──────────────────────┬──────────┬────────┐  │
│ │ Action   │ Permission      │ Object               │ Principal│ Was    │  │
│ │ GRANT    │ SELECT          │ sales.Orders         │ CORP\js… │ none   │  │
│ │ REVOKE   │ DELETE          │ sales.Orders         │ CORP\js… │ GRANT  │  │
│ └──────────┴─────────────────┴──────────────────────┴──────────┴────────┘  │
│ [ Review in matrix ]                           [ Cancel ]  [ Commit 12 ]   │
└────────────────────────────────────────────────────────────────────────────┘
```

- Full list in a sortable `QTableView` (no "show first 3" truncation; a table scrolls). Filter
  box narrows rows. Summary counts by action. Action column coloured by token with the action
  word always present (not colour-only, FR-024).
- **Commit N** is the default button. **Review in matrix** closes the dialog and opens the
  pending tray (step 3 will also highlight cells). **Cancel** closes.
- Rows sort by principal, then object, then permission by default.

### 10.4 Commit result (`dialogs/commit_result.py`)

- **Success (≥ 5)**: "12 changes applied" with the first 5 as sentences and "and 7 more";
  [View audit log] [Close]. Auto-close is **not** used (dialogs that vanish fail WCAG 2.2.1);
  a status message covers the < 5 case instead.
- **Partial failure**: "9 of 12 changes applied. 3 failed and are still staged." Table of
  failed changes with the reason column, plus a collapsed list of the successful ones.
  Buttons: [View audit log] [Discard failed] [Keep for retry] (default Keep for retry).
  - Discard failed → `matrix.revert(failed cells)` (only the failed cells, not all staged
    changes; the Tk app's "discard" cancelled everything, which was wrong).
  - View audit log → switch to the Audit tab filtered to the commit time (from = commit start).

### 10.5 Connection lost (`dialogs/connection_lost.py`)

"Lost the connection to sql01/FinanceDW", the error text, "Your 3 staged changes are kept." and
[Reconnect now] (default) [Open settings] [Stay offline] (Escape).

### 10.6 Messages (`dialogs/messages.py`)

Thin wrappers around `QMessageBox` with consistent wording and button roles: `confirm_discard`,
`confirm_quit`, `confirm_full_export`, `show_error`, `show_info`. Wording follows section 16.

### 10.7 Keyboard shortcuts and About

- Shortcuts dialog (F1) is generated from the action registry (section 12) so it never goes
  stale. Grouped by menu.
- About: version from `pyproject.toml` metadata (`importlib.metadata.version("bifrost")`, with
  "dev" fallback), Python, Qt and pyodbc versions, ODBC driver in use, config and log file
  paths (selectable text).

## 11. Export

- **Permissions** (Ctrl+E): Save dialog with a suggested name (`get_suggested_filename`) and an
  "Include cells with no permission" checkbox (off by default). If on and the cell count is over
  5,000,000, `confirm_full_export` with the estimated row count and file size.
- Because `PermissionIndex` is UI-thread-only, take a frozen copy on the UI thread first:
  add `PermissionIndex.freeze() -> FrozenIndex` (copies the `committed` and `staged` dicts;
  shares the principal and object lists, which are not mutated after build). About 20 ms for
  200,000 rows. The detached thread writes CSV from the frozen copy with
  `export_permissions_from_index`. Progress shows in the status bar; Cancel is available.
- **Audit log**: from the Audit tab (exports loaded rows) or File menu (exports with the
  current Audit tab filters; fetches via the DB worker first). Writing runs on a detached thread.
- Completion: status "Exported 48,210 rows to C:\…\FinanceDW_permissions_2026-10-01.csv" with
  an **Open folder** action. No modal "Export complete" box.

## 12. Actions and shortcuts (`src/qt/actions.py`)

Every command is a `QAction` created once in `ActionRegistry`, used by menus, toolbar,
status bar and the shortcuts dialog. A test asserts no two actions share a key sequence.

| Menu | Action | Shortcut | Notes |
|---|---|---|---|
| File | Connection settings… | Ctrl+, | also Ctrl+O (old binding) |
| File | Disconnect | — | |
| File | Export permissions… | Ctrl+E | |
| File | Export audit log… | Ctrl+Shift+E | |
| File | Exit | Alt+F4 / Ctrl+Q | platform default |
| Edit | Undo | Ctrl+Z | |
| Edit | Redo | Ctrl+Y, Ctrl+Shift+Z | |
| Edit | Commit changes… | Ctrl+S, Ctrl+Enter | |
| Edit | Discard all changes… | Ctrl+Shift+Delete | **Changed**: no longer Escape (see below) |
| Edit | Show pending changes | Ctrl+Shift+P | toggles the tray |
| View | Matrix | Ctrl+1 | |
| View | Grants | Ctrl+2 | added in step 4 |
| View | Audit log | Ctrl+3 | **Changed** from Ctrl+4 |
| View | Refresh | F5 | |
| View | Tags… | Ctrl+T | **Changed** from Ctrl+2 |
| View | Jump to… | Ctrl+K | disabled until step 3 |
| Help | Keyboard shortcuts | F1 | |
| Help | About Bifrost | — | |

**Escape** no longer discards staged changes. In the Tk app a stray Escape (for example to
close a dropdown) could throw away work; at hundreds of staged changes that's too costly.
Escape now only closes popups/dialogs and (step 3) clears the selection. This is open question
3 in [plan.md](plan.md); if the user wants Escape back, it goes in this table with the ≥ 5
confirmation.

## 13. Theme (`src/qt/theme.py`)

- Follow the OS light/dark setting (`QGuiApplication.styleHints().colorScheme()`), and update
  live on `colorSchemeChanged`.
- Tokens (same as the mockup page), exposed as a frozen dataclass `Tokens` for light and dark:
  `bg, surface, surface_2, line, line_soft, fg, muted, accent, accent_soft, grant, grant_bg,
  deny, deny_bg, staged, staged_bg, na`.
  - Light: grant `#1f7a4a` on `#d9f0e3`, deny `#b3261e` on `#f8dcd9`, staged `#a86a00` on
    `#fff1cc`, accent `#2f5fa7`.
  - Dark: grant `#6fd19c` on `#173a29`, deny `#f08a82` on `#43201e`, staged `#f2c046` on
    `#3d3113`, accent `#7fa8e6`.
  - A unit test checks every text/background pair meets WCAG AA 4.5:1 and every
    UI-component colour meets 3:1 against its background (FR-024).
- Only custom-painted elements (pills, step 3 cells) use tokens directly. Standard widgets use the
  platform style and `QPalette`, so Windows High Contrast themes work: when
  `QGuiApplication.styleHints().colorScheme()` is unknown and the palette looks like a high
  contrast theme, custom painting falls back to palette roles (`WindowText`, `Highlight`, …).
- Fonts: platform UI font (Segoe UI Variable on Windows 11). No bundled fonts. All sizes in
  points so system text scaling (up to 200%, FR-025) applies.
- Motion: no animations in this step. Any later animation must check reduced-motion
  (`QStyleHints` / Windows `SPI_GETCLIENTAREAANIMATION`).

## 14. Status bar and pending tray

### 14.1 Status bar (`widgets/status_bar.py`)

Left to right:

1. **Connection pill**: dot + `server/database as user`. Colours: green connected, amber
   connecting/loading, grey offline/disconnected, red failed. Text always states the state
   ("Offline", "Connecting…") so colour isn't the only signal. Click → Settings. In `OFFLINE`
   it shows a **Reconnect** button.
2. **Message area**: transient messages from `statusMessage` (timeout honoured); sticky messages
   for long operations with a progress bar (determinate for load stages and export,
   indeterminate for connect/commit) and a Cancel button when the job supports it.
3. **Pending pill**: "No pending changes" (muted) or "12 pending" (staged colours). Click toggles
   the tray.
4. **Undo**, **Discard**, **Review…**, **Commit 12** (primary button; label includes the count).

Accessibility: each count change calls `Session.announce` with "12 changes staged" / "No staged
changes", delivered through `QAccessibleAnnouncementEvent` (polite) by the main window.
Announcements are debounced to one per 500 ms so bulk staging doesn't flood screen readers.

### 14.2 Pending tray (`widgets/pending_tray.py`)

- Bottom `QDockWidget` ("Pending changes"), hidden by default, closable, visibility saved.
- `StagedChangesModel(QAbstractTableModel)` over `matrix.get_staged_changes()`, rebuilt on
  `matrixChanged` (debounced 100 ms; 1,000 changes rebuild in ≤ 20 ms per step 1).
- Columns: Change (sentence: "GRANT SELECT on sales.Orders to CORP\jsmith"), Was, Principal,
  Object. Sortable. Filter field above.
- Row actions: **Undo this change** (button in row and Delete key) → `Session.revert_change`;
  double-click or Enter → `Session.revealRequested(cell)` (step 3 scrolls to it; in this step
  the window switches to the Matrix tab and shows status "Cell reveal arrives with the matrix
  view").
- Empty state: "No pending changes. Changes you make in the matrix appear here until you
  commit them."

## 15. Logging and crashes

- Log to `<config dir>/logs/bifrost.log` (same folder as `config.json`, via
  `get_config_directory()`), `RotatingFileHandler` 1 MB × 5, level INFO; DEBUG with
  `BIFROST_DEBUG=1`. Also log to stderr when running from a terminal.
- Log every job start/end with duration, every state transition, every commit (counts only,
  never credentials).
- Never log the connection string or `BIFROST_DEV_SQL_PASSWORD`. Add a test that formats a
  connection error and checks the password isn't in the log output.
- `sys.excepthook` and `threading.excepthook`: log the traceback and show "Something went wrong"
  with the message, a **Copy details** button and the log path. The app keeps running; staged
  changes are untouched.

## 16. Copy rules

- Name things the way an admin does: "principal", "object", "permission", "staged changes",
  "commit". Avoid "assignment", "cell key", "snapshot" in UI text.
- Buttons say what happens: "Commit 12", "Discard 12 changes", "Reconnect now".
- Errors say what went wrong and what to do: "Couldn't connect to sql01: login failed for
  CORP\aadmin. Check that your account has access to FinanceDW." No "Oops", no apologies.
- Numbers use thousands separators (`f"{n:,}"`).

## 17. Matrix placeholder (`views/matrix_placeholder.py`)

States, driven by `Session.state`:

| State | Shows |
|---|---|
| `NEEDS_SETTINGS` | "Set up a connection to get started." [Open settings] |
| `CONNECTING` | "Connecting to sql01/FinanceDW…" with spinner |
| `LOADING` | Stage list (✓ principals 412 · ✓ objects 2,847 · ◌ permissions 120,000 rows · ○ privileges) with progress bar and [Cancel] |
| `FAILED` | Error text, [Retry] [Open settings] |
| `READY` / `COMMITTING` / `OFFLINE` | Summary: principals by type, objects by type, explicit grants/denies, staged count, load time per stage, loaded at. Text: "The new matrix view arrives in the next update. Use `--legacy-tk` to edit permissions until then." |

## 18. Audit log view (`views/audit_view.py`)

Port of `src/ui/views/audit.py`.

```
Principal [________]  Object [________]  Action [All ▾]  From [2026-09-01 ☐]  To [☐]
[Today] [7 days] [30 days] [Any time]                                 [ Search ]
┌───────────────────┬──────────────┬──────────────┬──────────────┬────────┬────────┬──────────────────┐
│ Time (local)      │ Administrator│ Principal    │ Object       │ Perm   │ Action │ Explanation      │
└───────────────────┴──────────────┴──────────────┴──────────────┴────────┴────────┴──────────────────┘
Showing newest 5,000 of 18,422 entries. Narrow the filters to see older ones.   [ Export… ]
```

- Filters: principal contains, object contains, action (All/GRANT/DENY/REVOKE), from/to dates
  with `QDateEdit` + "no limit" checkbox each, quick ranges. Enter in any field searches.
  Typing doesn't auto-search (each search is a DB query).
- Default on first open: last 30 days.
- Fetch via `Session.fetch_audit` (coalesced worker job). Limit 5,000 rows per fetch; show the
  total from `get_audit_entry_count` with the same filters when the limit is hit.
  `get_audit_entry_count` (`src/db/audit.py:422`) currently takes no filters; extend it to
  accept the same filter arguments as `fetch_audit_entries`, sharing the WHERE-clause builder.
- `AuditLogModel(QAbstractTableModel)` + `QSortFilterProxyModel` for column sorting. Timestamps
  stored UTC, shown in local time with the UTC offset in a tooltip.
- Loading state over the table; errors shown inline above the table with Retry.
- Opening the tab, or **View audit log** from a commit dialog, triggers a fetch if connected.
  The commit dialog sets From to the commit start time.
- Read-only. Copy selected rows with Ctrl+C (tab-separated).

## 19. Accessibility checklist for this step (FR-021, FR-024, FR-025)

- [ ] Every action reachable by keyboard; Tab order follows visual order in every dialog.
- [ ] Every interactive widget has an accessible name; icon-only buttons have text alternatives.
- [ ] Focus is always visible (platform focus rect; custom pills draw a 2 px accent ring).
- [ ] Staged count, connection state, load progress and commit outcomes are announced.
- [ ] Field errors are associated with their fields (Settings, Tag names).
- [ ] No information conveyed by colour alone (pills, actions, results).
- [ ] Usable at 200% text scaling at the minimum window size (scroll, not clip).
- [ ] Usable in each Windows High Contrast theme (manual check on the work machine).
- [ ] NVDA smoke test on Windows: launch, connect, open Settings, open Tags, commit preview.

## 20. Tests

Use `pytest-qt`. Set `QT_QPA_PLATFORM=offscreen` in `tests/conftest.py` (skip if already set) so
tests run headless on the Mac, in pre-commit and in CI.

`tests/unit/qt/test_worker.py`
- Jobs run in order on one non-UI thread; callbacks run on the UI thread.
- Errors reach `on_error`; progress reaches `on_progress` in order.
- `coalesce` replaces a queued job of the same name; doesn't touch a running one.
- `cancel` sets the event; `shutdown` cancels queued jobs.

`tests/unit/qt/test_session.py` (fake DB: monkeypatch `create_connection`,
`ensure_audit_log_table`, `fetch_snapshot`, `execute_commit`, `check_grant_privileges`; use a
small synthetic snapshot from step 1)
- Startup: missing config → `NEEDS_SETTINGS` + `settingsRequested`; valid config → `READY`
  with `dataLoaded`.
- Connect failure → `FAILED`, `last_error`, `settingsRequested` for login errors.
- Load cancel on first load → `FAILED`; on refresh → stays `READY` with old data.
- Refresh with staged changes → kept; `restageReport` emitted when some are dropped.
- Commit: < 5 commits directly; ≥ 5 emits `commitPreviewRequested`; privilege failure un-stages
  only failing cells; partial failure keeps failed staged; rollback keeps everything staged;
  connection error during commit → `OFFLINE` + `connectionLost`.
- Editing disabled (`can_edit` false) during `COMMITTING` and `OFFLINE`.
- Heartbeat: skipped while busy; connection error → `connectionLost` once.
- `is_connection_error` classification table.
- Quit: commit-and-quit stays open on failure; quit waits for a running commit.

`tests/unit/qt/test_dialogs.py`
- Settings: validation messages per field; bad port rejected; test result shown only while
  fields match; Save calls `save_settings`; Cancel doesn't.
- Commit preview: row count, filter, summary counts; Commit calls `confirm_commit`.
- Partial failure: Discard failed reverts only failed cells.
- Tag manager: new tag validation; rename; merge prompt; delete confirm counts; picker filters
  thousands of rows.

`tests/unit/qt/test_main_window.py`
- No duplicate shortcuts in the registry; every action has text and an accessible name.
- Enabled states follow section 8.2 for each `SessionState`.
- Title shows `[*]` modified marker when staged > 0.
- Window state round-trips through `QSettings` (use a temp `QSettings` path).

`tests/unit/qt/test_theme.py`
- WCAG contrast for every token pair in light and dark.

Coverage: `src/qt/session.py`, `worker.py`, `actions.py` and `theme.py` ≥ 80%. Dialog and
widget modules are covered by the dialog tests; don't add `src/qt/*` to the coverage `omit`
list.

## 21. Manual test script (BifrostDev)

1. Delete `config.json`; launch → Settings opens with the reason banner.
2. Enter dev settings; Test connection → ✓; Save and connect → loading stages → summary.
3. Run `dev/setup.sh --large` (step 1), Refresh → progress per stage; window stays responsive
   (drag it, open menus) during load.
4. The Qt app can't edit cells until step 3, so launch with `BIFROST_DEV=1` and use
   Help → "Dev: stage sample changes" (section 22) to stage 12 changes. Then: pending pill
   shows 12, tray lists them, undo one from the tray, Review… → preview with 11 rows, Commit →
   result dialog, View audit log → filtered entries.
5. `docker compose ... stop` while idle → within 30 s the Connection lost dialog appears;
   Stay offline → pill shows Offline + Reconnect; start the container; Reconnect → staged
   changes still there.
6. Tags: create a tag, add 3 principals and 50 objects, rename, delete.
7. Export permissions (without NONE) and audit log; open the files.
8. Quit with staged changes → three-way prompt behaves as specified.
9. Switch OS dark mode while running → colours update.
10. Keyboard only: repeat steps 2, 4 and 6 without the mouse.

## 22. Dev helper for staging before step 3

Add a dev-only action, registered in `src/qt/actions.py` only when `BIFROST_DEV=1`:
Help → "Dev: stage sample changes". It asks for a count (default 12) and stages that many random
applicable changes through `PermissionMatrix.stage` as one undo group. This lets the status bar,
tray, preview and commit flows be tested against BifrostDev before the matrix view exists.
Remove it in step 3.

## 23. Acceptance criteria

- [x] `python main.py` opens the Qt app; `python main.py --legacy-tk` opens the Tk app (the Tk
      path was checked by import only, not launched).
- [x] Window is visible within 0.5 s of launch with the config present: 178 ms (log timestamp
      from module import to `show()`, headless on the dev Mac).
- [x] During a load of `seed_large` the UI stays responsive: zero stall warnings (> 100 ms)
      in the log across the smoke runs. Note: `apply_snapshot` runs on the UI thread and took
      about 20 ms for seed_large and 109 ms for the 1,000 × 20,000 synthetic set, so very large
      databases may log one stall at the end of a load. Move the index build off the UI thread in
      step 3 if that shows up at work.
- [ ] Every flow in section 9 works per the manual script (section 21). **Mostly done
      headless**: connect, load with progress, refresh, staging via the dev action, pending
      tray, preview, commit and revert against BifrostDev, audit search, tags and export were
      driven by script and checked in screenshots. Still to do by hand on a desktop: stopping the
      container to trigger the connection-lost dialog, quitting with staged changes, and live
      dark-mode switching.
- [x] All dialogs in section 10 implemented; Tk feature parity for Settings, Tags, Audit,
      Export, Undo/Redo, Commit/Cancel, connection loss.
- [ ] Section 19 accessibility checklist. Built in: accessible names, keyboard-only actions,
      announcements, field-error association, text plus colour everywhere, contrast tests.
      **Needs the work machine**: NVDA smoke test, Windows High Contrast themes, 200% scaling.
- [x] All tests pass headless (328, of which 315 run in the pre-commit selection); `ruff check`
      clean for `src/qt` and Qt tests; coverage: session 84%, worker 95%, actions 100%, theme
      89% (target ≥ 80%).
- [x] README "Running" sections updated for the Qt app and `--legacy-tk`.
- [x] [plan.md](plan.md) status updated.

## 24. Results

Completed 2026-10-01 on branch `002-step2-app-shell`.

### Measured

| Measure | Target | Measured |
|---|---|---|
| Window shown after start | ≤ 0.5 s | 178 ms |
| Connect + load seed_large (506 × 5,007 × 49,246), start to READY | — | 465 ms |
| UI stalls over 100 ms during smoke runs | 0 | 0 |

### Bugs found and fixed during step 2

- **Crash: QObjects destroyed on worker threads.** Two causes, both fixed:
  1. Job callbacks (which hold the `Session`) were released on the worker thread. The worker now
     keeps callbacks in a registry on the UI thread and only sends a job id back
     (`src/qt/worker.py`).
  2. Python's cyclic garbage collector can run on any thread and destroy a QObject there.
     New `src/qt/gc_guard.py` (`UiThreadGarbageCollector`) disables automatic GC and collects
     on the UI thread every second; the Qt tests do the same per test. Before the fix,
     `tests/unit/qt/test_session.py` crashed in every run on its own; after, 10 of 10 runs passed.
- **Pending tray checkmark wrong after restore**: the tray reopened but its menu item wasn't
  ticked, because the window wasn't shown yet when state was restored.
- **Summary labels overlapped** when the staged count changed (old labels were deleted after
  repaint). Labels are now created once and updated.

### Deviations from this spec

- `Session.shutdown(callback)` became `Session.close()`; the quit prompts (commit and quit,
  wait for a running commit) live in `MainWindow.closeEvent`, keeping `Session` free of UI.
- Extra `Session` signals: `busyMessage` (status bar progress), `privilegeDenied`,
  `discardConfirmationRequested`.
- New modules not in the section 3 layout: `src/qt/gc_guard.py`, `src/qt/widgets/tables.py`.
- **File → Export audit log** exports what the Audit tab currently shows; if nothing has been
  searched yet it asks you to search first, instead of fetching with the tab's filters itself.
- **Export permissions** opens a small options dialog (explicit only, or every cell with row
  counts) before the save dialog, instead of a checkbox inside the save dialog (Qt's native save
  dialog can't hold one).
- `PermissionIndex.freeze()` (planned for step 2 in spec 01) is implemented and used by export.
- Ruff ignores `N802`/`N815` under `src/qt/` because Qt overrides and signals use camelCase.
- The light-theme GRANT colour changed from `#1f7a4a` to `#1a6e42` (the first was 4.45:1 on its
  background, just under 4.5:1); staged text `#8a5700` instead of `#a86a00` for the same reason.
- Escape no longer discards (Ctrl+Shift+Delete does), as proposed; still open question 3 in
  the plan until you confirm.

### Not verified here (needs a real desktop or the work machine)

- Dark mode rendering. The headless platform ignores the OS colour-scheme override, so only the
  contrast tests cover the dark tokens.
- NVDA, High Contrast and 200% scaling (section 19).
- Native look on Windows 11 (screenshots were taken on macOS with the Fusion style).
