# Quickstart Validation Guide: SQL Server Permissions Manager

**Feature**: SQL Server Permissions Manager | **Plan**: [plan.md (archived)](../archive/001-sql-permissions-manager/plan.md) | **Data model**: [data-model.md](data-model.md)

This guide describes how to validate that Bifrost works end-to-end. It covers prerequisites, environment setup, and a runnable validation scenario for each user story. It is a testing/validation guide — not an implementation reference.

---

## Prerequisites

### System
- Windows 11
- Python 3.11 or later (`python --version`)
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) installed
- Access to a SQL Server 2019+ instance where you hold `db_owner` or `sysadmin` on the target database

### Database test setup
Before running validations, prepare the target database with known fixture data:

```sql
-- Create test users (run as db_owner or sysadmin)
CREATE USER test_alice WITHOUT LOGIN;
CREATE USER test_bob WITHOUT LOGIN;
CREATE USER test_carol WITHOUT LOGIN;

-- Create test objects
CREATE TABLE dbo.TestOrders (id INT);
CREATE TABLE dbo.TestProducts (id INT);
CREATE VIEW dbo.TestOrdersView AS SELECT id FROM dbo.TestOrders;
CREATE PROCEDURE dbo.TestGetReport AS SELECT 1;
```

### Python environment
```bash
pip install -r requirements.txt       # installs pyodbc
pip install -r requirements-dev.txt   # installs pytest, pytest-cov, ruff
```

---

## Launching the Application

```bash
python main.py
```

On first launch (no config.json), the Settings view opens. On subsequent launches, the app connects automatically using the saved configuration.

---

## Validation Scenarios

### S1 — Application Configuration (User Story 6)

**Validates**: FR-013, FR-014, User Story 6 acceptance scenarios

1. Launch `python main.py` with no existing `%APPDATA%\Bifrost\config.json`.
2. **Expected**: Settings view opens with an explanatory message (not a blank form, not a crash).
3. Enter valid server, port, database, schema (default `dbo`), and select Windows Authentication. Click Save.
4. **Expected**: App connects using the current Windows identity, creates `Bifrost_audit_log` in the configured schema if it does not exist, and navigates to the permission matrix view.
5. Close and relaunch `python main.py`.
6. **Expected**: App connects automatically without showing the Settings view.
7. Open Settings (via menu or keyboard shortcut), change any field to an intentionally invalid value (e.g., port = `abc`). Click Save.
8. **Expected**: Error message identifies the invalid field; configuration is not saved; app does not crash.

---

### S2 — View & Toggle the Permission Matrix (User Story 1)

**Validates**: FR-001, FR-002, FR-002a, SC-001, SC-002

1. Connect to the test database. Confirm the permission matrix loads within 2 seconds.
2. **Expected**: Rows for `test_alice`, `test_bob`, `test_carol` are visible. Columns include `dbo.TestOrders` and `dbo.TestProducts`. All cells show their committed state (initially `NONE` for all).
3. Click (or keyboard-navigate to) the cell for `test_alice` / `dbo.TestOrders` / `SELECT`. Toggle it once.
4. **Expected**: Cell changes to `GRANT`; cell is visually distinct (pending style); Commit and Cancel buttons become active.
5. Toggle the same cell again.
6. **Expected**: Cell cycles to `DENY`; pending style still applied.
7. Toggle once more.
8. **Expected**: Cell cycles back to `NONE`; it now matches its committed state, so it is no longer shown as pending. If it is the only pending change, Commit and Cancel become inactive.
9. Stage a different change: set `test_alice` / `dbo.TestOrders` / `SELECT` to `GRANT` and `test_bob` / `dbo.TestProducts` / `INSERT` to `DENY`.
10. Press Cancel.
11. **Expected**: Both cells revert to `NONE`; Commit and Cancel become inactive; database is unchanged (verify via SSMS or re-launch).
12. Stage both changes again. Press Commit.
13. **Expected**: Both changes are applied. The matrix reflects `GRANT` for alice/TestOrders/SELECT and `DENY` for bob/TestProducts/INSERT as committed states. Audit log entries appear (validate in S5 below).

---

### S3 — Search, Filter & Sort (User Story 2)

**Validates**: FR-009, FR-010, FR-011, SC-003

*Prerequisite*: Use a dataset with at least 20 users and 50 objects; the test fixture users and objects suffice for basic checks.

1. Type `alice` in the search field.
2. **Expected**: Matrix filters within 1 second to show only rows for `test_alice`. No other user rows are visible.
3. Clear the search. Apply a filter for permission type `SELECT`.
4. **Expected**: Only `SELECT` permission columns (or rows, depending on matrix orientation) are shown.
5. Clear all filters.
6. **Expected**: Full unfiltered matrix is restored.
7. Click the sort control on the object name column.
8. **Expected**: Objects are sorted alphabetically ascending; a sort indicator is visible.
9. Click sort again.
10. **Expected**: Order reverses to descending; indicator updates.

---

### S4 — Tag and Metadata Management (User Story 3)

**Validates**: FR-006, FR-007, FR-008, FR-010, FR-023

1. Right-click (or keyboard-activate) `test_alice` in the matrix. Open the tag editor. Add tag `finance`.
2. **Expected**: `finance` tag appears on `test_alice`. Filtering the matrix by tag `finance` shows only `test_alice`.
3. Add a second tag `readonly` to `test_alice`. Filter by `readonly`.
4. **Expected**: `test_alice` appears. Filter by `finance` also shows `test_alice` (tags are independent).
5. Remove the `readonly` tag from `test_alice`. Filter by `readonly`.
6. **Expected**: `test_alice` does not appear.
7. Attempt to add a tag with a space or special character (e.g., `bad tag!`).
8. **Expected**: Validation error with a clear message; tag is not saved.
9. Select `dbo.TestOrders`. Open the description editor. Enter `This table stores test order records.`. Save.
10. **Expected**: Description is saved. Close and relaunch the app. Select `dbo.TestOrders` again.
11. **Expected**: Description `This table stores test order records.` is retrieved from the database unchanged.
12. Verify via SSMS:
    ```sql
    SELECT ep.value
    FROM sys.extended_properties ep
    WHERE ep.major_id = OBJECT_ID('dbo.TestOrders')
      AND ep.name = 'MS_Description'
      AND ep.minor_id = 0;
    ```
    **Expected**: Returns the description text entered above.

---

### S5 — Audit Log Review (User Story 4)

**Validates**: FR-012, User Story 4 acceptance scenarios

*Prerequisite*: Complete S2 step 12 (commit at least two permission changes).

1. Open the audit log view.
2. **Expected**: Entries appear for the `GRANT SELECT on dbo.TestOrders to test_alice` and `DENY INSERT on dbo.TestProducts to test_bob` changes. Each entry shows: acting administrator, affected user, schema, object, permission type, action, previous state, new state, timestamp.
3. Filter the log by today's date range.
4. **Expected**: Only today's entries are shown; entries from other dates (if any) are hidden.
5. Verify directly in the database (substitute your configured schema name for `<schema>`):
    ```sql
    SELECT * FROM [<schema>].[Bifrost_audit_log] ORDER BY changed_at DESC;
    ```
    **Expected**: Rows match the in-app view exactly, with correct timestamps in UTC.

---

### S6 — CSV Report Export (User Story 5)

**Validates**: FR-015, FR-016, SC-005, User Story 5 acceptance scenarios

1. From the matrix view, click Export Permissions. Save the file.
2. Open the CSV in a spreadsheet application (e.g., Excel).
3. **Expected**: First row contains headers: `User,Schema,Object,ObjectType,Permission,State`. Rows for `test_alice` show `SELECT,GRANT` on `dbo.TestOrders`; rows for `test_bob` show `INSERT,DENY` on `dbo.TestProducts` (from S2). All other rows show `NONE`. See [contracts/csv-formats.md](contracts/csv-formats.md) for the full column spec.
4. From the audit log view, click Export Audit Log. Open the file.
5. **Expected**: Columns match `Administrator,AffectedUser,Schema,Object,Permission,Action,PreviousState,NewState,Timestamp,Explanation`. All committed changes from S2 are present with accurate data.

---

### S7 — Edge Cases

**Validates**: Edge cases section of the spec

1. **Connection loss**: With changes staged, disconnect the machine from the network (or stop the SQL Server service). Attempt to commit.
   - **Expected**: Commit fails with a clear message; staged changes remain intact and retryable.
2. **Reconnection prompt**: Leave the app idle after a connection drop for 5+ seconds.
   - **Expected**: App detects the loss within 5 seconds and shows a reconnection prompt (SC-008).
3. **Privilege error**: Connect as a low-privilege SQL user. Attempt to toggle a permission.
   - **Expected**: Toggle reverts to its previous state; a plain-language error is displayed (FR-018).
4. **Keyboard-only navigation**: Complete the entire S2 validation scenario using only the keyboard (Tab, Shift-Tab, arrow keys, Enter, Space).
   - **Expected**: All operations succeed without touching the mouse (SC-006, FR-021).
5. **Large dataset**: On a database with 200+ users and 500+ objects, load the matrix and perform a search.
   - **Expected**: Load <2 seconds (SC-001); search result <1 second (SC-003); no freeze during either (SC-007).

---

## Cleanup

After validation, remove the test fixture objects:

```sql
DROP TABLE IF EXISTS dbo.TestOrders;
DROP TABLE IF EXISTS dbo.TestProducts;
DROP VIEW IF EXISTS dbo.TestOrdersView;
DROP PROCEDURE IF EXISTS dbo.TestGetReport;
DROP USER IF EXISTS test_alice;
DROP USER IF EXISTS test_bob;
DROP USER IF EXISTS test_carol;

-- Optionally remove the audit log entries for the test run
-- Replace <schema> with your configured schema name (default: dbo)
DELETE FROM [<schema>].[Bifrost_audit_log] WHERE affected_user IN ('test_alice', 'test_bob', 'test_carol');
```
