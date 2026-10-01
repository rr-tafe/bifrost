# Data Model: SQL Server Permissions Manager

**Phase**: 1 | **Date**: 2026-07-14 | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

## Overview

Bifrost's data model has two distinct storage zones:

| Zone | What lives here | Where |
|------|----------------|-------|
| SQL Server | Permissions, users, objects, audit log, object descriptions | Remote database |
| Local files | Connection configuration, tag assignments | `%APPDATA%\Bifrost\` |
| In-memory only | Staged (pending) permission changes | Runtime; lost on crash |

---

## Entities

### 1. DatabaseUser

Represents a SQL Server database principal that can hold object permissions.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `login_name` | `str` | `sys.database_principals.name` | Unique identifier; used as the key in local tag store |
| `display_name` | `str` | `sys.database_principals.name` | Same as login_name for v1; shown in UI |
| `principal_type` | `str` | `sys.database_principals.type` | `S` (SQL), `U` (Windows), `G` (group) |
| `is_disabled` | `bool` | `sys.database_principals.is_disabled` | Show visually but allow permission management |
| `tags` | `list[str]` | `tags.json` → `user_tags[login_name]` | Local only; alphanumeric, no spaces |

**Validation rules**:
- `login_name` must be non-empty
- Each tag must match `^[A-Za-z0-9]+$`

---

### 2. DatabaseObject

Represents a schema-scoped SQL Server object that permissions can be granted on.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `schema_name` | `str` | `sys.schemas.name` | Part of the unique object identifier |
| `object_name` | `str` | `sys.objects.name` | Part of the unique object identifier |
| `object_type` | `ObjectType` | `sys.objects.type` | TABLE, VIEW, PROCEDURE, FUNCTION |
| `tags` | `list[str]` | `tags.json` → `object_tags[schema.object]` | Local only |
| `description` | `str \| None` | `sys.extended_properties` (MS_Description) | Stored in SQL Server; shared across admins |

**Unique identifier**: `f"{schema_name}.{object_name}"`

**Object type enum**:
```
ObjectType.TABLE      → SQL type 'U'
ObjectType.VIEW       → SQL type 'V'
ObjectType.PROCEDURE  → SQL type 'P'
ObjectType.FUNCTION   → SQL types 'FN', 'IF', 'TF'
```

**Applicable permissions by type**:

| Permission | TABLE | VIEW | PROCEDURE | FUNCTION |
|------------|-------|------|-----------|----------|
| SELECT | ✓ | ✓ | — | — |
| INSERT | ✓ | ✓ | — | — |
| UPDATE | ✓ | ✓ | — | — |
| DELETE | ✓ | ✓ | — | — |
| EXECUTE | — | — | ✓ | ✓ |
| ALTER | ✓ | ✓ | ✓ | ✓ |
| REFERENCES | ✓ | ✓ | — | — |
| VIEW DEFINITION | ✓ | ✓ | ✓ | ✓ |

**Validation rules**:
- `schema_name` and `object_name` must be non-empty
- `description` free-text; no special character restrictions; max 7500 chars (SQL Server `extended_properties` string value limit)

---

### 3. PermissionState (enum)

The three possible explicit states for a permission assignment.

| Value | Meaning | Visual indicator |
|-------|---------|-----------------|
| `GRANT` | Explicitly permitted | Green / checkmark icon |
| `DENY` | Explicitly blocked (overrides role grants) | Red / X icon |
| `NONE` | No explicit assignment; access via role membership | Grey / dash |

**State cycle on toggle**: `NONE → GRANT → DENY → NONE`

---

### 4. PermissionAssignment

The in-memory record of a single cell in the permission matrix.

| Field | Type | Notes |
|-------|------|-------|
| `user_login` | `str` | FK → DatabaseUser.login_name |
| `schema_name` | `str` | Part of object key |
| `object_name` | `str` | Part of object key |
| `permission_type` | `PermissionType` | One of the 8 v1 permission types |
| `committed_state` | `PermissionState` | Last state fetched from / committed to SQL Server |
| `staged_state` | `PermissionState \| None` | `None` = no pending change; non-None = pending |

**Derived field**: `has_pending_change` = `staged_state is not None and staged_state != committed_state`

**Key**: `(user_login, schema_name, object_name, permission_type)` — used as the dict key for staged changes

---

### 5. StagedChange

A pending permission change held in memory until Commit or Cancel.

| Field | Type | Notes |
|-------|------|-------|
| `user_login` | `str` | |
| `schema_name` | `str` | |
| `object_name` | `str` | |
| `permission_type` | `PermissionType` | |
| `previous_state` | `PermissionState` | The committed state before this change |
| `new_state` | `PermissionState` | The desired state to apply on commit |

**On commit**: generates the appropriate T-SQL (`GRANT`, `DENY`, or `REVOKE`) and one AuditEntry per change.

**On cancel**: all StagedChanges are discarded; PermissionAssignment.staged_state reset to None for all cells.

---

### 6. AuditEntry

An immutable record of a single committed permission change. Stored in SQL Server.

**Table**: `<config.schema>.Bifrost_audit_log` — the schema comes from [Configuration](#7-configuration); table name is always `Bifrost_audit_log`.

| Field | SQL Column | Type | Notes |
|-------|-----------|------|-------|
| `id` | `id` | `BIGINT IDENTITY PK` | Auto-generated |
| `administrator` | `administrator` | `NVARCHAR(128)` | SQL Server identity of the connected admin (`SYSTEM_USER`) |
| `affected_user` | `affected_user` | `NVARCHAR(128)` | `user_login` of the database user whose permission changed |
| `schema_name` | `schema_name` | `NVARCHAR(128)` | |
| `object_name` | `object_name` | `NVARCHAR(128)` | |
| `permission_type` | `permission_type` | `NVARCHAR(64)` | e.g., `SELECT`, `EXECUTE` |
| `action` | `action` | `NVARCHAR(16)` | `GRANT`, `DENY`, or `REVOKE` |
| `previous_state` | `previous_state` | `NVARCHAR(16)` | `GRANT`, `DENY`, or `NONE` |
| `new_state` | `new_state` | `NVARCHAR(16)` | `GRANT`, `DENY`, or `NONE` |
| `changed_at` | `changed_at` | `DATETIME2` | `DEFAULT GETUTCDATE()` — set by SQL Server |
| `explanation` | `explanation` | `NVARCHAR(500)` | Auto-generated: e.g., `"GRANT SELECT on dbo.Orders to alice"` |

**Action derivation**:
- new_state = GRANT → action = `GRANT`
- new_state = DENY → action = `DENY`
- new_state = NONE → action = `REVOKE`

---

### 7. Configuration

Persisted in `%APPDATA%\Bifrost\config.json`. Loaded on startup; saved on settings form submit.

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `server` | `str` | non-empty | SQL Server hostname or IP |
| `port` | `int` | 1–65535, default 1433 | TCP port |
| `database` | `str` | non-empty | Target database name |
| `schema` | `str` | non-empty, valid SQL identifier, default `dbo` | Schema where Bifrost's own tables (e.g. `Bifrost_audit_log`) are created; must exist or the connecting account must have CREATE SCHEMA permission |
| `auth_type` | `str` | `"windows"` | Authentication method; only Windows Authentication is supported |
| `username` | `str \| None` | not used | Windows Authentication uses the current Windows user context |
| `password` | `str \| None` | not used | Credentials are not stored by Bifrost |

**If config.json is missing or corrupt**: show Settings view with explanatory message (not a crash).

---

### 8. TagStore

Persisted in `%APPDATA%\Bifrost\tags.json`. Loaded on startup; written on any tag change.

| Field | Type | Notes |
|-------|------|-------|
| `user_tags` | `dict[str, list[str]]` | Key = `login_name`; value = list of tags |
| `object_tags` | `dict[str, list[str]]` | Key = `"schema.object_name"`; value = list of tags |

**Tag validation** (enforced at write boundary):
- Must match `^[A-Za-z0-9]+$`
- Duplicate tags on the same entity are silently deduplicated
- Tags are case-preserved but case-insensitive for duplicate detection

---

## State Transitions

### Permission Cell Lifecycle

```
[Loaded from DB]
committed_state = GRANT|DENY|NONE
staged_state = None
        │
        ▼ user toggles cell
staged_state = next state in cycle (NONE→GRANT→DENY→NONE)
        │
   ┌────┴────┐
   │         │
[Commit]   [Cancel]
   │         │
   ▼         ▼
committed  staged_state
= staged   = None
 _state    (reverts to
            committed)
```

### Commit Flow

```
For each StagedChange:
  1. Execute T-SQL: GRANT/DENY/REVOKE <permission> ON [schema].[object] TO/FROM [user]
  2. On success: write AuditEntry to Bifrost.audit_log
  3. On DB error: mark that cell as failed; revert to committed_state (FR-018)
After all changes:
  4. Successful cells: set committed_state = staged_state, staged_state = None
  5. Failed cells: staged_state = None (reverted); show error summary to admin
```

---

## In-Memory Matrix Structure

The running application holds these in memory after initial load:

```python
users: list[DatabaseUser]                  # ordered by display_name
objects: list[DatabaseObject]              # ordered by schema_name, object_name
permissions: dict[                         # keyed by (user_login, schema, object, perm)
    tuple[str, str, str, str],
    PermissionAssignment
]
staged_changes: dict[                      # subset of permissions with staged_state != None
    tuple[str, str, str, str],
    StagedChange
]
```

**Filter state** (applied over the in-memory lists at render time; does not modify the underlying data):
- `search_term: str` — matched against user name, object name
- `active_filters: dict` — permission type filter, tag filter
- `sort_key: str` — current sort column and direction
