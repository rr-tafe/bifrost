# Implementation Plan: SQL Server Permissions Manager

**Branch**: `001-sql-permissions-manager` | **Date**: 2026-07-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-sql-permissions-manager/spec.md`

## Summary

Build Bifrost, a Python/Tkinter desktop application for Windows 11 that allows administrators to view and manage SQL Server 2019+ object-level permissions via a staged-commit permission matrix. The matrix renders up to 200 users × 500 objects × 8 permission types using Canvas-based virtual scrolling; changes are staged locally and applied as a batch via T-SQL GRANT/DENY/REVOKE; every committed change is recorded in an audit log table shared on the SQL Server.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- Tkinter (stdlib) — desktop UI
- pyodbc 5.x — SQL Server ODBC driver (justified: no stdlib SQL Server driver; actively maintained; full Windows Auth support; requires Microsoft ODBC Driver 18 for SQL Server installed at OS level)
- pytest + pytest-cov (dev-only) — test runner and coverage reporting

**Storage**:
- SQL Server 2019+ — permissions (sys.database_permissions), audit log (`<config.schema>.Bifrost_audit_log`), object descriptions (sys.extended_properties via MS_Description)
- `%APPDATA%\Bifrost\config.json` — connection configuration (local to each machine)
- `%APPDATA%\Bifrost\tags.json` — user and object tag assignments (local to each machine)

**Testing**: pytest with pytest-cov; 80% coverage floor enforced per constitution; unittest.mock for DB layer isolation in unit tests; integration tests require live SQL Server

**Target Platform**: Windows 11 desktop application (standalone; no installer required for v1)

**Project Type**: desktop-app

**Performance Goals**:
- Matrix load <2 seconds for 200 users × 500 objects (SC-001)
- Search/filter results <1 second on max dataset (SC-003)
- No UI freeze exceeding 1 second during any operation (SC-007)
- CSV export completes without blocking the UI thread

**Constraints**:
- Full keyboard operability — no mouse required (FR-021, SC-006)
- Single database connection at a time; no cross-server views in v1
- Staged changes held in memory only; lost if the app crashes before commit
- Windows Authentication only; SQL auth credentials are not supported and are not stored in config.json
- 80% test coverage gate enforced in CI (Constitution I)

**Scale/Scope**: 200 users × 500 objects × 8 permissions = up to 800k cells; single DB connection

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I — Test Coverage (≥80%) | PASS | pytest-cov enforced; test tasks mandatory per constitution |
| II — Security | PASS | No hardcoded credentials; Windows Auth only; config.json excluded from git; pre-commit secret scan configured |
| III — Simple Architecture | PASS | Single-project flat layout; no repository/DI patterns; pyodbc used directly in db/ module |
| IV — Clean Code | PASS | ruff enforced with zero warnings; single-responsibility functions throughout |
| V — Simple UX | PASS | Canvas matrix; ≤4 interactions per commit (SC-002); all errors actionable |
| VI — Minimal Dependencies | PASS | Only pyodbc added beyond stdlib (no stdlib SQL Server driver exists); pytest/pytest-cov dev-only; both documented here |
| VII — UI Accessibility | PASS | WCAG 2.2 Level AA compliant: Canvas matrix keyboard-navigable; non-color indicators (✓/✗/─); focus indicators (2px, 3:1 contrast); screen reader live regions; error message association; skip navigation shortcuts; high contrast mode support; 200% text scaling; semantic headings (H1-H3); all controls Tab/Enter accessible; Windows UI Automation integration for screen readers (FR-024, FR-025) |
| VIII — Input Validation | PASS | Tags, connection params, and search terms validated at entry boundary |

No violations detected. No Complexity Tracking entries required.

*Post-design re-check*: All principles remain satisfied after Phase 1 design. The Canvas virtual-scrolling approach avoids any external UI library dependency. The two local JSON files (config, tags) are simple flat structures with no ORM or storage abstraction needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-sql-permissions-manager/
├── plan.md                  # This file
├── spec.md                  # Feature specification
├── ui-spec.md               # UI layout, interaction model, and keyboard shortcuts
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output
├── contracts/
│   ├── db-schema.sql        # SQL Server audit log DDL
│   ├── config-schema.json   # Config file JSON schema
│   ├── tags-schema.json     # Tags file JSON schema
│   └── csv-formats.md       # CSV export column specifications
└── tasks.md                 # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/
├── db/
│   ├── connection.py        # pyodbc connection factory; Windows Authentication only
│   ├── permissions.py       # Read sys.database_permissions; apply GRANT/DENY/REVOKE
│   ├── objects.py           # Read sys.objects + sys.schemas; extended properties
│   ├── users.py             # Read sys.database_principals
│   └── audit.py             # Write <config.schema>.Bifrost_audit_log; ensure schema/table exists
├── models/
│   ├── user.py              # DatabaseUser dataclass
│   ├── db_object.py         # DatabaseObject dataclass
│   ├── permission.py        # PermissionAssignment, PermissionState enum, PermissionType enum
│   ├── audit_entry.py       # AuditEntry dataclass
│   └── config.py            # Configuration dataclass
├── services/
│   ├── matrix.py            # In-memory permission matrix; staging engine; commit/cancel
│   ├── tags.py              # Tag CRUD; read/write tags.json
│   ├── config.py            # Config load/save to %APPDATA%\Bifrost\config.json
│   └── export.py            # CSV export for permission matrix and audit log
├── ui/
│   ├── app.py               # Root Tk window; tab strip; view lifecycle; startup flow
│   ├── user_view.py         # User View: object rows × 8 permission columns for one user
│   ├── compare_view.py      # Compare View: object rows × all-user column groups
│   ├── object_view.py       # Object View: permission matrix for one object across all users
│   ├── settings_view.py     # Connection configuration form
│   ├── audit_view.py        # Audit log viewer with date/user/object filters
│   └── widgets/
│       ├── cell_renderer.py # Shared Canvas cell: click-to-cycle, right-click menu, highlight
│       ├── tag_editor.py    # Tag assignment dialog (users and objects)
│       └── status_bar.py    # Global staged-change count, Commit/Cancel, connection identity
└── validation.py            # Boundary-level input validation (tags, config fields, search)

tests/
├── unit/
│   ├── test_matrix.py       # Staging logic, commit/cancel, three-state transitions
│   ├── test_tags.py         # Tag validation (alphanumeric, no spaces) and CRUD
│   ├── test_export.py       # CSV output correctness (headers, row count, encoding)
│   ├── test_validation.py   # Input rejection for all invalid input cases
│   ├── test_audit.py        # Audit log retrieval, date/user/object filtering, entry correctness
│   ├── test_objects.py      # Object description save/round-trip via sys.extended_properties
│   └── test_config.py       # Config serialisation/deserialisation; corrupt file handling
└── integration/
    └── test_db.py           # Requires live SQL Server; permission reads and writes

requirements.txt             # Pinned runtime dependencies (pyodbc only)
requirements-dev.txt         # Pinned dev dependencies (pytest, pytest-cov, ruff)
main.py                      # Entry point: load config → connect → show matrix view
```

**Structure Decision**: Single-project layout. No backend/frontend split is needed for a desktop app. The db/, models/, services/, ui/ split reflects natural responsibility boundaries without introducing abstraction layers — each directory maps directly to a domain concern, not an architectural pattern.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations to track.

## Accessibility Implementation

**Standard**: WCAG 2.2 Level AA compliance (FR-024, FR-025)

**Platform Integration**:
- **Windows UI Automation (UIA)**: Tkinter widgets will expose accessibility properties via Windows UI Automation framework for screen reader compatibility (NVDA, Windows Narrator, JAWS)
- **System Settings Detection**: Use Windows APIs (`SystemParametersInfo`, registry keys) to detect:
  - High Contrast mode (via `SPI_GETHIGHCONTRAST`)
  - Animation preferences (via `SPI_GETCLIENTAREAANIMATION`)
  - Text scaling (via DPI awareness APIs)

**Critical Accessibility Features**:

1. **Non-Color Indicators** (FR-024, WCAG 1.4.1):
   - Permission state symbols: ✓ (GRANT), ✗ (DENY), ─ (none), * (staged)
   - Accessible color palette verified for WCAG AA contrast:
     - Green #006400 (7.3:1 on white)
     - Red #B22222 (5.0:1 on white)
     - Grey #767676 (4.6:1 on white)
   - Implementation: `cell_renderer.py` renders symbol + color together

2. **Focus Indicators** (WCAG 2.4.7, 2.4.11):
   - 2px solid border in system accent color (#0078D4)
   - 3:1 minimum contrast against background
   - 2px offset from widget edge
   - Implementation: Tkinter `highlightthickness=2`, `highlightbackground`, custom Canvas focus rings

3. **Screen Reader Support** (WCAG 4.1.3):
   - Live regions for dynamic content (staged count, search results, errors)
   - Accessible names for all icons and controls
   - Full context announcements for cell state changes
   - Implementation: Tkinter accessibility properties, Windows UIA `IAccessible` interface

4. **Keyboard Navigation** (WCAG 2.1.1):
   - Arrow keys for matrix navigation
   - Skip shortcuts: Ctrl+M (matrix), Ctrl+F (filters)
   - Context menu: Shift+F10 or Menu key
   - Direct edit: G (GRANT), D (DENY), Delete (clear)
   - Implementation: `bind()` handlers in `user_view.py`, `compare_view.py`, `object_view.py`

5. **Error Message Association** (WCAG 3.3.1):
   - Programmatic link between errors and fields
   - Implementation: Tkinter `Label` with `for` property or UIA `LabeledBy` pattern for Settings and Tag Editor

6. **Semantic Structure** (WCAG 2.4.6):
   - H1: Application title with database name
   - H2: Active tab name
   - H3: Section headers (filters, matrix, settings)
   - Implementation: Set `role="heading"` and `aria-level` via Windows UIA or Tkinter accessibility attributes

**Testing Strategy**:
- Manual screen reader testing with NVDA (free, open source)
- Automated contrast checking via library in `test_accessibility.py`
- Keyboard-only navigation tests in `test_accessibility.py`
- Focus indicator visibility verification with automated screenshots
- High Contrast mode testing on Windows 11 with all 4 themes

**Dependencies**: No new external dependencies required; Windows UIA support is built into Python's Tkinter on Windows, accessible via `ctypes` or `pywinauto` if needed for advanced UIA patterns.

**Implementation Priority**: Phase 1 Critical accessibility features (non-color indicators, focus, screen reader basics) are blocking for release. Phase 2 features (high contrast, reduced motion, text scaling) enhance experience but can follow initial release if schedule requires.
