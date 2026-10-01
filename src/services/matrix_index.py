"""
Integer-indexed permission store for Bifrost.

PermissionIndex holds every principal, object and explicit permission in a form
that is cheap to read at scale (hundreds of principals, tens of thousands of
objects). Principals and objects are addressed by their position in the index
(p and o). One (principal, object) pair is a "row"; its 8 permission cells are
packed into a single int:

    bits 0-7   GRANT mask  (bit i set -> PERMS[i] is GRANT)
    bits 8-15  DENY mask   (bit i set -> PERMS[i] is DENY)
    neither    NONE

Reading a row is one dict lookup with no allocation, which is what lets the UI
draw thousands of cells per frame.

Thread safety:
    Not thread-safe. Build and mutate on one thread (the UI thread). Code that
    runs on a worker thread must not read or write a PermissionIndex.

Usage:
    index = PermissionIndex.build(snapshot, tag_store)
    packed = index.row_state(p, o)
    if cell_code(packed, PERM_INDEX[PermissionType.SELECT]) == STATE_GRANT:
        ...
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from src.models.db_object import DatabaseObject, ObjectType
from src.models.permission import (
    CODE_STATES,
    PERMISSION_INDEX,
    PERMISSION_ORDER,
    STATE_DENY,
    STATE_GRANT,
    STATE_NONE,
    PermissionState,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from src.models.user import DatabaseUser
    from src.services.loader import MatrixSnapshot
    from src.services.tags import TagStore

PERMS = PERMISSION_ORDER
PERM_INDEX = PERMISSION_INDEX
PERM_COUNT = len(PERMS)
ALL_MASK = (1 << PERM_COUNT) - 1

# Bit i set = PERMS[i] applies to this object type (FR-001a). Derived from
# ObjectType.supports_permission so the two can never drift apart.
APPLICABLE_MASK: dict[ObjectType, int] = {
    object_type: sum(1 << i for i, perm in enumerate(PERMS) if object_type.supports_permission(perm))
    for object_type in ObjectType
}

# Order used when sorting objects by type
_OBJECT_TYPE_RANK = {object_type: rank for rank, object_type in enumerate(ObjectType)}


# --- Packed row helpers ---------------------------------------------------------


def cell_code(packed: int, perm_idx: int) -> int:
    """Return STATE_NONE, STATE_GRANT or STATE_DENY for one cell of a packed row."""
    if (packed >> perm_idx) & 1:
        return STATE_GRANT
    if (packed >> (perm_idx + 8)) & 1:
        return STATE_DENY
    return STATE_NONE


def with_cell(packed: int, perm_idx: int, code: int) -> int:
    """Return packed with one cell set to code (STATE_NONE, STATE_GRANT or STATE_DENY)."""
    grant_bit = 1 << perm_idx
    deny_bit = 1 << (perm_idx + 8)
    packed &= ~(grant_bit | deny_bit)
    if code == STATE_GRANT:
        packed |= grant_bit
    elif code == STATE_DENY:
        packed |= deny_bit
    return packed


def grant_mask(packed: int) -> int:
    """Return the 8-bit GRANT mask of a packed row."""
    return packed & ALL_MASK


def deny_mask(packed: int) -> int:
    """Return the 8-bit DENY mask of a packed row."""
    return (packed >> 8) & ALL_MASK


def diff_mask(a: int, b: int) -> int:
    """Return an 8-bit mask of the permissions whose state differs between two packed rows."""
    x = a ^ b
    return (x | (x >> 8)) & ALL_MASK


# --- Value types ---------------------------------------------------------------


@dataclass(frozen=True)
class RowCounts:
    """Cell counts for one principal or object, from the effective (staged-over-committed) state."""

    grants: int
    denies: int
    pending: int


@dataclass(frozen=True)
class CellView:
    """One cell's state. For tooltips and tests only; don't use in render loops."""

    effective: PermissionState
    committed: PermissionState
    pending: bool
    applicable: bool


@dataclass(frozen=True)
class SchemaSpan:
    """A run of objects from one schema: list positions [start, end) in an ordered object list."""

    schema: str
    start: int
    end: int


@dataclass(frozen=True)
class BuildStats:
    """What the index build skipped, for diagnostics."""

    permission_rows: int = 0
    skipped_unknown: int = 0
    skipped_not_applicable: int = 0


@dataclass(frozen=True)
class PrincipalQuery:
    """
    Filter and sort options for principals.

    Attributes:
        text: Whitespace-separated tokens; every token must appear in the login (case-insensitive)
        types: Principal types to include ("S", "U", "G"); empty = all
        tags: Casefolded tags; a principal must have all of them
        has_pending: Only principals with staged changes
        has_access_to_object: Object index; only principals with a non-empty row for it
        sort: "name", "type" or "grants" (most grants first)
        descending: Reverse the sort
    """

    text: str = ""
    types: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    has_pending: bool = False
    has_access_to_object: int | None = None
    sort: Literal["name", "type", "grants"] = "name"
    descending: bool = False


@dataclass(frozen=True)
class ObjectQuery:
    """
    Filter and sort options for objects.

    Attributes:
        text: Whitespace-separated tokens; every token must appear in "schema.name"
        schemas: Casefolded schema names to include; empty = all
        types: Object types to include; empty = all
        tags: Casefolded tags; an object must have all of them
        with_access_for: Principal index; only objects where that principal's row is non-empty
        pending_for: Principal index; only objects with staged changes for that principal
        sort: "schema_name" (default), "name" or "type"
        descending: Reverse the sort
    """

    text: str = ""
    schemas: frozenset[str] = frozenset()
    types: frozenset[ObjectType] = frozenset()
    tags: frozenset[str] = frozenset()
    with_access_for: int | None = None
    pending_for: int | None = None
    sort: Literal["schema_name", "name", "type"] = "schema_name"
    descending: bool = False


# --- Index ---------------------------------------------------------------------


@dataclass(eq=False)
class PermissionIndex:
    """
    In-memory permission store addressed by integer principal and object indexes.

    Build with PermissionIndex.build(). Only PermissionMatrix should call the
    write methods (set_effective, clear_staged, commit_rows).

    Invariants:
        - committed holds only rows with at least one GRANT or DENY
        - staged holds only rows whose effective state differs from committed
        - counts, membership sets and staged_cell_count always match committed + staged
    """

    principals: list[DatabaseUser] = field(default_factory=list)
    objects: list[DatabaseObject] = field(default_factory=list)
    principal_by_login: dict[str, int] = field(default_factory=dict)
    principal_by_id: dict[int, int] = field(default_factory=dict)
    object_by_name: dict[tuple[str, str], int] = field(default_factory=dict)
    object_by_id: dict[int, int] = field(default_factory=dict)
    object_applicable: list[int] = field(default_factory=list)
    committed: dict[tuple[int, int], int] = field(default_factory=dict)
    staged: dict[tuple[int, int], int] = field(default_factory=dict)
    objects_by_principal: list[set[int]] = field(default_factory=list)
    principals_by_object: list[set[int]] = field(default_factory=list)
    staged_objects_by_principal: list[set[int]] = field(default_factory=list)
    staged_cell_count: int = 0
    principal_search_key: list[str] = field(default_factory=list)
    object_search_key: list[str] = field(default_factory=list)
    object_order: list[int] = field(default_factory=list)
    schema_spans: list[SchemaSpan] = field(default_factory=list)
    principal_tags: list[frozenset[str]] = field(default_factory=list)
    object_tags: list[frozenset[str]] = field(default_factory=list)
    build_stats: BuildStats = field(default_factory=BuildStats)
    # Parallel count lists (faster than one object per principal/object)
    _p_grants: list[int] = field(default_factory=list)
    _p_denies: list[int] = field(default_factory=list)
    _p_pending: list[int] = field(default_factory=list)
    _o_grants: list[int] = field(default_factory=list)
    _o_denies: list[int] = field(default_factory=list)
    _o_pending: list[int] = field(default_factory=list)
    # Sort ranks: position of each principal/object in name order
    _principal_rank: list[int] = field(default_factory=list)
    _object_rank: list[int] = field(default_factory=list)
    _object_schema_key: list[str] = field(default_factory=list)
    _object_name_key: list[str] = field(default_factory=list)

    # --- Build -------------------------------------------------------------------

    @classmethod
    def build(cls, snapshot: MatrixSnapshot, tag_store: TagStore | None = None) -> PermissionIndex:
        """
        Build an index from a loaded snapshot.

        Args:
            snapshot: Principals, objects and permission rows from the loader
            tag_store: Local tags to attach (None = no tags)

        Returns:
            PermissionIndex: Ready to read; nothing staged

        Note:
            Permission rows for principals or objects not in the snapshot, or for
            permissions that don't apply to the object type, are skipped and
            counted in build_stats.
        """
        index = cls()
        principals = list(snapshot.principals)
        objects = list(snapshot.objects)
        index.principals = principals
        index.objects = objects
        p_count = len(principals)
        o_count = len(objects)

        index.principal_by_login = {u.login_name: p for p, u in enumerate(principals)}
        index.principal_by_id = {u.principal_id: p for p, u in enumerate(principals) if u.principal_id}
        index.object_by_name = {(o.schema_name, o.object_name): i for i, o in enumerate(objects)}
        index.object_by_id = {o.object_id: i for i, o in enumerate(objects) if o.object_id}
        index.object_applicable = [APPLICABLE_MASK[o.object_type] for o in objects]

        index.principal_search_key = [u.login_name.casefold() for u in principals]
        index._object_schema_key = [o.schema_name.casefold() for o in objects]
        index._object_name_key = [o.object_name.casefold() for o in objects]
        index.object_search_key = [o.full_name.casefold() for o in objects]

        principal_order = sorted(range(p_count), key=lambda p: (index.principal_search_key[p], p))
        index._principal_rank = [0] * p_count
        for rank, p in enumerate(principal_order):
            index._principal_rank[p] = rank

        schema_key = index._object_schema_key
        name_key = index._object_name_key
        index.object_order = sorted(range(o_count), key=lambda o: (schema_key[o], name_key[o], o))
        index._object_rank = [0] * o_count
        for rank, o in enumerate(index.object_order):
            index._object_rank[o] = rank
        index.schema_spans = index.group_by_schema(index.object_order)

        # Committed rows
        committed: dict[tuple[int, int], int] = {}
        principal_by_id = index.principal_by_id
        object_by_id = index.object_by_id
        applicable = index.object_applicable
        skipped_unknown = 0
        skipped_not_applicable = 0
        rows = snapshot.permission_rows
        for principal_id, object_id, perm_idx, code in rows:
            p = principal_by_id.get(principal_id)
            o = object_by_id.get(object_id)
            if p is None or o is None:
                skipped_unknown += 1
                continue
            bit = 1 << perm_idx
            if not applicable[o] & bit:
                skipped_not_applicable += 1
                continue
            key = (p, o)
            value = committed.get(key, 0)
            # GRANT sets the grant bit and clears the deny bit; DENY does the opposite
            value = (
                ((value & ~(bit << 8)) | bit) if code == STATE_GRANT else ((value & ~bit) | (bit << 8))
            )
            committed[key] = value
        index.committed = committed
        index.build_stats = BuildStats(
            permission_rows=len(rows),
            skipped_unknown=skipped_unknown,
            skipped_not_applicable=skipped_not_applicable,
        )

        # Counts and membership in one pass
        index._p_grants = [0] * p_count
        index._p_denies = [0] * p_count
        index._p_pending = [0] * p_count
        index._o_grants = [0] * o_count
        index._o_denies = [0] * o_count
        index._o_pending = [0] * o_count
        index.objects_by_principal = [set() for _ in range(p_count)]
        index.principals_by_object = [set() for _ in range(o_count)]
        index.staged_objects_by_principal = [set() for _ in range(p_count)]
        p_grants, p_denies = index._p_grants, index._p_denies
        o_grants, o_denies = index._o_grants, index._o_denies
        objects_by_principal = index.objects_by_principal
        principals_by_object = index.principals_by_object
        for (p, o), value in committed.items():
            grants = (value & ALL_MASK).bit_count()
            denies = (value >> 8).bit_count()
            p_grants[p] += grants
            p_denies[p] += denies
            o_grants[o] += grants
            o_denies[o] += denies
            objects_by_principal[p].add(o)
            principals_by_object[o].add(p)

        index.set_tags(tag_store)
        return index

    def freeze(self) -> PermissionIndex:
        """
        Return a read-only copy that is safe to read on another thread.

        The committed and staged dicts are copied; principals, objects and the
        other lists are shared, since they are not changed after build. Use it for
        exports and other background readers. Only read from the copy:
        row_state, committed_row, iter_explicit, iter_all_cells and the lists.
        """
        frozen = copy.copy(self)
        frozen.committed = dict(self.committed)
        frozen.staged = dict(self.staged)
        return frozen

    # --- Lookups -----------------------------------------------------------------

    def principal_index(self, login_name: str) -> int | None:
        """Return the index of a principal by login name, or None."""
        return self.principal_by_login.get(login_name)

    def object_index(self, schema_name: str, object_name: str) -> int | None:
        """Return the index of an object by schema and name, or None."""
        return self.object_by_name.get((schema_name, object_name))

    def principal_rank(self, p: int) -> int:
        """Return a principal's position in name order."""
        return self._principal_rank[p]

    def object_rank(self, o: int) -> int:
        """Return an object's position in schema, name order."""
        return self._object_rank[o]

    def is_applicable(self, o: int, perm_idx: int) -> bool:
        """Return True if permission perm_idx applies to object o."""
        return bool(self.object_applicable[o] & (1 << perm_idx))

    # --- Reads -------------------------------------------------------------------

    def row_state(self, p: int, o: int) -> int:
        """Return the effective packed state of a row (staged if any, else committed)."""
        key = (p, o)
        value = self.staged.get(key)
        if value is None:
            return self.committed.get(key, 0)
        return value

    def committed_row(self, p: int, o: int) -> int:
        """Return the committed packed state of a row."""
        return self.committed.get((p, o), 0)

    def pending_mask(self, p: int, o: int) -> int:
        """Return an 8-bit mask of the cells in a row that have staged changes."""
        key = (p, o)
        value = self.staged.get(key)
        if value is None:
            return 0
        return diff_mask(value, self.committed.get(key, 0))

    def cell(self, p: int, o: int, perm_idx: int) -> CellView:
        """Return one cell's state as a CellView (allocates; not for render loops)."""
        committed = cell_code(self.committed_row(p, o), perm_idx)
        effective = cell_code(self.row_state(p, o), perm_idx)
        return CellView(
            effective=CODE_STATES[effective],
            committed=CODE_STATES[committed],
            pending=effective != committed,
            applicable=self.is_applicable(o, perm_idx),
        )

    def principal_counts(self, p: int) -> RowCounts:
        """Return effective grant/deny counts and pending cells for a principal."""
        return RowCounts(self._p_grants[p], self._p_denies[p], self._p_pending[p])

    def object_pending(self, o: int) -> int:
        """Return the number of staged cells on object o (no allocation; for filters)."""
        return self._o_pending[o]

    def object_counts(self, o: int) -> RowCounts:
        """Return effective grant/deny counts and pending cells for an object."""
        return RowCounts(self._o_grants[o], self._o_denies[o], self._o_pending[o])

    # --- Writes (PermissionMatrix only) ------------------------------------------

    def set_effective(self, p: int, o: int, perm_idx: int, code: int) -> bool:
        """
        Set one cell's effective (staged) state.

        Args:
            p: Principal index
            o: Object index
            perm_idx: Permission index (PERM_INDEX)
            code: STATE_NONE, STATE_GRANT or STATE_DENY

        Returns:
            bool: True if the cell changed

        Raises:
            ValueError: If the permission doesn't apply to the object's type
        """
        if not self.object_applicable[o] & (1 << perm_idx):
            raise ValueError(
                f"{PERMS[perm_idx].value} does not apply to {self.objects[o].full_name}"
            )
        key = (p, o)
        committed = self.committed.get(key, 0)
        old_effective = self.staged.get(key, committed)
        new_effective = with_cell(old_effective, perm_idx, code)
        if new_effective == old_effective:
            return False
        self._set_row(p, o, committed, old_effective, committed, new_effective)
        return True

    def clear_staged(self) -> set[tuple[int, int]]:
        """Drop every staged change. Returns the rows that changed."""
        rows = set(self.staged)
        for p, o in rows:
            key = (p, o)
            committed = self.committed.get(key, 0)
            self._set_row(p, o, committed, self.staged[key], committed, committed)
        return rows

    def commit_rows(self, applied: Iterable[tuple[int, int, int, int]]) -> set[tuple[int, int]]:
        """
        Record cells as committed after they were applied to the database.

        Args:
            applied: (p, o, perm_idx, new_code) for each successfully applied cell

        Returns:
            set: Rows that changed
        """
        rows: set[tuple[int, int]] = set()
        for p, o, perm_idx, code in applied:
            key = (p, o)
            old_committed = self.committed.get(key, 0)
            old_effective = self.staged.get(key, old_committed)
            new_committed = with_cell(old_committed, perm_idx, code)
            self._set_row(p, o, old_committed, old_effective, new_committed, old_effective)
            rows.add(key)
        return rows

    def _set_row(
        self, p: int, o: int, old_committed: int, old_effective: int, new_committed: int, new_effective: int
    ) -> None:
        """Store a row's new committed and effective state and update every derived structure."""
        key = (p, o)

        grants_delta = (new_effective & ALL_MASK).bit_count() - (old_effective & ALL_MASK).bit_count()
        denies_delta = (new_effective >> 8).bit_count() - (old_effective >> 8).bit_count()
        pending_delta = (
            diff_mask(new_effective, new_committed).bit_count()
            - diff_mask(old_effective, old_committed).bit_count()
        )
        if grants_delta:
            self._p_grants[p] += grants_delta
            self._o_grants[o] += grants_delta
        if denies_delta:
            self._p_denies[p] += denies_delta
            self._o_denies[o] += denies_delta
        if pending_delta:
            self._p_pending[p] += pending_delta
            self._o_pending[o] += pending_delta
            self.staged_cell_count += pending_delta

        if new_committed:
            self.committed[key] = new_committed
        else:
            self.committed.pop(key, None)

        if new_effective != new_committed:
            self.staged[key] = new_effective
            self.staged_objects_by_principal[p].add(o)
        else:
            self.staged.pop(key, None)
            self.staged_objects_by_principal[p].discard(o)

        # A row stays "with access" while either side is non-empty, so a staged
        # revoke doesn't make the object vanish from an "only with access" list.
        if new_committed or new_effective:
            self.objects_by_principal[p].add(o)
            self.principals_by_object[o].add(p)
        else:
            self.objects_by_principal[p].discard(o)
            self.principals_by_object[o].discard(p)

    # --- Queries -----------------------------------------------------------------

    def query_principals(self, q: PrincipalQuery) -> list[int]:
        """Return principal indexes matching q, in display order."""
        candidates: Iterable[int]
        if q.has_access_to_object is not None:
            candidates = self.principals_by_object[q.has_access_to_object]
        else:
            candidates = range(len(self.principals))

        if q.types:
            principals = self.principals
            candidates = [p for p in candidates if principals[p].principal_type in q.types]
        if q.has_pending:
            pending = self._p_pending
            candidates = [p for p in candidates if pending[p]]
        if q.tags:
            tags = self.principal_tags
            candidates = [p for p in candidates if q.tags <= tags[p]]
        tokens = q.text.casefold().split()
        if tokens:
            keys = self.principal_search_key
            if len(tokens) == 1:
                token = tokens[0]
                candidates = [p for p in candidates if token in keys[p]]
            else:
                candidates = [p for p in candidates if all(t in keys[p] for t in tokens)]

        rank = self._principal_rank
        if q.sort == "type":
            principals = self.principals
            result = sorted(candidates, key=lambda p: (principals[p].principal_type, rank[p]))
        elif q.sort == "grants":
            grants = self._p_grants
            result = sorted(candidates, key=lambda p: (-grants[p], rank[p]))
        else:
            result = sorted(candidates, key=rank.__getitem__)
        if q.descending:
            result.reverse()
        return result

    def query_objects(self, q: ObjectQuery) -> list[int]:
        """Return object indexes matching q, in display order."""
        candidates: Iterable[int] | None = None
        if q.with_access_for is not None:
            candidates = self.objects_by_principal[q.with_access_for]
        if q.pending_for is not None:
            pending = self.staged_objects_by_principal[q.pending_for]
            candidates = pending if candidates is None else (pending & candidates)  # type: ignore[operator]

        filtered = q.types or q.schemas or q.tags or q.text.split()
        if candidates is None:
            if not filtered and q.sort == "schema_name":
                result = list(self.object_order)
                if q.descending:
                    result.reverse()
                return result
            candidates = range(len(self.objects))

        if q.types:
            objects = self.objects
            candidates = [o for o in candidates if objects[o].object_type in q.types]
        if q.schemas:
            schema_key = self._object_schema_key
            candidates = [o for o in candidates if schema_key[o] in q.schemas]
        if q.tags:
            tags = self.object_tags
            candidates = [o for o in candidates if q.tags <= tags[o]]
        tokens = q.text.casefold().split()
        if tokens:
            keys = self.object_search_key
            if len(tokens) == 1:
                token = tokens[0]
                candidates = [o for o in candidates if token in keys[o]]
            else:
                candidates = [o for o in candidates if all(t in keys[o] for t in tokens)]

        rank = self._object_rank
        if q.sort == "name":
            name_key = self._object_name_key
            result = sorted(candidates, key=lambda o: (name_key[o], rank[o]))
        elif q.sort == "type":
            objects = self.objects
            result = sorted(candidates, key=lambda o: (_OBJECT_TYPE_RANK[objects[o].object_type], rank[o]))
        else:
            result = sorted(candidates, key=rank.__getitem__)
        if q.descending:
            result.reverse()
        return result

    def group_by_schema(self, objects: list[int]) -> list[SchemaSpan]:
        """
        Split an ordered list of object indexes into runs of the same schema.

        Args:
            objects: Object indexes, normally sorted by schema

        Returns:
            list[SchemaSpan]: One span per consecutive run (positions in the given list)
        """
        spans: list[SchemaSpan] = []
        if not objects:
            return spans
        source = self.objects
        start = 0
        current = source[objects[0]].schema_name
        for position in range(1, len(objects)):
            schema = source[objects[position]].schema_name
            if schema != current:
                spans.append(SchemaSpan(current, start, position))
                start = position
                current = schema
        spans.append(SchemaSpan(current, start, len(objects)))
        return spans

    # --- Tags --------------------------------------------------------------------

    def set_tags(self, tag_store: TagStore | None) -> None:
        """
        Attach local tags to principals and objects.

        Also copies the tags onto DatabaseUser.tags / DatabaseObject.tags so code
        that calls has_tag() sees them.
        """
        principal_tags: list[frozenset[str]] = []
        for user in self.principals:
            tags = tag_store.get_user_tags(user.login_name) if tag_store else []
            user.tags = list(tags)
            principal_tags.append(frozenset(t.casefold() for t in tags))
        object_tags: list[frozenset[str]] = []
        for obj in self.objects:
            tags = tag_store.get_object_tags(obj.full_name) if tag_store else []
            obj.tags = list(tags)
            object_tags.append(frozenset(t.casefold() for t in tags))
        self.principal_tags = principal_tags
        self.object_tags = object_tags

    # --- Iteration ---------------------------------------------------------------

    def iter_explicit(self, effective: bool = False) -> Iterator[tuple[int, int, int, int]]:
        """
        Yield (p, o, perm_idx, code) for every GRANT/DENY cell.

        Args:
            effective: False = committed state; True = staged over committed
        """
        if effective:
            keys = sorted(set(self.committed) | set(self.staged))
            row_state = self.row_state
            rows: Iterable[tuple[tuple[int, int], int]] = ((key, row_state(*key)) for key in keys)
        else:
            rows = sorted(self.committed.items())
        for (p, o), value in rows:
            if not value:
                continue
            for perm_idx in range(PERM_COUNT):
                code = cell_code(value, perm_idx)
                if code != STATE_NONE:
                    yield p, o, perm_idx, code

    def iter_all_cells(self, effective: bool = True) -> Iterator[tuple[int, int, int, int]]:
        """
        Yield (p, o, perm_idx, code) for every applicable cell, including NONE.

        Principals in index order, objects in index order, permissions in PERMS order.
        Large: principals × objects × ~7 cells. The caller decides how much to keep.
        """
        row_state = self.row_state if effective else self.committed_row
        applicable = self.object_applicable
        for p in range(len(self.principals)):
            for o in range(len(self.objects)):
                value = row_state(p, o)
                mask = applicable[o]
                for perm_idx in range(PERM_COUNT):
                    if mask & (1 << perm_idx):
                        yield p, o, perm_idx, cell_code(value, perm_idx)
