"""
Bulk-change helpers for the matrix view: presets, "Make like…" and the
summaries shown before staging many cells (FR-030).

Everything here is plain Python over a PermissionIndex, so it is cheap to test
and never touches widgets or the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models.db_object import ObjectType
from src.models.permission import (
    CODE_STATES,
    STATE_CODES,
    STATE_DENY,
    STATE_GRANT,
    STATE_NONE,
    PermissionState,
    PermissionType,
)
from src.services.matrix import CellRef
from src.services.matrix_index import PERM_COUNT, PERM_INDEX, PERMS, cell_code

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.services.matrix_index import PermissionIndex

SELECTION_LIMIT = 20_000  # cells per action (decision 2); group actions aren't limited
CONFIRM_AT = 5  # this many changes or more ask first (FR-030)

Item = tuple[CellRef, PermissionState]

_T, _V, _P, _F = ObjectType.TABLE, ObjectType.VIEW, ObjectType.PROCEDURE, ObjectType.FUNCTION
_DML = frozenset({PermissionType.SELECT, PermissionType.INSERT, PermissionType.UPDATE, PermissionType.DELETE})
_EXEC = frozenset({PermissionType.EXECUTE})

# Preset name -> object type -> permissions to GRANT. Presets only ever grant.
PRESETS: dict[str, dict[ObjectType, frozenset[PermissionType]]] = {
    "Read": {_T: frozenset({PermissionType.SELECT}), _V: frozenset({PermissionType.SELECT}), _F: _EXEC},
    "Read/write": {_T: _DML, _V: _DML},
    "Execute": {_P: _EXEC, _F: _EXEC},
    "Full DML": {_T: _DML | {PermissionType.REFERENCES}, _V: _DML | {PermissionType.REFERENCES}},
    "View definition only": {t: frozenset({PermissionType.VIEW_DEFINITION}) for t in ObjectType},
}

_VERB = {STATE_GRANT: "Grant", STATE_DENY: "Deny", STATE_NONE: "Revoke"}


@dataclass(frozen=True)
class BulkSummary:
    """
    What staging a list of items would do, computed without staging.

    Attributes:
        changed: Cells whose state would change
        unchanged: Cells already in the target state
        skipped: Cells whose permission doesn't apply to the object
        grants, denies, revokes: Changed cells by target state
    """

    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    grants: int = 0
    denies: int = 0
    revokes: int = 0

    def counts_text(self) -> str:
        """E.g. "231 will change · 16 already set · 3 don't apply (skipped)"."""
        parts = [f"{self.changed:,} will change"]
        if self.unchanged:
            parts.append(f"{self.unchanged:,} already set")
        if self.skipped:
            parts.append(f"{self.skipped:,} don't apply (skipped)")
        return " · ".join(parts)

    def split_text(self) -> str:
        """E.g. "52 grants, 1 deny, 4 revokes" (only the non-zero kinds)."""
        parts = []
        for count, word in ((self.grants, "grant"), (self.denies, "deny"), (self.revokes, "revoke")):
            if count:
                plural = "denies" if word == "deny" else f"{word}s"
                parts.append(f"{count:,} {word if count == 1 else plural}")
        return ", ".join(parts) or "no changes"


def items_for(cells: Iterable[CellRef], state: PermissionState) -> list[Item]:
    """Pair every cell with the same target state."""
    return [(cell, state) for cell in cells]


def revert_items(index: PermissionIndex, cells: Iterable[CellRef]) -> list[Item]:
    """Pair every cell with its committed state ("Revert to committed")."""
    committed = index.committed_row
    return [(c, CODE_STATES[cell_code(committed(c.p, c.o), c.perm)]) for c in cells]


def cycle_state(index: PermissionIndex, cell: CellRef) -> PermissionState:
    """Next state for a cell: none -> GRANT -> DENY -> none."""
    code = cell_code(index.row_state(cell.p, cell.o), cell.perm)
    return {STATE_NONE: PermissionState.GRANT, STATE_GRANT: PermissionState.DENY}.get(code, PermissionState.NONE)


def summarize(index: PermissionIndex, items: Iterable[Item]) -> BulkSummary:
    """Count what staging items would change (FR-030 counts "changes", not selected cells)."""
    changed = unchanged = skipped = grants = denies = revokes = 0
    applicable = index.object_applicable
    row_state = index.row_state
    for cell, state in items:
        if not applicable[cell.o] & (1 << cell.perm):
            skipped += 1
            continue
        code = STATE_CODES[state]
        if cell_code(row_state(cell.p, cell.o), cell.perm) == code:
            unchanged += 1
            continue
        changed += 1
        if code == STATE_GRANT:
            grants += 1
        elif code == STATE_DENY:
            denies += 1
        else:
            revokes += 1
    return BulkSummary(changed, unchanged, skipped, grants, denies, revokes)


def describe_scope(index: PermissionIndex, cells: Iterable[CellRef]) -> str:
    """
    One-line scope for a set of cells.

    Returns:
        str: "on 247 objects in sales for CORP\\jsmith", "on 30 objects for CORP\\jsmith",
        "for 38 principals on sales.Orders" or "on 12 cells"
    """
    cells = list(cells)
    principals = {c.p for c in cells}
    objects = {c.o for c in cells}
    if len(principals) == 1:
        login = index.principals[next(iter(principals))].login_name
        schemas = {index.objects[o].schema_name for o in objects}
        if len(objects) == 1:
            return f"on {index.objects[next(iter(objects))].full_name} for {login}"
        if len(schemas) == 1:
            return f"on {len(objects):,} objects in {next(iter(schemas))} for {login}"
        return f"on {len(objects):,} objects for {login}"
    if len(objects) == 1:
        return f"for {len(principals):,} principals on {index.objects[next(iter(objects))].full_name}"
    return f"on {len(cells):,} cells"


def describe_action(index: PermissionIndex, items: list[Item]) -> str:
    """
    Sentence for an action, e.g. "Grant SELECT on 247 objects in sales for CORP\\jsmith".

    Mixed target states give "Change 57 permissions …".
    """
    states = {STATE_CODES[s] for _c, s in items}
    perms = {c.perm for c, _s in items}
    scope = describe_scope(index, (c for c, _s in items))
    perm_text = PERMS[next(iter(perms))].value if len(perms) == 1 else f"{len(perms)} permissions"
    if len(states) == 1:
        return f"{_VERB[next(iter(states))]} {perm_text} {scope}"
    return f"Change {perm_text} {scope}"


def preset_items(index: PermissionIndex, rows: Iterable[tuple[int, int]], preset: str) -> list[Item]:
    """
    GRANT items for a preset on (p, o) rows. Other permissions are left alone.

    Raises:
        KeyError: Unknown preset
    """
    by_type = PRESETS[preset]
    items: list[Item] = []
    objects = index.objects
    applicable = index.object_applicable
    for p, o in rows:
        perms = by_type.get(objects[o].object_type, ())
        for perm in perms:
            perm_idx = PERM_INDEX[perm]
            if applicable[o] & (1 << perm_idx):
                items.append((CellRef(p, o, perm_idx), PermissionState.GRANT))
    return items


def make_like_items(
    index: PermissionIndex, source_p: int, target_p: int, objects: Iterable[int]
) -> list[Item]:
    """
    Items that give target_p the same effective state as source_p on objects.

    Every applicable cell is included (GRANT, DENY or none), so this can revoke
    and deny; summarize() shows the split before staging.
    """
    items: list[Item] = []
    applicable = index.object_applicable
    row_state = index.row_state
    for o in objects:
        source = row_state(source_p, o)
        mask = applicable[o]
        for perm_idx in range(PERM_COUNT):
            if mask & (1 << perm_idx):
                items.append((CellRef(target_p, o, perm_idx), CODE_STATES[cell_code(source, perm_idx)]))
    return items
