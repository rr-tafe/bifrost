# Research: SQL Server Permissions Manager

> **Note (2026-10-01):** Decision 2 (Tk Canvas rendering) and the Tkinter threading note under Decision 1 are superseded by the move to PySide6. See [specs/002-pyside6-ui-redesign](../002-pyside6-ui-redesign/plan.md). The other decisions still apply.

**Phase**: 0 | **Date**: 2026-07-14 | **Plan**: [plan.md (archived)](../archive/001-sql-permissions-manager/plan.md)

## Decision 1: SQL Server Python Driver

**Decision**: Use pyodbc 5.x

**Rationale**: pyodbc is the most actively maintained Python SQL Server driver (regular 2024 releases), has full SQL Server 2019+ support, supports both Windows Authentication (Trusted_Connection=yes) and SQL Server authentication, and has a clean Windows installation path (pip install pyodbc + Microsoft ODBC Driver 18 for SQL Server MSI). T-SQL execution, parameterised queries, and connection string options are all first-class.

**Alternatives considered**: pymssql — rejected because it depends on the effectively unmaintained FreeTDS library, has limited Windows Auth support, and has seen minimal updates since 2022–2023.

**Installation requirement**: Microsoft ODBC Driver 17 or 18 for SQL Server must be installed at the OS level. This is a one-time prerequisite on the administrator's Windows 11 machine and is documented in quickstart.md.

**Threading note**: pyodbc is synchronous. Long-running DB calls (initial matrix load, commit) must be dispatched from `threading.Thread` to avoid blocking Tkinter's main loop. Results are passed back via `queue.Queue` and consumed in the UI thread via `root.after()`.

---

## Decision 2: Permission Matrix Rendering

**Decision**: Canvas widget with virtual (viewport-only) rendering

**Rationale**: The matrix can reach 800k cells (200 users × 500 objects × 8 permissions), which is far beyond what any static Tkinter widget can render. Canvas virtual scrolling renders only the visible rows (~20–50 at any time), keeping initial render time under 200ms after the DB fetch. Filter and search operations update an in-memory list and re-render the viewport only, achieving <100ms response. No external dependencies are introduced — Canvas is stdlib Tkinter.

**Alternatives considered**:
- ttk.Treeview — rejected; fundamentally a 1D tree widget, degrades severely past ~10k rows, no native 2D grid support.
- Pagination — rejected; forces navigation steps that violate SC-002 (≤4 interactions per commit) and makes cross-row scanning impractical.

**Architecture**:
- Full dataset (users, objects, permissions) loaded into memory on startup (~400–600ms total including DB fetch).
- Canvas renders rows within the current scroll viewport; scrollbar events trigger re-render.
- Staged changes are kept in a dict keyed by `(user_login, schema, object, permission_type)` and overlaid on committed state during render.
- Pending cells rendered with a distinct background colour; committed cells use the standard palette.
- Keyboard navigation: Tab moves between controls; arrow keys move focus within the matrix grid; Enter/Space toggles the focused cell's permission state.

---

## Decision 3: Object Descriptions (Extended Properties)

**Decision**: Store descriptions as SQL Server extended property `MS_Description` on each database object

**Rationale**: `MS_Description` is the standard Microsoft convention for object documentation and is recognised by SSMS and other tooling. Storing descriptions in SQL Server (not locally) satisfies FR-023: descriptions are shared across all administrators connecting to the same server.

**T-SQL patterns**:

Read:
```sql
SELECT
    ep.value AS description
FROM sys.extended_properties ep
WHERE ep.class = 1
  AND ep.name = 'MS_Description'
  AND ep.major_id = OBJECT_ID('[schema].[object]')
  AND ep.minor_id = 0;
```

Write (idempotent — drop if exists, then add):
```sql
BEGIN TRY
    EXEC sys.sp_dropextendedproperty
        @name = N'MS_Description',
        @level0type = N'SCHEMA', @level0name = N'<schema>',
        @level1type = N'<TABLE|VIEW|PROCEDURE|FUNCTION>', @level1name = N'<object>';
END TRY
BEGIN CATCH END CATCH;

EXEC sys.sp_addextendedproperty
    @name = N'MS_Description',
    @value = N'<description>',
    @level0type = N'SCHEMA', @level0name = N'<schema>',
    @level1type = N'<TABLE|VIEW|PROCEDURE|FUNCTION>', @level1name = N'<object>';
```

**Permissions required**: ALTER permission on the target object (db_owner or sysadmin satisfies this).

**Level1type mapping**:
- TABLE → `N'TABLE'`
- VIEW → `N'VIEW'`
- Stored Procedure → `N'PROCEDURE'`
- Function → `N'FUNCTION'`

---

## Decision 4: Local Storage Format

**Decision**: JSON files in `%APPDATA%\Bifrost\`

**Rationale**: The Python standard library's `json` module reads/writes JSON with no dependencies. `%APPDATA%` is the Windows-standard location for per-user application data and does not require elevated permissions. Two separate files keep config (sensitive) and tags (non-sensitive) separated.

**Files**:
- `config.json` — server address, port, database, schema, auth type
- `tags.json` — maps entity identifiers to tag lists for users and objects

See [contracts/config-schema.json](contracts/config-schema.json) and [contracts/tags-schema.json](contracts/tags-schema.json) for full schemas.

**Security note**: Only Windows Authentication is supported. No SQL Server login/password credentials are stored in `config.json`. The config file path is excluded from git via `.gitignore`.

---

## Decision 5: Audit Log Storage

**Decision**: Dedicated `Bifrost.audit_log` table in the SQL Server database

**Rationale**: Storing the audit log in SQL Server (not locally) satisfies FR-012: all administrators on the same server see the same log. The table is created on first connection if it does not exist, so no manual schema setup is required. The table is append-only by application design; no DELETE or UPDATE is issued against it.

**Schema**: See [contracts/db-schema.sql](contracts/db-schema.sql).

---

## Decision 6: Permission Matrix Data Source

**Decision**: Read directly from `sys.database_permissions`, `sys.database_principals`, `sys.objects`, and `sys.schemas`

**Rationale**: These are the authoritative SQL Server system views for object-level permission state. No intermediate tables or caches are needed. A manual refresh (FR-019) simply re-executes the same queries and replaces the in-memory dataset.

**Key query pattern**:
```sql
SELECT
    dp.name               AS user_name,
    s.name                AS schema_name,
    o.name                AS object_name,
    o.type_desc           AS object_type,
    p.permission_name     AS permission_type,
    p.state_desc          AS state       -- 'GRANT', 'DENY', or 'GRANT_WITH_GRANT_OPTION'
FROM sys.database_permissions p
JOIN sys.database_principals dp ON dp.principal_id = p.grantee_principal_id
JOIN sys.objects o              ON o.object_id = p.major_id
JOIN sys.schemas s              ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')  -- tables, views, procs, functions
  AND dp.type IN ('S', 'U', 'G')                      -- SQL users, Windows users/groups
ORDER BY dp.name, s.name, o.name, p.permission_name;
```

Users with no explicit assignment for a given permission show up as state `NONE` (absent from sys.database_permissions).

---

## Resolved Unknowns Summary

| Unknown | Resolution |
|---------|------------|
| SQL Server Python driver | pyodbc 5.x |
| Matrix rendering at scale | Canvas + virtual scrolling |
| Object descriptions storage | MS_Description extended property |
| Local persistence format | JSON in %APPDATA%\Bifrost\ |
| Audit log location | Bifrost.audit_log on SQL Server |
| Permission data source | sys.database_permissions + joined views |
| Tkinter + DB threading | threading.Thread + queue.Queue + root.after() |
