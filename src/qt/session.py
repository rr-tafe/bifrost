"""
Application state and flows for the Qt UI.

Session owns the configuration, the database connection, the PermissionMatrix
and the tag store, and runs every flow: connect, load, refresh, commit, discard,
undo/redo, connection-loss handling, audit fetches and exports. It has no
widgets; windows and dialogs call its methods and react to its signals.

All database work goes through the DbWorker. The connection is only used on the
worker thread; Session keeps it as an opaque handle to pass into jobs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Signal

from src.db import audit as db_audit
from src.db import connection as db_connection
from src.db import objects as db_objects
from src.db import permissions as db_permissions
from src.db.permissions import LoadCancelledError
from src.models.permission import STATE_GRANT, PermissionState, StagedChange
from src.qt.worker import DbWorker, JobCancelledError, JobHandle, run_detached
from src.services import config as config_service
from src.services import export as export_service
from src.services import loader
from src.services.matrix import CellRef, CommitPlan, MatrixChange, PermissionMatrix, RestageReport
from src.services.matrix_index import PERM_INDEX, PERMS, PermissionIndex, cell_code
from src.services.tags import TagStore
from src.validation import validate_description

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.models.audit_entry import AuditEntry
    from src.models.config import Configuration
    from src.services.loader import LoadProgress, MatrixSnapshot

logger = logging.getLogger("bifrost.session")

HEARTBEAT_MS = 30_000
EXPRESS_COMMIT_LIMIT = 5  # fewer changes than this commit without a preview (FR-026)
DISCARD_CONFIRM_AT = 5  # this many changes or more need confirmation to discard
AUDIT_FETCH_LIMIT = 5_000
ANNOUNCE_DEBOUNCE_MS = 500
STATUS_SHORT_MS = 5_000
STATUS_MS = 8_000

# Text in error messages that means the connection was lost
_CONNECTION_LOSS_TEXT = ("communication link failure", "tcp provider", "08s01")
# Connect errors that mean the settings are probably wrong
_SETTINGS_ERROR_TEXT = (
    "authentication failed",
    "login failed",
    "not found",
    "does not exist",
    "invalid configuration",
)


class SessionState(Enum):
    """Where the app is in its lifecycle."""

    NEEDS_SETTINGS = auto()  # no usable config
    CONNECTING = auto()
    LOADING = auto()  # connected, fetching a snapshot
    READY = auto()
    COMMITTING = auto()
    OFFLINE = auto()  # connection lost or user disconnected; staged changes kept
    FAILED = auto()  # connect or first load failed; see last_error


@dataclass(frozen=True)
class LoadSummary:
    """What was loaded, for the matrix placeholder and status messages."""

    principals: int
    objects: int
    grants: int
    denies: int
    principals_by_type: dict[str, int]
    objects_by_type: dict[str, int]
    skipped_rows: int
    timings: dict[str, float]
    loaded_at: datetime


@dataclass(frozen=True)
class CommitReport:
    """Outcome of a commit, for result dialogs."""

    succeeded: tuple[StagedChange, ...]
    failed: tuple[tuple[StagedChange, str], ...]
    rolled_back: bool
    error: str | None
    started_at: datetime
    connection_lost: bool = False

    @property
    def all_succeeded(self) -> bool:
        return not self.rolled_back and not self.failed


@dataclass(frozen=True)
class AuditResult:
    """Result of an audit fetch."""

    entries: list[AuditEntry] = field(default_factory=list)
    total: int = 0
    limited: bool = False


def describe_change(change: StagedChange) -> str:
    """Return a change as a sentence, e.g. "GRANT SELECT on sales.Orders to CORP\\jsmith"."""
    target = f"{change.schema_name}.{change.object_name}"
    perm = change.permission_type.value
    if change.action == "REVOKE":
        return f"REVOKE {perm} on {target} from {change.user_login}"
    return f"{change.action} {perm} on {target} to {change.user_login}"


def _looks_like_connection_loss(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _CONNECTION_LOSS_TEXT)


class Session(QObject):
    """
    Application controller for the Qt UI.

    Signals are the only way views learn about changes. A view created late must
    render correctly from Session's current state.
    """

    stateChanged = Signal(object)  # SessionState
    loadProgress = Signal(object)  # LoadProgress
    dataLoaded = Signal(object)  # LoadSummary
    matrixChanged = Signal(object)  # MatrixChange
    stagedCountChanged = Signal(int)
    undoStateChanged = Signal(bool, bool)  # can_undo, can_redo
    statusMessage = Signal(str, int)  # text, timeout ms (0 = until replaced)
    busyMessage = Signal(str, object)  # text ("" clears), progress (None = indeterminate, else (value, maximum))
    announce = Signal(str)  # for screen readers
    settingsRequested = Signal(str)  # reason ("" if user-initiated)
    connectionLost = Signal(str, int)  # error, staged count
    commitPreviewRequested = Signal(object)  # CommitPlan
    privilegeDenied = Signal(object)  # list[StagedChange] that were un-staged
    commitFinished = Signal(object)  # CommitReport
    discardConfirmationRequested = Signal(int)  # staged count
    restageReport = Signal(object)  # RestageReport
    tagsChanged = Signal()
    revealRequested = Signal(object)  # CellRef
    stagingDenied = Signal(object)  # list[StagedChange] not staged: the admin can't grant them (FR-017a)
    stagingBusyChanged = Signal(bool)  # True while a staging privilege check runs

    def __init__(self, worker: DbWorker | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.worker = worker or DbWorker(self)
        self.worker.jobError.connect(self._on_unhandled_job_error)
        self._state = SessionState.NEEDS_SETTINGS
        self.config: Configuration | None = None
        self.matrix: PermissionMatrix | None = None
        self.tag_store = TagStore()
        self.current_user: str | None = None
        self.last_error: str | None = None
        self.last_load: LoadSummary | None = None
        self._conn: Any = None
        self._load_handle: JobHandle | None = None
        self._export_handle: JobHandle | None = None
        self._last_staged_count = 0
        self._shutting_down = False
        self._staging_busy = False
        self._descriptions: dict[tuple[str, str], str | None] = {}

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self._on_heartbeat)

        self._announce_timer = QTimer(self)
        self._announce_timer.setSingleShot(True)
        self._announce_timer.setInterval(ANNOUNCE_DEBOUNCE_MS)
        self._announce_timer.timeout.connect(self._announce_staged_count)

    # --- State -------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        return self._state

    def _set_state(self, state: SessionState) -> None:
        if state is self._state:
            return
        logger.info("State %s -> %s", self._state.name, state.name)
        self._state = state
        self.stateChanged.emit(state)

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._state in (
            SessionState.LOADING,
            SessionState.READY,
            SessionState.COMMITTING,
        )

    @property
    def busy(self) -> bool:
        return self._state in (SessionState.CONNECTING, SessionState.LOADING, SessionState.COMMITTING)

    @property
    def can_edit(self) -> bool:
        """True when cells may be staged."""
        return self._state is SessionState.READY and self.matrix is not None and not self._staging_busy

    @property
    def staging_busy(self) -> bool:
        """True while a privilege check for a staging action runs; further edits are ignored."""
        return self._staging_busy

    def edit_blocked_reason(self) -> str:
        """Why editing is blocked right now, for the status bar ("" if it isn't)."""
        if self.matrix is None:
            return "Load data first"
        if self._staging_busy:
            return "Checking your grant privileges…"
        if self._state is SessionState.COMMITTING:
            return "Committing… editing resumes when it finishes"
        if self._state is SessionState.READY:
            return ""
        if self._state is SessionState.LOADING:
            return "Refreshing… editing resumes when it finishes"
        return "Offline. Reconnect to make changes."

    @property
    def staged_count(self) -> int:
        return self.matrix.get_staged_change_count() if self.matrix else 0

    @property
    def can_commit(self) -> bool:
        return self._state is SessionState.READY and self.staged_count > 0

    @property
    def can_undo(self) -> bool:
        return bool(self.matrix and self.matrix.can_undo()) and self._state is not SessionState.COMMITTING

    @property
    def can_redo(self) -> bool:
        return bool(self.matrix and self.matrix.can_redo()) and self._state is not SessionState.COMMITTING

    # --- Startup and connection --------------------------------------------------

    def start(self) -> None:
        """Load tags and config, then connect (or ask for settings)."""
        try:
            self.tag_store = TagStore.load()
        except Exception as e:  # corrupt tags file must not stop the app
            logger.exception("Could not load tags")
            self.tag_store = TagStore()
            self.statusMessage.emit(f"Couldn't load tags: {e}. Starting with no tags.", STATUS_MS)

        config, error = config_service.load_config()
        if error:
            self.config = None
            self._set_state(SessionState.NEEDS_SETTINGS)
            self.settingsRequested.emit(error)
            return
        self.connect(config)

    def connect(self, config: Configuration) -> None:
        """Open a new connection with config, then load (keeping any staged changes)."""
        self.config = config
        self._heartbeat.stop()
        old_conn, self._conn = self._conn, None
        self.last_error = None
        self._set_state(SessionState.CONNECTING)
        target = f"{config.server}/{config.database}"
        self.busyMessage.emit(f"Connecting to {target}…", None)

        def job(_ctx):
            if old_conn is not None:
                try:
                    old_conn.close()
                except Exception:
                    logger.debug("Closing the old connection failed", exc_info=True)
            conn = db_connection.create_connection(config)
            db_audit.ensure_audit_log_table(conn, config.schema)
            return conn

        def done(conn) -> None:
            self._conn = conn
            self._heartbeat.start()
            self._load()

        def failed(error: BaseException) -> None:
            message = str(error)
            self.last_error = message
            self.busyMessage.emit("", None)
            self._set_state(SessionState.FAILED)
            self.statusMessage.emit(f"Couldn't connect to {target}: {message}", 0)
            self.announce.emit(f"Connection failed. {message}")
            if any(text in message.lower() for text in _SETTINGS_ERROR_TEXT):
                self.settingsRequested.emit(message)

        self.worker.submit("connect", job, done, failed)

    def reconnect(self) -> None:
        """Connect again with the current config (staged changes are kept)."""
        if self.config is None:
            self.settingsRequested.emit("")
            return
        self.connect(self.config)

    def disconnect(self) -> None:
        """Close the connection. Staged changes and loaded data are kept."""
        self._heartbeat.stop()
        conn, self._conn = self._conn, None
        if conn is not None:
            self.worker.submit("disconnect", lambda _ctx: conn.close(), on_error=lambda _e: None)
        self._set_state(SessionState.OFFLINE)
        self.statusMessage.emit("Disconnected. Staged changes are kept.", STATUS_MS)

    # --- Load and refresh ----------------------------------------------------------

    def refresh(self) -> None:
        """Reload everything from the database, keeping staged changes (F5)."""
        if self._conn is None:
            self.statusMessage.emit("Not connected. Connect first to refresh.", STATUS_MS)
            return
        if self.busy:
            self.statusMessage.emit("Busy. Try again when the current task finishes.", STATUS_SHORT_MS)
            return
        self._load()

    def cancel_load(self) -> None:
        """Cancel a running load or refresh."""
        if self._load_handle is not None:
            self._load_handle.cancel()

    def _load(self) -> None:
        first = self.matrix is None
        conn = self._conn
        self._set_state(SessionState.LOADING)
        self.busyMessage.emit("Loading principals…", (0, 4))

        def progress(report: LoadProgress) -> None:
            self.loadProgress.emit(report)
            self.busyMessage.emit(report.message, (report.stage_number - 1, report.stage_count))

        def job(ctx):
            snapshot = loader.fetch_snapshot(conn, progress=ctx.report, cancel=ctx.cancel_event)
            # Build the index here, off the UI thread; tags are attached on the UI thread
            return snapshot, PermissionIndex.build(snapshot, None)

        def done(result: tuple[MatrixSnapshot, PermissionIndex]) -> None:
            self._load_handle = None
            self.apply_snapshot(*result)

        def failed(error: BaseException) -> None:
            self._load_handle = None
            self.busyMessage.emit("", None)
            cancelled = isinstance(error, LoadCancelledError | JobCancelledError)
            if not cancelled and db_connection.is_connection_error(error):
                self._connection_lost(error)
                return
            message = "Loading was cancelled" if cancelled else f"Loading failed: {error}"
            if first:
                self.last_error = message
                self._set_state(SessionState.FAILED)
                self.statusMessage.emit(message, 0)
            else:
                self._set_state(SessionState.READY)
                self.statusMessage.emit("Refresh cancelled" if cancelled else message, STATUS_MS)

        self._load_handle = self.worker.submit("load", job, done, failed, on_progress=progress)

    def apply_snapshot(self, snapshot: MatrixSnapshot, index: PermissionIndex | None = None) -> None:
        """Install a loaded snapshot (keeping staged changes) and go to READY. Tests call it directly."""
        if self.matrix is None:
            self.matrix = PermissionMatrix(None, self.config.schema if self.config else "dbo", self.tag_store)
            self.matrix.subscribe(self._on_matrix_change)
        report = self.matrix.apply_snapshot(snapshot, index)
        self.current_user = snapshot.current_user
        self.last_load = self._summarise(snapshot)
        self.busyMessage.emit("", None)
        self._set_state(SessionState.READY)
        self.dataLoaded.emit(self.last_load)
        summary = self.last_load
        self.statusMessage.emit(f"Loaded {summary.principals:,} principals and {summary.objects:,} objects", STATUS_MS)
        self.announce.emit(f"Loaded {summary.principals:,} principals and {summary.objects:,} objects")
        if report.dropped_missing or report.already_applied:
            self.restageReport.emit(report)

    def _summarise(self, snapshot: MatrixSnapshot) -> LoadSummary:
        index = self.matrix.index
        grants = sum(index.principal_counts(p).grants for p in range(len(index.principals)))
        denies = sum(index.principal_counts(p).denies for p in range(len(index.principals)))
        by_principal: dict[str, int] = {}
        for user in index.principals:
            by_principal[user.principal_type] = by_principal.get(user.principal_type, 0) + 1
        by_object: dict[str, int] = {}
        for obj in index.objects:
            by_object[obj.object_type.value] = by_object.get(obj.object_type.value, 0) + 1
        return LoadSummary(
            principals=len(index.principals),
            objects=len(index.objects),
            grants=grants,
            denies=denies,
            principals_by_type=by_principal,
            objects_by_type=by_object,
            skipped_rows=index.build_stats.skipped_unknown + index.build_stats.skipped_not_applicable,
            timings=dict(snapshot.timings),
            loaded_at=snapshot.loaded_at,
        )

    # --- Matrix changes ------------------------------------------------------------

    def _on_matrix_change(self, change: MatrixChange) -> None:
        self.matrixChanged.emit(change)
        if change.staged_count != self._last_staged_count:
            self._last_staged_count = change.staged_count
            self.stagedCountChanged.emit(change.staged_count)
            self._announce_timer.start()
        self.undoStateChanged.emit(self.can_undo, self.can_redo)

    def _announce_staged_count(self) -> None:
        count = self.staged_count
        self.announce.emit(f"{count:,} changes staged" if count else "No staged changes")

    # --- Commit ----------------------------------------------------------------------

    def request_commit(self, always_preview: bool = False) -> None:
        """Start a commit: commit directly for fewer than 5 changes, otherwise ask for a preview."""
        if self.matrix is None or self.staged_count == 0:
            self.statusMessage.emit("Nothing to commit", STATUS_SHORT_MS)
            return
        if self._state is not SessionState.READY or self._conn is None:
            self.statusMessage.emit("Not connected. Reconnect to commit your changes.", STATUS_MS)
            return
        plan = self.matrix.prepare_commit()
        if len(plan.changes) < EXPRESS_COMMIT_LIMIT and not always_preview:
            self.confirm_commit(plan)
        else:
            self.commitPreviewRequested.emit(plan)

    def confirm_commit(self, plan: CommitPlan) -> None:
        """Check grant privileges (FR-017a), then apply plan on the worker."""
        if self._state is not SessionState.READY or self._conn is None or self.matrix is None:
            self.statusMessage.emit("Not connected. Reconnect to commit your changes.", STATUS_MS)
            return
        matrix = self.matrix
        unknown = [
            (change.schema_name, change.object_name, change.permission_type)
            for cell, change in zip(plan.cells, plan.changes, strict=True)
            if change.new_state is PermissionState.GRANT and matrix.known_grant_privilege(cell) is None
        ]
        if not unknown:
            self._commit_after_privilege_check(plan)
            return

        conn = self._conn
        self._set_state(SessionState.COMMITTING)
        self.busyMessage.emit("Checking your grant privileges…", None)

        def done(results) -> None:
            matrix.remember_grant_privileges(results)
            self._set_state(SessionState.READY)
            self._commit_after_privilege_check(plan)

        def failed(error: BaseException) -> None:
            self.busyMessage.emit("", None)
            self._set_state(SessionState.READY)
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            else:
                self.statusMessage.emit(f"Couldn't check your privileges: {error}", 0)

        self.worker.submit(
            "privileges", lambda _ctx: db_permissions.check_grant_privileges(conn, unknown), done, failed
        )

    def _commit_after_privilege_check(self, plan: CommitPlan) -> None:
        matrix = self.matrix
        denied = [
            (cell, change)
            for cell, change in zip(plan.cells, plan.changes, strict=True)
            if change.new_state is PermissionState.GRANT and matrix.known_grant_privilege(cell) is False
        ]
        if denied:
            self.busyMessage.emit("", None)
            matrix.revert([cell for cell, _ in denied], label="Remove grants you aren't allowed to make")
            self.privilegeDenied.emit([change for _, change in denied])
            self.statusMessage.emit(
                f"{len(denied):,} grants were removed because you don't hold those permissions. "
                "Nothing was committed.",
                0,
            )
            return
        self._execute_commit(plan)

    def _execute_commit(self, plan: CommitPlan) -> None:
        conn = self._conn
        admin = self.current_user or "UNKNOWN"
        started_at = datetime.now(UTC)
        count = len(plan.changes)
        self._set_state(SessionState.COMMITTING)
        self.busyMessage.emit(f"Committing {count:,} changes…", None)
        self.undoStateChanged.emit(self.can_undo, self.can_redo)

        def done(outcome) -> None:
            self.busyMessage.emit("", None)
            self.matrix.apply_commit_results(plan, outcome)
            self._set_state(SessionState.READY)
            failed = tuple((c, e) for c, e in outcome.results if e is not None) if not outcome.rolled_back else ()
            succeeded = tuple(c for c, e in outcome.results if e is None) if not outcome.rolled_back else ()
            lost = outcome.rolled_back and _looks_like_connection_loss(outcome.error)
            report = CommitReport(succeeded, failed, outcome.rolled_back, outcome.error, started_at, lost)
            if report.all_succeeded:
                self.statusMessage.emit(f"Committed {len(succeeded):,} changes", STATUS_MS)
                self.announce.emit(f"Committed {len(succeeded):,} changes")
            elif outcome.rolled_back:
                self.statusMessage.emit(f"Nothing was committed. {count:,} changes are still staged.", 0)
                self.announce.emit("Commit failed. Nothing was committed.")
            else:
                self.statusMessage.emit(
                    f"Committed {len(succeeded):,} of {count:,} changes. {len(failed):,} failed and are still staged.",
                    0,
                )
                self.announce.emit(f"Commit partly failed. {len(failed):,} changes failed.")
            self.commitFinished.emit(report)
            if lost:
                self._connection_lost(RuntimeError(outcome.error))

        def failed(error: BaseException) -> None:
            # execute_commit doesn't raise; this is an unexpected bug or a lost connection
            self.busyMessage.emit("", None)
            self._set_state(SessionState.READY)
            report = CommitReport((), (), True, str(error), started_at, db_connection.is_connection_error(error))
            self.commitFinished.emit(report)
            if report.connection_lost:
                self._connection_lost(error)

        self.worker.submit("commit", lambda _ctx: PermissionMatrix.execute_commit(conn, plan, admin), done, failed)

    # --- Staging ---------------------------------------------------------------------

    def check_then_stage(
        self,
        items: Iterable[tuple[CellRef, PermissionState]],
        label: str | None = None,
        on_done: Callable[[int], None] | None = None,
    ) -> None:
        """
        Stage (cell, state) pairs as one undo step, after the FR-017a grant check.

        Cells that would become GRANT are checked against the admin's own
        permissions: from cache, or with one worker query for the unknown ones.
        Allowed cells are staged; denied ones are left alone and reported with
        stagingDenied. Edits are ignored while the check runs (staging_busy).

        Args:
            items: (cell, new state) pairs
            label: Undo label (generated if None)
            on_done: Called with the number of cells changed (0 if nothing was staged)
        """
        if not self.can_edit:
            self.statusMessage.emit(self.edit_blocked_reason(), STATUS_SHORT_MS)
            return
        matrix = self.matrix
        items = list(items)
        index = matrix.index
        unknown: dict[tuple[str, str, object], None] = {}
        for cell, state in items:
            if state is not PermissionState.GRANT:
                continue
            if cell_code(index.row_state(cell.p, cell.o), cell.perm) == STATE_GRANT:
                continue  # already GRANT; nothing to check
            if matrix.known_grant_privilege(cell) is None:
                obj = index.objects[cell.o]
                unknown[(obj.schema_name, obj.object_name, PERMS[cell.perm])] = None
        if not unknown:
            self._finish_stage(items, label, on_done)
            return

        conn = self._conn
        targets = list(unknown)
        self._set_staging_busy(True)
        self.busyMessage.emit("Checking your grant privileges…", None)

        def done(results) -> None:
            self._set_staging_busy(False)
            self.busyMessage.emit("", None)
            if self.matrix is not matrix:
                return
            matrix.remember_grant_privileges(results)
            if self._state is not SessionState.READY:
                self.statusMessage.emit(self.edit_blocked_reason(), STATUS_MS)
                return
            self._finish_stage(items, label, on_done)

        def failed(error: BaseException) -> None:
            self._set_staging_busy(False)
            self.busyMessage.emit("", None)
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            else:
                self.statusMessage.emit(f"Couldn't check your privileges: {error}. Nothing was staged.", 0)

        self.worker.submit("stage-privileges", lambda _ctx: db_permissions.check_grant_privileges(conn, targets), done, failed)

    def _finish_stage(
        self,
        items: list[tuple[CellRef, PermissionState]],
        label: str | None,
        on_done: Callable[[int], None] | None,
    ) -> None:
        matrix = self.matrix
        index = matrix.index
        allowed: list[tuple[CellRef, PermissionState]] = []
        denied: list[StagedChange] = []
        for cell, state in items:
            if (
                state is PermissionState.GRANT
                and cell_code(index.row_state(cell.p, cell.o), cell.perm) != STATE_GRANT
                and matrix.known_grant_privilege(cell) is False
            ):
                denied.append(self._staged_change(cell, state))
            else:
                allowed.append((cell, state))
        result = matrix.stage_states(allowed, label)
        if result.group is not None:
            self.statusMessage.emit(result.group.label, STATUS_SHORT_MS)
            self.announce.emit(result.group.label)
        if denied:
            self.stagingDenied.emit(denied)
        if on_done is not None:
            on_done(result.changed)

    def _staged_change(self, cell: CellRef, state: PermissionState) -> StagedChange:
        index = self.matrix.index
        obj = index.objects[cell.o]
        return StagedChange(
            user_login=index.principals[cell.p].login_name,
            schema_name=obj.schema_name,
            object_name=obj.object_name,
            permission_type=PERMS[cell.perm],
            previous_state=index.cell(cell.p, cell.o, cell.perm).committed,
            new_state=state,
        )

    def _set_staging_busy(self, busy: bool) -> None:
        if busy != self._staging_busy:
            self._staging_busy = busy
            self.stagingBusyChanged.emit(busy)

    def revert_cells(self, cells: Iterable[CellRef], label: str | None = None) -> int:
        """Set cells back to their committed state as one undo step. Returns cells changed."""
        if not self.can_edit:
            self.statusMessage.emit(self.edit_blocked_reason(), STATUS_SHORT_MS)
            return 0
        result = self.matrix.revert(cells, label)
        if result.group is not None:
            self.statusMessage.emit(result.group.label, STATUS_SHORT_MS)
            self.announce.emit(result.group.label)
        return result.changed

    # --- Discard, undo, redo, revert ----------------------------------------------

    def discard_all(self, confirmed: bool = False) -> None:
        """Discard every staged change (asks for confirmation at 5 or more)."""
        count = self.staged_count
        if count == 0:
            self.statusMessage.emit("No staged changes to discard", STATUS_SHORT_MS)
            return
        if self._state is SessionState.COMMITTING:
            self.statusMessage.emit("Wait for the commit to finish", STATUS_SHORT_MS)
            return
        if count >= DISCARD_CONFIRM_AT and not confirmed:
            self.discardConfirmationRequested.emit(count)
            return
        self.matrix.cancel()
        self.statusMessage.emit(f"Discarded {count:,} changes", STATUS_MS)

    def undo(self) -> None:
        """Undo the last staging action."""
        if not self.can_undo:
            self.statusMessage.emit("Nothing to undo", STATUS_SHORT_MS)
            return
        group = self.matrix.undo()
        self.statusMessage.emit(f"Undone: {group.label}", STATUS_SHORT_MS)
        self.announce.emit(f"Undone: {group.label}")

    def redo(self) -> None:
        """Redo the last undone action."""
        if not self.can_redo:
            self.statusMessage.emit("Nothing to redo", STATUS_SHORT_MS)
            return
        group = self.matrix.redo()
        self.statusMessage.emit(f"Redone: {group.label}", STATUS_SHORT_MS)
        self.announce.emit(f"Redone: {group.label}")

    def cell_for_change(self, change: StagedChange) -> CellRef | None:
        """Return the matrix cell for a staged change, or None if it no longer exists."""
        if self.matrix is None:
            return None
        index = self.matrix.index
        p = index.principal_index(change.user_login)
        o = index.object_index(change.schema_name, change.object_name)
        if p is None or o is None:
            return None
        return CellRef(p, o, PERM_INDEX[change.permission_type])

    def revert_change(self, change: StagedChange) -> None:
        """Undo one staged change (pending tray). Recorded as its own undo step."""
        if self._state is SessionState.COMMITTING:
            return
        cell = self.cell_for_change(change)
        if cell is None:
            return
        self.matrix.revert([cell], label=f"Undo {describe_change(change)}")

    def revert_changes(self, changes: list[StagedChange], label: str) -> None:
        """Undo several staged changes as one undo step (e.g. "Discard failed")."""
        cells = [cell for cell in (self.cell_for_change(c) for c in changes) if cell is not None]
        if cells and self.matrix is not None:
            self.matrix.revert(cells, label=label)

    def reveal(self, change: StagedChange) -> None:
        """Ask the matrix view to show a staged change's cell."""
        cell = self.cell_for_change(change)
        if cell is not None:
            self.revealRequested.emit(cell)

    # --- Connection health -----------------------------------------------------------

    def _on_heartbeat(self) -> None:
        if self._conn is None or not self.worker.is_idle():
            return  # a running job proves the connection or fails on its own
        conn = self._conn

        def ping(_ctx):
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()

        def failed(error: BaseException) -> None:
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            else:
                logger.warning("Heartbeat failed: %s", error)

        self.worker.submit("heartbeat", ping, on_error=failed, coalesce=True)

    def _connection_lost(self, error: BaseException) -> None:
        if self._state is SessionState.OFFLINE:
            return
        logger.warning("Connection lost: %s", error)
        self._heartbeat.stop()
        conn, self._conn = self._conn, None
        if conn is not None:
            self.worker.submit("close-lost", lambda _ctx: conn.close(), on_error=lambda _e: None)
        self.busyMessage.emit("", None)
        self._set_state(SessionState.OFFLINE)
        staged = self.staged_count
        self.statusMessage.emit(f"Connection lost. {staged:,} staged changes are kept.", 0)
        self.announce.emit("Connection to the database was lost")
        self.connectionLost.emit(str(error), staged)

    def _on_unhandled_job_error(self, name: str, error: BaseException) -> None:
        if db_connection.is_connection_error(error):
            self._connection_lost(error)
        else:
            self.statusMessage.emit(f"{name} failed: {error}", STATUS_MS)

    # --- Settings ------------------------------------------------------------------

    def save_settings(self, config: Configuration) -> str | None:
        """
        Save config and connect with it.

        Returns:
            str | None: Error message if the config is invalid or can't be saved
        """
        errors = config.validate()
        if errors:
            return "; ".join(errors)
        error = config_service.save_config(config)
        if error:
            return error
        self.connect(config)
        return None

    def test_connection(self, config: Configuration, callback: Callable[[bool, str], None]) -> JobHandle:
        """Test config on its own short-lived connection; callback(success, message) on the UI thread."""
        return run_detached(
            "test-connection",
            lambda _ctx: db_connection.test_connection(config),
            on_done=lambda result: callback(*result),
            on_error=lambda error: callback(False, f"Connection failed: {error}"),
        )

    # --- Audit ------------------------------------------------------------------------

    def fetch_audit(
        self,
        filters: dict,
        callback: Callable[[AuditResult | None, str | None], None],
    ) -> JobHandle | None:
        """
        Fetch audit entries on the worker. callback(result, error) runs on the UI thread.

        Args:
            filters: start_date, end_date, affected_user_contains, object_search, action
        """
        if self._conn is None or self.config is None:
            callback(None, "Not connected")
            return None
        conn = self._conn
        schema = self.config.schema
        keys = ("start_date", "end_date", "affected_user_contains", "object_search", "action")
        query = {k: filters[k] for k in keys if filters.get(k)}

        def job(_ctx) -> AuditResult:
            entries = db_audit.fetch_audit_entries(conn, schema, limit=AUDIT_FETCH_LIMIT, **query)
            if len(entries) < AUDIT_FETCH_LIMIT:
                return AuditResult(entries, len(entries), False)
            total = db_audit.get_audit_entry_count(conn, schema, **query)
            return AuditResult(entries, total, total > len(entries))

        def failed(error: BaseException) -> None:
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            callback(None, str(error))

        return self.worker.submit("audit", job, lambda result: callback(result, None), failed, coalesce=True)

    # --- Export ---------------------------------------------------------------------

    def estimate_export_rows(self, include_none: bool) -> int:
        """Rows a permissions export would write."""
        if self.matrix is None:
            return 0
        index = self.matrix.index
        if include_none:
            return sum(m.bit_count() for m in index.object_applicable) * len(index.principals)
        return sum(1 for _ in index.iter_explicit(effective=True))

    def export_permissions(
        self,
        path: str,
        include_none: bool,
        callback: Callable[[str | None], None],
    ) -> JobHandle | None:
        """Write the permission matrix to CSV on a background thread. callback(error) on the UI thread."""
        if self.matrix is None:
            callback("No permissions are loaded")
            return None
        frozen = self.matrix.index.freeze()

        def job(ctx):
            return export_service.export_permissions_from_index(
                path,
                frozen,
                include_none=include_none,
                progress_callback=lambda n, total: ctx.report((n, total)),
                cancel=ctx.cancel_event,
            )

        def progress(value) -> None:
            written, total = value
            self.busyMessage.emit(f"Exporting… {written:,} of {total:,} rows", (written, max(total, 1)))

        def done(error: str | None) -> None:
            self._export_handle = None
            self.busyMessage.emit("", None)
            callback(error)

        def failed(error: BaseException) -> None:
            self._export_handle = None
            self.busyMessage.emit("", None)
            callback(str(error))

        self.busyMessage.emit("Exporting permissions…", None)
        self._export_handle = run_detached("export-permissions", job, done, failed, progress)
        return self._export_handle

    def cancel_export(self) -> None:
        if self._export_handle is not None:
            self._export_handle.cancel()

    def export_audit(
        self, path: str, entries: list[AuditEntry], callback: Callable[[str | None], None]
    ) -> JobHandle:
        """Write audit entries to CSV on a background thread. callback(error) on the UI thread."""
        return run_detached(
            "export-audit",
            lambda _ctx: export_service.export_audit_csv(path, entries),
            on_done=callback,
            on_error=lambda error: callback(str(error)),
        )

    # --- Tags -----------------------------------------------------------------------

    def save_tags(self) -> str | None:
        """Save tags.json and refresh the matrix's tag indexes. Returns an error message or None."""
        error = self.tag_store.save()
        if self.matrix is not None:
            self.matrix.set_tag_store(self.tag_store)
        self.tagsChanged.emit()
        if error:
            logger.error("Saving tags failed: %s", error)
        return error

    # --- Object descriptions (FR-023) ------------------------------------------------

    def cached_description(self, o: int) -> tuple[bool, str | None]:
        """Return (known, text) for object o's description from this session's cache."""
        obj = self.matrix.index.objects[o]
        key = (obj.schema_name, obj.object_name)
        return (key in self._descriptions, self._descriptions.get(key))

    def load_description(self, o: int, callback: Callable[[str | None, str | None], None]) -> None:
        """
        Load object o's MS_Description on the worker (cached for the session).

        callback(text, error) runs on the UI thread. Only the latest queued request
        runs, so moving quickly through objects doesn't queue a query per object.
        """
        if self.matrix is None:
            callback(None, "No data loaded")
            return
        obj = self.matrix.index.objects[o]
        key = (obj.schema_name, obj.object_name)
        if key in self._descriptions:
            callback(self._descriptions[key], None)
            return
        if self._conn is None:
            callback(None, "Not connected")
            return
        conn = self._conn

        def done(text: str | None) -> None:
            self._descriptions[key] = text
            callback(text, None)

        def failed(error: BaseException) -> None:
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            callback(None, str(error))

        self.worker.submit(
            "description",
            lambda _ctx: db_objects.load_object_description(conn, *key),
            done,
            failed,
            coalesce=True,
        )

    def save_description(self, o: int, text: str, callback: Callable[[str | None], None]) -> None:
        """
        Save object o's description now (not staged, not audited). callback(error) on the UI thread.

        An empty text removes the description.
        """
        errors = validate_description(text)
        if errors:
            callback("; ".join(errors))
            return
        if self.matrix is None or self._conn is None or self._state is not SessionState.READY:
            callback("Not connected. Reconnect to save the description.")
            return
        obj = self.matrix.index.objects[o]
        key = (obj.schema_name, obj.object_name)
        object_type = obj.object_type
        conn = self._conn
        value = text.strip() or None

        def job(_ctx) -> None:
            try:
                db_objects.save_object_description(conn, key[0], key[1], value, object_type)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        def done(_result) -> None:
            self._descriptions[key] = value
            self.statusMessage.emit(f"Saved the description of {key[0]}.{key[1]}", STATUS_SHORT_MS)
            callback(None)

        def failed(error: BaseException) -> None:
            if db_connection.is_connection_error(error):
                self._connection_lost(error)
            callback(str(error))

        self.worker.submit("save-description", job, done, failed)

    # --- Shutdown ---------------------------------------------------------------------

    def close(self, wait_ms: int = 5000) -> str | None:
        """
        Stop timers, close the connection and stop the worker.

        Returns:
            str | None: Error from saving tags, if any
        """
        self._shutting_down = True
        self._heartbeat.stop()
        self._announce_timer.stop()
        error = self.tag_store.save()
        conn, self._conn = self._conn, None
        if conn is not None:
            self.worker.submit("close", lambda _ctx: conn.close(), on_error=lambda _e: None)
        self.worker.wait_idle(wait_ms / 1000)
        self.worker.shutdown(wait_ms)
        return error

    @property
    def commit_running(self) -> bool:
        return self._state is SessionState.COMMITTING


__all__ = [
    "AuditResult",
    "CommitReport",
    "LoadSummary",
    "RestageReport",
    "Session",
    "SessionState",
    "describe_change",
]
