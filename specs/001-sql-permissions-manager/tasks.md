# Tasks: SQL Server Permissions Manager

**Input**: Design documents from `/specs/001-sql-permissions-manager/`

**Prerequisites**: `plan.md`, `spec.md`, `data-model.md`, `contracts/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 [P] Create root project scaffold and dependency files: `requirements.txt`, `requirements-dev.txt`, `main.py`, `src/`, `tests/`
- [ ] T002 [P] Add Python packaging and lint/test config files for the desktop app and test
  harness: `pyproject.toml` with `[project]` metadata, `[tool.pytest.ini_options]` (testpaths,
  addopts, markers for `slow` and `integration`), and `[tool.ruff]` / `[tool.ruff.lint]`
  sections; `requirements.txt` (runtime: pyodbc pinned); `requirements-dev.txt` (dev: pytest,
  pytest-cov, ruff, pre-commit, detect-secrets — all pinned)
- [ ] T003 [P] Create `src/__init__.py` and package-level imports for the app module structure
- [ ] T004 [P] Configure pre-commit hooks in `.pre-commit-config.yaml` to run ruff (linting), detect-secrets (secret scanning), and pytest on every commit; add `*.env`, `*.pem`, `*.key`, and `config.json` patterns to `.gitignore` before any credential-bearing file is created (Constitution II + Dev Workflow)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core application structure and shared services that all user stories depend on.

- [ ] T010 [P] Implement database connection factory in `src/db/connection.py` supporting Windows authentication only
- [ ] T011 [P] Implement SQL Server data access modules:
  - `src/db/users.py`
  - `src/db/objects.py`
  - `src/db/permissions.py`
  - `src/db/audit.py`
- [ ] T012 [P] Implement domain models in `src/models/`:
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
- [ ] T022 [US1] Implement the tab strip (User View / Compare / Object View / Audit Log) and shared global status bar (staged-change count, Commit, Cancel, connection identity) in `src/ui/app.py`; Commit and Cancel MUST be disabled when no changes are staged (FR-002a); keyboard shortcuts `Ctrl+1–4`, `Ctrl+Enter`, `Escape` wired here
- [ ] T022a [US1] Implement User View in `src/ui/user_view.py`: Canvas-based virtual scrolling grid with objects as rows and 8 permission columns; user selector dropdown; search, tag, object-type, and sort controls; object-type icons and permission-column icons per ui-spec.md §3; tags displayed inline next to object name
- [ ] T022b [US1] Implement Compare View in `src/ui/compare_view.py`: Canvas-based virtual scrolling grid with objects as rows and all users as horizontally-scrollable column groups (8 sub-columns each); frozen object column; search, tag, type, and dual-axis sort controls per ui-spec.md §4
- [ ] T022c [US1] Implement Object View in `src/ui/object_view.py`: object selector (`Alt+O`) and permission-type selector (`Alt+P`) dropdowns (only applicable permissions enabled per object type); user list split into explicit-assignment and no-assignment sections with a labelled separator; per-row state dropdown (GRANT / DENY / none) that stages changes immediately; [+ Add User...] picker defaulting to GRANT; [🏷 Tags] and [📝] description editor buttons; search field filtering the user list live, tag filter dropdown, and user-name sort control per ui-spec.md §5
- [ ] T023 [US1] Implement cell click-to-cycle interaction (none → GRANT → DENY → none) and right-click context menu (Set to GRANT / DENY / Clear; Switch to User View; Switch to Object View) in the shared Canvas cell renderer used by User View and Compare View
- [ ] T024 [US1] Implement failed commit handling: report per-change failures and revert failed cells to last committed state (FR-018); include the offline-commit scenario — when Commit is pressed while disconnected, the entire commit fails gracefully with a clear message and all staged changes remain intact for retry; add test cases in `tests/unit/test_matrix.py` covering partial DB failure and full offline failure
- [ ] T025 [US1] Add status indicator for pending changes in `src/ui/widgets/status_bar.py`
- [ ] T026 [US1] Add unit tests for staging logic, commit/cancel semantics, and state visual
  flags in `tests/unit/test_matrix.py`; include an SC-002 interaction-count test: starting
  from a loaded matrix, simulate the minimum path to a committed change — (1) stage one cell
  via `matrix.stage_change()`, (2) call `matrix.commit()` — and assert the entire sequence
  completes in ≤2 programmatic steps with no intermediate mandatory prompts; document in the
  test docstring that the UI realises this as: toggle cell → press Ctrl+Enter (2 interactions,
  well within the SC-002 ≤4 limit) (SC-002)
- [ ] T027 [US1] Implement manual refresh control in `src/ui/app.py` (title-bar `[🔄 Refresh]` button, keyboard shortcut `F5` per ui-spec.md §1.1) wired to `src/services/matrix.py` to re-fetch authoritative permission state; staged changes are preserved during refresh
- [ ] T028 [US1] Implement object-type and permission-type icon rendering per ui-spec.md §2.1–2.2: object-type icons in the frozen object column of `src/ui/user_view.py` and `src/ui/compare_view.py`; permission-type icons and 3-letter abbreviations in column headers of `src/ui/user_view.py` and `src/ui/compare_view.py`; cell-state icon overlays in `src/ui/widgets/cell_renderer.py`
- [ ] T029 [US1] Add explicit keyboard navigation and accessibility handling for Phase 3 views and shared widgets: arrow-key cell navigation in `src/ui/user_view.py` and `src/ui/compare_view.py` (`Ctrl+Right/Left` for user-group jumps, `Home`/`End` per ui-spec.md §4); Object View selector shortcuts `Alt+O`/`Alt+P` in `src/ui/object_view.py` per ui-spec.md §5; tab-strip shortcuts `Ctrl+1`–`Ctrl+4`, `Ctrl+Enter` (Commit), `Escape` (Cancel) in `src/ui/app.py`; tag editor Tab order and rename focus in `src/ui/widgets/tag_editor.py`; add test cases covering Tab order, Enter/Space activation, and focus-indicator visibility for these views per ui-spec.md §12 (FR-021, SC-006)
- [ ] T029a [US1] Implement cross-query highlighting (FR-003): when a user, object, or permission type cell is selected in the matrix, visually highlight all other cells that share that user/object/permission in their committed state; provide a keyboard shortcut and a clear-highlight control; add test cases in `tests/unit/test_matrix.py` asserting the correct cell set is highlighted and clearing restores the default view (FR-003, US1 scenario 6)

---

## Phase 4: User Story 2 - Search, Filter & Sort (Priority: P2)

**Goal**: Make the matrix navigable at scale with search, object/user filtering, and sortable axes.

**Independent Test**: Apply search, permission filters, and sort controls on a large dataset and verify the displayed subset.

- [ ] T030 [US2] Implement search and filter state in `src/services/matrix.py`
- [ ] T031 [US2] Implement sort state and ordering for users/objects in `src/services/matrix.py`
- [ ] T032 [US2] Wire the search, filter, and sort service state (T030, T031) to the controls already present in `src/ui/user_view.py`, `src/ui/compare_view.py`, and `src/ui/object_view.py`; verify live-update behaviour within the 1-second constraint (SC-003) and confirm the [Clear] button resets all active filters and sort to defaults (US2 scenario 4)
- [ ] T033 [US2] Add tests for search, filter, and sort behavior in `tests/unit/test_matrix.py`

---

## Phase 5: User Story 3 - Tag and Metadata Management (Priority: P3)

**Goal**: Add local tag assignment, tag filtering, and object descriptions.

**Independent Test**: Tag users and objects, filter the matrix by tag, and save/reload object descriptions.

- [ ] T040 [US3] Implement `TagStore` CRUD and validation in `src/services/tags.py`
- [ ] T041 [US3] Implement object description load/save via `src/db/objects.py`
- [ ] T042 [US3] Add tag editor UI in `src/ui/widgets/tag_editor.py` per ui-spec.md §8: tag chips with `×` remove button; add-tag field with `^[A-Za-z0-9]+$` inline validation; rename by double-clicking a chip (editable inline; Enter commits, Escape cancels); modal dialog with keyboard-accessible `[Close]` / `Escape`; focus returns to the opener on close
- [ ] T043 [US3] Integrate tag filtering into `src/ui/user_view.py`, `src/ui/compare_view.py`, and `src/ui/object_view.py`: populate the tag filter dropdown from `TagStore` (T040) and apply selections to the service-layer filter state (T030)
- [ ] T044 [US3] Add tests for tag validation, local persistence, tag filtering, and rename in `tests/unit/test_tags.py`: valid/invalid format (`^[A-Za-z0-9]+$`), duplicate-insensitive add (case-insensitive deduplication), remove, rename (case-preservation verified), and round-trip persistence to `tags.json` after each mutation
- [ ] T045 [US3] Add object description tests in `tests/unit/test_objects.py`: verify save via `sys.extended_properties` (`MS_Description`), round-trip retrieval after app restart, correct handling of empty/null descriptions, and rejection of descriptions exceeding SQL Server's extended-property length limit
- [ ] T046 [US3] Add object description editor UI inline in `src/ui/object_view.py` per ui-spec.md §9: expands below the object/permission selectors when [📝] is clicked; free-text area; `[Save Description]` calls `src/db/objects.py` (T041); `Ctrl+Enter` saves; `Escape`/`[Cancel]` collapses without saving; no separate widget file

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
