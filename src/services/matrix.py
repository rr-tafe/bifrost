"""
Permission matrix service for Bifrost.

PermissionMatrix is the one object the UI talks to. It owns a PermissionIndex
(the integer-indexed permission store), the staging engine, grouped undo/redo,
change notifications and the commit pipeline.

DB I/O is kept apart from in-memory changes so a UI can run the slow parts on a
worker thread:

    worker thread                         UI thread
    fetch_snapshot(conn)          ──▶     matrix.apply_snapshot(snapshot)
    execute_commit(conn, plan)    ◀──     plan = matrix.prepare_commit()
                                  ──▶     matrix.apply_commit_results(plan, outcome)

The older synchronous methods (load, refresh, commit, stage_change, toggle_cell,
get_assignment, assignments) are kept for the Tkinter UI and call the split
functions in sequence.

Usage:
    matrix = PermissionMatrix(conn, schema="dbo", tag_store=tags)
    matrix.load()

    alice = matrix.index.principal_index("alice")
    orders = matrix.index.object_index("dbo", "Orders")
    matrix.stage([CellRef(alice, orders, PERM_INDEX[PermissionType.SELECT])], PermissionState.GRANT)

    plan = matrix.prepare_commit()
    outcome = PermissionMatrix.execute_commit(conn, plan, matrix.current_user)
    matrix.apply_commit_results(plan, outcome)

Thread safety:
    Not thread-safe. All methods except execute_commit and
    check_grant_privileges run on one thread (the UI thread).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from src.db import audit as db_audit
from src.db import permissions as db_permissions
from src.db.connection import get_current_user
from src.models.audit_entry import AuditEntry
from src.models.permission import (
    CODE_STATES,
    STATE_CODES,
    STATE_DENY,
    STATE_GRANT,
    STATE_NONE,
    PermissionAssignment,
    PermissionState,
    PermissionType,
    StagedChange,
)
from src.services.loader import MatrixSnapshot, fetch_snapshot
from src.services.matrix_index import (
    PERM_COUNT,
    PERM_INDEX,
    PERMS,
    ObjectQuery,
    PermissionIndex,
    PrincipalQuery,
    cell_code,
    diff_mask,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import pyodbc

    from src.models.db_object import DatabaseObject
    from src.models.user import DatabaseUser
    from src.services.tags import TagStore

logger = logging.getLogger("bifrost.matrix")

# Natural key for a cell that survives reloads: (login, schema, object, permission)
NaturalKey = tuple[str, str, str, PermissionType]

_NEXT_CODE = {STATE_NONE: STATE_GRANT, STATE_GRANT: STATE_DENY, STATE_DENY: STATE_NONE}
_VERB = {STATE_GRANT: "Grant", STATE_DENY: "Deny", STATE_NONE: "Revoke"}


# --- Value types ---------------------------------------------------------------


@dataclass(frozen=True)
class CellRef:
    """One matrix cell by index: principal p, object o, permission index perm."""

    p: int
    o: int
    perm: int


@dataclass(frozen=True)
class UndoGroup:
    """
    One undoable action, which may cover many cells.

    Attributes:
        label: What the action did, e.g. "Grant SELECT on 247 objects for CORP\\jsmith"
        cells: (p, o, perm, before_code, after_code); codes are effective states
    """

    label: str
    cells: tuple[tuple[int, int, int, int, int], ...]


@dataclass(frozen=True)
class StageResult:
    """
    Outcome of a staging call.

    Attributes:
        changed: Cells whose effective state changed
        unchanged: Cells already in the target state
        skipped_not_applicable: Cells whose permission doesn't apply to the object type
        group: The undo group recorded, or None if nothing changed
    """

    changed: int
    unchanged: int
    skipped_not_applicable: int
    group: UndoGroup | None


@dataclass(frozen=True)
class MatrixChange:
    """
    Notification sent to listeners after the matrix changes.

    Attributes:
        reason: What caused the change
        rows: (p, o) rows that changed, or None if anything may have changed
        staged_count: Cells that differ from committed, after the change
    """

    reason: Literal["stage", "undo", "redo", "cancel", "commit", "reload", "tags"]
    rows: frozenset[tuple[int, int]] | None
    staged_count: int


@dataclass(frozen=True)
class RestageReport:
    """
    What happened to staged changes when a new snapshot was applied.

    Attributes:
        kept: Still staged
        dropped_missing: Removed because the principal, object or permission no longer exists
        already_applied: Removed because the database already has the staged state
    """

    kept: tuple[StagedChange, ...] = ()
    dropped_missing: tuple[StagedChange, ...] = ()
    already_applied: tuple[StagedChange, ...] = ()


@dataclass(frozen=True)
class CommitPlan:
    """
    Staged changes captured for one commit.

    Attributes:
        changes: Changes to apply, sorted by principal, object, permission
        cells: Matching cell indexes at the time the plan was made
        schema: Schema of Bifrost's audit log table
    """

    changes: tuple[StagedChange, ...]
    cells: tuple[CellRef, ...]
    schema: str


@dataclass(frozen=True)
class CommitOutcome:
    """
    Result of execute_commit().

    Attributes:
        results: (change, error) for each change; error None = applied
        audit_written: Audit entries written
        rolled_back: True if nothing was committed
        error: Message when the whole batch failed (e.g. connection lost)
    """

    results: tuple[tuple[StagedChange, str | None], ...]
    audit_written: int
    rolled_back: bool
    error: str | None


@dataclass
class FilterState:
    """
    Filter/search/sort state for the legacy Tk matrix view.

    Attributes:
        user_search_term: Text search filter for users (matches login name)
        object_search_term: Text search filter for objects (matches schema.name)
        active_filters: "user_tag", "object_tag", "object_type"
        sort_key: "user_name", "object_name" or "object_type"
        sort_ascending: Sort direction
    """

    user_search_term: str = ""
    object_search_term: str = ""
    active_filters: dict = field(default_factory=dict)
    sort_key: str = "object_name"
    sort_ascending: bool = True


@dataclass
class DataSizeInfo:
    """
    Information about the total data size to help users filter large datasets.

    Attributes:
        total_users: Total users in database
        total_objects: Total objects in database
        is_large: Whether dataset exceeds performance threshold
        recommended_chunk_size: Recommended rows to display at once
        warning_message: Advice to show when is_large
    """

    total_users: int = 0
    total_objects: int = 0
    is_large: bool = False
    recommended_chunk_size: int = 50
    warning_message: str = ""


# --- Matrix --------------------------------------------------------------------


class PermissionMatrix:
    """
    In-memory permission matrix with staging, grouped undo/redo and commit.

    Attributes:
        conn: Database connection used by the legacy synchronous methods (may be None)
        schema: Schema of Bifrost's audit log table
        tag_store: Local tags (may be None)
        index: Current PermissionIndex
        current_user: SYSTEM_USER from the last load
        filter_state: Legacy filter state for get_filtered_users/get_filtered_objects
    """

    MAX_UNDO_GROUPS = 50
    # Kept for callers of the previous API
    MAX_UNDO_ENTRIES = MAX_UNDO_GROUPS
    PERF_THRESHOLD_USERS = 100
    PERF_THRESHOLD_OBJECTS = 50

    def __init__(
        self,
        conn: pyodbc.Connection | None,
        schema: str = "dbo",
        tag_store: TagStore | None = None,
    ):
        """
        Initialize an empty matrix.

        Args:
            conn: Database connection for the legacy synchronous methods. Pass None
                when all DB access goes through execute_commit/fetch_snapshot.
            schema: Schema of Bifrost's audit log table (default "dbo")
            tag_store: Local tags to attach to principals and objects
        """
        self.conn = conn
        self.schema = schema
        self.tag_store = tag_store
        self.index = PermissionIndex()
        self.current_user: str | None = None
        self.filter_state = FilterState()
        self._privileged = False
        self._grant_privileges: dict[NaturalKey, bool] = {}
        self._undo: list[UndoGroup] = []
        self._redo: list[UndoGroup] = []
        self._listeners: list[Callable[[MatrixChange], None]] = []
        self._legacy_unsubscribe: Callable[[], None] | None = None

    # --- Data access -------------------------------------------------------------

    @property
    def users(self) -> list[DatabaseUser]:
        """All principals, in index order."""
        return self.index.principals

    @property
    def objects(self) -> list[DatabaseObject]:
        """All objects, in index order."""
        return self.index.objects

    @property
    def privileged(self) -> bool:
        """True if the connected account can grant anything (sysadmin, db_owner, CONTROL)."""
        return self._privileged

    def row_state(self, p: int, o: int) -> int:
        """Return the effective packed state of a row. See matrix_index for the bit layout."""
        return self.index.row_state(p, o)

    # --- Listeners ---------------------------------------------------------------

    def subscribe(self, listener: Callable[[MatrixChange], None]) -> Callable[[], None]:
        """
        Register a listener for MatrixChange notifications.

        Args:
            listener: Called synchronously after each change

        Returns:
            Callable: Call it to unsubscribe
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def set_on_change_callback(self, callback: Callable[[], None] | None) -> None:
        """
        Legacy: set a no-argument callback for any change (replaces the previous one).

        Args:
            callback: Function to call on change, or None to remove it
        """
        if self._legacy_unsubscribe is not None:
            self._legacy_unsubscribe()
            self._legacy_unsubscribe = None
        if callback is not None:
            self._legacy_unsubscribe = self.subscribe(lambda _change: callback())

    def _emit(self, reason, rows: Iterable[tuple[int, int]] | None) -> None:
        """Send a MatrixChange to every listener; a failing listener doesn't stop the rest."""
        change = MatrixChange(
            reason=reason,
            rows=None if rows is None else frozenset(rows),
            staged_count=self.index.staged_cell_count,
        )
        for listener in list(self._listeners):
            try:
                listener(change)
            except Exception:
                logger.exception("Matrix change listener failed")

    # --- Loading -----------------------------------------------------------------

    def apply_snapshot(self, snapshot: MatrixSnapshot) -> RestageReport:
        """
        Replace the matrix data with a new snapshot, keeping staged changes.

        Staged changes are carried over by natural key (login, schema, object,
        permission), so they survive principals or objects being reordered.

        Args:
            snapshot: Data from fetch_snapshot()

        Returns:
            RestageReport: Which staged changes were kept or dropped
        """
        previous = self.get_staged_changes()
        self._install(snapshot)

        kept: list[StagedChange] = []
        dropped_missing: list[StagedChange] = []
        already_applied: list[StagedChange] = []
        index = self.index
        for change in previous:
            p = index.principal_index(change.user_login)
            o = index.object_index(change.schema_name, change.object_name)
            perm_idx = PERM_INDEX[change.permission_type]
            if p is None or o is None or not index.is_applicable(o, perm_idx):
                dropped_missing.append(change)
                continue
            code = STATE_CODES[change.new_state]
            if cell_code(index.committed_row(p, o), perm_idx) == code:
                already_applied.append(change)
                continue
            index.set_effective(p, o, perm_idx, code)
            kept.append(change)

        self._emit("reload", None)
        return RestageReport(tuple(kept), tuple(dropped_missing), tuple(already_applied))

    def _install(self, snapshot: MatrixSnapshot) -> None:
        """Build a new index from snapshot, dropping staged changes and undo history."""
        self.index = PermissionIndex.build(snapshot, self.tag_store)
        self.current_user = snapshot.current_user
        self._privileged = snapshot.privileged
        self._grant_privileges.clear()
        self._undo.clear()
        self._redo.clear()

    def load(self) -> None:
        """
        Legacy: load everything from the database, discarding staged changes.

        Raises:
            pyodbc.Error: If a query fails
        """
        self._install(fetch_snapshot(self.conn))
        self._emit("reload", None)

    def refresh(self) -> RestageReport:
        """
        Legacy: reload from the database, keeping staged changes (manual refresh, F5).

        Returns:
            RestageReport: Which staged changes were kept or dropped
        """
        return self.apply_snapshot(fetch_snapshot(self.conn))

    # --- Staging -----------------------------------------------------------------

    def stage(
        self, cells: Iterable[CellRef], state: PermissionState, label: str | None = None
    ) -> StageResult:
        """
        Stage one state for many cells as a single undoable action.

        Args:
            cells: Cells to change
            state: New state for every cell
            label: Undo label (generated if None)

        Returns:
            StageResult: Counts of changed, unchanged and skipped cells

        Note:
            FR-030 confirmation and FR-031 selection limits are the caller's job.
            Privilege checks (FR-017a) are also done by the caller first.
        """
        code = STATE_CODES[state]
        return self._stage_cells(((c.p, c.o, c.perm, code) for c in cells), label)

    def stage_cycle(self, cell: CellRef) -> StageResult:
        """Move one cell to its next state: NONE → GRANT → DENY → NONE."""
        current = cell_code(self.index.row_state(cell.p, cell.o), cell.perm)
        return self._stage_cells([(cell.p, cell.o, cell.perm, _NEXT_CODE[current])], None)

    def revert(self, cells: Iterable[CellRef], label: str | None = None) -> StageResult:
        """Set cells back to their committed state as a single undoable action."""
        index = self.index
        return self._stage_cells(
            ((c.p, c.o, c.perm, cell_code(index.committed_row(c.p, c.o), c.perm)) for c in cells),
            label,
        )

    def _stage_cells(
        self,
        cells: Iterable[tuple[int, int, int, int]],
        label: str | None,
        record_undo: bool = True,
    ) -> StageResult:
        """Apply (p, o, perm, code) changes, record one undo group and notify once."""
        index = self.index
        changed: list[tuple[int, int, int, int, int]] = []
        rows: set[tuple[int, int]] = set()
        unchanged = 0
        skipped = 0
        for p, o, perm_idx, code in cells:
            if not index.is_applicable(o, perm_idx):
                skipped += 1
                continue
            before = cell_code(index.row_state(p, o), perm_idx)
            if before == code:
                unchanged += 1
                continue
            index.set_effective(p, o, perm_idx, code)
            changed.append((p, o, perm_idx, before, code))
            rows.add((p, o))

        group = None
        if changed and record_undo:
            group = UndoGroup(label or self._describe(changed), tuple(changed))
            self._undo.append(group)
            if len(self._undo) > self.MAX_UNDO_GROUPS:
                del self._undo[0]
            self._redo.clear()
        if changed:
            self._emit("stage", rows)
        return StageResult(len(changed), unchanged, skipped, group)

    def _describe(self, cells: list[tuple[int, int, int, int, int]]) -> str:
        """Build an undo label such as "Grant SELECT on 247 objects for CORP\\jsmith"."""
        index = self.index
        if len(cells) == 1:
            p, o, perm_idx, _before, after = cells[0]
            return (
                f"{_VERB[after]} {PERMS[perm_idx].value} on {index.objects[o].full_name} "
                f"for {index.principals[p].login_name}"
            )
        afters = {c[4] for c in cells}
        perms = {c[2] for c in cells}
        principals = {c[0] for c in cells}
        if len(afters) == 1 and len(perms) == 1:
            verb = _VERB[next(iter(afters))]
            perm = PERMS[next(iter(perms))].value
            objects = len({c[1] for c in cells})
            if len(principals) == 1:
                login = index.principals[next(iter(principals))].login_name
                return f"{verb} {perm} on {objects:,} objects for {login}"
            return f"{verb} {perm} on {len(cells):,} cells"
        return f"Change {len(cells):,} permissions"

    # --- Undo / redo -------------------------------------------------------------

    def can_undo(self) -> bool:
        """True if there is an action to undo."""
        return bool(self._undo)

    def can_redo(self) -> bool:
        """True if there is an action to redo."""
        return bool(self._redo)

    def undo(self) -> UndoGroup | None:
        """
        Undo the last staging action.

        Returns:
            UndoGroup | None: The undone action (truthy), or None if nothing to undo
        """
        if not self._undo:
            return None
        group = self._undo.pop()
        self._apply_group(group, after=False)
        self._redo.append(group)
        self._emit("undo", {(c[0], c[1]) for c in group.cells})
        return group

    def redo(self) -> UndoGroup | None:
        """
        Redo the last undone action.

        Returns:
            UndoGroup | None: The redone action (truthy), or None if nothing to redo
        """
        if not self._redo:
            return None
        group = self._redo.pop()
        self._apply_group(group, after=True)
        self._undo.append(group)
        self._emit("redo", {(c[0], c[1]) for c in group.cells})
        return group

    def _apply_group(self, group: UndoGroup, after: bool) -> None:
        """Set every cell in group to its after (redo) or before (undo) state."""
        index = self.index
        cells = group.cells if after else reversed(group.cells)
        for p, o, perm_idx, before, after_code in cells:
            index.set_effective(p, o, perm_idx, after_code if after else before)

    def cancel(self) -> None:
        """Discard all staged changes and clear undo/redo."""
        rows = self.index.clear_staged()
        self._undo.clear()
        self._redo.clear()
        self._emit("cancel", rows)

    # --- Staged change queries ---------------------------------------------------

    def get_staged_changes(self) -> list[StagedChange]:
        """
        Return all staged changes, sorted by principal, object and permission.

        Returns:
            list[StagedChange]: One entry per cell that differs from committed
        """
        return [change for _cell, change in self._staged_cells()]

    def _staged_cells(self) -> list[tuple[CellRef, StagedChange]]:
        """Return (cell, change) pairs for every staged cell, in display order."""
        index = self.index
        result: list[tuple[CellRef, StagedChange]] = []
        keys = sorted(index.staged, key=lambda k: (index.principal_rank(k[0]), index.object_rank(k[1])))
        for p, o in keys:
            effective = index.staged[(p, o)]
            committed = index.committed_row(p, o)
            mask = diff_mask(effective, committed)
            principal = index.principals[p]
            obj = index.objects[o]
            for perm_idx in range(PERM_COUNT):
                if mask & (1 << perm_idx):
                    result.append(
                        (
                            CellRef(p, o, perm_idx),
                            StagedChange(
                                user_login=principal.login_name,
                                schema_name=obj.schema_name,
                                object_name=obj.object_name,
                                permission_type=PERMS[perm_idx],
                                previous_state=CODE_STATES[cell_code(committed, perm_idx)],
                                new_state=CODE_STATES[cell_code(effective, perm_idx)],
                            ),
                        )
                    )
        return result

    def get_staged_change_count(self) -> int:
        """Return the number of staged cells (O(1))."""
        return self.index.staged_cell_count

    def has_staged_changes(self) -> bool:
        """Return True if any cell is staged."""
        return self.index.staged_cell_count > 0

    # --- Commit ------------------------------------------------------------------

    def prepare_commit(self) -> CommitPlan:
        """Capture the staged changes to commit (UI thread)."""
        pairs = self._staged_cells()
        return CommitPlan(
            changes=tuple(change for _cell, change in pairs),
            cells=tuple(cell for cell, _change in pairs),
            schema=self.schema,
        )

    @staticmethod
    def execute_commit(conn: pyodbc.Connection, plan: CommitPlan, admin_user: str) -> CommitOutcome:
        """
        Apply a commit plan to the database and write audit entries (worker thread; DB only).

        Permission changes and their audit rows are committed together or not at all.
        Per-change errors are collected; nothing is raised.

        Args:
            conn: Database connection (autocommit off)
            plan: From prepare_commit()
            admin_user: Administrator recorded in the audit log

        Returns:
            CommitOutcome: Per-change results, or a whole-batch error with rolled_back=True
        """
        changes = list(plan.changes)
        if not changes:
            return CommitOutcome(results=(), audit_written=0, rolled_back=False, error=None)

        def failed(message: str) -> CommitOutcome:
            try:
                conn.rollback()
            except Exception:
                logger.warning("Rollback failed after commit error", exc_info=True)
            return CommitOutcome(
                results=tuple((change, message) for change in changes),
                audit_written=0,
                rolled_back=True,
                error=message,
            )

        # Any failure outside a single statement must roll back, whatever its type
        try:
            results = db_permissions.apply_permission_changes(conn, changes)
        except Exception as e:
            return failed(f"Nothing was committed: {e}")

        successes = [change for change, error in results if error is None]
        try:
            if successes:
                now = datetime.now(UTC)
                entries = [
                    AuditEntry(
                        id=0,  # Auto-generated
                        administrator=admin_user,
                        affected_user=change.user_login,
                        schema_name=change.schema_name,
                        object_name=change.object_name,
                        permission_type=change.permission_type.value,
                        action=change.action,
                        previous_state=change.previous_state.value,
                        new_state=change.new_state.value,
                        changed_at=now,
                        explanation=AuditEntry.generate_explanation(
                            action=change.action,
                            permission_type=change.permission_type.value,
                            schema_name=change.schema_name,
                            object_name=change.object_name,
                            affected_user=change.user_login,
                        ),
                    )
                    for change in successes
                ]
                db_audit.write_audit_entries(conn, entries, schema=plan.schema)
            conn.commit()
        except Exception as e:
            return failed(f"Nothing was committed because the audit log could not be written: {e}")

        return CommitOutcome(
            results=tuple(results), audit_written=len(successes), rolled_back=False, error=None
        )

    def apply_commit_results(self, plan: CommitPlan, outcome: CommitOutcome) -> None:
        """
        Record committed changes in the matrix (UI thread).

        Successful cells become committed; failed cells stay staged. If the batch
        was rolled back, nothing changes. Cells are matched by natural key, so this
        still works if the matrix was reloaded while the commit ran.

        Args:
            plan: The plan that was executed
            outcome: From execute_commit()
        """
        if outcome.rolled_back:
            return
        index = self.index
        applied: list[tuple[int, int, int, int]] = []
        for change, error in outcome.results:
            if error is not None:
                continue
            p = index.principal_index(change.user_login)
            o = index.object_index(change.schema_name, change.object_name)
            if p is None or o is None:
                continue
            applied.append((p, o, PERM_INDEX[change.permission_type], STATE_CODES[change.new_state]))
        rows = index.commit_rows(applied)
        self._undo.clear()
        self._redo.clear()
        self._emit("commit", rows)

    def commit(self) -> list[tuple[StagedChange, str | None]]:
        """
        Legacy: prepare, execute and apply a commit in one call.

        Returns:
            list[tuple[StagedChange, Optional[str]]]: (change, error) per change

        Raises:
            RuntimeError: If the whole batch failed (e.g. connection lost); nothing was committed
        """
        plan = self.prepare_commit()
        if not plan.changes:
            return []
        admin_user = self.current_user or get_current_user(self.conn)
        outcome = self.execute_commit(self.conn, plan, admin_user)
        if outcome.rolled_back and outcome.error:
            raise RuntimeError(outcome.error)
        self.apply_commit_results(plan, outcome)
        return list(outcome.results)

    # --- Privilege checks (FR-017a) ----------------------------------------------

    def known_grant_privilege(self, cell: CellRef) -> bool | None:
        """
        Return whether the admin may GRANT this cell's permission, from cache.

        Returns:
            bool | None: True/False if known, None if it needs a database check
        """
        if self._privileged:
            return True
        return self._grant_privileges.get(self._natural_key(cell))

    def remember_grant_privileges(self, results: dict[tuple[str, str, PermissionType], bool]) -> None:
        """Cache results from db.permissions.check_grant_privileges()."""
        for (schema_name, object_name, permission_type), allowed in results.items():
            # Cached per object and permission; the principal doesn't matter
            self._grant_privileges[("", schema_name, object_name, permission_type)] = allowed

    def _natural_key(self, cell: CellRef) -> NaturalKey:
        obj = self.index.objects[cell.o]
        return ("", obj.schema_name, obj.object_name, PERMS[cell.perm])

    def validate_grant_privilege(
        self,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> str | None:
        """
        Legacy: check one GRANT against the admin's own permissions (uses self.conn).

        Returns:
            Optional[str]: Error message if the admin lacks the permission, else None
        """
        key = ("", schema_name, object_name, permission_type)
        allowed = True if self._privileged else self._grant_privileges.get(key)
        if allowed is None:
            results = db_permissions.check_grant_privileges(
                self.conn, [(schema_name, object_name, permission_type)]
            )
            self.remember_grant_privileges(results)
            allowed = results[(schema_name, object_name, permission_type)]
        if not allowed:
            return (
                f"You cannot grant {permission_type.value} on {schema_name}.{object_name} "
                f"because you do not have this permission yourself."
            )
        return None

    # --- Tags --------------------------------------------------------------------

    def set_tag_store(self, tag_store: TagStore | None) -> None:
        """Attach a (possibly updated) tag store and notify listeners."""
        self.tag_store = tag_store
        self.index.set_tags(tag_store)
        self._emit("tags", None)

    # --- Legacy API (Tk UI) ------------------------------------------------------

    def _cell_ref(
        self, user_login: str, schema_name: str, object_name: str, permission_type: PermissionType
    ) -> CellRef | None:
        p = self.index.principal_index(user_login)
        o = self.index.object_index(schema_name, object_name)
        if p is None or o is None:
            return None
        return CellRef(p, o, PERM_INDEX[permission_type])

    def get_assignment(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> PermissionAssignment:
        """
        Legacy API for the Tk UI; new code uses row_state().

        Returns:
            PermissionAssignment: Committed and staged state for one cell
                (NONE if the principal or object is unknown)
        """
        cell = self._cell_ref(user_login, schema_name, object_name, permission_type)
        committed = PermissionState.NONE
        staged = None
        if cell is not None:
            committed_code = cell_code(self.index.committed_row(cell.p, cell.o), cell.perm)
            effective_code = cell_code(self.index.row_state(cell.p, cell.o), cell.perm)
            committed = CODE_STATES[committed_code]
            if effective_code != committed_code:
                staged = CODE_STATES[effective_code]
        return PermissionAssignment(
            user_login=user_login,
            schema_name=schema_name,
            object_name=object_name,
            permission_type=permission_type,
            committed_state=committed,
            staged_state=staged,
        )

    def stage_change(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
        new_state: PermissionState,
        add_to_undo: bool = True,
    ) -> str | None:
        """
        Legacy API for the Tk UI: stage one cell by name.

        Returns:
            Optional[str]: Error message if the cell doesn't exist or doesn't apply, else None
        """
        cell = self._cell_ref(user_login, schema_name, object_name, permission_type)
        if cell is None:
            return f"Unknown principal or object: {user_login} / {schema_name}.{object_name}"
        if not self.index.is_applicable(cell.o, cell.perm):
            return f"{permission_type.value} does not apply to {schema_name}.{object_name}"
        self._stage_cells(
            [(cell.p, cell.o, cell.perm, STATE_CODES[new_state])], None, record_undo=add_to_undo
        )
        return None

    def toggle_cell(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> str | None:
        """Legacy API for the Tk UI: cycle one cell NONE → GRANT → DENY → NONE."""
        cell = self._cell_ref(user_login, schema_name, object_name, permission_type)
        if cell is None:
            return f"Unknown principal or object: {user_login} / {schema_name}.{object_name}"
        if not self.index.is_applicable(cell.o, cell.perm):
            return f"{permission_type.value} does not apply to {schema_name}.{object_name}"
        self.stage_cycle(cell)
        return None

    @property
    def assignments(self) -> dict[tuple, PermissionAssignment]:
        """
        Legacy: explicit and staged cells as {cell_key: PermissionAssignment}.

        Built on each access; new code should use the index directly.
        """
        index = self.index
        result: dict[tuple, PermissionAssignment] = {}
        for p, o in set(index.committed) | set(index.staged):
            committed = index.committed_row(p, o)
            effective = index.row_state(p, o)
            principal = index.principals[p]
            obj = index.objects[o]
            for perm_idx in range(PERM_COUNT):
                committed_code = cell_code(committed, perm_idx)
                effective_code = cell_code(effective, perm_idx)
                if committed_code == STATE_NONE and effective_code == STATE_NONE:
                    continue
                key = (principal.login_name, obj.schema_name, obj.object_name, PERMS[perm_idx])
                result[key] = PermissionAssignment(
                    user_login=principal.login_name,
                    schema_name=obj.schema_name,
                    object_name=obj.object_name,
                    permission_type=PERMS[perm_idx],
                    committed_state=CODE_STATES[committed_code],
                    staged_state=CODE_STATES[effective_code] if effective_code != committed_code else None,
                )
        return result

    def get_performance_info(self) -> DataSizeInfo:
        """Return data size information and a warning for large datasets."""
        num_users = len(self.users)
        num_objects = len(self.objects)
        info = DataSizeInfo(total_users=num_users, total_objects=num_objects)
        if num_users > self.PERF_THRESHOLD_USERS or num_objects > self.PERF_THRESHOLD_OBJECTS:
            info.is_large = True
            info.warning_message = (
                f"⚠️  Large dataset detected: {num_users} users × {num_objects} objects.\n"
                f"Try using Search or Filters to reduce the view size for better performance.\n"
                f"(Viewing >100 users or >50 objects may be slow)"
            )
        return info

    def set_search_term(self, term: str) -> None:
        """Legacy: set both user and object search terms."""
        self.filter_state.user_search_term = term
        self.filter_state.object_search_term = term

    def set_user_search_term(self, term: str) -> None:
        """Legacy: set the user search term."""
        self.filter_state.user_search_term = term

    def set_object_search_term(self, term: str) -> None:
        """Legacy: set the object search term."""
        self.filter_state.object_search_term = term

    def set_filter(self, key: str, value: object) -> None:
        """Legacy: set an active filter ("user_tag", "object_tag", "object_type")."""
        self.filter_state.active_filters[key] = value

    def clear_filter(self, key: str) -> None:
        """Legacy: clear one filter."""
        self.filter_state.active_filters.pop(key, None)

    def clear_all_filters(self) -> None:
        """Legacy: clear all filters and reset sorting."""
        self.filter_state = FilterState()

    def set_sort(self, key: str, ascending: bool = True) -> None:
        """Legacy: set the sort key and direction."""
        self.filter_state.sort_key = key
        self.filter_state.sort_ascending = ascending

    def get_filtered_users(self) -> list[DatabaseUser]:
        """Legacy: principals matching filter_state, sorted by name."""
        state = self.filter_state
        tag = state.active_filters.get("user_tag")
        query = PrincipalQuery(
            text=state.user_search_term,
            tags=frozenset({tag.casefold()}) if tag else frozenset(),
            descending=state.sort_key == "user_name" and not state.sort_ascending,
        )
        return [self.index.principals[p] for p in self.index.query_principals(query)]

    def get_filtered_objects(self) -> list[DatabaseObject]:
        """Legacy: objects matching filter_state."""
        state = self.filter_state
        tag = state.active_filters.get("object_tag")
        object_type = state.active_filters.get("object_type")
        query = ObjectQuery(
            text=state.object_search_term,
            tags=frozenset({tag.casefold()}) if tag else frozenset(),
            types=frozenset({object_type}) if object_type else frozenset(),
            sort="type" if state.sort_key == "object_type" else "schema_name",
            descending=not state.sort_ascending
            and state.sort_key in ("object_name", "object_type"),
        )
        return [self.index.objects[o] for o in self.index.query_objects(query)]
