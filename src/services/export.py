"""
CSV export service for Bifrost.

This module provides functions to export the permission matrix and audit log
to CSV format for reporting and external analysis.

Exports run without blocking the UI thread (called from background worker).

Usage:
    from src.services.export import export_permissions_csv, export_audit_csv

    # Export permission matrix
    export_permissions_csv(
        file_path="permissions_report.csv",
        users=users,
        objects=objects,
        assignments=assignments
    )

    # Export audit log
    export_audit_csv(
        file_path="audit_log.csv",
        entries=audit_entries
    )
"""

import csv
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from src.models.user import DatabaseUser
from src.models.db_object import DatabaseObject
from src.models.permission import CODE_STATES, PermissionAssignment, PermissionType
from src.models.audit_entry import AuditEntry
from src.services.matrix_index import PERMS, cell_code, diff_mask

if TYPE_CHECKING:
    from src.services.matrix_index import PermissionIndex


def export_permissions_csv(
    file_path: str | Path,
    users: list[DatabaseUser],
    objects: list[DatabaseObject],
    assignments: dict[tuple, PermissionAssignment],
    include_none: bool = False,
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Export the permission matrix to a CSV file.

    Args:
        file_path: Path to the output CSV file
        users: List of database users
        objects: List of database objects
        assignments: Dictionary of permission assignments keyed by cell_key
        include_none: Whether to include NONE state rows (default False)
        progress_callback: Optional callback(current, total) for progress reporting

    Returns:
        Optional[str]: Error message if export fails, None if successful

    CSV Columns:
        User, Schema, Object, ObjectType, Permission, State, HasStagedChange

    Example:
        User,Schema,Object,ObjectType,Permission,State,HasStagedChange
        alice,dbo,Orders,TABLE,SELECT,GRANT,False
        alice,dbo,Orders,TABLE,INSERT,DENY,True
    """
    try:
        file_path = Path(file_path)

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculate total rows for progress
        total_rows = 0
        for user in users:
            for obj in objects:
                for perm_type in PermissionType:
                    if obj.supports_permission(perm_type):
                        total_rows += 1

        current_row = 0

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(
                [
                    "User",
                    "Schema",
                    "Object",
                    "ObjectType",
                    "Permission",
                    "State",
                    "HasStagedChange",
                ]
            )

            # Write data rows
            for user in users:
                for obj in objects:
                    for perm_type in PermissionType:
                        if not obj.supports_permission(perm_type):
                            continue

                        cell_key = (user.login_name, obj.schema_name, obj.object_name, perm_type)
                        assignment = assignments.get(cell_key)

                        if assignment:
                            state = assignment.effective_state.value
                            has_staged = assignment.has_pending_change
                        else:
                            state = "NONE"
                            has_staged = False

                        # Skip NONE states if not included
                        if not include_none and state == "NONE":
                            current_row += 1
                            if progress_callback:
                                progress_callback(current_row, total_rows)
                            continue

                        writer.writerow(
                            [
                                user.login_name,
                                obj.schema_name,
                                obj.object_name,
                                obj.object_type.value,
                                perm_type.value,
                                state,
                                has_staged,
                            ]
                        )

                        current_row += 1
                        if progress_callback:
                            progress_callback(current_row, total_rows)

        return None

    except PermissionError:
        return f"Permission denied writing to {file_path}"
    except Exception as e:
        return f"Failed to export permissions: {str(e)}"


# Report export progress every this many rows
EXPORT_PROGRESS_EVERY = 50_000


def export_permissions_from_index(
    file_path: str | Path,
    index: "PermissionIndex",
    include_none: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> str | None:
    """
    Export the permission matrix from a PermissionIndex to a CSV file.

    Same columns and row order as export_permissions_csv(), but reads packed
    rows directly, so it stays fast for large databases.

    Args:
        file_path: Path to the output CSV file
        index: Permission index to export (effective state: staged over committed)
        include_none: Also write cells with no permission (FR-015 full export).
            On a large database this is principals × objects × ~7 rows (can be
            hundreds of millions), so callers should warn before using it.
        progress_callback: Optional callback(rows_written, total_rows), called
            every EXPORT_PROGRESS_EVERY rows and at the end
        cancel: Optional event; when set, the export stops and the partial file is deleted

    Returns:
        Optional[str]: Error message if the export fails or is cancelled, None if successful

    Note:
        Do not pass an index that another thread may modify while this runs.
    """
    file_path = Path(file_path)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if include_none:
            applicable_cells = sum(mask.bit_count() for mask in index.object_applicable)
            total_rows = applicable_cells * len(index.principals)
            cells = index.iter_all_cells(effective=True)
        else:
            rows = set(index.committed) | set(index.staged)
            total_rows = sum(
                diff_mask(index.row_state(p, o), 0).bit_count() for p, o in rows
            )
            cells = index.iter_explicit(effective=True)

        principals = index.principals
        objects = index.objects
        committed_row = index.committed_row
        written = 0

        with open(file_path, "w", newline="", encoding="utf-8", buffering=1 << 20) as f:
            writer = csv.writer(f)
            writer.writerow(
                ["User", "Schema", "Object", "ObjectType", "Permission", "State", "HasStagedChange"]
            )
            for p, o, perm_idx, code in cells:
                obj = objects[o]
                committed_code = cell_code(committed_row(p, o), perm_idx)
                writer.writerow(
                    [
                        principals[p].login_name,
                        obj.schema_name,
                        obj.object_name,
                        obj.object_type.value,
                        PERMS[perm_idx].value,
                        CODE_STATES[code].value,
                        committed_code != code,
                    ]
                )
                written += 1
                if written % EXPORT_PROGRESS_EVERY == 0:
                    if cancel is not None and cancel.is_set():
                        break
                    if progress_callback:
                        progress_callback(written, total_rows)

        if cancel is not None and cancel.is_set():
            file_path.unlink(missing_ok=True)
            return "Export cancelled"
        if progress_callback:
            progress_callback(written, total_rows)
        return None

    except PermissionError:
        return f"Permission denied writing to {file_path}"
    except Exception as e:
        return f"Failed to export permissions: {str(e)}"


def export_audit_csv(
    file_path: str | Path,
    entries: list[AuditEntry],
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Export the audit log to a CSV file.

    Args:
        file_path: Path to the output CSV file
        entries: List of audit entries to export
        progress_callback: Optional callback(current, total) for progress reporting

    Returns:
        Optional[str]: Error message if export fails, None if successful

    CSV Columns:
        ID, Administrator, AffectedUser, Schema, Object, Permission,
        Action, PreviousState, NewState, ChangedAt, Explanation

    Example:
        ID,Administrator,AffectedUser,Schema,Object,Permission,Action,PreviousState,NewState,ChangedAt,Explanation
        1,DOMAIN\\admin,alice,dbo,Orders,SELECT,GRANT,NONE,GRANT,2024-01-15T10:30:00Z,"GRANT SELECT on dbo.Orders to alice"
    """
    try:
        file_path = Path(file_path)

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        total_rows = len(entries)
        current_row = 0

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(
                [
                    "ID",
                    "Administrator",
                    "AffectedUser",
                    "Schema",
                    "Object",
                    "Permission",
                    "Action",
                    "PreviousState",
                    "NewState",
                    "ChangedAt",
                    "Explanation",
                ]
            )

            # Write data rows
            for entry in entries:
                # Format timestamp as ISO 8601
                changed_at_str = entry.changed_at.isoformat() if entry.changed_at else ""

                writer.writerow(
                    [
                        entry.id,
                        entry.administrator,
                        entry.affected_user,
                        entry.schema_name,
                        entry.object_name,
                        entry.permission_type,
                        entry.action,
                        entry.previous_state,
                        entry.new_state,
                        changed_at_str,
                        entry.explanation,
                    ]
                )

                current_row += 1
                if progress_callback:
                    progress_callback(current_row, total_rows)

        return None

    except PermissionError:
        return f"Permission denied writing to {file_path}"
    except Exception as e:
        return f"Failed to export audit log: {str(e)}"


def get_suggested_filename(export_type: str, database: str) -> str:
    """
    Generate a suggested filename for an export.

    Args:
        export_type: Type of export ("permissions" or "audit")
        database: Database name

    Returns:
        str: Suggested filename (e.g., "Bifrost_permissions_MyDB_2024-01-15.csv")

    Example:
        >>> get_suggested_filename("permissions", "MyAppDB")
        "Bifrost_permissions_MyAppDB_2024-01-15.csv"
    """
    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"Bifrost_{export_type}_{database}_{date_str}.csv"
