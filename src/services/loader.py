"""
Matrix loading for Bifrost.

fetch_snapshot() reads everything the permission matrix needs from SQL Server
and returns it as an immutable MatrixSnapshot. It only does DB I/O, so it is
safe to run on a worker thread; the caller then hands the snapshot to
PermissionMatrix.apply_snapshot() on the UI thread.

Usage:
    snapshot = fetch_snapshot(conn, progress=print_progress)
    matrix.apply_snapshot(snapshot)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from src.db import objects as db_objects
from src.db import permissions as db_permissions
from src.db import users as db_users
from src.db.connection import get_current_user
from src.db.permissions import LoadCancelledError

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    import pyodbc

    from src.models.db_object import DatabaseObject
    from src.models.user import DatabaseUser

__all__ = ["LoadCancelledError", "LoadProgress", "MatrixSnapshot", "fetch_snapshot"]

STAGE_COUNT = 4
# How often (in rows) to report progress while reading permissions
PROGRESS_EVERY_ROWS = 10_000


@dataclass(frozen=True)
class MatrixSnapshot:
    """
    Everything loaded from the database for one matrix load.

    Attributes:
        principals: Database principals, ordered by name
        objects: Database objects, ordered by schema then name
        permission_rows: (principal_id, object_id, permission index, state code)
        current_user: SYSTEM_USER at load time (recorded in audit entries)
        privileged: True if the account is sysadmin, db_owner or has CONTROL on the database
        loaded_at: When the load finished (UTC)
        timings: Seconds spent in each stage, for diagnostics
    """

    principals: tuple[DatabaseUser, ...]
    objects: tuple[DatabaseObject, ...]
    permission_rows: tuple[tuple[int, int, int, int], ...]
    current_user: str = ""
    privileged: bool = False
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadProgress:
    """
    Progress report from fetch_snapshot().

    Attributes:
        stage: Which stage is running
        stage_number: 1-based stage number
        stage_count: Total stages (4)
        rows: Rows fetched so far in this stage
        message: Human-readable status, e.g. "Loading permissions… 120,000 rows"
    """

    stage: Literal["principals", "objects", "permissions", "privileges"]
    stage_number: int
    stage_count: int
    rows: int
    message: str


def fetch_snapshot(
    conn: pyodbc.Connection,
    progress: Callable[[LoadProgress], None] | None = None,
    cancel: threading.Event | None = None,
) -> MatrixSnapshot:
    """
    Read principals, objects, permissions and privilege flags from the database.

    Args:
        conn: Active database connection (read-only use; no commit or rollback)
        progress: Optional callback for progress reports. May be called from a
            worker thread, so it must not touch UI objects directly.
        cancel: Optional event checked between stages and between fetch batches

    Returns:
        MatrixSnapshot: Immutable data for PermissionMatrix.apply_snapshot()

    Raises:
        LoadCancelledError: If cancel is set
        pyodbc.Error: If a query fails
    """
    timings: dict[str, float] = {}

    def report(stage, number: int, rows: int, message: str) -> None:
        if progress is not None:
            progress(LoadProgress(stage, number, STAGE_COUNT, rows, message))

    def check_cancel() -> None:
        if cancel is not None and cancel.is_set():
            raise LoadCancelledError("Loading was cancelled")

    check_cancel()
    report("principals", 1, 0, "Loading principals…")
    started = time.perf_counter()
    principals = tuple(db_users.fetch_all_users(conn))
    timings["principals"] = time.perf_counter() - started

    check_cancel()
    report("objects", 2, 0, f"Loading objects… ({len(principals):,} principals loaded)")
    started = time.perf_counter()
    objects = tuple(db_objects.fetch_all_objects(conn))
    timings["objects"] = time.perf_counter() - started

    check_cancel()
    report("permissions", 3, 0, "Loading permissions…")
    started = time.perf_counter()
    last_reported = 0

    def on_batch(total: int) -> None:
        nonlocal last_reported
        if total - last_reported >= PROGRESS_EVERY_ROWS:
            last_reported = total
            report("permissions", 3, total, f"Loading permissions… {total:,} rows")

    permission_rows = tuple(
        db_permissions.fetch_permission_rows(conn, on_batch=on_batch, cancel=cancel)
    )
    timings["permissions"] = time.perf_counter() - started

    check_cancel()
    report("privileges", 4, len(permission_rows), "Checking your privileges…")
    started = time.perf_counter()
    current_user = get_current_user(conn)
    privileged = db_permissions.fetch_privilege_flags(conn)
    timings["privileges"] = time.perf_counter() - started

    return MatrixSnapshot(
        principals=principals,
        objects=objects,
        permission_rows=permission_rows,
        current_user=current_user,
        privileged=privileged,
        timings=timings,
    )
