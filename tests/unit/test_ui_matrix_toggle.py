"""Focused tests for MatrixView toggle behavior around privilege validation."""

from src.models.permission import PermissionState, PermissionType
from src.ui.views import matrix as matrix_module
from src.ui.views.matrix import MatrixView


class _FakeUser:
    def __init__(self, login_name):
        self.login_name = login_name


class _FakeObject:
    def __init__(self, schema_name, object_name):
        self.schema_name = schema_name
        self.object_name = object_name

    def supports_permission(self, _perm):
        return True


class _FakeAssignment:
    def __init__(self, state):
        self.effective_state = state


class _FakeMatrix:
    def __init__(self, privilege_error=None):
        self.privilege_error = privilege_error
        self.stage_calls = []

    def get_assignment(self, *_args):
        return _FakeAssignment(PermissionState.NONE)

    def validate_grant_privilege(self, *_args):
        return self.privilege_error

    def stage_change(self, user_login, schema_name, object_name, permission_type, new_state):
        self.stage_calls.append((user_login, schema_name, object_name, permission_type, new_state))
        return None


def test_toggle_skips_to_deny_when_grant_not_allowed(monkeypatch):
    info_calls = {"count": 0}

    monkeypatch.setattr(
        matrix_module.messagebox,
        "showinfo",
        lambda *_args, **_kwargs: info_calls.__setitem__("count", info_calls["count"] + 1),
    )

    view = object.__new__(MatrixView)
    view.matrix = _FakeMatrix(privilege_error="cannot grant")
    view._selected_cell = (0, 0)
    view._filtered_users = [_FakeUser("alice")]
    view._filtered_objects = [_FakeObject("dbo", "Orders")]
    view._permission_types = [PermissionType.SELECT]
    view._column_defs = [(0, PermissionType.SELECT, 0)]
    view._shown_grant_validation_hint = False
    view._update_cell_display = lambda _cell: None
    view._update_changes_count = lambda: None
    view._update_orientation_banner = lambda: None

    MatrixView._toggle_selected_cell(view)

    assert len(view.matrix.stage_calls) == 1
    staged = view.matrix.stage_calls[0]
    assert staged[4] == PermissionState.DENY
    assert info_calls["count"] == 1


def test_toggle_shows_grant_hint_only_once(monkeypatch):
    info_calls = {"count": 0}

    monkeypatch.setattr(
        matrix_module.messagebox,
        "showinfo",
        lambda *_args, **_kwargs: info_calls.__setitem__("count", info_calls["count"] + 1),
    )

    view = object.__new__(MatrixView)
    view.matrix = _FakeMatrix(privilege_error="cannot grant")
    view._selected_cell = (0, 0)
    view._filtered_users = [_FakeUser("alice")]
    view._filtered_objects = [_FakeObject("dbo", "Orders")]
    view._permission_types = [PermissionType.SELECT]
    view._column_defs = [(0, PermissionType.SELECT, 0)]
    view._shown_grant_validation_hint = False
    view._update_cell_display = lambda _cell: None
    view._update_changes_count = lambda: None
    view._update_orientation_banner = lambda: None

    MatrixView._toggle_selected_cell(view)
    MatrixView._toggle_selected_cell(view)

    assert info_calls["count"] == 1
    assert len(view.matrix.stage_calls) == 2
