# Feature Specification: SQL Server Permissions Manager

**Feature Branch**: `001-sql-permissions-manager`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "I want to build a Python desktop application that allows me to
manage SQL Server permissions for other users quickly and easily."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View & Toggle the Permission Matrix (Priority: P1)

An administrator opens the application and is immediately presented with a permission matrix:
database users on one axis, database objects on the other, and permission types as columns or
layers within each cell. Each cell shows whether a permission is currently granted and can be
toggled on or off directly. The administrator can change any permission in seconds without
navigating away from the main view.

**Why this priority**: This is the core value proposition of the entire application. Every
other feature exists to support or extend this central interaction.

**Independent Test**: Can be fully tested by connecting to a live database, loading the matrix,
staging one or more permission changes, committing them, and confirming: (a) staged cells
show a pending visual state before commit, (b) changes are applied to the database only on
commit, (c) cancelling staged changes restores the matrix to its pre-staged state, (d) audit
log entries appear only after a successful commit.

**Acceptance Scenarios**:

1. **Given** the app is connected to a database, **When** the administrator opens the permission
   matrix view, **Then** all database users, objects, and their current committed permission
   states are displayed in a scannable grid within 2 seconds of launch.
2. **Given** the permission matrix is loaded, **When** the administrator changes a cell's
   permission state (e.g., none → GRANT, GRANT → DENY, DENY → none), **Then** the cell
   is marked visually as pending (not yet applied) and the Commit and Cancel controls
   become active; the database is not changed until Commit is pressed.
3. **Given** one or more changes are staged, **When** the administrator presses Commit, **Then**
   all staged changes are applied to the database as a single operation, the matrix reflects
   the new committed states, and one audit log entry per changed permission is written.
4. **Given** one or more changes are staged, **When** the administrator presses Cancel, **Then**
   all staged changes are discarded and every cell returns to its last committed state with
   no changes written to the database.
5. **Given** a commit fails at the database level (partial or full), **When** the commit is
   attempted, **Then** the system reports which changes succeeded and which failed; failed
   cells revert to their last committed state and the administrator can retry or cancel.
6. **Given** the matrix is loaded, **When** the administrator selects a specific database object
   and permission type, **Then** the view highlights or filters to show only users who hold
   that committed permission on that object.

---

### User Story 1b - Object View: Manage Access List by Object + Permission (Priority: P1)

When an administrator needs to answer "who has SELECT on dbo.Orders?" or quickly grant a
permission to several users for a specific object, they switch to the Object View. They select
a database object and a permission type; the view shows every user split into two sections —
those with an explicit GRANT or DENY above a divider, and those with no explicit assignment
below. The administrator can change any user's state via a per-row dropdown, or click
[+ Add User...] to search for a user and add them to the explicit list (defaulting to GRANT).
All changes are staged to the shared staging area and committed or cancelled via the global
Commit / Cancel controls.

**Why this priority**: Complements the User View (US1) — together they give administrators
maximum flexibility to manage permissions either per-user or per-object+permission.

**Independent Test**: Can be tested independently by selecting an object + permission type,
verifying the correct user list appears, changing states, adding a user, committing, and
confirming the database reflects the changes and the audit log records them.

**Acceptance Scenarios**:

1. **Given** an object and permission type are selected in the Object View, **When** the view
   loads, **Then** all users with an explicit GRANT or DENY appear above the divider; all
   users with no explicit assignment appear below; the divider is clearly labelled.
2. **Given** a user's State dropdown is changed from none to GRANT, **When** the change is
   staged, **Then** the user row moves above the divider with a pending `*GRANT` indicator
   and the global staged-change count increments by one.
3. **Given** [+ Add User...] is clicked, **When** the administrator selects a user from the
   picker, **Then** the user appears at the top of the explicit-assignment section with
   `*GRANT` staged; the staged-change count increments.
4. **Given** staged changes exist in the Object View, **When** the administrator switches to
   the User View or Compare View, **Then** those changes remain staged and are visible as
   pending cells in the other views.

---

### User Story 2 - Search, Filter & Sort (Priority: P2)

When managing a large database with many users and objects, the administrator uses search,
filter, and sort controls to quickly locate what they need. They can type to search by user
name, object name, or permission; apply filters to narrow the matrix to matching rows and
columns; and sort any axis alphabetically or by permission state.

**Why this priority**: Without search/filter/sort, the matrix becomes unusable at scale.
These controls are essential for any realistically sized database environment.

**Independent Test**: Can be tested independently on a dataset with 20+ users and 50+ objects
by verifying that search, filter, and sort each produce correct, instant results without
affecting the underlying permission data.

**Acceptance Scenarios**:

1. **Given** the permission matrix is loaded, **When** the administrator types a partial user
   name into the search field, **Then** the matrix filters live to show only matching users
   within 1 second.
2. **Given** the matrix is loaded, **When** the administrator applies a filter for a specific
   permission type, **Then** only entries with that permission type are shown; all others are
   hidden until the filter is cleared.
3. **Given** the matrix is loaded, **When** the administrator clicks the sort control on the
   object name column, **Then** objects are sorted alphabetically and a visible indicator shows
   the sort direction; clicking again reverses the order.
4. **Given** multiple filters are active, **When** the administrator clears all filters,
   **Then** the full unfiltered matrix is restored.

---

### User Story 3 - Tag and Metadata Management (Priority: P3)

To organise users and database objects into logical groups, the administrator assigns custom
tags (e.g., "finance", "readonly", "tier1") to any user or object. Tags are alphanumeric with
no spaces. Once tagged, the administrator can filter the entire matrix to show only tagged
entities, making bulk review and management faster. The administrator can also add metadata 
to tables, views, functions, etc. explaining what they do - as a form of DB-level documentation.

**Why this priority**: Tags provide the organisational layer needed to manage large databases
efficiently. They turn an overwhelming list into a structured, navigable set of groups.

**Independent Test**: Can be tested independently by assigning tags to users and objects,
filtering the matrix by tag, verifying only the correctly tagged entities appear, and
confirming that object descriptions written through the app are stored in and retrieved
from the database.

**Acceptance Scenarios**:

1. **Given** a user is selected in the matrix, **When** the administrator adds an alphanumeric
   tag with no spaces, **Then** the tag is saved, displayed on the user, and the user appears
   when filtering by that tag.
2. **Given** a database object has two tags assigned, **When** the administrator filters by
   either tag, **Then** the object appears in both filtered views.
3. **Given** a tag is assigned to a user, **When** the administrator removes that tag,
   **Then** the tag is no longer displayed on the user and the user no longer appears when
   filtering by that tag.
4. **Given** the administrator enters a tag value containing a space or special character,
   **When** they attempt to save the tag, **Then** the system rejects the input with a clear
   validation message explaining the allowed format.
5. **Given** a database object is selected, **When** the administrator adds or edits its
   description, **Then** the description is saved to the database and displayed when the
   object is viewed; if the app is closed and reopened, the description is retrieved from
   the database unchanged.

---

### User Story 4 - Audit Log Review (Priority: P4)

For accountability and compliance, every permission change made through the app is recorded
in an in-app audit log. The administrator can open the audit log view to review a chronological
history of all actions: who made each change, when, what was changed, and what the change was.
The log can be filtered by date, user, or object.

**Why this priority**: Audit logging is non-negotiable for a permission management tool.
It ensures every change is traceable and the tool can be used with confidence in regulated
or business-critical environments.

**Independent Test**: Can be tested independently by performing a known sequence of permission
changes, then verifying the audit log contains a complete, accurate, and correctly timestamped
record of every action.

**Acceptance Scenarios**:

1. **Given** a permission was granted by an administrator, **When** the audit log is viewed,
   **Then** an entry appears showing the acting administrator's identity, the affected user,
   the database object, the permission type, the action ("GRANT"), and the timestamp.
2. **Given** a permission was revoked, **When** the audit log is viewed, **Then** an entry
   appears with action "REVOKE" and all the same contextual fields.
3. **Given** the audit log contains many entries, **When** the administrator filters by a
   specific date range, **Then** only entries within that range are displayed.

---

### User Story 5 - CSV Report Export (Priority: P5)

At any time, the administrator can export the current permission state as a structured CSV
report. The file includes all users, all database objects, all permissions, and their current
grant status — laid out clearly for external review, sign-off, or archiving. The audit log
can also be exported separately.

**Why this priority**: Reporting provides external auditability and satisfies governance
processes that require a paper trail beyond what is visible in the app.

**Independent Test**: Can be tested independently by exporting a report and comparing every
row against the known permission state in the database.

**Acceptance Scenarios**:

1. **Given** the matrix is populated, **When** the administrator exports a CSV permission
   report, **Then** a file is produced with column headers for user, database object,
   permission type, and grant status; one row per user/object/permission combination.
2. **Given** the audit log has entries, **When** the administrator exports the audit log as
   CSV, **Then** a file is produced with columns for acting administrator, affected user,
   object, permission, action, timestamp, and explanation.
3. **Given** a CSV file is opened in a spreadsheet application, **Then** all data is correctly
   delimited and accurately reflects the state at the time of export.

---

### User Story 6 - Application Configuration (Priority: P6)

Before using the app for the first time, the administrator configures the database connection
via a dedicated settings screen. They enter the server address, port, and authentication
details. The configuration is saved to a local file so the app reconnects automatically on
every subsequent launch. The administrator can update the configuration at any time.

**Why this priority**: Configuration must exist before any other feature works, but once set
it is rarely revisited. It is the lowest user-facing priority because it is a one-time setup
with minimal ongoing interaction.

**Independent Test**: Can be tested independently by saving a configuration, closing and
relaunching the app, and confirming it reconnects without requesting credentials again.

**Acceptance Scenarios**:

1. **Given** the configuration screen is open, **When** the administrator enters valid
   connection details and saves, **Then** the app connects to the specified database and
   navigates to the main matrix view.
2. **Given** a valid configuration exists, **When** the app is launched, **Then** it connects
   automatically without prompting for connection details.
3. **Given** invalid connection details are entered, **When** the administrator attempts to
   save, **Then** a clear error identifies the invalid field(s) and the configuration is not
   saved.
4. **Given** a configuration is already saved, **When** the administrator opens settings and
   updates any field, **Then** the new configuration is saved and the app reconnects to the
   updated target.

---

### Edge Cases

- What happens when the database has hundreds of users and thousands of objects? The matrix
  must remain scrollable, searchable, and responsive without freezing.
- What happens when the database connection is lost mid-session? The app must detect the loss,
  display a clear reconnection prompt, and preserve any staged-but-uncommitted changes so
  the administrator can commit or cancel after reconnecting.
- What happens if a commit is attempted while the connection is down? The commit must fail
  gracefully with a clear message; staged changes must remain intact for retry.
- What happens if a permission change is attempted by an administrator account that lacks the
  privilege to grant/revoke that permission? The UI must revert the toggle and display the
  database error in plain language.
- What happens when two administrators use the app simultaneously and make conflicting changes?
  A manual refresh must always pull the authoritative state from the database.
- What happens when the configuration file is missing or corrupt on launch? The app must open
  the configuration screen with an explanatory message rather than crashing.
- What happens when an exported CSV is very large (e.g., 10,000+ rows)? The export must
  complete without making the app unresponsive.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide three distinct permission management views, all operating
  on the same shared staging area and accessible via tabs:
  - **User View**: displays all database objects as rows and all 8 permission types as columns
    for one selected user at a time; the administrator selects a user from a dropdown and edits
    that user's permissions across all objects.
  - **Compare View**: displays all database objects as rows and all database users as column
    groups (each group containing the 8 permission sub-columns); all users are visible
    simultaneously with horizontal scrolling; tag and search filters narrow both rows and
    columns.
  - **Object View**: displays all database users as rows for a selected object and permission
    type combination; the administrator selects one object and one permission type, sees every
    user's state (GRANT / DENY / none) for that combination, and can add users to the explicit
    access list (defaulting to GRANT) or change existing states.
  In all three views, each permission state MUST be shown as one of: GRANT (explicitly allowed),
  DENY (explicitly blocked), or none (no explicit assignment).
- **FR-002**: The system MUST allow the administrator to stage permission state changes in the
  matrix (GRANT / DENY / none) without immediately applying them to the database; staged
  cells MUST be visually distinct from committed cells so pending changes are obvious at a
  glance.
- **FR-002a**: The system MUST provide a Commit control that applies all staged changes to the
  database in a single operation and a Cancel control that discards all staged changes and
  restores the matrix to its last committed state; both controls MUST be disabled when no
  changes are staged.
- **FR-003**: The system MUST support cross-query highlighting in the User View and Compare View:
  clicking a permission column header highlights all rows where the relevant user(s) hold a
  committed permission of that type, dimming all other rows; clicking an object row header in
  Compare View highlights all user columns that have any committed permission on that object;
  clicking the active header clears the highlight; only one highlight may be active at a time;
  the highlight is visual only and does not affect staging, filtering, or the underlying data.
- *(FR-004 and FR-005 are unassigned — these numbers were skipped during authoring and do not represent removed or pending requirements.)*
- **FR-006**: The system MUST allow the administrator to assign one or more alphanumeric tags
  (no spaces, no special characters) to any database user.
- **FR-007**: The system MUST allow the administrator to assign one or more alphanumeric tags
  (no spaces, no special characters) to any database object.
- **FR-008**: The system MUST allow the administrator to add, rename, and remove tags from
  users and database objects at any time.
- **FR-009**: The system MUST allow the administrator to search the matrix by user name,
  database object name, and permission type; results MUST update within 1 second of input.
- **FR-010**: The system MUST allow filtering the matrix by user, database object, permission
  type, and assigned tag; multiple filters MUST be combinable.
- **FR-011**: The system MUST allow sorting the matrix by user name, database object name, and
  permission type in ascending and descending order, with a visible sort indicator.
- **FR-012**: The system MUST record every permission change in an audit log persisted in the
  SQL Server database at commit time (not on individual cell changes), capturing one entry
  per permission changed: acting administrator identity, affected database user, affected
  object, permission type, action (GRANT / DENY / REVOKE), previous state, new state,
  timestamp, and a descriptive explanation; the explanation MUST be auto-generated by the
  system at commit time from the captured fields (e.g., "Granted SELECT on dbo.Orders for
  user jsmith") — no additional administrator input is required; all administrators
  connecting to the same server MUST see the same log.
- **FR-013**: The system MUST provide a configuration screen for entering and saving: database
  server address, port, database name, schema (the SQL Server schema used for Bifrost's own
  tables, e.g. the audit log), and authentication method; v1 uses Windows Authentication only
  (field is displayed for confirmation and is non-editable); credentials are not stored locally.
- **FR-014**: The system MUST persist configuration to a local file and load it automatically
  on every launch without requiring re-entry.
- **FR-015**: The system MUST export the current permission matrix to a CSV file with clear
  column headers: User, Object, Permission, State — where State is one of GRANT, DENY,
  or none.
- **FR-016**: The system MUST export the audit log to a CSV file with clear column headers:
  Administrator, AffectedUser, Object, Permission, Action, Timestamp, Explanation.
- **FR-017**: The system MUST validate all user inputs (tags, connection parameters, search
  terms) before processing; invalid inputs MUST be rejected with a specific, actionable error
  message identifying the problem.
- **FR-018**: The system MUST revert any toggle to its previous state and display an actionable
  error message if a permission change fails at the database level.
- **FR-019**: The system MUST provide a manual refresh control that re-fetches all permission
  data from the database and updates the matrix to reflect the current authoritative state.
- **FR-020**: The system MUST display a visual icon alongside each permission type to aid
  scannability and recognition.
- **FR-021**: All interactive controls (matrix toggles, buttons, search fields, filters, sort
  controls, configuration fields) MUST be fully operable using only a keyboard.
- **FR-022**: The system MUST detect database connection loss and display a reconnection prompt
  without crashing or corrupting the current session state.
- **FR-023**: The system MUST allow the administrator to add, edit, and remove a free-text
  description for any database object; descriptions MUST be persisted in the database itself
  (not locally) so they are visible to any administrator connecting to the same server.

### Key Entities

- **Database User**: A login or user account recognised by the database server; has a unique
  identifier, display name, and zero or more assigned tags.
- **Database Object**: A schema-level object on the database (e.g., table, view, stored
  procedure, function); has a name, schema, object type, zero or more assigned tags, and an
  optional free-text description stored in the database for documentation purposes.
- **Permission**: A specific access right applicable to a database object for a user (e.g.,
  SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION).
- **Permission Assignment**: The explicit state of a specific permission for a specific user
  on a specific database object — one of three values: GRANT (explicitly allowed), DENY
  (explicitly blocked, overrides role-based grants), or none (no explicit assignment; access
  determined by role membership).
- **Tag**: An alphanumeric label with no spaces that can be assigned to users or database
  objects for grouping and filtering purposes; stored locally by the application.
- **Audit Entry**: An immutable record of a single permission change, persisted in the SQL
  Server database and shared across all administrators; captures all contextual fields needed
  to understand what happened, when, and who authorised it.
- **Configuration**: The set of parameters required to establish a connection to the database
  server; persisted locally on the administrator's machine.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The permission matrix is fully loaded and interactive within 2 seconds of
  application launch on a database with up to 200 users and 500 objects.
- **SC-002**: An administrator can stage and commit any permission change in 4 or fewer
  interactions from the main matrix view (select cell → change state → review → commit).
- **SC-003**: Search and filter results appear within 1 second of the administrator completing
  their input, with no perceptible lag on datasets up to 200 users × 500 objects.
- **SC-004**: Every permission change produces a corresponding audit log entry with no
  omissions, verified by comparing a known sequence of test changes against the log.
- **SC-005**: CSV exports contain data that is 100% accurate relative to the database state
  at the time of export, verified by direct comparison.
- **SC-006**: All primary tasks — view matrix, toggle permission, search, filter, tag, export —
  can be completed end-to-end without using a mouse, verified by keyboard-only testing.
- **SC-007**: The application remains responsive (no freeze exceeding 1 second) during any
  search, filter, sort, or export operation on the maximum supported dataset size.
- **SC-008**: Connection loss is detected within 5 seconds and surfaced to the administrator
  with a reconnection prompt; no data loss or silent failure occurs.

## Assumptions

- The target database platform is Microsoft SQL Server 2019 or later; other database engines
  are out of scope.
- The application runs on Windows 11 as a standalone desktop application; web, mobile, and
  macOS/Linux are out of scope.
- Any user who successfully authenticates to the SQL Server database with sufficient privileges
  (e.g., db_owner or sysadmin role membership) is treated as an administrator by Bifrost;
  the database itself is the access gatekeeper. Bifrost maintains no separate allow-list.
- The acting administrator is identified by the database account used to connect; this identity
  is recorded in every audit log entry. No separate Bifrost login screen is required.
- Tags are stored in a local application file on the administrator's machine, not in the
  database. They are organisational metadata for the tool, not database-native constructs.
- Object descriptions (FR-023) are the exception: these are stored in the database itself
  so that all administrators connecting to the same server share the same documentation.
- The configuration file is stored in the operating system's standard user application data
  directory and is not automatically shared between machines.
- The scope of database objects for v1 covers: tables, views, stored procedures, and functions.
  Other object types (sequences, synonyms, triggers, etc.) are out of scope for v1.
- The scope of permission types for v1 covers standard object-level permissions: SELECT,
  INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION. Database-level and
  server-level permissions are out of scope for v1.
- The application connects to one database at a time; multi-database and cross-server views
  are out of scope for v1.
- Parallelisation of data retrieval is used where it materially improves load time, but the
  specific concurrency approach is an implementation decision.
- The audit log is stored in a dedicated table in the SQL Server database; it is shared
  across all administrators connecting to the same server.
- The audit log is append-only; past entries cannot be edited or deleted through the
  application.

## Clarifications

### Session 2026-07-14

- Q: What is "metadata" for database objects — how is it structured, where stored, and is it distinct from tags? → A: Free-text description per object, stored in the SQL Server database (shared across all admins); separate from tags which remain local.
- Q: Where is the audit log stored? → A: In a dedicated table in the SQL Server database, shared across all administrators on the same server.
- Q: Should the matrix expose GRANT / DENY / none (three states) or just GRANT / revoke (two states)? → A: Three states — GRANT, DENY, and none — each visually distinct; audit log captures previous and new state on every change.
- Q: Should permission changes apply immediately on toggle, or be staged for batch commit? → A: Staged — changes are queued locally with a pending visual indicator; applied to the database only when the administrator explicitly commits; audit log written at commit time.
- Q: How does Bifrost decide who is allowed to use it — DB privileges, app allow-list, or super-admin designation? → A: DB privileges only — anyone who authenticates with sufficient SQL Server privileges (e.g., db_owner/sysadmin) is automatically an admin; Bifrost maintains no separate access list.
