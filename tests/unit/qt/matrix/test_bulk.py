"""Bulk helpers, FR-030 confirmation, presets, Make like and PermissionMatrix.stage_states."""

from src.models.permission import PermissionState, PermissionType
from src.qt.views.matrix import bulk
from src.services.matrix import CellRef
from src.services.matrix_index import PERM_INDEX
from tests.unit.qt.matrix.conftest import DELETE, EXECUTE, INSERT, SELECT, cell, state_name

GRANT, DENY, NONE = PermissionState.GRANT, PermissionState.DENY, PermissionState.NONE


def object_cells(session, login, perm):
    ix = session.matrix.index
    p = ix.principal_index(login)
    return [CellRef(p, o, perm) for o in ix.object_order]


class TestSummaries:
    def test_counts_changed_unchanged_skipped(self, session):
        ix = session.matrix.index
        items = bulk.items_for(object_cells(session, "alice", SELECT), GRANT)
        summary = bulk.summarize(ix, items)
        # Orders already GRANT, Customers changes, usp_Close: SELECT doesn't apply
        assert (summary.changed, summary.unchanged, summary.skipped) == (1, 1, 1)
        assert summary.grants == 1 and summary.denies == 0 and summary.revokes == 0
        assert summary.counts_text() == "1 will change · 1 already set · 1 don't apply (skipped)"

    def test_split_text(self):
        assert bulk.BulkSummary(changed=57, grants=52, denies=1, revokes=4).split_text() == "52 grants, 1 deny, 4 revokes"
        assert bulk.BulkSummary().split_text() == "no changes"

    def test_describe_scope(self, session):
        ix = session.matrix.index
        alice_cells = [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "alice", "dbo", "Orders", INSERT)]
        assert bulk.describe_scope(ix, alice_cells) == "on dbo.Orders for alice"
        two_dbo = [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "alice", "dbo", "usp_Close", EXECUTE)]
        assert bulk.describe_scope(ix, two_dbo) == "on 2 objects in dbo for alice"
        mixed = [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "alice", "sales", "Customers", SELECT)]
        assert bulk.describe_scope(ix, mixed) == "on 2 objects for alice"
        by_object = [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "bob", "dbo", "Orders", SELECT)]
        assert bulk.describe_scope(ix, by_object) == "for 2 principals on dbo.Orders"
        scattered = [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "bob", "sales", "Customers", SELECT)]
        assert bulk.describe_scope(ix, scattered) == "on 2 cells"

    def test_describe_action(self, session):
        ix = session.matrix.index
        items = bulk.items_for(
            [cell(session, "alice", "dbo", "Orders", SELECT), cell(session, "alice", "sales", "Customers", SELECT)], GRANT
        )
        assert bulk.describe_action(ix, items) == "Grant SELECT on 2 objects for alice"
        mixed = [(items[0][0], GRANT), (items[1][0], DENY)]
        assert bulk.describe_action(ix, mixed).startswith("Change SELECT")

    def test_cycle_and_revert_items(self, session):
        ix = session.matrix.index
        c = cell(session, "alice", "dbo", "Orders", SELECT)  # GRANT
        assert bulk.cycle_state(ix, c) is DENY
        session.matrix.stage([c], DENY)
        assert bulk.cycle_state(ix, c) is NONE
        assert bulk.revert_items(ix, [c]) == [(c, GRANT)]


class TestPresets:
    def test_read_preset_per_object_type(self, session):
        ix = session.matrix.index
        p = ix.principal_index("bob")
        rows = [(p, o) for o in ix.object_order]
        items = bulk.preset_items(ix, rows, "Read")
        perms = {(ix.objects[c.o].object_name, c.perm) for c, s in items}
        assert perms == {("Orders", SELECT), ("Customers", SELECT)}  # procedures get nothing from Read
        assert all(s is GRANT for _c, s in items)

    def test_execute_and_full_dml(self, session):
        ix = session.matrix.index
        p = ix.principal_index("bob")
        rows = [(p, o) for o in ix.object_order]
        execute = {(ix.objects[c.o].object_name, c.perm) for c, _s in bulk.preset_items(ix, rows, "Execute")}
        assert execute == {("usp_Close", EXECUTE)}
        dml = {c.perm for c, _s in bulk.preset_items(ix, [(p, ix.object_index("dbo", "Orders"))], "Full DML")}
        assert dml == {SELECT, INSERT, PERM_INDEX[PermissionType.UPDATE], DELETE, PERM_INDEX[PermissionType.REFERENCES]}

    def test_view_definition_applies_to_every_type(self, session):
        ix = session.matrix.index
        p = ix.principal_index("bob")
        items = bulk.preset_items(ix, [(p, o) for o in ix.object_order], "View definition only")
        assert len(items) == 3


class TestMakeLike:
    def test_items_copy_effective_states(self, session):
        ix = session.matrix.index
        team = ix.principal_index("CORP\\team")
        alice = ix.principal_index("alice")
        items = bulk.make_like_items(ix, team, alice, ix.object_order)
        summary = bulk.summarize(ix, items)
        # alice loses SELECT on Orders (revoke) and gains the EXECUTE DENY on usp_Close
        assert (summary.grants, summary.denies, summary.revokes) == (0, 1, 1)

    def test_make_like_is_one_undo_step(self, view, session):
        ix = session.matrix.index
        pane = view.panes["principal"]
        pane.left.select_entity(ix.principal_index("alice"))
        pane.apply_make_like(ix.principal_index("CORP\\team"), "all")
        assert session.staged_count == 2
        session.undo()
        assert session.staged_count == 0


class TestStageStates:
    def test_mixed_states_one_group_one_change(self, session):
        changes = []
        session.matrix.subscribe(changes.append)
        a = cell(session, "bob", "dbo", "Orders", SELECT)
        b = cell(session, "bob", "dbo", "usp_Close", EXECUTE)
        result = session.matrix.stage_states([(a, GRANT), (b, DENY)], label="mixed")
        assert result.changed == 2 and result.group.label == "mixed"
        assert len(changes) == 1 and changes[0].reason == "stage"
        assert state_name(session, a) == "GRANT" and state_name(session, b) == "DENY"
        session.matrix.undo()
        assert state_name(session, a) == "NONE" and state_name(session, b) == "NONE"


class TestConfirmation:
    def test_confirm_at_five_changes_not_four(self, big_view, big_session, confirmations):
        ix = big_session.matrix.index
        p = 0
        tables = [o for o in ix.object_order if ix.is_applicable(o, INSERT) and not ix.row_state(p, o)]
        cells = [CellRef(p, o, INSERT) for o in tables[:9]]
        big_view.editor.set_state(cells[:4], GRANT)
        assert confirmations.calls == [] and big_session.staged_count == 4
        big_view.editor.set_state(cells[4:9], GRANT)
        assert len(confirmations.calls) == 1 and big_session.staged_count == 9
        sentence, summary = confirmations.calls[0]
        assert summary.changed == 5 and sentence.startswith("Grant INSERT on 5 objects")

    def test_counts_changes_not_selected_cells(self, big_view, big_session, confirmations):
        ix = big_session.matrix.index
        tables = [o for o in ix.object_order if ix.is_applicable(o, INSERT) and not ix.row_state(0, o)]
        cells = [CellRef(0, o, INSERT) for o in tables[:4]]
        big_session.matrix.stage(cells[:2], GRANT)
        big_view.editor.set_state(cells, GRANT)  # 4 selected, 2 change
        assert confirmations.calls == []

    def test_cancel_stages_nothing(self, big_view, big_session, confirmations):
        confirmations.answer = (False, False)
        ix = big_session.matrix.index
        cells = [CellRef(0, o, INSERT) for o in ix.object_order if ix.is_applicable(o, INSERT)][:10]
        assert not big_view.editor.set_state(cells, GRANT)
        assert big_session.staged_count == 0

    def test_dont_ask_again(self, big_view, big_session, confirmations):
        confirmations.answer = (True, True)
        ix = big_session.matrix.index
        cells = [CellRef(1, o, DELETE) for o in ix.object_order if ix.is_applicable(o, DELETE)][:20]
        big_view.editor.set_state(cells[:10], DENY)
        big_view.editor.set_state(cells[10:], DENY)
        assert len(confirmations.calls) == 1
        assert big_session.staged_count == 20

    def test_selection_limit(self, big_view, big_session, monkeypatch):
        monkeypatch.setattr(bulk, "SELECTION_LIMIT", 10)
        messages = []
        big_session.statusMessage.connect(lambda text, _ms: messages.append(text))
        ix = big_session.matrix.index
        cells = [CellRef(2, o, SELECT) for o in ix.object_order if ix.is_applicable(o, SELECT)][:11]
        assert not big_view.editor.set_state(cells, GRANT)
        assert any("Select at most" in m for m in messages)
        assert big_view.editor.set_state(cells, GRANT, limited=False)  # group actions aren't limited
