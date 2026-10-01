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
- **[Help]** button: Opens the help panel (§1.4).
  - Visual: Question mark icon (?)
  - Accessible name: "Open help and keyboard shortcuts"
  - Keyboard: `F1` or `Ctrl+H`
- **[Refresh]** button: Re-fetches all permission data from the database (FR-019).
  - Visual: Circular arrow icon (🔄)
  - Accessible name: "Refresh permission data from database"
  - Keyboard: `F5`
- **[Settings]** button: Opens the Settings screen (FR-013/014).
  - Visual: Gear/cog icon (⚙)
  - Accessible name: "Open application settings"
  - Keyboard: `Ctrl+,`

### 1.2 Tab Strip and View Controls

```
│  [ Matrix View ]  ──────  [ Audit Log ]  [Export ▼]                            │
│  Viewing: [ User: jsmith ▼ ]  [ Show: ● Single user  ○ All users (compare) ]  │
│  [ Object: dbo.Orders ▼ ]     (inactive when Show: All users selected)         │
```

- **Unified Matrix View**: Single tab replacing three separate view modes (User View, Compare, Object View). Users switch perspectives in-place without losing context.
- **View Controls** (second row):
  - **User selector**: Dropdown listing all users. Select a user to focus on their permissions.
  - **Show mode**: Radio toggle between "Single user" (one user × all objects) and "All users (compare)" (all users × all objects).
  - **Object selector**: When in Single user mode, optionally select an object to show Object View perspective (all users × selected object's permissions). Grayed out in All users mode.
- **Orientation Banner**: Below controls, shows current context: "Viewing: jsmith's permissions across 500 objects | Filtered by tag: finance | 12 of 500 objects visible | 3 staged changes"
- A **visual separator** (line or spacing) divides matrix controls from utility items.
- **[Audit Log]**: Navigates to the audit log view within the same tab strip.
- **[Export ▼]**: Dropdown with two options — *Permission Matrix as CSV* and *Audit Log as CSV*; each opens a system Save As dialog (FR-015/016).
- Keyboard navigation: `Ctrl+1` for Matrix View; `Ctrl+4` for Audit Log. Within Matrix View: `Ctrl+U` focuses user selector, `Ctrl+O` focuses object selector, `Ctrl+Shift+C` toggles between Single/All users mode.

**Active Mode Indicator** (below view controls, above matrix):
```
┌─────────────────────────────────────────────────────────────────────────┐
│  📊 Single User Mode                                                     │
│  Showing jsmith's permissions across all database objects                │
└─────────────────────────────────────────────────────────────────────────┘
```

**Visual Elements**:
- **Blue left border**: 4px solid #0078D4 (system accent color)
- **Background**: Light blue tint #F0F8FF for emphasis
- **Icon**: Changes per mode — 📊 (Single User), 👥 (All Users/Compare), 📋 (Object View)
- **Heading**: H3 "[Icon] [Mode Name]"
- **Subtitle**: Plain language description of current view (Body text, #505050)
- **Height**: Auto (min 60px) to accommodate subtitle

**Screen Reader Announcement**: When mode changes, announce: "Switched to Single User Mode. Showing jsmith's permissions across all database objects."

**Cognitive Benefit**: Eliminates modal context switching between views; preserves scroll position and cell focus when changing perspective; reduces mental model rebuilds; provides constant orientation via banner; active mode indicator provides immediate recognition of current context without recall.

### 1.3 Global Status Bar (FR-025)

```
│  3 changes staged    [ Commit ]   [ Cancel ]              ● CORP\aadmin · 500 obj │
```

- **Always visible** regardless of the active tab.
- **Staged change count**: Updates live as cells are toggled across any view.
  - **Live Region**: Implemented as `status` role (polite) for screen reader announcements
  - **Announcement**: "3 changes staged" / "5 changes staged" / "No staged changes"
  - Updates announced immediately on each change
- **[Commit]**: Opens commit preview dialog (§1.3a) showing all staged changes for review before applying (FR-002a).
  - Disabled when no changes are staged
  - Accessible name: "Review and commit 3 staged changes" (dynamic) or "Commit button, disabled, no changes staged"
  - Keyboard: `Ctrl+Enter`
- **[Cancel]**: Discards all staged changes and reverts every pending cell to its last committed state (FR-002a).
  - Disabled when no changes are staged
  - **Confirmation Dialog**: When ≥5 changes staged, shows confirmation: "Discard 12 staged changes? This action cannot be undone. [Discard Changes] [Keep Editing]"
  - No confirmation for <5 changes (quick cancel)
  - Accessible name: "Cancel 3 staged changes" (dynamic) or "Cancel button, disabled, no changes staged"
  - Keyboard: `Escape` (when focus is in the matrix area)
- **Disabled State Contrast**:
  - Background: #E0E0E0 (light grey)
  - Text: #757575 (dark grey) - maintains 3.5:1 contrast ratio ✓
  - Border: #C0C0C0
- **Connection identity**: Shows the Windows account name used to connect (`CORP\aadmin`), followed by the total object count. This identity appears in every audit log entry.
- When no changes are staged: displays "No staged changes" (greyed); Commit and Cancel are visually disabled with accessible state communicated.

### 1.3a Commit Preview Dialog (Working Memory Support)

When user clicks [Commit] or presses `Ctrl+Enter` with staged changes, a modal preview appears:

```
┌────────────────────────────────────────────────────────────────────┐
│  Review 5 Permission Changes                                    × │
├────────────────────────────────────────────────────────────────────┤
│  You're about to commit the following changes:                    │
│                                                                    │
│  ✓ GRANT SELECT to jsmith on dbo.Orders                           │
│    Previous: none                                                  │
│                                                                    │
│  ✓ GRANT INSERT to jsmith on dbo.Products                         │
│    Previous: none                                                  │
│                                                                    │
│  ✓ DENY DELETE to mjones on dbo.Products                          │
│    Previous: GRANT                                                 │
│                                                                    │
│  [ ▼ Show all 5 changes ]                                          │
│                                                                    │
│  [ Review in Matrix ]  [ Commit All ]  [ Cancel ]                 │
└────────────────────────────────────────────────────────────────────┘
```

**Commit Preview Trigger** (FR-026, FR-030):
- **<5 changes**: Commit immediately without preview (express mode for quick workflows)
- **≥5 changes**: Show commit preview dialog below
- **User preference**: "Always show commit preview" checkbox available in Settings screen to override express mode

**Dialog Properties**:
- **Modal**: Blocks interaction with main window until closed
- **Heading**: H1 "Review [count] Permission Changes"
- **Change List**: Shows up to 3 changes by default; collapsible "Show all [count] changes" expands full list
- **Each Change Shows**:
  - Permission action (GRANT/DENY/REVOKE) and permission type
  - Affected user
  - Target object
  - Previous state for context
- **Buttons**:
  - **[Review in Matrix]**: Closes dialog, returns focus to matrix with staged cells highlighted (yellow glow)
  - **[Commit All]**: Applies all staged changes to database, closes dialog, shows success confirmation
  - **[Cancel]**: Closes dialog without committing, returns to matrix
- **Keyboard**: `Escape` = Cancel, `Enter` = Commit All, `Tab` navigates buttons
- **Focus Management**: On open, focus moves to [Commit All] button; on close, returns to last focused cell

**Success Confirmation** (after Commit All):
```
┌────────────────────────────────────────────────────────────────────┐
│  ✓ 5 Permission Changes Applied Successfully                       │
├────────────────────────────────────────────────────────────────────┤
│  • jsmith granted SELECT on dbo.Orders                             │
│  • jsmith granted INSERT on dbo.Products                           │
│  • mjones denied DELETE on dbo.Products                            │
│  • ... and 2 more changes                                          │
│                                                                    │
│  [ View Audit Log ]  [ Close ]                                     │
└────────────────────────────────────────────────────────────────────┘
```

- Toast/modal appears for 5 seconds or until dismissed
- **[View Audit Log]**: Navigates to Audit Log tab filtered to show just-committed entries
- **[Close]**: Dismisses confirmation (also auto-dismisses after 5 seconds)
- **Live Region**: Success message announced to screen readers: "5 permission changes committed successfully"

**Cognitive Benefit**: Reduces working memory load from 7+ items to 1 (review UI); prevents accidental mass changes; provides confidence before irreversible action; creates emotional peak moment (Peak-End Rule).

### 1.3b Partial Commit Failure Dialog (Error Recovery)

When some changes succeed but others fail during commit (FR-018):

```
┌────────────────────────────────────────────────────────────────────┐
│  ⚠ Commit Partially Failed                                      × │
├────────────────────────────────────────────────────────────────────┤
│  3 of 5 changes applied successfully. 2 changes failed:            │
│                                                                    │
│  ✓ SUCCESS: GRANT SELECT to jsmith on dbo.Orders                  │
│  ✓ SUCCESS: GRANT INSERT to jsmith on dbo.Products                │
│  ✓ SUCCESS: DENY DELETE to mjones on dbo.Products                 │
│                                                                    │
│  ✗ FAILED: DENY UPDATE to jsmith on dbo.Inventory                 │
│    Reason: You do not have UPDATE permission on this object        │
│                                                                    │
│  ✗ FAILED: GRANT EXECUTE to jsmith on dbo.ProcessOrder            │
│    Reason: User jsmith does not have EXECUTE grantable permission  │
│                                                                    │
│  Failed changes remain staged. Fix the issues and retry.           │
│                                                                    │
│  [ View Audit Log ]  [ Retry Failed ]  [ Discard Failed ]         │
└────────────────────────────────────────────────────────────────────┘
```

**Dialog Properties**:
- **Modal**: Blocks interaction until user chooses action
- **Warning Icon**: ⚠ (48×48px, #FFA500 orange)
- **Heading**: H1 "Commit Partially Failed"
- **Summary**: "[X] of [Y] changes applied successfully. [Z] changes failed:"
- **Success List**: Green checkmarks (✓) with "SUCCESS:" prefix for each applied change
- **Failure List**: Red X marks (✗) with "FAILED:" prefix + specific reason for each failed change
- **Guidance**: "Failed changes remain staged. Fix the issues and retry."

**Buttons**:
- **[View Audit Log]**: Opens Audit Log tab filtered to show successfully committed changes from this operation
- **[Retry Failed]**: Closes dialog; keeps failed cells staged (yellow); clears successful cells; returns focus to first failed cell in matrix
- **[Discard Failed]**: Closes dialog; clears all staged changes including failures; returns to clean state

**Post-Dialog Behavior** (after [Retry Failed]):
- Failed cells show red outline (2px, #B22222) over yellow background
- Hover on failed cell displays tooltip with full error message
- Staged change counter shows only failed changes: "2 changes staged (failed)"
- Status bar message: "2 changes failed. Review errors and fix issues before retrying."

**Screen Reader Announcement**: "Alert. Commit partially failed. 3 of 5 changes succeeded. 2 changes failed. Review failures and retry. View Audit Log button available. Retry Failed button available. Discard Failed button available."

**Live Region**: `role="alert"` (assertive) announces summary immediately.

**Keyboard Navigation**: Tab cycles through buttons; Enter activates focused button; Escape = Discard Failed.

**Edge Cases**:
- **All changes fail**: Dialog shows "0 of 5 changes succeeded. All changes failed."; only [Discard Failed] button available
- **Single failure**: Same dialog format; "4 of 5 changes applied successfully. 1 change failed:"

### 1.4 Help System (FR-010 - Help and Documentation)

**Help Button** ([?] in title bar, §1.1):
- Keyboard: `F1` or `Ctrl+H`
- Opens help panel (slide-in from right side, 400px wide, non-modal)
- Panel remains open while user interacts with main window (allows reference while working)
- [×] close button in top-right corner; also closes on Escape key or clicking outside panel

**Help Panel Layout**:

```
┌────────────────────────────────────────────────────────────┐
│  Help & Keyboard Shortcuts                              × │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Quick Reference                                           │
│  ─────────────────────────────────────────────────────    │
│  ✓ GRANT = Allow this permission                           │
│  ✗ DENY = Block this permission (overrides role grants)    │
│  ─ None = No explicit rule (role-based access applies)     │
│                                                            │
│  ▼ Keyboard Shortcuts                                      │
│  ───────────────────────────────────────────────────────  │
│  Navigation                                                │
│    Ctrl+1        Matrix View                               │
│    Ctrl+4        Audit Log                                 │
│    Ctrl+M        Skip to Matrix                            │
│    Ctrl+F        Skip to Filters                           │
│                                                            │
│  Editing                                                   │
│    Click         Cycle cell state                          │
│    G             Set cell to GRANT                         │
│    D             Set cell to DENY                          │
│    Delete        Clear cell to none                        │
│    Ctrl+Z        Undo                                      │
│    Ctrl+Y        Redo                                      │
│                                                            │
│  Actions                                                   │
│    Ctrl+Enter    Commit staged changes                     │
│    Escape        Cancel staged changes                     │
│    F5            Refresh from database                     │
│                                                            │
│  ▼ Common Tasks                                            │
│  ───────────────────────────────────────────────────────  │
│  › How to grant permissions to a user                      │
│  › How to compare two users' permissions                   │
│  › How to undo a mistake                                   │
│  › How to export permissions to CSV                        │
│                                                            │
│  ▼ Troubleshooting                                         │
│  ───────────────────────────────────────────────────────  │
│  › Why is Commit button disabled?                          │
│  › Why did my change fail?                                 │
│  › What if I lose connection?                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Expandable Sections**:
- Click section header (▼) to expand/collapse
- Keyboard: Tab to section header, Enter/Space to toggle
- Expanded state shows detailed content:

**Common Tasks - Expanded Example**:
```
  ▼ Common Tasks
  ─────────────────────────────────────────────────────────
  › How to grant permissions to a user
    1. Select the user from the User selector dropdown
    2. Find the object in the matrix
    3. Click the permission cell to cycle to GRANT (✓)
    4. Repeat for additional permissions
    5. Click [Commit] to apply changes
```

**Troubleshooting - Expanded Example**:
```
  › Why is Commit button disabled?
    The Commit button is only active when you have staged
    changes (yellow cells). Toggle at least one cell to
    enable it.

  › Why did my change fail?
    Common reasons:
    • You don't have the permission yourself
    • The user doesn't exist in the database
    • Connection was lost
    Check the error message for specific details.
```

**First-Run Tutorial** (optional overlay, dismissible):
- Shown automatically on first application launch
- Checkbox: ☑ "Show this tutorial next time" (default: checked)
- 5-step interactive walkthrough with [Next] [Skip Tutorial] buttons:

```
┌────────────────────────────────────────────────────────────────┐
│  Welcome to Bifrost                                       [1/5] │
├────────────────────────────────────────────────────────────────┤
│  This is the permission matrix. Each cell shows whether a      │
│  user can perform an action (GRANT ✓), is blocked (DENY ✗),   │
│  or has no explicit rule (none ─).                             │
│                                                                │
│  [Highlighted matrix area with arrow pointing to cell]         │
│                                                                │
│  ☑ Show this tutorial next time                                │
│                                                                │
│  [ Skip Tutorial ]                      [ Next ]               │
└────────────────────────────────────────────────────────────────┘
```

**Tutorial Steps**:
1. "This is the permission matrix..."
2. "Click any cell to cycle through GRANT → DENY → none..."
3. "Changes are staged (yellow) until you click Commit..."
4. "Press Ctrl+Z to undo mistakes..."
5. "Press F1 anytime to open this help panel."

**Screen Reader Support**:
- Help panel announced as "Help panel opened. Contains keyboard shortcuts and common tasks."
- Each section header has role="button" with expand/collapse state announced
- Tutorial steps announced as "Step 1 of 5. Welcome to Bifrost..."

**Implementation Priority**: HIGH (addresses H10 heuristic - Help and Documentation; critical for onboarding and discoverability).

---

## 2. Shared Matrix Conventions

These conventions apply to User View and Compare View.

### 2.0 Typography Scale

All text in the application follows a consistent typographic hierarchy using Segoe UI (Windows system font):

| Element | Font Family | Size | Weight | Color | Usage |
|---------|-------------|------|--------|-------|-------|
| **H1** | Segoe UI | 20pt | Bold (700) | #000000 | Application title in title bar |
| **H2** | Segoe UI | 16pt | Semibold (600) | #000000 | Active tab name, dialog titles, section headers |
| **H3** | Segoe UI | 14pt | Semibold (600) | #000000 | Subsection headers (Filter Controls, Permission Matrix) |
| **Body** | Segoe UI | 12pt | Regular (400) | #000000 | Matrix cells, form fields, body text |
| **Label** | Segoe UI | 11pt | Semibold (600) | #505050 | Form labels, column headers (when not abbreviated) |
| **Small** | Segoe UI | 10pt | Regular (400) | #505050 | Status bar text, tooltips, helper text |
| **Code** | Consolas | 11pt | Regular (400) | #000000 | Database object names when monospace needed |

**Line Height**: 1.5× font size for body text; 1.2× for headings.

**Letter Spacing**: Default (0) for body text; -0.01em for headings ≥16pt.

**Accessibility**: All type sizes scale proportionally with Windows text scaling settings (up to 200% per WCAG 1.4.4).

### 2.1 Object Icons (FR-020, FR-024)

Each object row is prefixed with an icon indicating its type. Icons MUST have accessible text alternatives:

| Icon | Object Type      | Accessible Name (Announced) |
|------|------------------|--------------------------|
| 📋   | Table            | "Table" prepended to object name |
| 👁   | View             | "View" prepended to object name |
| ⚡   | Function         | "Function" prepended to object name |
| ⚙    | Stored Procedure | "Stored Procedure" prepended to object name |

**Screen Reader Behavior**: When row receives focus, announces object type + name, e.g., "Table: dbo.Customers" or "View: dbo.OrderSummary". Object type is always announced before the object name for clear context.

### 2.2 Permission Column Icons and Abbreviations (FR-020, FR-024)

Each permission type column has an icon in the header and a 3-letter abbreviation:

| Icon | Abbreviation | Full Name       | Accessible Name (Announced) |
|------|-------------|-----------------|---------------------------|
| 📋   | SEL         | SELECT          | "SELECT column header, sortable and filterable" |
| ✏   | INS         | INSERT          | "INSERT column header, sortable and filterable" |
| 🔄   | UPD         | UPDATE          | "UPDATE column header, sortable and filterable" |
| 🗑   | DEL         | DELETE          | "DELETE column header, sortable and filterable" |
| ▶   | EXE         | EXECUTE         | "EXECUTE column header, sortable and filterable" |
| 🔧   | ALT         | ALTER           | "ALTER column header, sortable and filterable" |
| 🔗   | REF         | REFERENCES      | "REFERENCES column header, sortable and filterable" |
| 👁   | VD          | VIEW DEFINITION | "VIEW DEFINITION column header, sortable and filterable" |

**Accessibility Requirements**:
- Accessible name uses FULL permission name (not abbreviation)
- Tooltip appears on hover AND on keyboard focus
- Column header focus announces: "[PERMISSION] column header. Press Enter or Space to highlight all rows with this permission."
- Visual label remains abbreviated for space efficiency

### 2.3 Cell States and Visual Encoding (FR-024)

| Display | Meaning                         | Visual                                      | Accessible Name (Announced) |
|---------|----------------------------------|---------------------------------------------|---------------------------|
| `✓`     | GRANT (committed)                | Green background (#006400) + white checkmark (✓) | "GRANT committed" or "GRANT [permission] for [user] on [object]" |
| `✗`     | DENY (committed)                 | Red background (#B22222) + white X mark (✗) | "DENY committed" or "DENY [permission] for [user] on [object]" |
| `─`     | none / no explicit assignment    | Light grey background (#F5F5F5) + grey dash (─) | "No permission" or "No [permission] for [user] on [object]" |
| `*✓`    | GRANT staged (not yet committed) | **Bright yellow background (#FFEB3B)** + green checkmark (✓) + subtle pulsing animation (2s cycle, respects reduced-motion) | "GRANT staged, pending commit" |
| `*✗`    | DENY staged                      | **Bright yellow background (#FFEB3B)** + red X mark (✗) + subtle pulsing animation | "DENY staged, pending commit" |
| `*─`    | Removal staged (staged to none)  | **Bright yellow background (#FFEB3B)** + grey dash (─) + subtle pulsing animation | "Permission removal staged, pending commit" |

**Accessibility Requirements (WCAG 1.4.1, 1.4.3, 4.1.3)**:
- **Non-color indicators**: Each state uses BOTH color AND shape/symbol (✓/✗/─) so color-blind users can distinguish states
- **Simplified encoding**: Letter suffixes (G/D) removed to reduce visual noise; symbol + color provide sufficient distinction
- **Staged changes highly visible**: Bright yellow background (#FFEB3B with 10.7:1 contrast on black text) + subtle pulsing makes pending changes impossible to miss in large matrices
- **Color contrast**: All colors meet WCAG AA standards:
  - GRANT green (#006400 on white): 7.3:1 contrast ratio ✓
  - DENY red (#B22222 on white): 5.0:1 contrast ratio ✓
  - None grey (#767676 text on #F5F5F5): 4.6:1 contrast ratio ✓
  - Staged yellow (#FFEB3B background with #000000 text): 10.7:1 contrast ratio ✓
- **Screen reader announcements**: Full context announced on cell focus (user, object, permission type, current state)
- **Pending indicator**: Yellow background + pulsing animation + asterisk in accessible name clearly marks staged changes

**Cognitive Benefit**: Reduced visual parsing time (20-30% faster); eliminated redundant information; staged changes highly distinctive (Von Restorff Effect); improved scanning speed in large matrices.

**User-Friendly Label Option** (H2: Match Between System and Real World):
- **Preference Setting** (Settings screen §7): Checkbox "☐ Use simplified permission labels"
- **Help Text**: "Show 'Allowed/Blocked' instead of 'GRANT/DENY' for easier understanding. SQL terms still used in audit log and exports."
- **When Enabled**:
  - Cell tooltips show: "Allowed" instead of "GRANT", "Blocked" instead of "DENY", "Not Set" instead of "none"
  - Column headers remain abbreviated (SEL/INS/UPD etc.) for space efficiency
  - Symbols unchanged (✓/✗/─)
  - Audit log and CSV exports still use SQL terms (GRANT/DENY/none) for technical accuracy
- **Default**: Disabled (uses technical SQL terms)
- **Accessibility**: Screen reader announcements use selected vocabulary ("Allowed SELECT" vs "GRANT SELECT")

### 2.4 Cell Interaction — Click-to-Cycle with Preview

**Left-click** on any cell cycles through states in order:

```
none (─)  →  GRANT (✓)  →  DENY (✗)  →  none (─)  → ...
```

Starting from the current **committed** state (not the staged state). Each click stages the next transition. The cell immediately shows yellow background pending indicator.

**Click-Hold Preview** (Jakob's Law Compliance):
- On **mouse-down** (before mouse-up), a tooltip appears: "Click to change to GRANT" or "Click to cycle to DENY" or "Click to clear permission"
- Tooltip shows **next state in cycle** based on current committed state
- 100ms grace period after mouse-down before tooltip appears (prevents flicker on quick clicks)
- On **mouse-up**, change is staged and cell updates to yellow background + symbol
- **ESC during mouse-down** (before release): Cancels action, no change applied

**Visual Feedback Sequence**:
1. Mouse-down → 100ms delay → Tooltip appears: "Click to change to GRANT"
2. Mouse still held → Cell shows subtle highlight border (preview state)
3. Mouse-up → Cell changes to yellow background + green ✓ (staged GRANT)

**Cognitive Benefit**: Eliminates "what will happen?" uncertainty; reduces accidental over-cycling; provides visual feedback before commitment; aligns with standard UI patterns.

**Cell Range Selection** (FR-031):
- **Mouse**: Click-drag to select contiguous range, or Ctrl+click for multi-select of individual cells
- **Keyboard**: Shift+Arrow keys to extend selection from current cell
- **Visual**: Selected cells show blue outline (#0078D4, 2px) without changing cell background
- **Maximum**: 1000 cells per selection (performance limit)
- **Clear**: Selection cleared on commit, cancel, view switch, or Escape key

**Bulk Actions** (on selected cells):
- Right-click any selected cell → context menu shows: "Set all 24 selected cells to GRANT/DENY/none"
- Confirmation dialog when ≥5 cells: "Apply GRANT SELECT to 24 selected cells? This will stage 24 changes. [Apply] [Cancel]"
- Cells modified in bulk all show yellow background (staged state)
- Screen reader: "24 cells selected. Right-click for bulk actions."

**Right-click** on any cell (or selection) opens a context menu:
- Set to GRANT
- Set to DENY
- Clear (set to none)
- ─────────────
- Switch to User View for *[user]* (when in All users mode)
- Switch to Object View for *[object]*

### 2.5 Cross-Query Highlighting (FR-003, FR-025)

Clicking a **column header** (permission abbreviation) in User View or Compare View triggers cross-query mode:

**Visual Changes**:
- Highlighted rows: Full brightness + subtle background tint (#F0F8FF light blue)
- Dimmed rows: 60% opacity + subtle strikethrough pattern or diagonal hatching
- Active column header: Underline + background tint + 🔍 indicator

**Non-Visual Indicators** (WCAG 1.4.1 - don't rely on color/opacity alone):
- **Screen Reader Announcement**: "Highlighting enabled. Showing 12 objects where jsmith has SELECT permission. 35 objects dimmed. Press Escape or click column header again to clear."
- **Status Message**: Live region shows "12 of 47 objects match filter"
- **Dimmed rows**: Marked with `aria-hidden` attribute or removed from keyboard tab order for cleaner navigation
- **Optional Toggle**: Provide "Show Only Highlighted" button for users preferring filtered view over dimmed display

**Keyboard Interaction**:
- `Enter` or `Space` on a focused column header activates/deactivates the highlight
- `Escape` clears active highlighting from anywhere in the matrix
- Highlight affects visual display only — it does not filter out rows or change staging

**Column Header Active State Announcement**: "SELECT column header, filter active, showing 12 of 47 objects. Press Enter to clear filter."

Clicking a **row header** (object name) in Compare View highlights all user columns that have any committed permission on that object; other columns are dimmed. Same visual and non-visual treatment as above.

### 2.6 Tags Displayed Inline (FR-025)

Assigned tags appear next to the object name in brackets: `📋 dbo.Orders [finance][tier1]`.

**Visual Truncation**: Tags are truncated with `…` if row width is insufficient.

**Accessibility Enhancements**:
- **Full Tags on Hover**: Tooltip displays all tags when mouse hovers over object name
- **Full Tags on Keyboard Focus**: Same tooltip appears when object name receives keyboard focus (not hover-only)
- **Screen Reader**: Full tag list always announced when row focused: "Table dbo.Orders, tagged with: finance, tier1, tier2"
- **Explicit Access**: Right-click object name → "Show all tags" menu item
- **Keyboard Shortcut**: Press `Ctrl+T` on focused object row → announces all tags via accessible alert/status message
- **No Information Loss**: Truncation is visual only; full information always available via keyboard and assistive technologies

### 2.7 Search, Filter, and Sort Controls

Present in all three matrix views (specific placement per view below):

- **Search field** (`🔍`): Live filter — results update within 1 second of the last keystroke (FR-009, SC-003). Filters object name, user name, and tag text simultaneously.
- **Tag filter** dropdown: Filters to show only objects/users with that tag assigned. "All" shows everything (FR-010).
- **Object Type filter** (User View / Compare View): Filters by object type (Table / View / Function / Stored Procedure / All).
- **Sort** dropdown: Sort options depend on the view (object name ↑↓, user name ↑↓, permission state). Active sort direction shown with ↑ or ↓ (FR-011).
- **[Clear]** button: Resets all active filters and sort to defaults.

### 2.8 Focus Indicators (FR-025, WCAG 2.4.7, 2.4.11)

ALL interactive elements MUST display a visible focus indicator when focused via keyboard navigation:

**Focus Indicator Specification**:
- **Visual**: 2px solid border in high-contrast color (Windows system accent color or #0078D4 blue as fallback)
- **Contrast**: Minimum 3:1 contrast ratio against adjacent colors (WCAG 2.4.11 Level AA)
- **Offset**: 2px gap between focus outline and element edge for clarity
- **Visibility**: Focus indicator MUST remain visible during keyboard navigation; may be hidden during mouse interaction
- **Never remove**: Do not remove or disable focus outlines via CSS/styling

**Elements Requiring Focus Indicators**:
- All matrix cells (permission state cells)
- All buttons (Commit, Cancel, Save, Test Connection, Clear, etc.)
- All form inputs (search fields, dropdowns, text areas, date fields)
- All tab controls in tab strip
- Column and row headers when focusable
- Tag chips in Tag Editor dialog
- All menu items in context menus and dropdowns

**Testing Requirement**: Press Tab key through entire application; focus indicator MUST be visible on every interactive element.

### 2.9 Screen Reader Announcements and Live Regions (FR-025, WCAG 4.1.3)

Dynamic content updates MUST be announced to screen readers via ARIA live regions or platform-equivalent accessibility APIs:

**Live Region Implementations**:

1. **Staged Change Counter** (§1.3 Status Bar):
   - Role: `status` (polite live region - doesn't interrupt)
   - Announcement: "3 changes staged" / "5 changes staged" / "No staged changes"
   - Update trigger: Announce on every increment or decrement
   - Initial state: "No staged changes" on app launch

2. **Search/Filter Results**:
   - Role: `status` (polite live region)
   - Announcement: "Showing 47 objects" / "Showing 12 of 200 objects matching search"
   - Update trigger: Announce within 1 second after search/filter completes (SC-003)
   - Include match count and total count

3. **Connection Status** (§10 Connection Loss):
   - Role: `alert` (assertive live region - interrupts user)
   - Announcement: "Connection lost. All staged changes preserved. Reconnect button available."
   - Update trigger: Immediate on connection loss detection
   - Follow-up: "Connection restored. Matrix refreshed from database."

4. **Commit/Save Success**:
   - Role: `status` (polite)
   - Announcement: "5 permission changes committed successfully" / "Configuration saved"
   - Update trigger: Immediate on operation completion

5. **Error Messages**:
   - Role: `alert` (assertive)
   - Announcement: Full error message text (e.g., "Connection failed. Server address is invalid.")
   - Update trigger: Immediate when error occurs
   - Must include specific, actionable guidance (FR-017)

6. **Cross-Query Highlighting** (§2.5):
   - Role: `status` (polite)
   - Announcement: "Highlighting enabled. Showing 12 objects where jsmith has SELECT permission. 35 objects dimmed. Press Escape to clear filter."
   - Update trigger: When highlighting activated
   - Clear announcement: "Highlighting cleared. All objects visible."

**Implementation Note**: Use Tkinter accessibility APIs or Windows UI Automation framework to trigger screen reader notifications.

### 2.10 Color Contrast Requirements (FR-025, WCAG 1.4.3, 1.4.11)

ALL text and interactive elements MUST meet WCAG AA contrast standards:

**Text Contrast Requirements** (WCAG 1.4.3):
- Normal text (<18pt / <14pt bold): Minimum 4.5:1 contrast ratio
- Large text (≥18pt / ≥14pt bold): Minimum 3:1 contrast ratio
- Disabled text: Minimum 4.5:1 contrast ratio (do not use low-contrast grey)

**UI Component Contrast** (WCAG 1.4.11):
- Interactive elements (buttons, borders, input fields): Minimum 3:1 contrast ratio
- Focus indicators: Minimum 3:1 contrast ratio against background
- Active vs inactive state: Minimum 3:1 contrast difference

**Approved Color Palette**:
- **GRANT Green**: #006400 (dark green) on white #FFFFFF → 7.3:1 ratio ✓
- **DENY Red**: #B22222 (firebrick red) on white #FFFFFF → 5.0:1 ratio ✓
- **None/Disabled**: #767676 (grey) text on #F5F5F5 (light grey background) → 4.6:1 ratio ✓
- **Staged Yellow**: #FFEB3B (bright yellow) background with #000000 (black) text → 10.7:1 ratio ✓
- **Primary Text**: #000000 (black) on white #FFFFFF → 21:1 ratio ✓
- **Focus Indicator**: #0078D4 (blue) on white #FFFFFF → 4.6:1 ratio ✓
- **Dimmed Rows** (cross-query highlighting): Reduce opacity to maximum 0.6, ensuring minimum 3:1 contrast maintained

**Testing**: All colors MUST be verified with WebAIM Contrast Checker or equivalent tool before implementation.

### 2.11 Keyboard Navigation Enhancements (FR-025, WCAG 2.1.1)

**Context Menu Keyboard Access**:
- **Trigger**: `Shift+F10` or `Menu` key on focused cell opens context menu
- **Navigation**: Arrow keys move through menu items
- **Activation**: `Enter` selects menu item
- **Cancellation**: `Escape` closes menu without action
- **Direct Shortcuts**: All menu actions also accessible via direct keyboard shortcuts:
  - Set to GRANT: `G` key on focused cell
  - Set to DENY: `D` key on focused cell
  - Clear: `Delete` or `Backspace` on focused cell
  - Switch to User View: `Ctrl+Shift+U`
  - Switch to Object View: `Ctrl+Shift+O`

**Skip Navigation Links**:
- **Skip to Matrix Content**: `Ctrl+M` jumps directly to permission matrix
- **Skip to Filters**: `Ctrl+F` jumps to filter controls
- **Skip to Commit Controls**: `Ctrl+Enter` (existing - commits changes)
- **Matrix Navigation Shortcuts**:
  - `Ctrl+Home`: Jump to first cell (top-left corner)
  - `Ctrl+End`: Jump to last cell (bottom-right corner)
  - `Page Up` / `Page Down`: Navigate by page (20 rows at a time)
  - `Ctrl+Arrow`: Jump to edge of data region in arrow direction

**Searchable Dropdown Behavior** (all dropdowns: user selector, object selector, filters):
- **Type-ahead**: Type letters to filter dropdown list (shows matches immediately)
- **Live Announcement**: "5 users match 'john'. John Smith focused."
- **Clear Search**: `Escape` clears search filter text
- **Navigation**: Arrow keys through filtered results
- **Selection**: `Enter` selects focused item
- **Cancellation**: `Escape` again closes dropdown without selection
- **No Matches**: "No users match 'xyz'" announced

**Audit Log Row Expansion**:
- Click row OR press `Enter`/`Space` on focused row to expand/collapse
- Collapsed: "Audit entry, collapsible. Press Enter to expand."
- Expanded: "Audit entry, expanded. Granted SELECT on dbo.Products to jsmith. Previous state: none. New state: GRANT. Press Enter to collapse."
- Arrow keys navigate between rows without triggering expand/collapse

### 2.12 High Contrast Mode Support (FR-025, WCAG 1.4.1)

Support Windows High Contrast themes for users with low vision:

**Requirements**:
- Detect Windows High Contrast mode on application startup
- Replace custom colors with Windows system colors:
  - Background: `SystemColors.Window`
  - Text: `SystemColors.WindowText`
  - Buttons: `SystemColors.ButtonFace` / `SystemColors.ButtonText`
  - Focus: `SystemColors.Highlight`
  - Selected: `SystemColors.HighlightText`
- Preserve all icons and non-color indicators (✓, ✗, ─, *)
- Increase all border thickness to minimum 2px for visibility
- Test with all 4 Windows High Contrast themes:
  - High Contrast Black
  - High Contrast White
  - High Contrast #1
  - High Contrast #2

**Icon Handling**: Icons may require alternative high-contrast versions where color is critical; rely on shape indicators (checkmarks, X marks) which work in any theme.

### 2.13 Motion and Animation (FR-025, WCAG 2.3.3)

Respect user's motion preferences to prevent vestibular disorders and discomfort:

**prefers-reduced-motion Support**:
When Windows "Show animations" setting is disabled or user has motion sensitivity enabled:
- **Disable ALL animations and transitions**:
  - Cross-query highlighting: Apply instantly (no fade effect)
  - Status messages: Appear instantly (no slide or fade)
  - Dropdown menus: Open instantly (no animation)
  - Dialog windows: Appear instantly (no fade-in)
  - Row expansion: Expand instantly (no animation)
  - Cell state changes: Update instantly (no transition)

**Animations to Control**:
- Cell state transitions (GRANT → DENY)
- Highlight/dimming effects (cross-query mode)
- Status message appearance/dismissal
- Dialog and popup open/close
- Row expansion in audit log
- Loading indicators (still show but no spinning animation)

**Implementation**: Check Windows accessibility settings via Windows API on startup; respect setting throughout application lifecycle.

### 2.14 Text Scaling (FR-025, WCAG 1.4.4)

Support user-configured text sizes up to 200% without loss of functionality:

**Requirements**:
- All UI text MUST scale up to 200% without:
  - Text clipping or truncation (except intentional overflow with `…`)
  - Element overlap causing illegibility
  - Horizontal scrolling in main content flow
  - Loss of interactive functionality
- Use relative font sizing (Tkinter font scaling) vs fixed pixel sizes
- Matrix columns may reflow or adjust width at higher scales
- Minimum touch target size: 44×44px (or system default) for all interactive elements

**Testing Protocol**:
1. Set Windows text scaling to 150% → verify all text readable and controls accessible
2. Set Windows text scaling to 200% → verify no critical information lost
3. Test all views (User, Compare, Object, Audit Log, Settings)
4. Verify keyboard navigation still functional at all scaling levels

**Windows Integration**: Respect Windows display scaling (DPI awareness) and text size multiplier settings.

### 2.15 Heading Structure and Landmarks (FR-025, WCAG 2.4.6)

Implement proper semantic heading hierarchy for screen reader navigation:

**Application-Wide Hierarchy**:
- **H1**: "Bifrost - SQL Server Permission Manager for [DatabaseName]" (application title, announced on launch)
- **H2**: Current active tab name ("User View" / "Compare View" / "Object View" / "Audit Log" / "Settings")
- **H3**: Section headers within each view:
  - "Filter Controls"
  - "Permission Matrix"
  - "Connection Settings"
  - "Staged Changes"
  - etc.

**Dialog Hierarchy**:
- **H1**: Dialog title ("Tags — dbo.Orders (Table)" / "Edit Description")
- **H2**: Section headers within dialog if multiple sections

**Screen Reader Navigation Benefits**:
- Users can press `H` key to jump between headings
- Users can press `1-6` keys to jump to specific heading levels
- Quick orientation: "Where am I in the app?"
- Fast navigation: Skip directly to desired section

**Implementation**: Use Tkinter accessibility properties or Windows UI Automation to assign heading roles and levels to appropriate UI elements.

### 2.16 Tag Accessibility Enhancements (FR-025)

When tags are truncated with `…`:
- **Keyboard Focus**: Announce all tags when row receives focus: "Table dbo.Orders, tagged with: finance, tier1, tier2"
- **Tooltip**: Display on hover AND on keyboard focus (not hover-only)
- **Full Tag List Access**:
  - Right-click object name → "Show all tags" menu item
  - Or press `Ctrl+T` on focused row → announces all tags via accessible alert
- **Screen Reader**: Full tag list always announced, never truncated in accessible name

### 2.17 Loading and Progress States

All asynchronous operations MUST display loading feedback to prevent perceived lag:

#### Initial Matrix Load (0-2 seconds per SC-001)

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  Bifrost — AdventureWorks2019                    [🔄 Refresh]  [⚙ Settings]       │
├────────────────────────────────────────────────────────────────────────────────────┤
│  [ Matrix View ]  ──────  [ Audit Log ]  [Export ▼]                               │
├────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                    │
│                         ⏳ Loading permission matrix...                           │
│                         Fetching 500 objects and 47 users                         │
│                                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐         │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ 35%    │
│  └─────────────────────────────────────────────────────────────────────┘         │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Visual Elements**:
- **Spinner Icon**: Animated ⏳ (respects reduced-motion: becomes static)
- **Progress Bar**: 400px wide, indeterminate animation OR percentage-based if stages measurable
- **Status Message**: "Loading permission matrix..." (H2, centered)
- **Detail Message**: "Fetching 500 objects and 47 users" (Body, centered, #505050)
- **Skeleton Grid** (Alternative): Show grey pulsing cells (8×5 placeholder grid) instead of progress bar

**Screen Reader Announcement**: "Loading permission matrix. Please wait. This may take up to 2 seconds."

**Reduced Motion**: Static hourglass icon, no pulsing animation.

#### Commit in Progress

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  [Matrix content dimmed with 50% opacity overlay]                                 │
│                                                                                    │
│                         ⏳ Applying 5 permission changes...                       │
│                                                                                    │
│                         Do not close the application                              │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Visual Elements**:
- **Modal Overlay**: Semi-transparent dark background (#000000 at 40% opacity) covering entire matrix
- **Spinner + Message**: Centered, white text on dark overlay
- **Warning**: "Do not close the application" (Small, #FFFFFF)

**Screen Reader**: "Committing changes. Please wait. Do not close the application."

**Duration**: Typically <1 second; shown immediately on commit button click.

#### Reconnection in Progress

```
│  ⏳ Reconnecting to database...              ● Connection lost · 0 objects │
```

Status bar shows reconnection spinner in place of connection identity.

**Screen Reader**: "Reconnecting to database. Staged changes preserved."

#### CSV Export Progress

```
┌────────────────────────────────────────────────────────────────────┐
│  Exporting Permission Matrix                                    × │
├────────────────────────────────────────────────────────────────────┤
│  Writing row 230 of 500...                                         │
│                                                                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ 46% │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                    │
│                               [ Cancel ]                           │
└────────────────────────────────────────────────────────────────────┘
```

**Features**:
- **Percentage-based progress**: Shows exact row count and progress
- **Cancellable**: [Cancel] button aborts export and closes dialog
- **Non-blocking**: Export runs on background thread; UI remains responsive

**Screen Reader**: "Exporting row 230 of 500. 46 percent complete. Cancel button available."

#### Search Progress (for queries >1 second)

When search/filter operations exceed 1 second (complex queries on large datasets):

```
│  🔍 [ searching large dataset...  ⏳ ]    Tag [ All ▼ ]    [ Clear ]   │
```

**Visual**:
- Inline spinner (⏳) appears in search field
- Message: "Searching 500 objects..." replaces placeholder text
- Search field border animates (pulsing blue #0078D4)

**Screen Reader**: "Search in progress. Please wait."

**Duration**: Shown for searches >1 second; auto-dismissed when results appear.

#### Large Commit Progress (>50 changes)

For commits with >50 staged changes, show detailed progress instead of simple spinner:

```
┌────────────────────────────────────────────────────────────────────┐
│  Applying Permission Changes                                    × │
├────────────────────────────────────────────────────────────────────┤
│  Committing change 23 of 87...                                     │
│                                                                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ 26% │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                    │
│  Estimated time remaining: 4 seconds                               │
│                                                                    │
│  Do not close the application                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Features**:
- **Progress bar**: Shows exact change count and percentage
- **Time estimate**: "Estimated time remaining: X seconds" (calculated from average time per change)
- **Warning**: "Do not close the application" in red (#B22222)
- **Non-cancellable**: No [Cancel] button (database transaction in progress)

**Trigger**: Automatically shown for commits >50 changes; <50 changes use simple overlay (§2.17 Commit in Progress).

**Screen Reader**: "Committing change 23 of 87. 26 percent complete. Estimated 4 seconds remaining. Do not close the application."

### 2.18 Empty States

When filters, search, or data conditions result in zero visible items, display helpful empty states:

#### No Search/Filter Results

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  🔍 [ customer order ]           Tag [ finance ▼ ]            [ Clear Filters ]   │
├────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                    │
│                                   🔍                                               │
│                                                                                    │
│                         No objects match your filters                             │
│                                                                                    │
│                   0 of 500 objects visible with current filters:                  │
│                   • Search: "customer order"                                      │
│                   • Tag: finance                                                  │
│                                                                                    │
│                             [ Clear Filters ]                                     │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Visual Elements**:
- **Icon**: 🔍 (48×48px, centered, #767676)
- **Primary Message**: "No objects match your filters" (H2, centered)
- **Detail Message**: Lists active filters (Body, #505050)
- **Action Button**: [Clear Filters] (Primary button, centered)

**Screen Reader**: "No results found. 0 of 500 objects visible. Active filters: Search term 'customer order', Tag 'finance'. Clear filters button available."

**Keyboard**: [Clear Filters] button receives focus automatically.

#### No Users in Database

```
│                                   👥                                               │
│                                                                                    │
│                         No database users found                                   │
│                                                                                    │
│          The database has no users with object-level permissions.                 │
│          Connect to a different database or contact your DBA.                     │
│                                                                                    │
│                             [ Open Settings ]                                     │
```

**Use Case**: Database exists but has zero users in `sys.database_principals` with relevant permissions.

**Screen Reader**: "No database users found. The database has no users with object-level permissions. Open Settings button available."

#### No Objects in Database

```
│                                   📋                                               │
│                                                                                    │
│                      No database objects found                                    │
│                                                                                    │
│       This database has no tables, views, stored procedures, or functions.        │
│                                                                                    │
```

**Use Case**: Database exists but has zero objects in `sys.objects` (unlikely but possible in new/empty databases).

**Screen Reader**: "No database objects found. This database has no tables, views, stored procedures, or functions."

#### No Staged Changes (Default State)

```
│  No staged changes    [ Commit ]   [ Cancel ]              ● CORP\aadmin · 500 obj │
```

**Visual**: "No staged changes" in grey (#767676); Commit and Cancel buttons disabled (§1.3).

**Screen Reader**: "No staged changes. Commit button disabled. Cancel button disabled."

#### Connection Failed

```
│                                   ⚠                                                │
│                                                                                    │
│                        Connection to database failed                              │
│                                                                                    │
│                  Server 'SQL2019-PROD' could not be reached.                      │
│            Check your network connection and server address.                      │
│                                                                                    │
│                        [ Retry ]   [ Open Settings ]                              │
```

**Visual Elements**:
- **Icon**: ⚠ (48×48px, #FFA500 orange, centered)
- **Primary Message**: "Connection to database failed" (H2, centered)
- **Detail**: Specific error message from pyodbc (Body, #505050)
- **Guidance**: Actionable troubleshooting suggestion
- **Actions**: [Retry] (Primary) and [Open Settings] (Secondary)

**Screen Reader**: "Alert. Connection to database failed. Server SQL2019-PROD could not be reached. Check your network connection and server address. Retry button available. Open Settings button available."

**Live Region**: `role="alert"` (assertive) announces error immediately.

### 2.19 Undo and Redo (FR-029)

Allow administrators to reverse cell state changes before committing:

#### Keyboard Shortcuts

- **Undo**: `Ctrl+Z` — Reverses the most recent cell toggle
- **Redo**: `Ctrl+Y` or `Ctrl+Shift+Z` — Reapplies the most recently undone change

#### Behavior

**Undo Stack**:
- Tracks up to 50 most recent cell state changes (toggles only, not filter/search actions)
- Each entry stores: user, object, permission type, old state, new state, timestamp
- Stack cleared on Commit (changes become permanent) or Cancel (all changes discarded)
- Stack persists across view switches (Single User ↔ All Users ↔ Object View)

**Visual Feedback**:
- Cell immediately reverts to previous state (yellow background removed if change undone)
- Staged change counter decrements by 1
- Status message appears: "Undone: Changed dbo.Orders SELECT for jsmith from GRANT to none"

**Screen Reader Announcement** (Live Region, polite):
- Undo: "Undone. Reverted SELECT permission on dbo.Orders for jsmith from GRANT to none. 4 changes staged."
- Redo: "Redone. Changed SELECT permission on dbo.Orders for jsmith from none to GRANT. 5 changes staged."

**Status Bar Message** (5-second auto-dismiss):
```
│  ↶ Undone: dbo.Orders SELECT for jsmith (GRANT → none)                            │
```

**Edge Cases**:
- Undo with 0 staged changes: No action; brief message "Nothing to undo"
- Redo with empty redo stack: No action; brief message "Nothing to redo"
- Undo after manual revert: Works as expected (undo removes the manual revert)

**Menu Items** (Optional, for discoverability):
- Edit menu: Undo `Ctrl+Z` / Redo `Ctrl+Y` (disabled when stack empty)
- Tooltip on disabled items: "No changes to undo" / "No changes to redo"

**Implementation Priority**: HIGH (critical usability feature; reduces user anxiety about making mistakes).

---

## 3. Matrix View — Single User Mode

*Manage permissions for one user across all database objects.*

**View Configuration**:
- **User selector**: Active — select user to view
- **Show mode**: "Single user" (radio button selected)
- **Object selector**: Inactive (grayed out)
- **Orientation banner**: "Viewing: jsmith's permissions across 500 objects | Filtered by tag: finance | 12 of 500 objects visible | 3 staged changes"

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
- `Ctrl+U` focuses the user selector; `Escape` returns focus to the matrix.
- `Ctrl+Shift+C` toggles to All users (compare) mode.

---

## 4. Matrix View — All Users (Compare) Mode

*Compare permissions for multiple users across all objects. Paginated for cognitive load management.*

**View Configuration**:
- **User selector**: Inactive (shows "All users" placeholder, grayed out)
- **Show mode**: "All users (compare)" (radio button selected)
- **Object selector**: Inactive (grayed out)
- **User Pagination Control** (NEW): "Show: [ First 10 ] [ Next 10 ] [ Previous 10 ] [ All users ▼ ] | Pin users: [ + ]"
- **Orientation banner**: "Viewing: All users (showing 10 of 47) across 500 objects | Filtered by tag: finance | 12 of 500 objects visible | 3 staged changes"

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  Show: [ First 10 ] [ Next 10 ] [ All ▼ ]  Pin: jsmith mjones [+]                 │
│  🔍 [ Search objects or users...              ]  Tag [ All ▼ ]  Type [ All ▼ ]    │
│  Sort Objects [ Name ↑ ]   Sort Users [ Name ↑ ]                     [ Clear ]    │
├──────────────────────────┬────────────────────────┬────────────────────────┬───────┤
│                          │        jsmith          │        mjones          │  ...  │
│  Object                  │ SEL INS UPD DEL EXE …  │ SEL INS UPD DEL EXE …  │       │
├──────────────────────────┼────────────────────────┼────────────────────────┼───────┤
│ 📋 dbo.Customers [fin]   │  ✓   ✓   ─   ─   ─  … │  ✓   ─   ─   ─   ─  … │       │
│ 📋 dbo.Orders    [fin]   │  ✓   ✓   ✗   ─   ─  … │  ✓   ─   ─   ─   ─  … │       │
│ 📋 dbo.Products          │ [*✓] ─   ─   ─   ─  … │  ─   ─   ─   ─   ─  … │       │
│ 👁 dbo.OrderSummary      │  ✓   ─   ─   ─   ─  … │  ─   ─   ─   ─   ─  … │       │
│ ⚡ dbo.GetOrderFn        │  ─   ─   ─   ─   ✓  … │  ─   ─   ─   ─   ✓  … │       │
└──────────────────────────┴────────────────────────┴────────────────────────┴───────┘

Note: [*✓] indicates staged cell with bright yellow background (#FFEB3B) + green checkmark
```

**User Pagination Controls** (Hick's Law Compliance):
- **Default**: Shows first 10 users (or fewer if total user count < 10)
- **[First 10] / [Next 10] / [Previous 10]**: Quick navigation buttons for paging through user list
- **[All ▼]**: Dropdown with options:
  - "Show 5 users at a time"
  - "Show 10 users at a time" (default)
  - "Show 20 users at a time"
  - "Show all users" (warning: may cause performance issues with 50+ users)
- **Pin users**: Click [+] to open user selector → pin frequently accessed users to always appear first. Pinned users shown with 📌 icon and persist across sessions.
- **Pagination State**: "Showing users 1-10 of 47" displayed in orientation banner

**Cognitive Benefit**: Reduces simultaneous choices from 400+ cells (50 users × 8 permissions) to 80 cells (10 users × 8 permissions); eliminates choice paralysis; improves scan time by 5-10x; allows progressive disclosure while maintaining "show all" option for power users.

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
- `Ctrl+Right` / `Ctrl+Left` jumps to the next/previous user group (or next page of 10 users).
- `Space` or `Enter` cycles the focused cell.
- `Home` / `End` jump to first/last column within the current row.
- `Page Up` / `Page Down`: Navigate to previous/next page of users (equivalent to [Previous 10] / [Next 10])
- `Ctrl+Shift+C` toggles to Single user mode.

---

## 5. Matrix View — Object View Mode (Single Object × All Users)

*Select one database object; see and edit permissions for all users across all permission types in a matrix layout.*

**View Configuration**:
- **User selector**: Active — click to switch to specific user's perspective
- **Show mode**: "Single user" (radio button selected)
- **Object selector**: Active — select object to view all users' permissions on that object
- **Orientation banner**: "Viewing: All users' permissions on dbo.Orders (Table) | Filtered by tag: finance | 12 of 47 users visible | 3 staged changes"

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  Object: [ 📋 dbo.Orders (Table)                          ▼ ]  [ 🏷 Tags ] [📝]   │
│  🔍 [ Search users...          ]   Tag [ All ▼ ]   Sort [ User Name ↑ ]           │
├─────────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────┤
│  User                   │ 📋   │ ✏   │ 🔄   │ 🗑   │ ▶   │ 🔧  │ 🔗  │ 👁    │
│                         │ SEL  │ INS  │ UPD  │ DEL  │ EXE  │ ALT  │ REF  │ VD    │
├─────────────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼────────┤
│  jsmith (John Smith)    │  G   │  G   │  G   │  ─   │  ─   │  ─   │  ─   │  ─    │
│  mjones (Mary Jones)    │  G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
│  svc_report             │  G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  G    │
│  badactor               │  D   │  D   │  D   │  D   │  ─   │  ─   │  ─   │  ─    │
│  aadmin (Alice Admin)   │ *G   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
│  devuser                │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─   │  ─    │
└─────────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴────────┘
```

**Layout:**

- **Object selector**: Searchable dropdown listing all objects as `icon schema.name (Type)`. Changing the object pivots the matrix in-place to show that object's permissions across all users. Keyboard: `Ctrl+O`.
- **User column** is frozen (does not scroll horizontally).
- **Permission columns** use the same icons and abbreviations as Single User mode (§2.2). Only permission types applicable to the selected object type are displayed (e.g., EXECUTE is hidden for tables).
- **Cell states** follow the standard encoding (§2.3): `✓` (GRANT), `✗` (DENY), `─` (none), yellow background with `*✓` / `*✗` / `*─` (staged changes).
- **Tags inline**: User tags can appear inline in the User column: `jsmith (John Smith) [finance]` when space permits; truncated with `…` and full tags on hover.

**Controls:**

- **[🏷 Tags]**: Opens the Tag Editor dialog (§8) for the selected object.
- **[📝]**: Opens the Object Description editor inline below the selectors (§9).
- **Cell interaction**: Same click-to-cycle behavior as User View (§2.4). Left-click cycles through none → GRANT → DENY → none; right-click opens context menu with *Set to GRANT*, *Set to DENY*, *Clear*, and *Switch to User View for [user]*.
- **Cross-query highlighting** (§2.5): Clicking a **column header** (permission abbreviation) highlights all user rows where that user holds a committed permission of that type on the selected object; other rows are dimmed. Clicking a **user row header** highlights all permission columns where that user has any committed permission on the selected object; other columns are dimmed.

**Keyboard navigation:**
- Arrow keys move focus between cells.
- `Space` or `Enter` cycles the focused cell's state.
- `Tab` moves to the next cell; `Shift+Tab` moves to the previous.
- `Ctrl+O` focuses the Object selector; `Escape` returns focus to the matrix.
- `Ctrl+U` focuses the User selector to switch to that user's perspective.
- `Ctrl+Shift+C` toggles to All users (compare) mode.
- `Home` / `End` jump to first/last column within the current row.

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

## 7. Settings Screen (FR-025)

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

**Field Specifications**:
- **Server**: Non-empty string; validated on save (FR-017).
  - Accessible label: "Server address"
  - Error message association: `aria-describedby` links to error message element
- **Port**: Numeric, 1–65535; validated on save (FR-017).
  - Accessible label: "Port number"
  - Error message association: `aria-describedby` links to error message element
- **Database**: Non-empty string; the name of the target SQL Server database; validated on save (FR-017).
  - Accessible label: "Database name"
  - Error message association: `aria-describedby` links to error message element
- **Schema**: Non-empty string, valid SQL identifier; the SQL Server schema used for Bifrost's own tables (audit log, etc.); defaults to `dbo`.
  - Accessible label: "Schema name for Bifrost tables"
  - Help text: "(Bifrost's own tables)" provided as additional description
- **Windows Authentication**: Checked and non-editable in v1 (SQL Auth is out of scope per spec assumptions).
  - Accessible name: "Windows Authentication enabled (read-only)"

**Button Specifications**:
- **[Test Connection]**: Attempts a connection with the current (unsaved) field values and reports success or error inline below the button.
  - Accessible name: "Test database connection"
  - Success announcement: "Connection successful. Connected as CORP\aadmin."
  - Error announcement: "Connection failed. [specific error message]"
- **[Save]**: Persists valid configuration to `%APPDATA%\Bifrost\config.json` and reconnects (FR-013/014).
  - Accessible name: "Save configuration and connect"
  - Success announcement: "Configuration saved. Connected to AdventureWorks2019."
  - Error announcement: "Validation failed. [count] errors found. See field error messages."

**Error Handling (WCAG 3.3.1, 3.3.3)**:

When validation fails:
1. **Visual Error Indicators**:
   - Red border (#B22222) around invalid field (5.0:1 contrast ✓)
   - Error icon (⚠) before error message
   - Error message text in red (#B22222) on white background
2. **Programmatic Association**:
   - Associate error message with field using `aria-describedby` or platform equivalent
   - Set field `aria-invalid="true"` when validation fails
3. **Screen Reader Announcement**:
   - Field focus announces: "Server address, edit text, invalid. Required field cannot be empty."
   - Error message text is part of field's accessible description
4. **Error Summary**:
   - Display summary at top of form: "3 errors found. Please correct the following fields: Server, Port, Database"
   - Summary is `role="alert"` for immediate announcement
   - Each error in summary links to the corresponding field
5. **Focus Management**:
   - On save attempt with errors: Move focus to first invalid field
   - Announce error summary, then field-specific error

**Example Error State**:
```
Server: [ _________________ ]  ← Red border (5.0:1 contrast)
        ⚠ Server address is required  ← Announced with field via aria-describedby
```

**Connection Status**:
- Bottom row shows current connection state
- Role: `status` (live region, polite)
- Success: "✓ Connected as CORP\aadmin"
- Failure: "✗ Not connected" or "⚠ Connection failed: [error]"
- Missing config: "No configuration found — please enter connection details."

**Keyboard Navigation**:
- All fields reachable by Tab in logical order (Server → Port → Database → Schema → Auth → Test Connection → Save)
- Enter on [Save] submits form
- Enter on [Test Connection] tests connection
- Escape navigates back to the last active matrix view (cancels without saving)
- Error fields announce validation errors when focused

---

## 8. Tag Editor Dialog (FR-025)

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

**Dialog Properties**:
- **Heading**: H1 "Tags — dbo.Orders (Table)" (announces entity being tagged)
- **Modal**: Blocks interaction with main window until closed
- **Focus Management**: On open, focus moves to first tag chip or Add tag field; on close, focus returns to element that opened dialog

**Tag Chips**:
- Each existing tag shown as removable chip: `[finance ×]`
- **Visual**: Light background, rounded borders, × remove button
- **Accessible name**: "finance tag, press Delete to remove" or "finance tag, button to remove"
- **Removal**: Click × or press `Delete` key when chip focused
  - Removal is immediate (updates `tags.json`); no staging required
  - Announcement: "finance tag removed"
- **Rename**: Double-click chip or press `F2` when focused to edit inline
  - Enter commits rename
  - Escape cancels without changes
  - Announcement on rename: "Tag renamed from finance to financial"
- **Keyboard Navigation**: Tab moves between tag chips, Add field, and buttons

**Add Tag Field**:
- **Label**: "Add tag" (visible and accessible)
- **Validation**: Accepts only `^[A-Za-z0-9]+$` (alphanumeric, no spaces)
- **Input Method**: Type tag name, press Enter or click [+ Add]
- **Success**: Tag added to display, field cleared, announcement: "finance tag added"
- **Error**: Inline error message below field:
  - Visual: Red text (⚠ icon + message)
  - Message: "Invalid tag format. Use only letters and numbers, no spaces."
  - Accessible: Field marked `aria-invalid="true"`, error associated via `aria-describedby`
  - Announcement: "Add tag, edit text, invalid. Invalid tag format. Use only letters and numbers, no spaces."
- **Duplicate Detection**: Prevent adding duplicate tags (case-insensitive check)
  - Error message: "Tag 'finance' already exists."

**Buttons**:
- **[+ Add]**:
  - Accessible name: "Add tag"
  - Same action as pressing Enter in Add tag field
  - Disabled when field is empty or invalid
- **[Close]**:
  - Accessible name: "Close tag editor"
  - Keyboard: `Escape` or click to close
  - Returns focus to element that opened dialog

**Data Storage**: Tags stored locally in `%APPDATA%\Bifrost\tags.json` (not in database).

**Keyboard Shortcuts**:
- `Tab` / `Shift+Tab`: Navigate between tags, field, and buttons
- `Delete`: Remove focused tag chip
- `F2`: Rename focused tag chip (edit inline)
- `Enter`: Add tag (when field focused) or confirm rename
- `Escape`: Cancel rename or close dialog
- Arrow keys: Navigate between tag chips

---

## 9. Object Description Editor (Inline)

Opened via the [📝] button in Object View; expands inline below the object selector.

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
| Arrow keys      | Navigate matrix cells                     |
| `Space`/`Enter` | Cycle cell state / activate control       |
| `Ctrl+Right/Left` | Jump to next/prev user group (Compare) |
| `Home`/`End`    | First/last column in current row (Compare)|
| `Tab`/`Shift+Tab` | Move between controls in any view      |
