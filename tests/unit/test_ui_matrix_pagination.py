"""Focused tests for simplified matrix selection behavior."""

from types import SimpleNamespace

from src.models.db_object import ObjectType
from src.models.permission import PermissionState, PermissionType
from src.ui.views.matrix import MatrixView


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeButton:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


class _FakeCanvas:
    def __init__(self):
        self.create_text_calls = []

    def canvasy(self, value):
        return value

    def canvasx(self, value):
        return value

    def create_rectangle(self, *_args, **_kwargs):
        return 1

    def create_text(self, *args, **kwargs):
        self.create_text_calls.append((args, kwargs))
        return 1


def _fake_matrix(users, objects):
    return SimpleNamespace(
        get_filtered_users=lambda: users,
        get_filtered_objects=lambda: objects,
        get_performance_info=lambda: SimpleNamespace(is_large=False, warning_message=""),
        get_staged_change_count=lambda: 0,
    )


def test_apply_filters_requires_applied_selection():
    view = object.__new__(MatrixView)
    view.matrix = _fake_matrix(
        [SimpleNamespace(login_name="alice")],
        [SimpleNamespace(full_name="dbo.Orders")],
    )
    view._pending_user_selection = set()
    view._pending_object_selection = set()
    view._applied_user_selection = set()
    view._applied_object_selection = set()
    view._users_selector_btn = _FakeButton()
    view._objects_selector_btn = _FakeButton()
    view._selection_error_label = _FakeLabel()
    view._warning_label = _FakeLabel()
    view._display_users_per_page = 10
    view._display_objects_per_page = 10
    view._user_page_index = 0
    view._object_page_index = 0
    view._update_scroll_region = lambda: None
    view._redraw_all = lambda: None
    view._update_orientation_banner = lambda: None
    view._update_display_pagination_labels = lambda: None
    view._rebuild_column_layout = lambda: None
    view._rebuild_column_layout = lambda: None

    MatrixView._apply_filters(view)

    assert view._filtered_users == []
    assert view._filtered_objects == []
    assert "Select users and objects" in view._selection_error_label.text


def test_apply_filters_projects_applied_user_and_object_sets():
    users = [
        SimpleNamespace(login_name="alice"),
        SimpleNamespace(login_name="bob"),
    ]
    objects = [
        SimpleNamespace(full_name="dbo.Orders"),
        SimpleNamespace(full_name="dbo.Customers"),
    ]

    view = object.__new__(MatrixView)
    view.matrix = _fake_matrix(users, objects)
    view._pending_user_selection = {"alice"}
    view._pending_object_selection = {"dbo.Customers"}
    view._applied_user_selection = {"alice"}
    view._applied_object_selection = {"dbo.Customers"}
    view._users_selector_btn = _FakeButton()
    view._objects_selector_btn = _FakeButton()
    view._selection_error_label = _FakeLabel()
    view._warning_label = _FakeLabel()
    view._display_users_per_page = 10
    view._display_objects_per_page = 10
    view._user_page_index = 0
    view._object_page_index = 0
    view._update_scroll_region = lambda: None
    view._redraw_all = lambda: None
    view._update_orientation_banner = lambda: None
    view._update_display_pagination_labels = lambda: None
    view._rebuild_column_layout = lambda: None

    MatrixView._apply_filters(view)

    assert [u.login_name for u in view._filtered_users] == ["alice"]
    assert [o.full_name for o in view._filtered_objects] == ["dbo.Customers"]
    assert view._selection_error_label.text == ""


def test_selector_button_labels_show_pending_selection_counts():
    view = object.__new__(MatrixView)
    view._pending_user_selection = {"alice", "bob"}
    view._pending_object_selection = {"dbo.Orders"}
    view._users_selector_btn = _FakeButton()
    view._objects_selector_btn = _FakeButton()

    MatrixView._update_selector_button_labels(view)

    assert view._users_selector_btn.text == "Users (2 selected)"
    assert view._objects_selector_btn.text == "Objects (1 selected)"


def test_draw_headers_uses_full_rotated_permission_text():
    obj = SimpleNamespace(
        full_name="dbo.Orders",
        supports_permission=lambda _perm: True,
    )
    view = object.__new__(MatrixView)
    view._canvas = _FakeCanvas()
    view._filtered_objects = [obj]
    view._permission_types = [PermissionType.SELECT]
    view._active_highlight = None
    view._column_defs = [(0, PermissionType.SELECT, view.USER_COL_WIDTH)]
    view._column_spans = [
        (view.USER_COL_WIDTH, view.USER_COL_WIDTH + view.CELL_WIDTH, 0, obj),
    ]

    MatrixView._draw_headers(view)

    perm_text_calls = [c for c in view._canvas.create_text_calls if c[1].get("text") == PermissionType.SELECT.value]
    assert perm_text_calls
    assert perm_text_calls[0][1].get("angle") == 90


def test_get_state_symbol_uses_checkbox_glyphs():
    view = object.__new__(MatrixView)
    assert MatrixView._get_state_symbol(view, PermissionState.NONE, False) == "☐"
    assert MatrixView._get_state_symbol(view, PermissionState.GRANT, False) == "☑"
    assert MatrixView._get_state_symbol(view, PermissionState.DENY, False) == "☒"


def test_apply_selection_allows_more_than_ten_users():
    view = object.__new__(MatrixView)
    view._pending_user_selection = {f"u{i}" for i in range(11)}
    view._pending_object_selection = {"dbo.Orders"}
    view._applied_user_selection = set()
    view._applied_object_selection = set()
    view._selection_error_label = _FakeLabel()
    view._update_selector_button_labels = lambda: None
    view._apply_filters = lambda: None

    MatrixView._apply_selection(view)

    assert view._applied_user_selection == view._pending_user_selection
    assert view._selection_error_label.text == ""


def test_apply_selection_updates_applied_sets_when_within_limit():
    view = object.__new__(MatrixView)
    view._pending_user_selection = {"alice", "bob"}
    view._pending_object_selection = {"dbo.Orders", "dbo.Customers"}
    view._applied_user_selection = set()
    view._applied_object_selection = set()
    view._selection_error_label = _FakeLabel()

    calls = {"labels": 0, "filters": 0}
    view._update_selector_button_labels = lambda: calls.__setitem__("labels", calls["labels"] + 1)
    view._apply_filters = lambda: calls.__setitem__("filters", calls["filters"] + 1)

    MatrixView._apply_selection(view)

    assert view._applied_user_selection == {"alice", "bob"}
    assert view._applied_object_selection == {"dbo.Orders", "dbo.Customers"}
    assert view._selection_error_label.text == ""
    assert calls["labels"] == 1
    assert calls["filters"] == 1


def test_is_likely_service_account_uses_name_heuristics():
    view = object.__new__(MatrixView)

    assert MatrixView._is_likely_service_account(view, "svc_reporter") is True
    assert MatrixView._is_likely_service_account(view, "batch_loader") is True
    assert MatrixView._is_likely_service_account(view, "sqlservice-user") is True

    # SAS-style service-account patterns.
    assert MatrixView._is_likely_service_account(view, "misasuser") is True
    assert MatrixView._is_likely_service_account(view, "miusersas") is True

    # Tableau-related operational accounts.
    assert MatrixView._is_likely_service_account(view, "tableauprep_CustInter") is True
    assert MatrixView._is_likely_service_account(view, "tableau_agent") is True

    # Environment/workload prefixed service-account patterns.
    assert MatrixView._is_likely_service_account(view, "npe9-sql_cpci_nonci") is True
    assert MatrixView._is_likely_service_account(view, "npe12-loader") is True

    assert MatrixView._is_likely_service_account(view, "normal.user") is False


def test_build_selector_sections_groups_users_service_accounts_and_groups():
    view = object.__new__(MatrixView)
    view._all_users = [
        SimpleNamespace(login_name="alice", principal_type="U"),
        SimpleNamespace(login_name="svc_etl", principal_type="U"),
        SimpleNamespace(login_name="finance_readers", principal_type="G"),
    ]

    sections = MatrixView._build_selector_sections(
        view,
        "users",
        ["alice", "svc_etl", "finance_readers"],
    )

    assert sections == [
        ("Users", ["alice"]),
        ("Service Accounts", ["svc_etl"]),
        ("Groups", ["finance_readers"]),
    ]


def test_build_selector_sections_defaults_unknown_to_users():
    view = object.__new__(MatrixView)
    view._all_users = [SimpleNamespace(login_name="known", principal_type="U")]

    sections = MatrixView._build_selector_sections(view, "users", ["known", "missing-principal"])

    assert sections == [("Users", ["known", "missing-principal"])]


def test_build_selector_sections_groups_objects_by_type():
    view = object.__new__(MatrixView)
    view._all_objects = [
        SimpleNamespace(full_name="dbo.Orders", object_type=ObjectType.TABLE),
        SimpleNamespace(full_name="dbo.vwOrders", object_type=ObjectType.VIEW),
        SimpleNamespace(full_name="dbo.usp_LoadOrders", object_type=ObjectType.PROCEDURE),
        SimpleNamespace(full_name="dbo.fn_Total", object_type=ObjectType.FUNCTION),
    ]

    sections = MatrixView._build_selector_sections(
        view,
        "objects",
        ["dbo.Orders", "dbo.vwOrders", "dbo.usp_LoadOrders", "dbo.fn_Total"],
    )

    assert sections == [
        ("Tables", ["dbo.Orders"]),
        ("Views", ["dbo.vwOrders"]),
        ("Stored Procedures", ["dbo.usp_LoadOrders"]),
        ("Functions", ["dbo.fn_Total"]),
    ]


def test_build_selector_sections_puts_unknown_objects_in_other_bucket():
    view = object.__new__(MatrixView)
    view._all_objects = [SimpleNamespace(full_name="dbo.Orders", object_type=ObjectType.TABLE)]

    sections = MatrixView._build_selector_sections(
        view,
        "objects",
        ["dbo.Orders", "dbo.UnmappedObject"],
    )

    assert sections == [
        ("Tables", ["dbo.Orders"]),
        ("Other", ["dbo.UnmappedObject"]),
    ]
