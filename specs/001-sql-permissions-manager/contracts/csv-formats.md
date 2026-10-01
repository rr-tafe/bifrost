# CSV Export Formats

**Feature**: SQL Server Permissions Manager | **Plan**: [plan.md (archived)](../../archive/001-sql-permissions-manager/plan.md)

Two CSV exports are available (FR-015, FR-016). Both use comma delimiters, double-quote string enclosing, and UTF-8 encoding without BOM. The first row is always a header.

---

## 1. Permission Matrix Export (FR-015)

**Trigger**: Administrator clicks "Export Permissions" from the main matrix view.

**Filename convention**: `Bifrost_permissions_<YYYY-MM-DD_HHMMSS>.csv`

**Represents**: The committed permission state at the moment of export. Staged (pending) changes are NOT included.

### Columns

| Column | Type | Values | Notes |
|--------|------|--------|-------|
| `User` | string | SQL Server login name | `sys.database_principals.name` |
| `Schema` | string | Schema name | `sys.schemas.name` |
| `Object` | string | Object name | `sys.objects.name` |
| `ObjectType` | string | TABLE, VIEW, PROCEDURE, FUNCTION | Normalised from `sys.objects.type_desc` |
| `Permission` | string | SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION | |
| `State` | string | GRANT, DENY, NONE | Committed state only |

### Example rows

```csv
User,Schema,Object,ObjectType,Permission,State
alice,dbo,Orders,TABLE,SELECT,GRANT
alice,dbo,Orders,TABLE,INSERT,NONE
alice,dbo,Orders,TABLE,DELETE,DENY
bob,dbo,GetReportData,FUNCTION,EXECUTE,GRANT
```

### Scope

One row per (user, schema, object, permission) combination for all applicable permission types on each object type (see data-model.md § Applicable permissions by type). Combinations with state NONE are included so the export is a complete audit snapshot.

---

## 2. Audit Log Export (FR-016)

**Trigger**: Administrator clicks "Export Audit Log" from the audit log view.

**Filename convention**: `Bifrost_audit_<YYYY-MM-DD_HHMMSS>.csv`

**Represents**: All entries currently visible in the audit log view (respecting any active date/user/object filters). An unfiltered export contains the full log.

### Columns

| Column | Type | Values | Notes |
|--------|------|--------|-------|
| `Administrator` | string | SQL Server login name of the acting admin | `Bifrost.audit_log.administrator` |
| `AffectedUser` | string | SQL Server login name of the database user | `Bifrost.audit_log.affected_user` |
| `Schema` | string | Schema name | `Bifrost.audit_log.schema_name` |
| `Object` | string | Object name | `Bifrost.audit_log.object_name` |
| `Permission` | string | e.g., SELECT, EXECUTE | `Bifrost.audit_log.permission_type` |
| `Action` | string | GRANT, DENY, REVOKE | `Bifrost.audit_log.action` |
| `PreviousState` | string | GRANT, DENY, NONE | `Bifrost.audit_log.previous_state` |
| `NewState` | string | GRANT, DENY, NONE | `Bifrost.audit_log.new_state` |
| `Timestamp` | string | ISO 8601 UTC: `YYYY-MM-DDTHH:MM:SS.sssZ` | `Bifrost.audit_log.changed_at` converted to string |
| `Explanation` | string | Auto-generated description | `Bifrost.audit_log.explanation` |

### Example rows

```csv
Administrator,AffectedUser,Schema,Object,Permission,Action,PreviousState,NewState,Timestamp,Explanation
sysadmin,alice,dbo,Orders,SELECT,GRANT,NONE,GRANT,2026-07-14T10:23:45.000Z,GRANT SELECT on dbo.Orders to alice
sysadmin,bob,dbo,Orders,DELETE,DENY,NONE,DENY,2026-07-14T10:23:45.001Z,DENY DELETE on dbo.Orders to bob
sysadmin,alice,dbo,Orders,SELECT,REVOKE,GRANT,NONE,2026-07-14T11:01:12.000Z,REVOKE SELECT on dbo.Orders from alice
```

---

## Encoding and Delimiter Notes

- Encoding: UTF-8 (no BOM)
- Delimiter: comma (`,`)
- Text qualifier: double-quote (`"`) — applied to all string fields
- Line ending: CRLF (`\r\n`) for Windows compatibility
- Null/empty values: written as empty string between delimiters (e.g., `,,`)
- All timestamps are UTC; consumers should be aware of the UTC convention
