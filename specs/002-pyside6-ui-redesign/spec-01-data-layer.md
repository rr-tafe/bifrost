# Spec — Step 1: Data Layer and Speed

**Plan**: [plan.md](plan.md) | **Created**: 2026-10-01 | **Status**: Ready to implement
**Depends on**: nothing | **Blocks**: step 2 (app shell), step 3 (split view)

## 1. Goal

Make the in-memory permission matrix fast and correct at work-database scale, and shape its API
for the PySide6 views that come next. This step is UI-free. Nothing in `src/qt/` is built here,
and the current Tk app must keep working on top of the new layer.

When this step is done:

- Loading 1,000 principals × 20,000 objects × 200,000 explicit permissions builds the index in
  ≤ 1 s (after the DB fetch).
- Reading one row's state for all 8 permissions is one dict lookup with no allocation.
- Search and filter calls return in ≤ 50 ms on that dataset.
- DB I/O is separated from in-memory mutation, so step 2 can run all DB work on a worker thread.
- Four existing bugs are fixed (section 9).

## 2. Scope

**In scope**

- New module `src/services/matrix_index.py` (`PermissionIndex` and helpers).
- New module `src/services/loader.py` (`MatrixSnapshot`, `fetch_snapshot`, progress reporting).
- Changes to `src/services/matrix.py` (`PermissionMatrix` rebuilt on the index; old API kept).
- Changes to `src/db/users.py`, `src/db/objects.py`, `src/db/permissions.py` (ids, raw fetch,
  identifier quoting, batched privilege check).
- New helper `src/db/sql.py` (`quote_ident`).
- Model additions: `DatabaseUser.principal_id`, `DatabaseObject.object_id`.
- `src/services/export.py` reads from the index.
- Synthetic data generator and perf tests; `dev/seed_large.sql`.

**Out of scope**

- Any PySide6 code (step 2).
- Changing what the Tk UI shows. It only needs to keep working.
- Column-level permissions, database roles, effective permissions via group membership.
- Changes to the audit log schema or CSV formats.

## 3. Current state and problems

| # | Problem | Where |
|---|---|---|
| P1 | `get_assignment` creates a new `PermissionAssignment` for every cell without an explicit permission. The Tk view calls it for every visible cell on every redraw. | `src/services/matrix.py:282-314` |
| P2 | Cell keys are 4-tuples of strings plus an enum: `(login, schema, object, perm)`. Hashing them is slow, and a row (8 cells) costs 8 lookups. | `src/services/matrix.py:301` |
| P3 | `refresh()` only re-stages a change if its key is still in `assignments` after reload. `load()` rebuilds `assignments` sparsely, so any staged change on a cell whose committed state is NONE is silently dropped on refresh. | `src/services/matrix.py:225-249` |
| P4 | Tags live in `TagStore`, but nothing copies them onto `DatabaseUser.tags` / `DatabaseObject.tags`, so `get_filtered_users`/`get_filtered_objects` tag filters never match. | `src/services/matrix.py:790-845`, `src/services/tags.py` |
| P5 | `apply_permission_changes` wraps names in `[...]` without escaping `]`. A name containing `]` breaks the statement and is an injection vector. | `src/db/permissions.py:285-301` |
| P6 | `validate_grant_privilege` builds `HAS_PERMS_BY_NAME('{schema}.{object}', ...)` with an f-string (quote injection; also wrong for names containing `.` or `'`) and runs one round trip per cell. A 250-cell bulk grant means 250 queries. | `src/services/matrix.py:691-740` |
| P7 | `commit()` mixes DB I/O and in-memory mutation in one call, so it cannot run on a worker thread without the UI thread seeing a half-updated matrix. | `src/services/matrix.py:594-689` |
| P8 | Undo works per cell. FR-030/FR-031 bulk actions need one undo step per action. | `src/services/matrix.py:444-528` |
| P9 | One change callback with no detail on what changed, so the UI repaints everything. | `src/services/matrix.py:178-190` |
| P10 | `fetch_all_permissions` joins and returns names, sorts with `ORDER BY` (not needed), and calls `fetchall()` on the whole result. | `src/db/permissions.py:50-145` |

## 4. Design overview

```
            worker thread (step 2)                         UI thread
 ┌────────────────────────────────────────┐    ┌─────────────────────────────────────┐
 │ loader.fetch_snapshot(conn, progress)   │──▶│ PermissionMatrix.apply_snapshot(s)  │
 │   db.users.fetch_all_users              │    │   PermissionIndex.build(s, tags)    │
 │   db.objects.fetch_all_objects          │    │   re-stage preserved changes        │
 │   db.permissions.fetch_permission_rows  │    │   emit MatrixChange(reason=reload)  │
 └────────────────────────────────────────┘    └─────────────────────────────────────┘

 ┌────────────────────────────────────────┐    ┌─────────────────────────────────────┐
 │ matrix.execute_commit(conn, plan)       │◀──│ plan = matrix.prepare_commit()       │
 │   apply GRANT/DENY/REVOKE               │    │                                     │
 │   write audit rows, COMMIT/ROLLBACK     │──▶│ matrix.apply_commit_results(results) │
 └────────────────────────────────────────┘    └─────────────────────────────────────┘
```

Rules:

- **`PermissionIndex` and `PermissionMatrix` are only mutated on one thread** (the UI thread in
  step 2). They are not thread-safe and this spec does not make them so.
- **Functions that touch pyodbc take a connection and plain data, and return plain data.** They
  never read or write `PermissionMatrix` state. These are the only functions step 2 runs on the
  worker.
- The old synchronous methods (`load()`, `refresh()`, `commit()`) stay as wrappers that call the
  split functions in sequence, so the Tk app and existing tests keep working.

## 5. Models

### 5.1 `DatabaseUser` (`src/models/user.py`)

Add `principal_id: int = 0` (from `sys.database_principals.principal_id`). Default `0` keeps
existing constructors and tests valid. Field order: add it **last** so positional construction
in tests does not break.

### 5.2 `DatabaseObject` (`src/models/db_object.py`)

Add `object_id: int = 0` (from `sys.objects.object_id`), last field, same reason.

### 5.3 Permission ordering and masks (`src/services/matrix_index.py`)

```python
PERMS: tuple[PermissionType, ...] = (
    PermissionType.SELECT, PermissionType.INSERT, PermissionType.UPDATE, PermissionType.DELETE,
    PermissionType.EXECUTE, PermissionType.ALTER, PermissionType.REFERENCES,
    PermissionType.VIEW_DEFINITION,
)
PERM_INDEX: dict[PermissionType, int] = {p: i for i, p in enumerate(PERMS)}
ALL_MASK = 0xFF

# Bit i set = PERMS[i] applies to this object type (FR-001a)
APPLICABLE_MASK: dict[ObjectType, int]
#   TABLE, VIEW         -> SELECT|INSERT|UPDATE|DELETE|ALTER|REFERENCES|VIEW_DEFINITION
#   PROCEDURE, FUNCTION -> EXECUTE|ALTER|VIEW_DEFINITION
```

`APPLICABLE_MASK` must be derived from `ObjectType.supports_permission` at import time, not
hard-coded a second time, so the two cannot drift.

State codes (small ints, used everywhere inside the index):

```python
NONE, GRANT, DENY = 0, 1, 2
STATE_TO_CODE: dict[PermissionState, int]
CODE_TO_STATE: tuple[PermissionState, PermissionState, PermissionState]
```

### 5.4 Packed row state

One (principal, object) pair is a **row**. Its 8 cells are packed into one int:

```
bits 0-7  : GRANT mask  (bit i set → PERMS[i] is GRANT)
bits 8-15 : DENY mask   (bit i set → PERMS[i] is DENY)
neither   : NONE
```

Invariant: `(packed & 0xFF) & (packed >> 8) == 0` (a cell is never both GRANT and DENY).

Pure helpers (module-level functions, no classes, all O(1)):

```python
def cell_code(packed: int, perm_idx: int) -> int            # NONE/GRANT/DENY
def with_cell(packed: int, perm_idx: int, code: int) -> int # returns new packed value
def grant_mask(packed: int) -> int
def deny_mask(packed: int) -> int
def diff_mask(a: int, b: int) -> int                        # 8-bit mask of perms that differ
```

`diff_mask(a, b)` = `((a ^ b) | ((a ^ b) >> 8)) & 0xFF`. Count changes with `int.bit_count()`.

## 6. `PermissionIndex` (`src/services/matrix_index.py`)

### 6.1 Fields

| Field | Type | Meaning |
|---|---|---|
| `principals` | `list[DatabaseUser]` | Position = principal index `p` |
| `objects` | `list[DatabaseObject]` | Position = object index `o` |
| `principal_by_login` | `dict[str, int]` | login → `p` |
| `principal_by_id` | `dict[int, int]` | `principal_id` → `p` |
| `object_by_name` | `dict[tuple[str, str], int]` | `(schema, name)` → `o` |
| `object_by_id` | `dict[int, int]` | `object_id` → `o` |
| `object_applicable` | `list[int]` | `o` → `APPLICABLE_MASK` for its type |
| `committed` | `dict[tuple[int, int], int]` | `(p, o)` → packed state. Only rows with at least one GRANT/DENY. |
| `staged` | `dict[tuple[int, int], int]` | `(p, o)` → packed **effective** state, only for rows where effective ≠ committed |
| `objects_by_principal` | `list[set[int]]` | `p` → objects where committed or staged row is non-zero |
| `principals_by_object` | `list[set[int]]` | `o` → principals, same rule |
| `principal_counts` | `list[RowCounts]` | `p` → grants, denies, pending (cells) |
| `object_counts` | `list[RowCounts]` | `o` → grants, denies, pending (cells) |
| `staged_cell_count` | `int` | Total cells that differ from committed |
| `principal_search_key` | `list[str]` | Lowercased login |
| `object_search_key` | `list[str]` | Lowercased `schema.name` |
| `object_order` | `list[int]` | Object indexes sorted by `(schema.casefold(), name.casefold())` |
| `schema_spans` | `list[SchemaSpan]` | `(schema, start, end)` slices of `object_order` |
| `principal_tags` | `list[frozenset[str]]` | `p` → casefolded tags |
| `object_tags` | `list[frozenset[str]]` | `o` → casefolded tags |

`RowCounts` is a small mutable dataclass with `__slots__`: `grants`, `denies`, `pending`. Counts
reflect the **effective** state (staged overrides committed), because that is what the UI shows.
`pending` is the number of cells that differ from committed.

### 6.2 Build

```python
@classmethod
def build(cls, snapshot: MatrixSnapshot, tag_store: TagStore | None) -> "PermissionIndex"
```

1. Assign `p` and `o` in snapshot order (principals by name; objects by schema then name).
2. Fill lookup dicts, `object_applicable`, search keys, tag sets (from `tag_store`; empty
   frozensets if `None`).
3. For each permission row `(principal_id, object_id, perm_idx, code)`:
   - Skip if the principal or object is not in the index (e.g. a permission on an object type
     Bifrost doesn't manage). Count skipped rows in `build_stats.skipped_rows`.
   - Skip if the permission doesn't apply to the object type (count separately).
   - `committed[(p, o)] = with_cell(committed.get((p, o), 0), perm_idx, code)`.
4. Build `objects_by_principal`, `principals_by_object` and counts in one pass over `committed`.
5. Build `object_order` and `schema_spans`.

Must not create per-cell objects. Must run in ≤ 1.0 s on the reference dataset
(section 11).

### 6.3 Reads

```python
def row_state(self, p: int, o: int) -> int                  # effective packed
def committed_row(self, p: int, o: int) -> int
def pending_mask(self, p: int, o: int) -> int               # 8-bit diff mask
def cell(self, p: int, o: int, perm_idx: int) -> CellView   # for tooltips/tests only
```

`row_state` is `staged.get(key)` then `committed.get(key, 0)`, with no allocation beyond the
tuple key. `CellView` is a frozen dataclass (`effective`, `committed`, `pending`, `applicable`)
and is **not** to be used in render loops.

### 6.4 Writes (called only by `PermissionMatrix`)

```python
def set_effective(self, p: int, o: int, perm_idx: int, code: int) -> bool
```

Updates `staged` for one cell; returns `True` if anything changed. It must:

- Raise `ValueError` if the permission doesn't apply to the object (`object_applicable`).
- Remove the row from `staged` when the effective row equals committed again.
- Keep `objects_by_principal`, `principals_by_object`, counts and `staged_cell_count` correct
  incrementally (adjust by the before/after diff of that one row; never rescan).

```python
def clear_staged(self) -> set[tuple[int, int]]   # returns rows that changed
def commit_rows(self, applied: Iterable[tuple[int, int, int, int]]) -> set[tuple[int, int]]
    # (p, o, perm_idx, new_code): move the cell into committed, drop it from staged
```

### 6.5 Queries

All queries return `list[int]` of indexes in display order. They read precomputed keys and
never touch the DB.

```python
@dataclass(frozen=True)
class PrincipalQuery:
    text: str = ""
    types: frozenset[str] = frozenset()        # subset of {"S","U","G"}; empty = all
    tags: frozenset[str] = frozenset()          # casefolded; principal must have ALL
    has_pending: bool = False
    has_access_to_object: int | None = None     # o: only principals with a non-zero row
    sort: Literal["name", "type", "grants"] = "name"
    descending: bool = False

@dataclass(frozen=True)
class ObjectQuery:
    text: str = ""
    schemas: frozenset[str] = frozenset()       # casefolded; empty = all
    types: frozenset[ObjectType] = frozenset()  # empty = all
    tags: frozenset[str] = frozenset()          # object must have ALL
    with_access_for: int | None = None          # p: only objects where row(p, o) != 0
    pending_for: int | None = None              # p: only objects with pending cells for p
    sort: Literal["schema_name", "name", "type"] = "schema_name"
    descending: bool = False

def query_principals(self, q: PrincipalQuery) -> list[int]
def query_objects(self, q: ObjectQuery) -> list[int]
def group_by_schema(self, objects: list[int]) -> list[SchemaSpan]  # spans over the given list
```

Text matching:

- Case-insensitive (`str.casefold`). Split on whitespace; every token must be a substring of the
  search key (AND).
- The text is validated with `validation.validate_search_term` by the caller (FR-017); the index
  assumes valid input.

Filtering order (cheapest first): start from the smallest candidate set. When
`with_access_for` is set, start from `objects_by_principal[p]` instead of all objects, which is
what makes "Only with access" fast for any principal.

### 6.6 Tags

```python
def set_tags(self, tag_store: TagStore) -> None   # rebuild principal_tags/object_tags
```

Called after build and whenever the tag manager saves. Tags are looked up by login and by
`schema.name` (the keys `TagStore` already uses). Also copy tags onto `DatabaseUser.tags` /
`DatabaseObject.tags` so existing `has_tag` callers (Tk UI, export) see them. This fixes P4.

### 6.7 Iteration (for export and the Grants tab)

```python
def iter_explicit(self, effective: bool = False) -> Iterator[tuple[int, int, int, int]]
    # (p, o, perm_idx, code) for every GRANT/DENY cell, committed or effective
def iter_all_cells(self) -> Iterator[tuple[int, int, int, int]]
    # every applicable cell including NONE (for FR-015 full export)
```

Both are generators; the caller decides how much to materialise.

## 7. Loader (`src/services/loader.py`)

### 7.1 Snapshot

```python
@dataclass(frozen=True)
class MatrixSnapshot:
    principals: tuple[DatabaseUser, ...]
    objects: tuple[DatabaseObject, ...]
    permission_rows: tuple[tuple[int, int, int, int], ...]  # (principal_id, object_id, perm_idx, code)
    current_user: str                                       # SYSTEM_USER at load time
    privileged: bool                                        # see 8.6
    loaded_at: datetime                                     # UTC
    timings: dict[str, float]                               # seconds per stage, for diagnostics
```

### 7.2 Fetch

```python
@dataclass(frozen=True)
class LoadProgress:
    stage: Literal["principals", "objects", "permissions", "privileges"]
    stage_number: int     # 1-based
    stage_count: int      # 4
    rows: int             # rows fetched so far in this stage
    message: str          # "Loading permissions… 120,000 rows"

class LoadCancelled(Exception): ...

def fetch_snapshot(
    conn: pyodbc.Connection,
    progress: Callable[[LoadProgress], None] | None = None,
    cancel: threading.Event | None = None,
) -> MatrixSnapshot
```

- Runs the four DB stages in order on the given connection. DB-only: no index building.
- Calls `progress` at the start of each stage and every 10,000 rows within the permissions
  stage. `progress` may be called from a worker thread; it must not touch UI objects directly
  (step 2 marshals it to the UI thread).
- Checks `cancel` between stages and between fetch batches; raises `LoadCancelled` if set.
- Records per-stage wall time in `timings`.
- Does not commit or roll back; it only reads.

### 7.3 DB changes

`src/db/users.py` — `fetch_all_users` also selects `principal_id`.

`src/db/objects.py` — `fetch_all_objects` also selects `o.object_id`.

`src/db/permissions.py` — new function:

```python
def fetch_permission_rows(
    conn: pyodbc.Connection, batch_size: int = 10_000,
    on_batch: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[tuple[int, int, int, int]]
```

```sql
SELECT p.grantee_principal_id, p.major_id, p.permission_name, p.state
FROM sys.database_permissions AS p
WHERE p.class = 1
  AND p.minor_id = 0
  AND p.permission_name IN ('SELECT','INSERT','UPDATE','DELETE',
                            'EXECUTE','ALTER','REFERENCES','VIEW DEFINITION')
  AND p.state IN ('G','W','D')
```

- No joins and no `ORDER BY`. The index build filters to known principals and objects.
- `state` `'G'` and `'W'` (grant with grant option) map to GRANT; `'D'` to DENY (same rule as
  today, grant option not tracked).
- Read with `cursor.fetchmany(batch_size)` in a loop; call `on_batch(total_so_far)`; check
  `cancel` between batches.
- Map `permission_name` → `perm_idx` with a dict built once.
- Keep `fetch_all_permissions` unchanged for existing callers/tests; mark it deprecated in its
  docstring.

### 7.4 Identifier quoting (`src/db/sql.py`)

```python
def quote_ident(name: str) -> str:
    """Return name as a bracket-quoted T-SQL identifier, like QUOTENAME()."""
    # "[" + name.replace("]", "]]") + "]"
```

- Raise `ValueError` for names longer than 128 characters or containing NUL.
- Use it in `apply_permission_changes` for schema, object and principal names (fixes P5).
- Use it anywhere else the codebase builds `[...]` from a variable. At least
  `src/db/audit.py` (schema of the audit table) and `src/db/objects.py`
  (`save_object_description`, if it interpolates). Grep for `f"[` and `[{` to find them all.
- Permission names come from the `PermissionType` enum, never from user input; they can stay
  interpolated.

## 8. `PermissionMatrix` (`src/services/matrix.py`)

`PermissionMatrix` stays the one object the UI talks to. It owns a `PermissionIndex`, the undo
stack and the change listeners.

### 8.1 Construction and loading

```python
def __init__(self, conn: pyodbc.Connection | None, schema: str = "dbo",
             tag_store: TagStore | None = None)
def apply_snapshot(self, snapshot: MatrixSnapshot) -> RestageReport
def load(self) -> None          # = apply_snapshot(fetch_snapshot(self.conn)); clears staged
def refresh(self) -> RestageReport   # = apply_snapshot(fetch_snapshot(self.conn)); keeps staged
```

`apply_snapshot`:

1. Capture the current staged changes by **natural key** `(login, schema, object, perm)` and
   new state. Natural keys survive principals or objects being dropped and recreated.
2. Build a new `PermissionIndex` from the snapshot and current tag store.
3. Re-stage each captured change on the new index without adding undo entries:
   - If the principal or object no longer exists → add to `report.dropped_missing`.
   - If the permission no longer applies (object type changed) → `report.dropped_missing`.
   - If the new committed state already equals the staged state (someone else made the same
     change) → `report.already_applied`.
   - Otherwise → `report.kept`.
4. Clear undo/redo stacks (row indexes have changed).
5. Emit `MatrixChange(rows=None, reason="reload")`.

`RestageReport` is a frozen dataclass of three tuples of `StagedChange`. Step 2 shows a message
when `dropped_missing` or `already_applied` is non-empty. This fixes P3.

`users` and `objects` stay as read-only properties returning the index's lists, for the Tk UI
and export.

### 8.2 Staging

```python
@dataclass(frozen=True)
class CellRef:
    p: int
    o: int
    perm: int          # perm_idx

def stage(self, cells: Iterable[CellRef], state: PermissionState,
          label: str | None = None) -> StageResult
def stage_cycle(self, cell: CellRef) -> StageResult          # NONE→GRANT→DENY→NONE
def revert(self, cells: Iterable[CellRef], label: str | None = None) -> StageResult
    # set each cell's effective state back to committed
```

- Cells where the permission doesn't apply are skipped and counted in
  `StageResult.skipped_not_applicable`. They are never an error in bulk calls.
- Cells already in the target state are skipped and counted in `StageResult.unchanged`.
- All cells changed by one call form **one undo group** (FR-029 counts groups, max 50).
- One call emits **one** `MatrixChange` naming all changed rows.
- `label` describes the action for undo/redo announcements, for example
  `"Grant SELECT on 247 objects for CORP\jsmith"`. If `None`, it is generated from the cells.
- FR-030 confirmation (≥5 cells) and FR-031 selection limits (≤1,000 cells) are UI concerns and
  are **not** enforced here. `stage` accepts any number of cells. It must handle 20,000 cells in
  ≤ 1 s (section 11).
- Privilege checks (FR-017a) are **not** done inside `stage`. The caller checks first using
  section 8.6, because that check needs the DB.

Old name-based methods stay as thin wrappers with unchanged behavior and signatures:
`stage_change(...)`, `toggle_cell(...)`, `get_assignment(...)`. `get_assignment` keeps returning
a `PermissionAssignment` (it allocates, which is fine for the Tk UI until step 6). Add a
`DeprecationWarning`-free docstring note: "Legacy API for the Tk UI; new code uses
`row_state`."

`assignments` (dict attribute) is used by `export_permissions_csv` and tests. Replace it with a
read-only property that materialises the old dict shape on demand (explicit cells only, with
staged state). Mark it legacy. Export moves to the index API (section 10).

### 8.3 Undo and redo

```python
@dataclass(frozen=True)
class UndoGroup:
    label: str
    cells: tuple[tuple[int, int, int, int, int], ...]  # (p, o, perm, before_code, after_code)

def undo(self) -> UndoGroup | None
def redo(self) -> UndoGroup | None
def can_undo(self) -> bool
def can_redo(self) -> bool
```

- `before_code`/`after_code` are **effective** states, so undo restores exactly what was shown.
- Undo applies `before_code` to every cell in the group; redo applies `after_code`. Neither
  creates a new group. Each emits one `MatrixChange` with `reason="undo"`/`"redo"`.
- Max 50 groups (`MAX_UNDO_GROUPS`); oldest dropped first.
- New `stage`/`revert` clears the redo stack.
- `cancel()`, `apply_commit_results()` and `apply_snapshot()` clear both stacks.
- The return value lets the UI announce "Undone: <label>" (FR-029).
- The existing `undo() -> bool` callers (Tk app) treat a non-`None` group as truthy, so the
  return type change is compatible. Verify `src/ui/app.py:_undo/_redo` still work.

### 8.4 Change events

```python
@dataclass(frozen=True)
class MatrixChange:
    reason: Literal["stage", "undo", "redo", "cancel", "commit", "reload", "tags"]
    rows: frozenset[tuple[int, int]] | None    # None = everything may have changed
    staged_count: int                          # cells differing from committed, after the change

def subscribe(self, listener: Callable[[MatrixChange], None]) -> Callable[[], None]
    # returns an unsubscribe function
```

- Listeners are called synchronously, in subscription order, after the index is consistent.
- An exception in one listener is logged (`logging.getLogger("bifrost.matrix")`) and does not
  stop the others or roll back the change.
- `set_on_change_callback(cb)` stays for the Tk UI: it subscribes a wrapper that calls `cb()`
  with no arguments, replacing any previous callback set this way.

### 8.5 Commit

```python
@dataclass(frozen=True)
class CommitPlan:
    changes: tuple[StagedChange, ...]          # sorted by principal, object, perm
    cells: tuple[CellRef, ...]                 # same order, for applying results
    schema: str                                # audit table schema

@dataclass(frozen=True)
class CommitOutcome:
    results: tuple[tuple[StagedChange, str | None], ...]   # error None = success
    audit_written: int
    rolled_back: bool
    error: str | None                          # set if the whole batch failed

def prepare_commit(self) -> CommitPlan                      # UI thread
@staticmethod
def execute_commit(conn: pyodbc.Connection, plan: CommitPlan,
                   admin_user: str) -> CommitOutcome         # worker thread; DB only
def apply_commit_results(self, plan: CommitPlan,
                         outcome: CommitOutcome) -> None     # UI thread
def commit(self) -> list[tuple[StagedChange, str | None]]   # legacy: all three in sequence
```

`execute_commit` must keep today's transaction behavior and make it explicit:

1. Apply each change with `apply_permission_changes` (one statement each; per-change errors are
   collected, not raised).
2. Write one audit entry per **successful** change with `write_audit_entries` (FR-012).
3. If the audit write succeeds, `conn.commit()`. If it raises, `conn.rollback()`, set
   `rolled_back=True`, mark every change as failed with the audit error, and return.
   Permission changes and their audit rows must never be committed separately.
4. Any `pyodbc.Error` not tied to one statement (for example connection loss) →
   `conn.rollback()` if possible, `rolled_back=True`, `error=<message>`, return. Do not raise,
   so the worker can report it.

`apply_commit_results`:

- If `rolled_back`: change nothing; staged changes stay for retry; emit nothing.
- Otherwise move successful cells into committed (`index.commit_rows`), leave failed cells
  staged, clear undo/redo, emit `MatrixChange(reason="commit", rows=<changed rows>)`.
- If the index was rebuilt between prepare and apply (a refresh ran), apply by natural key, and
  skip cells that no longer exist.

`admin_user` comes from `MatrixSnapshot.current_user`, so `execute_commit` doesn't need an extra
`SYSTEM_USER` round trip.

### 8.6 Privilege check (FR-017a)

```python
def check_grant_privileges(conn: pyodbc.Connection,
                           targets: Sequence[tuple[str, str, PermissionType]]
                           ) -> dict[tuple[str, str, PermissionType], bool]   # DB only, worker
def known_grant_privilege(self, cell: CellRef) -> bool | None       # cache lookup, UI thread
def remember_grant_privileges(self, result: dict[...]) -> None      # UI thread
```

- At load (`fetch_snapshot` stage 4), compute `privileged` once:
  `SELECT IS_SRVROLEMEMBER('sysadmin'), IS_ROLEMEMBER('db_owner'), HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL')`.
  If any is 1, every check passes without a query.
- Otherwise `check_grant_privileges` checks all targets in **one** query, passing names as
  parameters and building the securable name with `QUOTENAME` in T-SQL:

  ```sql
  SELECT t.s, t.o, t.perm,
         HAS_PERMS_BY_NAME(QUOTENAME(t.s) + '.' + QUOTENAME(t.o), 'OBJECT', t.perm)
  FROM (VALUES (?, ?, ?), (?, ?, ?), ...) AS t(s, o, perm)
  ```

  Chunk to at most 600 targets per statement (3 parameters each, under SQL Server's 2,100
  parameter limit).
- Results are cached per session in the matrix (`dict` keyed by natural key) and cleared by
  `apply_snapshot`.
- Only GRANT needs checking (DENY and REVOKE follow the DB's own rules and fail at commit with a
  readable error, FR-018).
- `validate_grant_privilege` (single cell) stays as a wrapper over `check_grant_privileges` for
  the Tk UI. This fixes P6.

Note for later: having a permission is not the same as being allowed to grant it (that needs
WITH GRANT OPTION or CONTROL). The current FR-017a check uses "has the permission"; keep that
behavior in this step and raise it as a follow-up.

### 8.7 Other methods

| Method | Behavior |
|---|---|
| `cancel()` | `index.clear_staged()`, clear undo/redo, emit `reason="cancel"` with the changed rows |
| `get_staged_changes()` | Build `StagedChange` list from `index.staged`, sorted by principal name, schema, object, perm. ≤ 20 ms for 1,000 changes. |
| `get_staged_change_count()` | `index.staged_cell_count` (O(1)) |
| `has_staged_changes()` | count > 0 |
| `set_tag_store(store)` | `index.set_tags(store)`, emit `reason="tags"`, `rows=None` |
| `get_filtered_users()` / `get_filtered_objects()` and the `FilterState` setters | Keep for the Tk UI, reimplemented on `query_principals`/`query_objects`. Tag filters now work. |
| `get_performance_info()` | Keep; unchanged meaning. |

## 9. Bugs fixed in this step

| Bug | Fix | Test |
|---|---|---|
| P3 refresh drops staged NONE→X changes | 8.1 re-stage by natural key | stage GRANT on a NONE cell, `refresh()` with the same snapshot, change still staged |
| P4 tag filters never match | 6.6 | tag a user in `TagStore`, `query_principals(tags={"finance"})` returns it |
| P5 unescaped `]` in identifiers | 7.4 | `quote_ident("a]b") == "[a]]b]"`; `apply_permission_changes` emits `[a]]b]` (mock cursor) |
| P6 f-string `HAS_PERMS_BY_NAME`, one query per cell | 8.6 | names with `'` and `]` are passed as parameters; 1,000 targets → 2 statements |

## 10. Export (`src/services/export.py`)

- Add `export_permissions_from_index(file_path, index, include_none, progress_callback,
  cancel)` that writes from `iter_explicit` / `iter_all_cells`. Same columns and format as
  today (contracts/csv-formats.md): `User, Schema, Object, ObjectType, Permission, State,
  HasStagedChange`.
- Write with `csv.writer` and a buffered file handle. Report progress every 50,000 rows.
- `include_none=True` on the reference dataset is about 20,000 × 1,000 × ~7 = 140M rows (GBs).
  Keep the option (FR-015 asks for it), but make the default `False`, and have step 2 warn
  before a full export over 5M rows. Note this in the function docstring.
- Keep `export_permissions_csv` as a wrapper for the Tk app.

## 11. Performance budgets and tests

### 11.1 Synthetic data (`tests/perf/synthetic.py`)

```python
def make_snapshot(principals: int, objects: int, explicit: int, seed: int = 7,
                  deny_ratio: float = 0.02, schemas: int = 25) -> MatrixSnapshot
```

- Deterministic for a given seed.
- Realistic distribution: object types 70% tables, 10% views, 15% procedures, 5% functions;
  principal types 70% Windows users, 20% Windows groups, 10% SQL users; permissions skewed so
  5% of principals hold 60% of explicit permissions (service accounts and broad groups).
- Only applicable permissions are generated.
- Names include awkward characters in a few rows: `]`, `'`, `.`, spaces, non-ASCII.

### 11.2 Budgets

Measured with `time.perf_counter`, best of 3, on the dev Mac. Tests assert against **3× the
budget** so they don't flake on slower machines, and print the measured numbers.

| Operation (reference: 1,000 × 20,000 × 200,000) | Budget |
|---|---|
| `PermissionIndex.build` | 1.0 s |
| `row_state` × 1,000,000 calls | 0.5 s (≤ 0.5 µs each) |
| `query_objects(text="ord")` | 30 ms |
| `query_objects(with_access_for=p)` for the busiest principal | 10 ms |
| `query_principals(text="smi", types={"U"})` | 5 ms |
| `stage` of 1,000 cells (one call) | 50 ms |
| `stage` of 20,000 cells (one call) | 1.0 s |
| `undo` of a 1,000-cell group | 50 ms |
| `get_staged_changes` with 1,000 staged | 20 ms |
| `apply_snapshot` with 1,000 staged changes to preserve | 1.3 s |
| Index memory (tracemalloc peak during build) | 150 MB |

Perf tests live in `tests/perf/` and are marked `@pytest.mark.slow`, so the pre-commit hook
(`-m "not slow and not integration"`) skips them. Run with `pytest -m slow tests/perf`.

### 11.3 Large dev database (`dev/seed_large.sql`)

- T-SQL script (loops, no Python) that adds to `BifrostDev`: 500 principals
  (`CREATE USER ... WITHOUT LOGIN`), 5,000 objects across 20 schemas (mostly small tables, plus
  views and procedures) and about 50,000 explicit permissions.
- Idempotent: safe to re-run; skips existing objects.
- `dev/setup.sh --large` runs it after the normal seed. Document in README.
- Used to time `fetch_snapshot` against a real server. Record the timings in this spec's
  "Results" section when step 1 is done.

## 12. Unit tests

New and changed tests (all in `tests/unit/` unless noted; no DB needed):

`test_matrix_index.py`
- Packing helpers: every (perm, code) round-trips; invariant holds; `diff_mask` correct.
- `APPLICABLE_MASK` matches `ObjectType.supports_permission` for all 32 combinations.
- Build: skips rows for unknown principals/objects and non-applicable permissions, and counts them.
- `row_state` returns staged over committed; `pending_mask` correct.
- `set_effective`: counts, `objects_by_principal`, `principals_by_object`, `staged_cell_count`
  stay correct across grant→deny→none→grant sequences (compare with a brute-force recount).
- Queries: text tokens AND; casefold (`"ß"` matches `"SS"` via casefold); type, schema and tag
  filters; `with_access_for`; `pending_for`; sort orders; `group_by_schema` spans.
- Property-style test: 500 random stage/revert/undo/redo/cancel operations on a small synthetic
  index, then compare every count and set with a brute-force recount.

`test_loader.py`
- `fetch_snapshot` with a fake connection/cursor: stage order, progress calls, batching with
  `fetchmany`, `LoadCancelled` between batches, state mapping `G`/`W`/`D`, timings recorded.

`test_matrix_service.py` (extend `test_services.py` or new file)
- `stage` groups one undo entry; `undo`/`redo` restore effective states; max 50 groups.
- One `MatrixChange` per call with the right rows; listener exception doesn't break others.
- `apply_snapshot` re-stage report: kept, dropped_missing, already_applied.
- Commit split: `execute_commit` with a fake connection covering all-success, partial failure,
  audit-write failure (rolled back, nothing applied), connection error (rolled back, error
  set). `apply_commit_results` for each outcome.
- Legacy API (`stage_change`, `toggle_cell`, `get_assignment`, `assignments`, `commit`,
  `refresh`, `undo() -> truthy`) behaves as before.

`test_db_sql.py`
- `quote_ident` escaping and limits.
- `apply_permission_changes` statements use quoted identifiers (mock cursor captures SQL).
- `check_grant_privileges` chunks at 600 targets and passes names as parameters.

`test_export.py`
- `export_permissions_from_index` output matches the existing format and the legacy function's
  output for the same data.

All existing tests must still pass. That includes the Tk UI tests
(`tests/unit/test_ui_*.py`), which exercise the legacy API.

## 13. Acceptance criteria

- [ ] All new modules and functions in sections 5–10 exist with the signatures given (names may
      change if a better name is found; update this spec when they do).
- [ ] `pytest` passes (unit), and `pytest -m slow tests/perf` passes on the dev Mac.
- [ ] Perf numbers measured and recorded in "Results" below.
- [ ] `fetch_snapshot` timings against `dev/seed_large.sql` recorded.
- [ ] Tk app still launches, loads, toggles, commits, cancels, refreshes and exports against
      BifrostDev with no visible change in behavior (other than being faster and tag filters
      working).
- [ ] P3–P6 regression tests exist and pass.
- [ ] `ruff check` clean for changed files.
- [ ] `pyproject.toml` coverage `omit` no longer excludes `src/services/matrix.py`. New service
      modules are ≥ 80% covered.
- [ ] [plan.md](plan.md) status table updated.

## 14. Results

_Fill in when step 1 is done._

| Measure | Budget | Measured |
|---|---|---|
| Index build (1,000 × 20,000 × 200,000) | 1.0 s | |
| `query_objects` text | 30 ms | |
| `stage` 1,000 cells | 50 ms | |
| Index memory | 150 MB | |
| `fetch_snapshot` on seed_large (500 × 5,000 × 50,000) | — | |
