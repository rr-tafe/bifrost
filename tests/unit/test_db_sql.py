"""Unit tests for identifier quoting and the SQL that permission functions send."""

import pytest

from src.db import permissions as db_permissions
from src.db.sql import quote_ident
from src.models.permission import PermissionState, PermissionType, StagedChange
from tests.unit.fake_db import FakeConnection


class TestQuoteIdent:
    def test_plain(self):
        assert quote_ident("Orders") == "[Orders]"

    def test_closing_bracket_is_doubled(self):
        assert quote_ident("a]b") == "[a]]b]"
        assert quote_ident("]]") == "[]]]]]"

    def test_other_characters_pass_through(self):
        assert quote_ident("it's a.b [x]") == "[it's a.b [x]]]"

    def test_limits(self):
        assert quote_ident("x" * 128) == "[" + "x" * 128 + "]"
        with pytest.raises(ValueError):
            quote_ident("x" * 129)
        with pytest.raises(ValueError):
            quote_ident("")
        with pytest.raises(ValueError):
            quote_ident("a\x00b")


def change(user, schema, obj, perm, new_state) -> StagedChange:
    return StagedChange(user, schema, obj, perm, PermissionState.NONE, new_state)


def test_apply_permission_changes_quotes_identifiers():
    """Regression (P5): names containing ] used to break the statement."""
    conn = FakeConnection()
    db_permissions.apply_permission_changes(
        conn,
        [
            change("weird]name", "fin]ance", "close]bracket", PermissionType.SELECT, PermissionState.GRANT),
            change("bob", "dbo", "Orders", PermissionType.VIEW_DEFINITION, PermissionState.DENY),
            change("bob", "dbo", "Orders", PermissionType.SELECT, PermissionState.NONE),
        ],
    )
    sql = [s for s, _ in conn.executed]
    assert sql == [
        "GRANT SELECT ON [fin]]ance].[close]]bracket] TO [weird]]name]",
        "DENY VIEW DEFINITION ON [dbo].[Orders] TO [bob]",
        "REVOKE SELECT ON [dbo].[Orders] FROM [bob]",
    ]


def test_check_grant_privileges_passes_names_as_parameters():
    """Regression (P6): names with quotes used to be pasted into the SQL text."""
    conn = FakeConnection()
    conn.held = {("dbo", "it's", "SELECT")}
    result = db_permissions.check_grant_privileges(
        conn, [("dbo", "it's", PermissionType.SELECT), ("x]y", "a.b", PermissionType.INSERT)]
    )
    assert result == {
        ("dbo", "it's", PermissionType.SELECT): True,
        ("x]y", "a.b", PermissionType.INSERT): False,
    }
    sql, params = conn.executed[0]
    assert "it's" not in sql and "x]y" not in sql
    assert "QUOTENAME(t.s)" in sql
    assert params == ["dbo", "it's", "SELECT", "x]y", "a.b", "INSERT"]


def test_check_grant_privileges_chunks_and_dedupes():
    conn = FakeConnection()
    targets = [("dbo", f"T{i}", PermissionType.SELECT) for i in range(1000)]
    result = db_permissions.check_grant_privileges(conn, targets + targets[:10])
    assert len(result) == 1000
    assert len(conn.executed) == 2
    assert all(len(params) <= 2100 for _sql, params in conn.executed)


def test_check_grant_privileges_empty():
    conn = FakeConnection()
    assert db_permissions.check_grant_privileges(conn, []) == {}
    assert conn.executed == []


@pytest.mark.parametrize("flags,expected", [((0, 0, 0), False), ((1, 0, 0), True), ((0, 0, 1), True), ((None, 1, 0), True)])
def test_fetch_privilege_flags(flags, expected):
    conn = FakeConnection()
    conn.flags = flags
    assert db_permissions.fetch_privilege_flags(conn) is expected
