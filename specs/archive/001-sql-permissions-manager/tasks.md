# Tasks: SQL Server Permissions Manager

**Input**: Design documents from `/specs/001-sql-permissions-manager/`

**Prerequisites**: `plan.md`, `spec.md`, `data-model.md`, `contracts/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] Create root project scaffold and dependency files: `requirements.txt`, `requirements-dev.txt`, `main.py`, `src/`, `tests/`
- [X] T002 [P] Add Python packaging and lint/test config files for the desktop app and test
  harness: `pyproject.toml` with `[project]` metadata, `[tool.pytest.ini_options]` (testpaths,
  addopts, markers for `slow` and `integration`), and `[tool.ruff]` / `[tool.ruff.lint]`
  sections; `requirements.txt` (runtime: pyodbc pinned); `requirements-dev.txt` (dev: pytest,
  pytest-cov, ruff, pre-commit, detect-secrets — all pinned)
- [X] T003 [P] Create `src/__init__.py` and package-level imports for the app module structure
- [X] T004 [P] Configure pre-commit hooks in `.pre-commit-config.yaml` to run ruff (linting), detect-secrets (secret scanning), and pytest on every commit; add `*.env`, `*.pem`, `*.key`, and `config.json` patterns to `.gitignore` before any credential-bearing file is created (Constitution II + Dev Workflow)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core application structure and shared services that all user stories depend on.

- [X] T010 [P] Implement database connection factory in `src/db/connection.py` supporting Windows authentication only
- [X] T011 [P] Implement SQL Server data access modules:
  - `src/db/users.py`
  - `src/db/objects.py`
  - `src/db/permissions.py`
  - `src/db/audit.py`
- [X] T012 [P] Implement domain models in `src/models/`:
  - `user.py`
  - `db_object.py`
  - `permission.py`
  - `audit_entry.py`
  - `config.py`
- [ ] T013 Implement persistence and validation services:
  - `src/services/config.py` for `%APPDATA%\Bifrost\config.json`
  - `src/services/tags.py` for `%APPDATA%\Bifrost\tags.json`
  - `src/validation.py` for config and tag rules
- [ ] T014 Create the in-memory permission matrix and staging engine in `src/services/matrix.py`; include the filter/sort state fields (`search_term: str`, `active_filters: dict`, `sort_key: str`) as defined in data-model.md so Phase 3 view controls (T022a–c) can wire against them; full search/filter/sort logic is implemented in T030/T031
- [ ] T015 Implement UI shell and view lifecycle in `src/ui/app.py`: root Tk window, tab strip wiring, connection-startup flow (load config → connect → show matrix or fall back to Settings on failure), and window resize geometry management
- [ ] T016 Add schema and audit-log creation contract support in `contracts/db-schema.sql` and ensure `src/db/audit.py` can create the configured schema/table on first connection
- [ ] T017 Implement config schema enforcement using `contracts/config-schema.json`
- [ ] T018 Implement tag store schema enforcement using `contracts/tags-schema.json`
- [ ] T019 Add foundational validation unit tests in `tests/unit/test_validation.py` covering: tag format rule (`^[A-Za-z0-9]+$`), config field constraints (non-empty server/port/schema, port in valid range), and search-term boundary cases (empty string, special characters); these MUST pass before any story-phase tests are written (Constitution Principle I — tested as part of Foundational phase)
- [ ] T019a [P] Add unit tests for domain models in `tests/unit/test_models.py`: verify
  `DatabaseUser` and `DatabaseObject` field validation (non-empty login_name, valid
  object_type enum), `PermissionAssignment.has_pending_change` derived field, `StagedChange`
  action derivation (GRANT/DENY/REVOKE), `Configuration` serialise/deserialise round-trip
  with all fields present and with optional fields absent; confirm `PermissionState` cycle
  order (NONE→GRANT→DENY→NONE) (Constitution Principle I — models must be tested before use)
- [ ] T019b [P] Add unit tests for persistence services in `tests/unit/test_services.py`:
  `src/services/config.py` — load from valid JSON, load from missing file (returns default),
  load from corrupt JSON (raises recoverable error), save round-trip; `src/services/tags.py`
  — load from missing file (returns empty TagStore), load from valid tags.json, save and
  reload; mock filesystem with `tmp_path`; verify no live DB required (Constitution Principle I)

---

## Phase 3: User Story 1 - Permission Matrix (Priority: P1) 🎯

**Goal**: Build the staged, commit/cancel permission matrix UI and commit engine.

**Independent Test**: Open the matrix, toggle permission cells, stage changes, commit or cancel, and verify state updates and audit entries.

- [ ] T020 [US1] Implement `PermissionAssignment` state transitions and staged-change tracking in `src/services/matrix.py`
- [ ] T021 [US1] Implement commit and cancel behavior in `src/services/matrix.py` using `src/db/permissions.py`; at commit time auto-generate the `explanation` field for each `AuditEntry` from its captured fields per FR-012 (e.g., `"GRANT SELECT on dbo.Orders to jsmith"`, `"REVOKE DELETE on dbo.Products from mjones"`); add assertions in `tests/unit/test_audit.py` verifying the correct explanation string for GRANT, DENY, and REVOKE actions
- [ ] T021a [US1] Implement commit preview dialog per FR-026 and ui-spec.md §1.3a: modal dialog showing up to 3 staged changes by default with collapsible "Show all [N] changes" expansion; each change displays permission action (GRANT/DENY/REVOKE), affected user, target object, and previous state; provide [Review in Matrix] (closes dialog, highlights staged cells with yellow glow), [Commit All] (applies changes to database), and [Cancel] buttons; on successful commit, display confirmation summary with [View Audit Log] and [Close] buttons; implement keyboard navigation (Enter=Commit All, Escape=Cancel, Tab between buttons); focus management (opens with focus on Commit All, closes returning focus to last focused cell)
- [ ] T022 [US1] Implement the unified Matrix View tab and view controls in `src/ui/app.py` per ui-spec.md §1.2: single "Matrix View" tab with user selector dropdown, "Show: ● Single user / ○ All users (compare)" radio toggle, and object selector dropdown (active in Single user mode only); add orientation banner below controls showing current context ("Viewing: jsmith's permissions across 500 objects | Filtered by tag: finance | 12 of 500 objects visible | 3 staged changes"); implement tab strip with Matrix View and Audit Log tabs plus [Export ▼] dropdown; add shared global status bar (staged-change count, Commit, Cancel, connection identity); Commit and Cancel MUST be disabled when no changes are staged (FR-002a); keyboard shortcuts: `Ctrl+1` (Matrix View), `Ctrl+4` (Audit Log), `Ctrl+U` (focus user selector), `Ctrl+O` (focus object selector), `Ctrl+Shift+C` (toggle Single/All users mode), `Ctrl+Enter` (Commit), `Escape` (Cancel)
- [ ] T022a [US1] Implement Single User mode in `src/ui/matrix_view.py`: Canvas-based virtual scrolling grid with objects as rows and 8 permission columns; displays permissions for the selected user across all objects; search, tag, object-type, and sort controls; object-type icons and permission-column icons per ui-spec.md §3; tags displayed inline next to object name; wired to user selector dropdown from T022; activated when "Single user" radio is selected
- [ ] T022b [US1] Implement All Users (Compare) mode in `src/ui/matrix_view.py`: Canvas-based virtual scrolling grid with objects as rows and user column groups (8 sub-columns each); frozen object column; search, tag, type, and dual-axis sort controls per ui-spec.md §4; implement pagination controls per FR-028: default 10 users per page with [First 10] / [Next 10] / [Previous 10] / [All ▼] navigation buttons, dropdown options for 5/10/20 users per page or all users, user pinning functionality with [+] button to mark frequently accessed users (persist pinned users to tags.json or separate config), and pagination state display in orientation banner ("Showing users 1-10 of 47"); visual grouping via zebra striping or subtle borders between user column groups; activated when "All users (compare)" radio is selected
- [ ] T022c [US1b] Implement Object View mode in `src/ui/matrix_view.py`: Canvas-based permission matrix with users in rows and all 8 permission types (SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION) in columns; only applicable permission columns displayed per object type (e.g., EXECUTE hidden for tables); click-to-cycle cell interaction (none → GRANT → DENY → none) with staging; cross-query highlighting on column/row headers; [🏷 Tags] and [📝] description editor buttons; search field filtering user rows live, tag filter dropdown, and user-name sort control per ui-spec.md §5; keyboard shortcut `Ctrl+O` focuses object selector (not `Alt+O`); activated by selecting an object from the object selector in Single user mode
- [ ] T023 [US1] Implement cell click-to-cycle interaction with click-hold preview tooltip per FR-027 and ui-spec.md §2.4: on mouse-down (before release) display tooltip showing next state in cycle ("Click to change to GRANT", "Click to cycle to DENY", "Click to clear permission") with 100ms delay to prevent flicker on quick clicks; on mouse-up apply the staged change; ESC key during mouse-down cancels action without staging; also implement right-click context menu (Set to GRANT / DENY / Clear; separator; View This User / View This Object) in the shared Canvas cell renderer used by all matrix modes; ensure cycle order starts from committed state not staged state
- [ ] T024 [US1] Implement failed commit handling: report per-change failures and revert failed cells to last committed state (FR-018); include the offline-commit scenario — when Commit is pressed while disconnected, the entire commit fails gracefully with a clear message and all staged changes remain intact for retry; add test cases in `tests/unit/test_matrix.py` covering partial DB failure and full offline failure
- [ ] T025 [US1] Add status indicator for pending changes in `src/ui/widgets/status_bar.py`
- [ ] T026 [US1] Add unit tests for staging logic, commit/cancel semantics, and state visual
  flags in `tests/unit/test_matrix.py`; include an explicit SC-002 interaction-count test:
  starting from a loaded matrix, simulate the minimum path to a committed change — (1) stage
  one cell via `matrix.stage_change()`, (2) call `matrix.commit()` — and assert (a) the entire
  sequence completes in ≤2 programmatic steps with no intermediate mandatory prompts, and
  (b) explicitly verify the interaction count is ≤4 as required by SC-002; document in the
  test docstring that the UI realizes this as: toggle cell → press Ctrl+Enter (2 user
  interactions, well within the SC-002 ≤4 limit) (SC-002)
- [ ] T027 [US1] Implement manual refresh control in `src/ui/app.py` (title-bar `[🔄 Refresh]` button, keyboard shortcut `F5` per ui-spec.md §1.1) wired to `src/services/matrix.py` to re-fetch authoritative permission state; staged changes are preserved during refresh
- [ ] T028 [US1] Implement object-type and permission-type icon rendering per ui-spec.md §2.1–2.2: object-type icons in the frozen object column of `src/ui/matrix_view.py` (both Single User and All Users modes); permission-type icons and 3-letter abbreviations in column headers of `src/ui/matrix_view.py` (all three modes); cell-state icon overlays in `src/ui/widgets/cell_renderer.py`
- [ ] T029 [US1] Add explicit keyboard navigation and accessibility handling for Phase 3 matrix modes and shared widgets: arrow-key cell navigation in all matrix modes (`Ctrl+Right/Left` for user-group jumps or page navigation in All Users mode, `Home`/`End` per ui-spec.md §3-5, `Page Up/Down` for user page navigation in Compare mode); view control shortcuts `Ctrl+U` (focus user selector), `Ctrl+O` (focus object selector), `Ctrl+Shift+C` (toggle Single user / All users mode) in `src/ui/app.py` per ui-spec.md §1.2; tab-strip shortcuts `Ctrl+1` (Matrix View), `Ctrl+4` (Audit Log), `Ctrl+Enter` (Commit), `Escape` (Cancel) in `src/ui/app.py`; tag editor Tab order and rename focus in `src/ui/widgets/tag_editor.py`; add test cases covering Tab order, Enter/Space activation, and focus-indicator visibility for these views per ui-spec.md §2.11 (FR-021, SC-006)
- [ ] T029a [US1] Implement cross-query highlighting (FR-003, FR-025): when a user, object, or permission type cell is selected in the matrix, visually highlight all other cells that share that user/object/permission in their committed state; include non-visual indicators (screen reader announcements, status messages) per ui-spec.md §2.5; provide a keyboard shortcut and a clear-highlight control; add test cases in `tests/unit/test_matrix.py` asserting the correct cell set is highlighted and clearing restores the default view (FR-003, US1 scenario 6)
- [ ] T029b [US1] Implement accessibility enhancements for cell states (FR-024, FR-025): add non-color indicators (✓ checkmark for GRANT, ✗ X mark for DENY, ─ dash for none, * asterisk prefix for staged changes) with NO LETTER SUFFIXES (simplified encoding per ui-spec.md §2.3) to cell rendering in `src/ui/widgets/cell_renderer.py`; use approved color palette (#006400 green, #B22222 red, #767676 grey for committed states, #FFEB3B bright yellow for staged states) verified to meet WCAG AA contrast requirements per ui-spec.md §2.3, §2.10; ensure all cell state changes announce full context to screen readers ("GRANT SELECT for jsmith on dbo.Orders"); staged cells display bright yellow background (#FFEB3B) with subtle pulsing animation (2-second cycle, respects reduced-motion preference)
- [ ] T029c [US1] Implement visible focus indicators on all interactive elements (FR-025): 2px solid border in system accent color (#0078D4) with 3:1 minimum contrast and 2px offset per ui-spec.md §2.8; apply to all matrix cells, buttons, form inputs, tabs, column/row headers, tag chips, and menu items; test focus visibility with keyboard-only navigation (Tab key test)
- [ ] T029d [US1] Implement accessible names for all icons and buttons (FR-024, FR-025): set accessible names for object type icons ("Table: dbo.Customers"), permission column headers ("SELECT column header, sortable and filterable"), and all icon-only buttons (Refresh, Settings, Tags, Edit Description) per ui-spec.md §1.1, §2.1, §2.2; ensure tooltips appear on both hover AND keyboard focus

---

## Phase 4: User Story 2 - Search, Filter & Sort (Priority: P2)

**Goal**: Make the matrix navigable at scale with search, object/user filtering, and sortable axes.

**Independent Test**: Apply search, permission filters, and sort controls on a large dataset and verify the displayed subset.

- [ ] T030 [US2] Implement search and filter state in `src/services/matrix.py`
- [ ] T031 [US2] Implement sort state and ordering for users/objects in `src/services/matrix.py`
- [ ] T032 [US2] Wire the search, filter, and sort service state (T030, T031) to the controls in `src/ui/matrix_view.py` (all three perspective modes: Single User, All Users, Object View); verify live-update behaviour within the 1-second constraint (SC-003) and confirm the [Clear] button resets all active filters and sort to defaults (US2 scenario 4)
- [ ] T033 [US2] Add tests for search, filter, and sort behavior in `tests/unit/test_matrix.py`

---

## Phase 5: User Story 3 - Tag and Metadata Management (Priority: P3)

**Goal**: Add local tag assignment, tag filtering, and object descriptions.

**Independent Test**: Tag users and objects, filter the matrix by tag, and save/reload object descriptions.

- [ ] T040 [US3] Implement `TagStore` CRUD and validation in `src/services/tags.py`
- [ ] T041 [US3] Implement object description load/save via `src/db/objects.py`
- [ ] T042 [US3] Add tag editor UI in `src/ui/widgets/tag_editor.py` per ui-spec.md §8: tag chips with `×` remove button; add-tag field with `^[A-Za-z0-9]+$` inline validation; rename by double-clicking a chip (editable inline; Enter commits, Escape cancels); modal dialog with keyboard-accessible `[Close]` / `Escape`; focus returns to the opener on close
- [ ] T043 [US3] Integrate tag filtering into `src/ui/matrix_view.py` (all three perspective modes): populate the tag filter dropdown from `TagStore` (T040) and apply selections to the service-layer filter state (T030)
- [ ] T044 [US3] Add tests for tag validation, local persistence, tag filtering, and rename in `tests/unit/test_tags.py`: valid/invalid format (`^[A-Za-z0-9]+$`), duplicate-insensitive add (case-insensitive deduplication), remove, rename (case-preservation verified), and round-trip persistence to `tags.json` after each mutation
- [ ] T045 [US3] Add object description tests in `tests/unit/test_objects.py`: verify save via `sys.extended_properties` (`MS_Description`), round-trip retrieval after app restart, correct handling of empty/null descriptions, and rejection of descriptions exceeding SQL Server's extended-property length limit
- [ ] T046 [US3] Add object description editor UI inline in `src/ui/matrix_view.py` (Object View mode) per ui-spec.md §9: expands below the object selector when [📝] is clicked; free-text area; `[Save Description]` calls `src/db/objects.py` (T041); `Ctrl+Enter` saves; `Escape`/`[Cancel]` collapses without saving; no separate widget file

---

## Phase 6: User Story 4 - Audit Log Review (Priority: P4)

**Goal**: Provide a browsable audit log with date/user/object filters.

**Independent Test**: View the audit log and verify filter results for date range, user, and object.

- [ ] T050 [US4] Implement audit log query support in `src/db/audit.py`
- [ ] T051 [US4] Add audit log viewer in `src/ui/audit_view.py`
- [ ] T051a [US4] Add keyboard navigation for `src/ui/audit_view.py`: Tab order across date-range fields, User and Object dropdowns, column sort headers, and Export CSV button; Enter to apply filters; keyboard-accessible row expansion to show full explanation, previous state, and new state per ui-spec.md §6 (FR-021)
- [ ] T052 [US4] Add date/user/object filter controls in `src/ui/audit_view.py`
- [ ] T053 [US4] Add unit/integration tests for audit log retrieval and filtering in `tests/unit/test_audit.py`

---

## Phase 7: User Story 5 - CSV Report Export (Priority: P5)

**Goal**: Export current permission state and audit log entries to CSV.

**Independent Test**: Export both reports and verify headers, row counts, and formatting.

- [ ] T060 [US5] Implement permission and audit CSV export in `src/services/export.py`
- [ ] T061 [US5] Add export controls: the `[Export ▼]` dropdown in the tab strip (`src/ui/app.py`, per ui-spec.md §1.2 and §11) with options *Permission Matrix as CSV* and *Audit Log as CSV*, each opening a system Save As dialog with a suggested filename; add the inline `[Export CSV]` button in `src/ui/audit_view.py` (per ui-spec.md §6) that exports only the currently filtered audit entries
- [ ] T062 [US5] Ensure CSV export runs without blocking the UI thread
- [ ] T063 [US5] Add tests for CSV format, headers, and row data in `tests/unit/test_export.py`

---

## Phase 8: User Story 6 - Application Configuration (Priority: P6)

**Goal**: Save and load database connection configuration, with startup recovery from missing/corrupt config.

**Independent Test**: Save config, restart app, confirm automatic connection or settings fallback.

- [ ] T070 [US6] Implement settings form and config persistence in `src/ui/settings_view.py` and `src/services/config.py`
- [ ] T070a [US6] Add keyboard navigation for `src/ui/settings_view.py`: Tab order through Server → Port → Database → Schema → Auth fields; Enter on `[Test Connection]` and `[Save]`; Escape navigates back to the last active matrix view per ui-spec.md §7 (FR-021)
- [ ] T071 [US6] Add startup config load logic and corrupt-file recovery in `src/ui/app.py`
- [ ] T072 [US6] Add validation and clear error messages for invalid config fields in `src/validation.py`
- [ ] T073 [US6] Add tests for config serialization, corrupt config handling, and startup fallback in `tests/unit/test_config.py`

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Final quality work and platform readiness across all stories.

- [ ] T080 [P] Implement application-wide error handling and user-facing database error messages
- [ ] T081 [P] Add reconnection detection and preservation of staged changes during connection loss per ui-spec.md §10: status bar shows `⚠ Connection lost — [Reconnect]`, matrix cells are disabled, Commit shows an error if attempted while disconnected, staged changes are preserved in memory; add a unit test in `tests/unit/` using a mock pyodbc connection that raises `pyodbc.OperationalError` to assert detection triggers within 5 seconds and that staged changes remain intact after a failed commit (SC-008)
- [ ] T082 [P] Profile matrix load and CSV export using `cProfile` + `pstats` on a synthetic
  200-user × 500-object fixture; identify any single call-site consuming >20% of total time;
  document top-3 bottlenecks and any applied optimisations in a `## Performance Notes` section
  appended to `specs/001-sql-permissions-manager/quickstart.md`; no code change required if
  all timing assertions in T082a already pass on the target machine
- [ ] T082a [P] Add timing-assertion tests for SC-001, SC-003, and SC-007 in `tests/unit/test_matrix.py`: use `time.perf_counter` around the in-memory filter/sort application with a synthetic 200-user × 500-object fixture to assert filter results appear within 1 second (SC-003) and matrix state is ready within 2 seconds (SC-001); add a separate assertion that no single render call blocks longer than 1 second (SC-007); annotate with `@pytest.mark.slow` so the pre-commit hook can skip them while CI runs them unconditionally
- [ ] T083 [P] Add documentation updates to `specs/001-sql-permissions-manager/quickstart.md`
- [ ] T084 [P] Add additional unit tests to meet the 80% coverage goal in `tests/unit/`
- [ ] T085 [P] Validate the feature against `contracts/` and `data-model.md` before merge
- [ ] T086 [P] Write integration tests in `tests/integration/test_db.py` covering: connection factory (T010), permission reads via `sys.database_permissions` (T011), GRANT/DENY/REVOKE round-trips, and audit log write/read; annotate with `pytest.mark.integration` and document the live SQL Server requirement in `quickstart.md` (Constitution Principle I — all production DB code must have test coverage)
- [ ] T087 [P] Implement screen reader live regions and announcements (FR-025): add live region support via Tkinter accessibility APIs or Windows UI Automation for: (a) staged change counter (status/polite role, "3 changes staged"), (b) search/filter results (status/polite, "Showing 12 of 47 objects"), (c) connection status (alert/assertive, "Connection lost. Staged changes preserved."), (d) commit/save success (status/polite), (e) error messages (alert/assertive), (f) cross-query highlighting (status/polite, "Showing 12 objects with filter active") per ui-spec.md §2.9; test with NVDA or Windows Narrator
- [ ] T088 [P] Implement proper error message association for form fields (FR-025): in Settings screen (`src/ui/settings_view.py`) and Tag Editor (`src/ui/widgets/tag_editor.py`), use aria-describedby or Tkinter equivalent to programmatically link error messages to fields; set aria-invalid=true on validation failure; display error summary at top of form with role=alert; move focus to first invalid field on submit; test that screen readers announce field label + error message when field receives focus per ui-spec.md §7, §8
- [ ] T089 [P] Implement Windows High Contrast mode support (FR-025): detect Windows High Contrast setting on startup via Windows API; replace custom colors with system colors (SystemColors.Window, WindowText, ButtonFace, Highlight); preserve non-color indicators (✓, ✗, ─, *); increase border thickness to 2px minimum; test with all 4 Windows High Contrast themes (Black, White, #1, #2) per ui-spec.md §2.12
- [ ] T090 [P] Implement reduced motion support (FR-025): detect Windows "Show animations" setting or prefers-reduced-motion preference via Windows API; when reduced motion enabled, disable all animations and transitions (cross-query fade, status message slide, dropdown animation, dialog fade, row expansion, cell state transitions); verify instant updates without animation per ui-spec.md §2.13
- [ ] T091 [P] Implement text scaling support (FR-025): use relative font sizing in Tkinter (font scaling vs fixed px); test at 150% and 200% Windows text scale; verify no text clipping, element overlap, or horizontal scrolling in main content flow; verify all interactive elements maintain minimum 44×44px touch target size; matrix columns may reflow at higher scales per ui-spec.md §2.14
- [ ] T092 [P] Implement semantic heading structure (FR-025): assign heading roles and levels via Tkinter accessibility properties or Windows UI Automation: H1 for application title ("Bifrost - SQL Server Permission Manager for [Database]"), H2 for active tab name ("User View" / "Compare View" / etc.), H3 for section headers ("Filter Controls", "Permission Matrix", "Connection Settings"); H1 for dialog titles; test screen reader heading navigation (H key, 1-6 keys) per ui-spec.md §2.15
- [ ] T093 [P] Add comprehensive accessibility tests in `tests/unit/test_accessibility.py`: (a) focus indicator visibility on all interactive elements, (b) color contrast ratios meet WCAG AA (test approved palette with contrast checker library), (c) accessible names present for all icons and buttons, (d) live region announcements trigger on dynamic updates (mock screen reader), (e) error messages properly associated with fields, (f) keyboard-only navigation completes all primary tasks (automated Tab order test), (g) text scales to 200% without loss of functionality
- [ ] T094 [P] Update Phase 3 keyboard navigation tests to include skip navigation shortcuts (FR-025): add test cases in `tests/unit/test_matrix.py` for Ctrl+M (skip to matrix), Ctrl+F (skip to filters), Ctrl+Home/End (jump to matrix edges), Page Up/Down (navigate by page), Ctrl+Arrow (jump to data edge); verify context menu keyboard access (Shift+F10, Menu key) and direct shortcuts (G/D/Delete keys on cells, Ctrl+Shift+U/O for view switching) per ui-spec.md §2.11
- [ ] T095 [P] Implement typography scale system (ui-spec.md §2.0): create `src/ui/typography.py` with constants for font families, sizes, weights, line heights, and letter spacing; define H1 (20pt bold), H2 (16pt semibold), H3 (14pt semibold), Body (12pt regular), Label (11pt semibold), Small (10pt regular), Code (Consolas 11pt); apply consistently across all UI components (app.py, matrix_view.py, audit_view.py, settings_view.py, all widgets); verify text hierarchy is visually clear and scales properly with Windows text scaling (150%, 200%)
- [ ] T096 [P] Implement loading and progress states (ui-spec.md §2.17): add loading indicators for (a) initial matrix load (skeleton grid with pulsing cells OR progress bar with "Loading permission matrix..." message and percentage), (b) commit in progress (modal overlay with spinner + "Applying 5 changes..." message), (c) reconnection (spinner in status bar), (d) CSV export progress (modal dialog with percentage bar, row count, [Cancel] button); all loading states MUST respect reduced-motion preference (static icons vs animations); include screen reader announcements for all loading states; implement in `src/ui/widgets/loading.py` and integrate into relevant views
- [ ] T097 [P] Implement empty state designs (ui-spec.md §2.18): add empty state screens for (a) no search/filter results (icon + "No objects match your filters" + active filter list + [Clear Filters] button), (b) no users in database (icon + "No database users found" + guidance + [Open Settings] button), (c) no objects in database (icon + message), (d) connection failed (warning icon + error message + [Retry] and [Open Settings] buttons); all empty states MUST include screen reader announcements (role=alert or status) and keyboard-accessible action buttons; implement in `src/ui/widgets/empty_state.py` and integrate into matrix_view.py, audit_view.py, and app.py startup flow
- [ ] T098 [P] Implement undo/redo functionality (FR-029, ui-spec.md §2.19): add undo stack (max 50 entries) to `src/services/matrix.py` tracking cell state changes (user, object, permission, old state, new state, timestamp); wire `Ctrl+Z` (undo) and `Ctrl+Y`/`Ctrl+Shift+Z` (redo) keyboard shortcuts in `src/ui/app.py`; on undo/redo, revert cell to previous state, update staged change counter, display status bar message ("Undone: dbo.Orders SELECT for jsmith GRANT → none"), and announce via screen reader live region (polite); clear stack on commit or cancel; preserve stack across view switches; add Edit menu items (optional) with Undo/Redo commands showing keyboard shortcuts; test undo/redo with 50+ changes to verify stack limit
- [ ] T099 [P] Implement cancel confirmation dialog (ui-spec.md §1.3): when administrator presses Cancel or Escape with ≥5 staged changes, display modal confirmation dialog: "Discard 12 staged changes? This action cannot be undone. [Discard Changes] [Keep Editing]"; for <5 changes, cancel immediately without confirmation (quick cancel workflow); dialog MUST be keyboard accessible (Escape = Keep Editing, Enter = Discard Changes, Tab navigates buttons); implement in `src/ui/widgets/confirmation_dialog.py` and wire to Cancel button and Escape key handler in `src/ui/app.py`; add unit test in `tests/unit/test_matrix.py` verifying threshold logic (4 changes = no confirmation, 5 changes = confirmation shown)
- [ ] T100 [P] Implement privilege validation at staging time (FR-017a): on first cell toggle in each session, query administrator's own permission set from `sys.database_permissions` and cache in memory; before staging any GRANT change, validate administrator possesses that permission themselves; if validation fails, display warning dialog: "You cannot grant SELECT on dbo.Orders because you do not have this permission yourself. Contact a database owner or sysadmin. [OK]"; change is not staged; validation cache refreshed on manual refresh (F5); implement in `src/services/matrix.py` with validation method and `src/ui/widgets/warning_dialog.py` for warning display; add unit test in `tests/unit/test_matrix.py` with mocked permission set
- [ ] T101 [P] Implement partial commit failure dialog (ui-spec.md §1.3b): when commit operation completes with some successes and some failures, display modal dialog showing: success list with green checkmarks, failure list with red X marks and specific error reasons, summary count (e.g., "3 of 5 changes applied successfully. 2 changes failed"); provide [View Audit Log], [Retry Failed], [Discard Failed] buttons; after [Retry Failed], keep only failed cells staged with red outline (#B22222, 2px) over yellow background, hover tooltip shows full error; implement in `src/ui/widgets/commit_failure_dialog.py` and wire to commit logic in `src/services/matrix.py`; include screen reader announcements via live region (alert/assertive); add unit test simulating partial failure scenario
- [ ] T102 [P] Implement help system (ui-spec.md §1.4): add [?] button to title bar opening slide-in help panel (400px wide, right side, non-modal); help panel contains: Quick Reference (GRANT/DENY/none definitions), expandable Keyboard Shortcuts section (organized by category), expandable Common Tasks section (3-5 step instructions), expandable Troubleshooting section (FAQ-style); all sections collapsible with ▼/▶ indicators; keyboard accessible (F1/Ctrl+H to open, Escape/× to close, Tab through sections, Enter/Space to expand/collapse); implement in `src/ui/widgets/help_panel.py` with markdown-based content stored in `src/ui/help_content.md`; include first-run tutorial overlay (5 steps, dismissible, preference to show/hide); add help button and panel integration to `src/ui/app.py`
- [ ] T103 [P] Implement active mode indicator (ui-spec.md §1.2): add visual banner below view controls showing current mode with icon (📊 Single User, 👥 All Users, 📋 Object View), mode name (H3), and plain language subtitle; blue left border (4px, #0078D4), light blue background tint (#F0F8FF); update on view mode changes with screen reader announcement: "Switched to Single User Mode. Showing jsmith's permissions across all database objects"; implement in `src/ui/matrix_view.py` with live region announcement; include in all three perspective modes; test screen reader announcements with NVDA
- [ ] T104 [P] Implement bulk cell selection and bulk actions (FR-031, ui-spec.md §2.4): add click-drag for contiguous range selection, Ctrl+click for multi-select, Shift+Arrow keys for keyboard selection; visual feedback with blue outline (#0078D4, 2px) on selected cells; maximum 1000 cells per selection; right-click on selection shows context menu with "Set all [N] selected cells to GRANT/DENY/none"; confirmation dialog when ≥5 cells: "Apply GRANT SELECT to 24 selected cells? This will stage 24 changes. [Apply] [Cancel]" (FR-030); selection cleared on commit/cancel/view switch/Escape; implement in `src/ui/widgets/cell_renderer.py` with selection state tracking in `src/services/matrix.py`; add unit test for selection logic and bulk application; include screen reader announcement: "[N] cells selected. Right-click for bulk actions"
- [ ] T105 [P] Implement user-friendly label preference (ui-spec.md §2.3a): add Settings screen checkbox "☐ Use simplified permission labels" with help text; when enabled, cell tooltips and screen reader announcements use "Allowed" (GRANT), "Blocked" (DENY), "Not Set" (none) instead of SQL terms; column headers and symbols unchanged; audit log and CSV exports always use SQL terms for technical accuracy; preference persisted to config.json; implement toggle logic in `src/ui/settings_view.py` and vocabulary switching in `src/ui/widgets/cell_renderer.py`; test with screen reader to verify announcements use selected vocabulary
- [ ] T106 [P] Implement additional progress indicators (ui-spec.md §2.17): (a) search progress: inline spinner (⏳) in search field for queries >1 second with "Searching 500 objects..." message and pulsing blue border animation, (b) large commit progress: for commits >50 changes, show modal progress dialog with percentage bar, change count ("Committing change 23 of 87..."), estimated time remaining, and "Do not close" warning (non-cancellable); both states respect reduced-motion preference; implement in `src/ui/widgets/progress_indicators.py` and integrate into `src/services/matrix.py` (commit) and `src/ui/matrix_view.py` (search); include screen reader announcements for progress updates
- [ ] T107 [P] Update express mode commit logic (ui-spec.md §1.3a): when <5 changes staged, commit immediately without showing preview dialog (express mode for quick workflows); when ≥5 changes, show commit preview dialog (existing behavior); add Settings preference: "Always show commit preview" checkbox to override express mode and show preview for all commits; implement threshold check in `src/ui/app.py` commit handler; add unit test verifying express mode triggers for 1-4 changes and preview shows for 5+ changes; ensure preference persisted to config.json
- [ ] T108 [P] Add mass change confirmation dialog (FR-030): when bulk action would affect ≥5 cells (via right-click menu on selection, column header operation, or other bulk operation), display confirmation: "Apply GRANT SELECT to 247 objects for jsmith? This will stage 247 changes. [Apply] [Cancel]"; dialog shows exact cell count and affected scope; confirmation threshold matches other thresholds (Cancel, Commit preview) for consistency; implement in `src/ui/widgets/bulk_confirmation_dialog.py` and wire to all bulk operation entry points; add unit test verifying threshold logic (4 cells = no confirmation, 5 cells = confirmation shown)
