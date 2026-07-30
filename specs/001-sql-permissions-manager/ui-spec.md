# UI Specification: SQL Server Permissions Manager (Bifrost)

**Branch**: `001-sql-permissions-manager` | **Date**: 2026-07-15
**Status**: Agreed | **Derived from**: spec.md, plan.md, design session 2026-07-15

---

## 1. Window Layout

The main application window has four fixed zones:

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  TITLE BAR                                                                         │
├────────────────────────────────────────────────────────────────────────────────────┤
│  TAB STRIP                                                                         │
├────────────────────────────────────────────────────────────────────────────────────┤
│  ACTIVE VIEW CONTENT                                                               │
│  (fills remaining height; scrollable within the view)                              │
├────────────────────────────────────────────────────────────────────────────────────┤
│  GLOBAL STATUS BAR                                                                 │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Title Bar

```
│  Bifrost — AdventureWorks2019                    [🔄 Refresh]  [⚙ Settings]       │
```

- **Database name** is shown after the em-dash. Updates on reconnect.
- **[🔄 Refresh]**: Re-fetches all permission data from the database (FR-019). Keyboard: `F5`.
- **[⚙ Settings]**: Opens the Settings screen (FR-013/014). Keyboard: `Ctrl+,`.

### 1.2 Tab Strip

```
│  [ User View ]  [ Compare ]  [ Object View ]  ──────  [ Audit Log ]  [Export ▼]  │
```

- Three **matrix tabs** on the left: `User View`, `Compare`, `Object View`.
- A **visual separator** (line or spacing) divides the matrix tabs from utility items.
- **[Audit Log]**: Navigates to the audit log view within the same tab strip.
- **[Export ▼]**: Dropdown with two options — *Permission Matrix as CSV* and *Audit Log as CSV*; each opens a system Save As dialog (FR-015/016).
- Keyboard navigation: `Ctrl+1` / `Ctrl+2` / `Ctrl+3` for the three matrix tabs; `Ctrl+4` for Audit Log.

### 1.3 Global Status Bar

```
│  3 changes staged    [ Commit ]   [ Cancel ]              ● CORP\aadmin · 500 obj │
```

- **Always visible** regardless of the active tab.
- **Staged change count**: Updates live as cells are toggled across any view.
- **[Commit]**: Applies all staged changes as a single database operation (FR-002a). Disabled when no changes are staged. Keyboard: `Ctrl+Enter`.
- **[Cancel]**: Discards all staged changes and reverts every pending cell to its last committed state (FR-002a). Disabled when no changes are staged. Keyboard: `Escape` (when focus is in the matrix area).
- **Connection identity**: Shows the Windows account name used to connect (`CORP\aadmin`), followed by the total object count. This identity appears in every audit log entry.
- When no changes are staged: displays "No staged changes" (greyed); Commit and Cancel are visually disabled.

---

## 2. Shared Matrix Conventions

These conventions apply to User View and Compare View.

### 2.1 Object Icons (FR-020)

Each object row is prefixed with an icon indicating its type:

| Icon | Object Type      |
|------|-----------------|
| 📋   | Table           |
| 👁   | View            |
| ⚡   | Function        |
| ⚙    | Stored Procedure |

### 2.2 Permission Column Icons and Abbreviations (FR-020)

Each permission type column has an icon in the header and a 3-letter abbreviation:

| Icon | Abbreviation | Full Name       |
|------|-------------|-----------------|
| 📋   | SEL         | SELECT          |
| ✏   | INS         | INSERT          |
| 🔄   | UPD         | UPDATE          |
| 🗑   | DEL         | DELETE          |
| ▶   | EXE         | EXECUTE         |
| 🔧   | ALT         | ALTER           |
| 🔗   | REF         | REFERENCES      |
| 👁   | VD          | VIEW DEFINITION |

Full name shown in tooltip on hover / keyboard focus on column header.

### 2.3 Cell States and Visual Encoding

| Display | Meaning                         | Visual                        |
|---------|---------------------------------|-------------------------------|
| `G`     | GRANT (committed)               | Green text or filled indicator |
| `D`     | DENY (committed)                | Red text or filled indicator  |
| `─`     | none / no explicit assignment   | Grey dash                     |
| `*G`    | GRANT staged (not yet committed)| Green with pending highlight  |
| `*D`    | DENY staged                     | Red with pending highlight    |
| `*─`    | Removal staged (staged to none) | Grey dash with pending highlight |

### 2.4 Cell Interaction — Click-to-Cycle

**Left-click** on any cell cycles through states in order:

```
none (─)  →  GRANT (G)  →  DENY (D)  →  none (─)  → ...
```

Starting from the current **committed** state (not the staged state). Each click stages the next transition. The cell immediately shows the `*` pending indicator.

**Right-click** on any cell opens a context menu:
- Set to GRANT
- Set to DENY
- Clear (set to none)
- ─────────────
- Switch to User View for *[user]* (Compare View only)
- Switch to Object View for *[object]*

### 2.5 Cross-Query Highlighting (FR-003)

Clicking a **column header** (permission abbreviation) in User View or Compare View triggers cross-query mode:

- All rows where the selected user (User View) or any visible user (Compare View) holds a **committed** permission of that type are **highlighted** (full brightness).
- All other rows are **dimmed** (reduced opacity / greyed).
- A visible indicator in the column header shows the highlight is active (e.g., underline or background tint).
- Clicking the same column header again clears the highlight and restores normal view.
- Keyboard: `Enter` or `Space` on a focused column header activates/deactivates the highlight.
- Highlight affects visual display only — it does not filter out rows or change staging.

Clicking a **row header** (object name) in Compare View highlights all user columns that have any committed permission on that object; other columns are dimmed.

### 2.6 Tags Displayed Inline

Assigned tags appear next to the object name in brackets: `📋 dbo.Orders [finance][tier1]`. Tags are truncated with `…` if the row width is insufficient; full tags visible on hover.

### 2.7 Search, Filter, and Sort Controls

Present in all three matrix views (specific placement per view below):

- **Search field** (`🔍`): Live filter — results update within 1 second of the last keystroke (FR-009, SC-003). Filters object name, user name, and tag text simultaneously.
- **Tag filter** dropdown: Filters to show only objects/users with that tag assigned. "All" shows everything (FR-010).
- **Object Type filter** (User View / Compare View): Filters by object type (Table / View / Function / Stored Procedure / All).
- **Sort** dropdown: Sort options depend on the view (object name ↑↓, user name ↑↓, permission state). Active sort direction shown with ↑ or ↓ (FR-011).
- **[Clear]** button: Resets all active filters and sort to defaults.

---

## 3. Tab 1 — User View

*Manage permissions for one user across all database objects.*

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  User: [ jsmith — John Smith                              ▼ ]  🔍 [ Search...   ] │
│  Tag   [ All ▼ ]   Type [ All ▼ ]   Sort [ Object Name ↑ ]           [ Clear ]   │
├─────────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────┤
│  Object                 │ 📋   │ ✏   │ 🔄   │ 🗑   │ ▶   │ 🔧  │ 🔗  │ 👁    │
│                         │ SEL  │ INS  │ UPD  │ DEL  │ EXE  │ ALT  │ REF  │ VD    │
├─────────────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼────────┤
│ 📋 dbo.Customers [fin]  │  G   │  G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
│ 📋 dbo.Orders    [fin]  │  G   │  G   │  D   │  ─   │  ─   │  ─   │  ─   │  ─    │
│ 📋 dbo.Products         │ *G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
│ 👁 dbo.OrderSummary     │  G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
│ ⚡ dbo.GetOrderFn       │  ─   │  ─   │  ─   │  ─   │  G   │  ─   │  ─   │  ─    │
│ ⚙  dbo.ProcessOrder     │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
└─────────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴────────┘
```

**Controls:**

- **User selector** (top-left): Searchable dropdown listing all database users by `username — Display Name`. Changing the user loads that user's permissions immediately. Keyboard: `Alt+U` focuses the selector.
- **Object column** is frozen (does not scroll horizontally).
- **Permission columns** are fixed (always 8, no horizontal scroll needed in this view).
- **Column header click**: Triggers cross-query highlight for that permission type (§2.5).
- **Object name right-click**: Context menu with *Add/Edit Tags*, *Edit Description*, *Switch to Object View for this object*.

**Keyboard navigation:**
- Arrow keys move focus between cells.
- `Space` or `Enter` cycles the focused cell's state.
- `Tab` moves to the next cell; `Shift+Tab` moves to the previous.
- `Alt+U` focuses the user selector; `Escape` returns focus to the matrix.

---

## 4. Tab 2 — Compare View

*Compare permissions for all users across all objects simultaneously. Scrolls horizontally for many users.*

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  🔍 [ Search objects or users...              ]  Tag [ All ▼ ]  Type [ All ▼ ]    │
│  Sort Objects [ Name ↑ ]   Sort Users [ Name ↑ ]                     [ Clear ]    │
├──────────────────────────┬────────────────────────┬────────────────────────┬───── →
│                          │        jsmith          │        mjones          │  ...
│  Object                  │ SEL INS UPD DEL EXE …  │ SEL INS UPD DEL EXE …  │
├──────────────────────────┼────────────────────────┼────────────────────────┼───── →
│ 📋 dbo.Customers [fin]   │  G   G   ─   ─   ─  … │  G   ─   ─   ─   ─  … │
│ 📋 dbo.Orders    [fin]   │  G   G   D   ─   ─  … │  G   ─   ─   ─   ─  … │
│ 📋 dbo.Products          │ *G   ─   ─   ─   ─  … │  ─   ─   ─   ─   ─  … │
│ 👁 dbo.OrderSummary      │  G   ─   ─   ─   ─  … │  ─   ─   ─   ─   ─  … │
│ ⚡ dbo.GetOrderFn        │  ─   ─   ─   ─   G  … │  ─   ─   ─   ─   G  … │
└──────────────────────────┴────────────────────────┴────────────────────────┴───── →
```

**Layout:**

- **Object column** is frozen on the left during horizontal scroll.
- Each **user column group** has a user name header spanning its 8 sub-columns. Sub-column abbreviations (SEL INS UPD DEL EXE ALT REF VD) repeat under each user name.
- Permission abbreviations in sub-column headers are shortened to 3 characters. Full name in tooltip.
- The `…` at the right edge of each user group indicates ALT, REF, and VD columns exist but may be scrolled off screen.

**Cross-query highlight in Compare View:**
- Click a **user name header** → highlights all object rows where that user has any committed permission; other rows dimmed.
- Click an **object row header** → highlights all user columns that have any committed permission on that object; other columns dimmed.
- Click the **permission sub-column header** (e.g., `SEL`) under a specific user → highlights all rows where that specific user has a committed SELECT permission.
- Only one highlight active at a time. Clicking a new header replaces the previous highlight. Clicking the active header clears it.

**Keyboard navigation:**
- Arrow keys navigate cells; horizontal arrow keys cross user-group boundaries.
- `Ctrl+Right` / `Ctrl+Left` jumps to the next/previous user group.
- `Space` or `Enter` cycles the focused cell.
- `Home` / `End` jump to first/last column within the current row.

---

## 5. Tab 3 — Object View

*Select one database object and one permission type; see and edit the full user access list for that combination.*

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  Object:     [ 📋 dbo.Orders (Table)                      ▼ ]  [ 🏷 Tags ] [📝]  │
│  Permission: [ 📋 SELECT                                  ▼ ]                     │
│  🔍 [ Search users...          ]   Tag [ All ▼ ]   Sort [ User Name ↑ ]           │
├──────────────────────────────────────┬─────────────────┬───────────────────────────┤
│  User                                │  Tags           │  State                    │
├──────────────────────────────────────┼─────────────────┼───────────────────────────┤
│  jsmith (John Smith)                 │  finance        │  [ GRANT  ▼ ]             │
│  mjones (Mary Jones)                 │  finance        │  [ GRANT  ▼ ]             │
│  svc_report                          │  readonly       │  [ GRANT  ▼ ]             │
│  badactor                            │  ─              │  [ DENY   ▼ ]             │
├ ─ ─ ─ ─ ─ ─ ─ Users with no explicit assignment ─ ─ ─ ─┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│  aadmin (Alice Admin)                │  admin          │  [  ─     ▼ ]             │
│  devuser                             │  ─              │  [  ─     ▼ ]             │
├──────────────────────────────────────┴─────────────────┴───────────────────────────┤
│  [ + Add User... ]   Defaults to GRANT when added                                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Controls:**

- **Object selector**: Searchable dropdown listing all objects as `icon schema.name (Type)`. Keyboard: `Alt+O`.
- **Permission selector**: Dropdown of the 8 permission types with icons. Only permission types applicable to the selected object type are enabled (e.g., EXECUTE is disabled for tables). Keyboard: `Alt+P`.
- **[🏷 Tags]**: Opens the Tag Editor dialog (§8) for the selected object.
- **[📝]**: Opens the Object Description editor inline below the selectors (§9).
- **State dropdown per row**: Three options — GRANT, DENY, ─ (none). Selecting a different value stages the change immediately; the row shows `*` pending indicator.
- **User sections**: Users with an explicit GRANT or DENY are listed first; a dashed divider separates them from users with no explicit assignment. Both sections are always visible.
- **[+ Add User...]**: Opens a searchable popup listing all database users not already in the explicit-assignment section. Selecting a user adds them with `*GRANT` staged. The new row appears at the top of the explicit-assignment section with the pending indicator.
- **Right-click a user row**: Context menu offers *Switch to User View for [user]*.

**Keyboard navigation:**
- `Tab` / `Shift+Tab` moves through rows.
- `Space` or `Enter` on the State cell opens its dropdown.
- Arrow keys within the open State dropdown select a value; `Enter` confirms.
- `Alt+O` focuses the Object selector; `Alt+P` focuses the Permission selector; `Escape` returns focus to the user list.

---

## 6. Audit Log Tab

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  From [ 2026-07-01 ]  To [ 2026-07-15 ]   User [ All ▼ ]   Object [ All ▼ ]      │
│                                                                   [ Export CSV ]   │
├─────────────────┬──────────┬────────────────┬─────────────────┬──────┬────────────┤
│  Timestamp    ↓ │  Admin   │  Affected User │  Object         │ Perm │  Action    │
├─────────────────┼──────────┼────────────────┼─────────────────┼──────┼────────────┤
│ 2026-07-15 14:32│ aadmin   │ jsmith         │ dbo.Products    │ SEL  │ GRANT      │
│ 2026-07-15 14:31│ aadmin   │ mjones         │ dbo.Orders      │ INS  │ REVOKE     │
│ 2026-07-14 09:15│ aadmin   │ svc_report     │ dbo.Orders      │ SEL  │ GRANT      │
├─────────────────┴──────────┴────────────────┴─────────────────┴──────┴────────────┤
│  Showing 3 of 47 entries                                                           │
└────────────────────────────────────────────────────────────────────────────────────┘
```

- **Date range fields**: Standard date-entry format (`YYYY-MM-DD`). Both fields are required; invalid dates are rejected with an inline error (FR-017).
- **User / Object dropdowns**: Populated from the same lists used in the matrix views. "All" shows all entries.
- **Sortable columns**: Clicking any column header sorts by that column; clicking again reverses direction. Active sort shown with ↑ / ↓ in the header.
- **Row expansion**: Clicking a row expands it to show the full auto-generated explanation (FR-012), previous state, and new state.
- **[Export CSV]**: Opens a Save As dialog; exports all currently filtered entries with the full column set defined in FR-016 (Administrator, AffectedUser, Object, Permission, Action, Timestamp, Explanation).
- **Entry count**: Bottom bar shows `Showing N of M entries` reflecting active filters.

---

## 7. Settings Screen

Accessed via [⚙ Settings] in the title bar. Replaces the main view content area (not a popup).

```
┌───────────────────────────────────────────────────────┐
│  Database Connection                                  │
├───────────────────────────────────────────────────────┤
│  Server    [ sql-server.corp.local                  ] │
│  Port      [ 1433    ]                                │
│  Database  [ AdventureWorks2019                     ] │
│  Schema    [ dbo     ]   (Bifrost's own tables)       │
│  Auth      [✓] Windows Authentication                 │
├───────────────────────────────────────────────────────┤
│  [ Test Connection ]                    [ Save ]      │
├───────────────────────────────────────────────────────┤
│  ✓ Connected as CORP\aadmin                           │
└───────────────────────────────────────────────────────┘
```

- **Server**: Non-empty string; validated on save (FR-017).
- **Port**: Numeric, 1–65535; validated on save (FR-017).
- **Database**: Non-empty string; the name of the target SQL Server database; validated on save (FR-017).
- **Schema**: Non-empty string, valid SQL identifier; the SQL Server schema used for Bifrost's own tables (audit log, etc.); defaults to `dbo`.
- **Windows Authentication**: Checked and non-editable in v1 (SQL Auth is out of scope per spec assumptions).
- **[Test Connection]**: Attempts a connection with the current (unsaved) field values and reports success or error inline below the button.
- **[Save]**: Persists valid configuration to `%APPDATA%\Bifrost\config.json` and reconnects (FR-013/014). Invalid fields are highlighted with error messages before saving.
- **Connection status**: Bottom row shows current connection state. On startup with missing/corrupt config, shows "No configuration found — please enter connection details." (edge case from spec).
- **Tab/keyboard**: All fields are reachable by Tab; Enter on [Save] submits; Escape navigates back to the last active matrix view.

---

## 8. Tag Editor Dialog

Modal popup, opened from any object row's right-click menu or the [🏷 Tags] button in Object View.

```
┌──────────────────────────────────────────────────┐
│  Tags — dbo.Orders (Table)                       │
├──────────────────────────────────────────────────┤
│  [finance ×]  [tier1 ×]                          │
│                                                  │
│  Add tag:  [ _______________ ]  [ + Add ]        │
│            Alphanumeric only (^[A-Za-z0-9]+$)    │
│                                                  │
│                                     [ Close ]    │
└──────────────────────────────────────────────────┘
```

- The title shows the entity being tagged (object or user name and type).
- Each existing tag is shown as a chip with `×` to remove. Removal is immediate (updates `tags.json`); no staging required.
- **Add tag field**: Validates on `+ Add` or `Enter`; rejects input that doesn't match `^[A-Za-z0-9]+$` with a clear inline error (FR-017).
- Tags are stored locally in `%APPDATA%\Bifrost\tags.json`; not in the database.
- **Rename**: Double-clicking a tag chip makes it editable inline; pressing Enter commits the rename; Escape cancels.
- **[Close]** or `Escape` closes the dialog; focus returns to the element that opened it.

---

## 9. Object Description Editor (Inline)

Opened via the [📝] button in Object View; expands inline below the object/permission selectors.

```
│  Description for dbo.Orders:                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │ Stores all sales orders. Each row represents one order header; line items   │  │
│  │ are in dbo.OrderItems.                                                       │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│  [ Save Description ]   [ Cancel ]                                                 │
```

- Description is free-text (no length restriction enforced by the UI, though SQL Server `extended_properties` has a 7500-character limit).
- **[Save Description]**: Writes to `sys.extended_properties` (`MS_Description`) via `src/db/objects.py`. Visible to all administrators on the same server (FR-023).
- **[Cancel]**: Discards unsaved text and collapses the editor.
- The editor is accessible via Tab when expanded; `Ctrl+Enter` saves; `Escape` cancels.

---

## 10. Connection Loss Behaviour (FR-022)

When the database connection is lost mid-session:

1. The global status bar immediately shows: `⚠ Connection lost — [Reconnect]`.
2. All matrix cell toggles are disabled; the grid is greyed out with an overlay message.
3. Staged changes are preserved in memory.
4. [Commit] and [Cancel] remain available — Cancel is always safe; Commit shows an error if attempted while disconnected.
5. Clicking [Reconnect] attempts to re-establish the connection using the saved configuration.
6. On successful reconnect, the matrix refreshes from the database and staged changes are re-applied as pending (the admin reviews and then commits or cancels).

---

## 11. Export Flow (FR-015/016)

Clicking **[Export ▼]** in the tab strip opens a dropdown:

```
  ┌────────────────────────────────┐
  │ Permission Matrix as CSV       │
  │ Audit Log as CSV               │
  └────────────────────────────────┘
```

Selecting either option opens a system **Save As** dialog pre-populated with a suggested filename:
- `Bifrost_Permissions_YYYYMMDD_HHMM.csv`
- `Bifrost_AuditLog_YYYYMMDD_HHMM.csv`

The export runs without blocking the UI thread (FR-015/016, SC-007). A progress indicator appears in the status bar during large exports; completion is confirmed with a brief inline message.

---

## 12. Keyboard Shortcut Summary (FR-021, SC-006)

| Shortcut        | Action                                    |
|-----------------|-------------------------------------------|
| `Ctrl+1`        | Switch to User View                       |
| `Ctrl+2`        | Switch to Compare View                    |
| `Ctrl+3`        | Switch to Object View                     |
| `Ctrl+4`        | Switch to Audit Log                       |
| `F5`            | Refresh all data from database            |
| `Ctrl+,`        | Open Settings                             |
| `Ctrl+Enter`    | Commit staged changes                     |
| `Escape`        | Cancel staged changes (matrix focus) / close dialog |
| `Alt+U`         | Focus user selector (User View)           |
| `Alt+O`         | Focus object selector (Object View)       |
| `Alt+P`         | Focus permission selector (Object View)   |
| Arrow keys      | Navigate matrix cells                     |
| `Space`/`Enter` | Cycle cell state / activate control       |
| `Ctrl+Right/Left` | Jump to next/prev user group (Compare) |
| `Home`/`End`    | First/last column in current row (Compare)|
| `Tab`/`Shift+Tab` | Move between controls in any view      |
