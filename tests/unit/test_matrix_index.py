"""Unit tests for the integer-indexed permission store (src/services/matrix_index.py)."""

import random

import pytest

from src.models.db_object import DatabaseObject, ObjectType
from src.models.permission import (
    STATE_DENY,
    STATE_GRANT,
    STATE_NONE,
    PermissionState,
    PermissionType,
)
from src.models.user import DatabaseUser
from src.services.loader import MatrixSnapshot
from src.services.matrix import CellRef, PermissionMatrix
from src.services.matrix_index import (
    ALL_MASK,
    APPLICABLE_MASK,
    PERM_INDEX,
    PERMS,
    ObjectQuery,
    PermissionIndex,
    PrincipalQuery,
    cell_code,
    deny_mask,
    diff_mask,
    grant_mask,
    with_cell,
)
from src.services.tags import TagStore
from tests.perf.synthetic import make_snapshot

SELECT = PERM_INDEX[PermissionType.SELECT]
INSERT = PERM_INDEX[PermissionType.INSERT]
EXECUTE = PERM_INDEX[PermissionType.EXECUTE]


def small_snapshot() -> MatrixSnapshot:
    """alice/bob/team; Orders (table), Customers (table), usp_Close (procedure)."""
    principals = (
        DatabaseUser("CORP\\team", "CORP\\team", "G", principal_id=7),
        DatabaseUser("alice", "alice", "S", principal_id=5),
        DatabaseUser("bob", "bob", "U", principal_id=6),
    )
    objects = (
        DatabaseObject("dbo", "Orders", ObjectType.TABLE, object_id=100),
        DatabaseObject("sales", "Customers", ObjectType.TABLE, object_id=101),
        DatabaseObject("dbo", "usp_Close", ObjectType.PROCEDURE, object_id=102),
    )
    rows = (
        (5, 100, SELECT, STATE_GRANT),
        (5, 100, INSERT, STATE_DENY),
        (6, 101, SELECT, STATE_GRANT),
        (7, 102, EXECUTE, STATE_GRANT),
        (99, 100, SELECT, STATE_GRANT),  # unknown principal
        (5, 999, SELECT, STATE_GRANT),  # unknown object
        (5, 102, SELECT, STATE_GRANT),  # SELECT doesn't apply to a procedure
    )
    return MatrixSnapshot(principals, objects, rows, current_user="CORP\\admin")


def recount(index: PermissionIndex) -> None:
    """Assert every derived structure matches a brute-force recount from committed + staged."""
    p_count, o_count = len(index.principals), len(index.objects)
    grants_p, denies_p, pending_p = [0] * p_count, [0] * p_count, [0] * p_count
    grants_o, denies_o, pending_o = [0] * o_count, [0] * o_count, [0] * o_count
    objects_by_principal = [set() for _ in range(p_count)]
    principals_by_object = [set() for _ in range(o_count)]
    staged_objects = [set() for _ in range(p_count)]
    total_pending = 0

    for value in index.committed.values():
        assert value != 0, "committed must not hold empty rows"
        assert grant_mask(value) & deny_mask(value) == 0
    for key, value in index.staged.items():
        assert value != index.committed.get(key, 0), "staged must differ from committed"
        assert grant_mask(value) & deny_mask(value) == 0

    for p, o in set(index.committed) | set(index.staged):
        committed = index.committed_row(p, o)
        effective = index.row_state(p, o)
        grants = grant_mask(effective).bit_count()
        denies = deny_mask(effective).bit_count()
        pending = diff_mask(effective, committed).bit_count()
        grants_p[p] += grants
        denies_p[p] += denies
        pending_p[p] += pending
        grants_o[o] += grants
        denies_o[o] += denies
        pending_o[o] += pending
        total_pending += pending
        if committed or effective:
            objects_by_principal[p].add(o)
            principals_by_object[o].add(p)
        if pending:
            staged_objects[p].add(o)

    for p in range(p_count):
        counts = index.principal_counts(p)
        assert (counts.grants, counts.denies, counts.pending) == (grants_p[p], denies_p[p], pending_p[p])
    for o in range(o_count):
        counts = index.object_counts(o)
        assert (counts.grants, counts.denies, counts.pending) == (grants_o[o], denies_o[o], pending_o[o])
    assert index.objects_by_principal == objects_by_principal
    assert index.principals_by_object == principals_by_object
    assert index.staged_objects_by_principal == staged_objects
    assert index.staged_cell_count == total_pending


class TestPacking:
    def test_every_cell_round_trips(self):
        for perm_idx in range(len(PERMS)):
            for code in (STATE_NONE, STATE_GRANT, STATE_DENY):
                packed = with_cell(0, perm_idx, code)
                assert cell_code(packed, perm_idx) == code
                for other in range(len(PERMS)):
                    if other != perm_idx:
                        assert cell_code(packed, other) == STATE_NONE

    def test_grant_and_deny_never_overlap(self):
        packed = with_cell(0, SELECT, STATE_GRANT)
        packed = with_cell(packed, SELECT, STATE_DENY)
        assert grant_mask(packed) == 0
        assert deny_mask(packed) == 1 << SELECT
        packed = with_cell(packed, SELECT, STATE_GRANT)
        assert grant_mask(packed) & deny_mask(packed) == 0

    def test_diff_mask(self):
        a = with_cell(with_cell(0, SELECT, STATE_GRANT), INSERT, STATE_DENY)
        b = with_cell(with_cell(0, SELECT, STATE_DENY), INSERT, STATE_DENY)
        assert diff_mask(a, b) == 1 << SELECT
        assert diff_mask(a, a) == 0
        assert diff_mask(a, 0) == (1 << SELECT) | (1 << INSERT)
        assert diff_mask(0xFFFF, 0) == ALL_MASK

    def test_applicable_mask_matches_object_type_rules(self):
        for object_type in ObjectType:
            for perm_idx, perm in enumerate(PERMS):
                assert bool(APPLICABLE_MASK[object_type] & (1 << perm_idx)) == object_type.supports_permission(perm)


class TestBuild:
    def test_skips_unknown_and_not_applicable_rows(self):
        index = PermissionIndex.build(small_snapshot())
        assert index.build_stats.permission_rows == 7
        assert index.build_stats.skipped_unknown == 2
        assert index.build_stats.skipped_not_applicable == 1
        assert len(index.committed) == 3

    def test_row_state_and_counts(self):
        index = PermissionIndex.build(small_snapshot())
        alice = index.principal_index("alice")
        orders = index.object_index("dbo", "Orders")
        packed = index.row_state(alice, orders)
        assert cell_code(packed, SELECT) == STATE_GRANT
        assert cell_code(packed, INSERT) == STATE_DENY
        counts = index.principal_counts(alice)
        assert (counts.grants, counts.denies, counts.pending) == (1, 1, 0)
        recount(index)

    def test_object_order_and_schema_spans(self):
        index = PermissionIndex.build(small_snapshot())
        names = [index.objects[o].full_name for o in index.object_order]
        assert names == ["dbo.Orders", "dbo.usp_Close", "sales.Customers"]
        assert [(s.schema, s.start, s.end) for s in index.schema_spans] == [("dbo", 0, 2), ("sales", 2, 3)]

    def test_empty_index_is_usable(self):
        index = PermissionIndex()
        assert index.query_objects(ObjectQuery()) == []
        assert index.query_principals(PrincipalQuery()) == []
        assert index.staged_cell_count == 0

    def test_cell_view(self):
        index = PermissionIndex.build(small_snapshot())
        alice = index.principal_index("alice")
        usp = index.object_index("dbo", "usp_Close")
        view = index.cell(alice, usp, SELECT)
        assert view.applicable is False
        assert view.effective == PermissionState.NONE


class TestWrites:
    def test_set_effective_tracks_pending_and_counts(self):
        index = PermissionIndex.build(small_snapshot())
        bob = index.principal_index("bob")
        orders = index.object_index("dbo", "Orders")
        assert index.set_effective(bob, orders, SELECT, STATE_GRANT) is True
        assert index.pending_mask(bob, orders) == 1 << SELECT
        assert index.staged_cell_count == 1
        recount(index)
        # Same state again is a no-op
        assert index.set_effective(bob, orders, SELECT, STATE_GRANT) is False
        # Back to committed removes the staged row
        assert index.set_effective(bob, orders, SELECT, STATE_NONE) is True
        assert (bob, orders) not in index.staged
        assert index.staged_cell_count == 0
        recount(index)

    def test_set_effective_rejects_not_applicable(self):
        index = PermissionIndex.build(small_snapshot())
        usp = index.object_index("dbo", "usp_Close")
        with pytest.raises(ValueError):
            index.set_effective(0, usp, SELECT, STATE_GRANT)

    def test_staged_revoke_keeps_row_in_access_list(self):
        index = PermissionIndex.build(small_snapshot())
        bob = index.principal_index("bob")
        customers = index.object_index("sales", "Customers")
        index.set_effective(bob, customers, SELECT, STATE_NONE)
        assert customers in index.objects_by_principal[bob]
        recount(index)

    def test_clear_staged(self):
        index = PermissionIndex.build(small_snapshot())
        index.set_effective(0, 0, SELECT, STATE_DENY)
        index.set_effective(1, 1, INSERT, STATE_GRANT)
        rows = index.clear_staged()
        assert rows == {(0, 0), (1, 1)}
        assert index.staged == {}
        recount(index)

    def test_commit_rows_moves_cells_to_committed(self):
        index = PermissionIndex.build(small_snapshot())
        bob = index.principal_index("bob")
        orders = index.object_index("dbo", "Orders")
        index.set_effective(bob, orders, SELECT, STATE_GRANT)
        index.set_effective(bob, orders, INSERT, STATE_GRANT)
        index.commit_rows([(bob, orders, SELECT, STATE_GRANT)])
        assert cell_code(index.committed_row(bob, orders), SELECT) == STATE_GRANT
        assert index.pending_mask(bob, orders) == 1 << INSERT
        recount(index)


class TestQueries:
    def setup_method(self):
        store = TagStore()
        store.add_user_tag("alice", "Finance")
        store.add_object_tag("sales.Customers", "pii")
        self.index = PermissionIndex.build(small_snapshot(), store)

    def names(self, principals):
        return [self.index.principals[p].login_name for p in principals]

    def objects(self, objects):
        return [self.index.objects[o].full_name for o in objects]

    def test_principals_default_order(self):
        assert self.names(self.index.query_principals(PrincipalQuery())) == ["alice", "bob", "CORP\\team"]

    def test_principal_text_tokens_are_and(self):
        assert self.names(self.index.query_principals(PrincipalQuery(text="CORP TEAM"))) == ["CORP\\team"]
        assert self.index.query_principals(PrincipalQuery(text="corp alice")) == []

    def test_principal_type_tag_and_access_filters(self):
        assert self.names(self.index.query_principals(PrincipalQuery(types=frozenset({"U"})))) == ["bob"]
        assert self.names(self.index.query_principals(PrincipalQuery(tags=frozenset({"finance"})))) == ["alice"]
        orders = self.index.object_index("dbo", "Orders")
        assert self.names(self.index.query_principals(PrincipalQuery(has_access_to_object=orders))) == ["alice"]

    def test_principal_pending_and_sorts(self):
        bob = self.index.principal_index("bob")
        self.index.set_effective(bob, 0, SELECT, STATE_GRANT)
        assert self.names(self.index.query_principals(PrincipalQuery(has_pending=True))) == ["bob"]
        by_type = self.names(self.index.query_principals(PrincipalQuery(sort="type")))
        assert by_type == ["CORP\\team", "alice", "bob"]  # G, S, U
        desc = self.names(self.index.query_principals(PrincipalQuery(descending=True)))
        assert desc == ["CORP\\team", "bob", "alice"]

    def test_objects_filters(self):
        q = self.index.query_objects
        assert self.objects(q(ObjectQuery(text="ord"))) == ["dbo.Orders"]
        assert self.objects(q(ObjectQuery(schemas=frozenset({"sales"})))) == ["sales.Customers"]
        assert self.objects(q(ObjectQuery(types=frozenset({ObjectType.PROCEDURE})))) == ["dbo.usp_Close"]
        assert self.objects(q(ObjectQuery(tags=frozenset({"pii"})))) == ["sales.Customers"]
        alice = self.index.principal_index("alice")
        assert self.objects(q(ObjectQuery(with_access_for=alice))) == ["dbo.Orders"]

    def test_objects_pending_for_and_sorts(self):
        q = self.index.query_objects
        alice = self.index.principal_index("alice")
        customers = self.index.object_index("sales", "Customers")
        self.index.set_effective(alice, customers, SELECT, STATE_GRANT)
        assert self.objects(q(ObjectQuery(pending_for=alice))) == ["sales.Customers"]
        assert self.objects(q(ObjectQuery(pending_for=alice, with_access_for=alice))) == ["sales.Customers"]
        assert self.objects(q(ObjectQuery(sort="name"))) == ["sales.Customers", "dbo.Orders", "dbo.usp_Close"]
        assert self.objects(q(ObjectQuery(sort="type")))[-1] == "dbo.usp_Close"
        assert self.objects(q(ObjectQuery(descending=True))) == ["sales.Customers", "dbo.usp_Close", "dbo.Orders"]

    def test_casefold_matching(self):
        snapshot = small_snapshot()
        principals = snapshot.principals + (DatabaseUser("STRASSE", "STRASSE", "S", principal_id=8),)
        index = PermissionIndex.build(MatrixSnapshot(principals, snapshot.objects, ()))
        found = index.query_principals(PrincipalQuery(text="straße"))
        assert [index.principals[p].login_name for p in found] == ["STRASSE"]

    def test_group_by_schema_on_filtered_list(self):
        objects = self.index.query_objects(ObjectQuery(types=frozenset({ObjectType.TABLE})))
        spans = self.index.group_by_schema(objects)
        assert [(s.schema, s.start, s.end) for s in spans] == [("dbo", 0, 1), ("sales", 1, 2)]

    def test_tags_copied_onto_models(self):
        alice = self.index.principals[self.index.principal_index("alice")]
        assert alice.tags == ["Finance"]
        assert alice.has_tag("finance")


class TestIteration:
    def test_iter_explicit_committed_and_effective(self):
        index = PermissionIndex.build(small_snapshot())
        committed = list(index.iter_explicit())
        assert len(committed) == 4
        bob = index.principal_index("bob")
        index.set_effective(bob, 0, SELECT, STATE_GRANT)
        assert len(list(index.iter_explicit())) == 4
        assert len(list(index.iter_explicit(effective=True))) == 5

    def test_iter_all_cells_counts_applicable_cells(self):
        index = PermissionIndex.build(small_snapshot())
        cells = list(index.iter_all_cells())
        per_principal = sum(mask.bit_count() for mask in index.object_applicable)
        assert len(cells) == per_principal * len(index.principals)
        assert sum(1 for c in cells if c[3] != STATE_NONE) == 4


def test_random_operations_keep_index_consistent():
    """500 random stage/revert/undo/redo/cancel/commit operations, then a brute-force recount."""
    rng = random.Random(42)
    snapshot = make_snapshot(principals=12, objects=30, explicit=120, seed=3)
    matrix = PermissionMatrix(None)
    matrix.apply_snapshot(snapshot)
    index = matrix.index

    def random_cell() -> CellRef:
        o = rng.randrange(len(index.objects))
        applicable = [i for i in range(len(PERMS)) if index.is_applicable(o, i)]
        return CellRef(rng.randrange(len(index.principals)), o, rng.choice(applicable))

    states = list(PermissionState)
    for _ in range(500):
        action = rng.random()
        if action < 0.45:
            matrix.stage([random_cell() for _ in range(rng.randint(1, 6))], rng.choice(states))
        elif action < 0.55:
            matrix.stage_cycle(random_cell())
        elif action < 0.65:
            matrix.revert([random_cell() for _ in range(3)])
        elif action < 0.78:
            matrix.undo()
        elif action < 0.88:
            matrix.redo()
        elif action < 0.92:
            matrix.cancel()
        else:
            plan = matrix.prepare_commit()
            if plan.changes:
                from src.services.matrix import CommitOutcome

                results = tuple((c, None if rng.random() < 0.7 else "failed") for c in plan.changes)
                matrix.apply_commit_results(plan, CommitOutcome(results, 0, False, None))
        recount(index)
