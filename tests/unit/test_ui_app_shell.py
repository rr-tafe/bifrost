"""Focused tests for app shell shortcut and dialog behavior."""

from types import SimpleNamespace

import src.ui.app as app_module


class FakeToplevel:
    """Small Toplevel test double used for dialog lifecycle tests."""

    instances = []

    def __init__(self, *_args, **_kwargs):
        self.exists = True
        self.protocols = {}
        self.lifted = False
        self.focused = False
        FakeToplevel.instances.append(self)

    def title(self, _text):
        return None

    def geometry(self, _geometry):
        return None

    def transient(self, _parent):
        return None

    def grab_set(self):
        return None

    def resizable(self, _x, _y):
        return None

    def deiconify(self):
        return None

    def lift(self):
        self.lifted = True

    def focus_force(self):
        self.focused = True

    def winfo_exists(self):
        return self.exists

    def destroy(self):
        self.exists = False

    def protocol(self, name, callback):
        self.protocols[name] = callback


class FakeSettingsView:
    """Settings view test double."""

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs
        self.packed = False

    def pack(self, **_kwargs):
        self.packed = True


class FakeTagsView:
    """Tags view test double."""

    def __init__(self, _parent, tag_store, users, objects):
        self.tag_store = tag_store
        self.users = users
        self.objects = objects
        self.packed = False
        self.refresh_called = False
        self.last_set_data = None

    def pack(self, **_kwargs):
        self.packed = True

    def refresh(self):
        self.refresh_called = True

    def set_data(self, tag_store, users, objects):
        self.last_set_data = (tag_store, users, objects)


def test_bind_shortcuts_registers_dialog_and_commit_keys():
    """Shell shortcuts should route to current tab and dialog actions."""
    app = object.__new__(app_module.BifrostApp)

    handlers = {}
    calls = {
        "settings": 0,
        "tags": 0,
        "commit": 0,
        "switch": [],
    }

    app.bind = lambda key, fn: handlers.setdefault(key, fn)
    app._open_settings_dialog = lambda: calls.__setitem__("settings", calls["settings"] + 1)
    app._open_tags_dialog = lambda: calls.__setitem__("tags", calls["tags"] + 1)
    app._commit_changes = lambda: calls.__setitem__("commit", calls["commit"] + 1)
    app._export_permissions = lambda: None
    app._undo = lambda: None
    app._redo = lambda: None
    app._cancel_changes = lambda: None
    app._refresh = lambda: None
    app.switch_view = lambda view_type: calls["switch"].append(view_type)

    app_module.BifrostApp._bind_shortcuts(app)

    assert "<Control-Return>" in handlers
    assert "<Control-Key-2>" in handlers
    assert "<Control-Key-1>" in handlers
    assert "<Control-Key-4>" in handlers

    handlers["<Control-Return>"](None)
    handlers["<Control-Key-2>"](None)
    handlers["<Control-Key-1>"](None)
    handlers["<Control-Key-4>"](None)

    assert calls["commit"] == 1
    assert calls["tags"] == 1
    assert calls["switch"] == [app_module.ViewType.MATRIX, app_module.ViewType.AUDIT]


def test_settings_dialog_lifecycle_reuses_window(monkeypatch):
    """Opening settings twice should reuse existing window and clean state on close."""
    FakeToplevel.instances = []

    monkeypatch.setattr(app_module.tk, "Toplevel", FakeToplevel)
    monkeypatch.setattr(app_module, "SettingsView", FakeSettingsView)

    app = object.__new__(app_module.BifrostApp)
    app._settings_window = None
    app._settings_view = None
    app.config = None
    app._last_connection_test = None
    app._on_settings_saved = lambda _config: None
    app._test_connection = lambda _config: (True, "ok")

    app_module.BifrostApp._open_settings_dialog(app)

    assert len(FakeToplevel.instances) == 1
    first_window = app._settings_window
    assert first_window is not None
    assert app._settings_view is not None

    app_module.BifrostApp._open_settings_dialog(app)

    assert len(FakeToplevel.instances) == 1
    assert first_window.lifted is True
    assert first_window.focused is True

    first_window.protocols["WM_DELETE_WINDOW"]()

    assert app._settings_window is None
    assert app._settings_view is None


def test_settings_dialog_cancel_closes_and_receives_last_test(monkeypatch):
    """Cancel should close the dialog; the view should get the remembered test result."""
    FakeToplevel.instances = []

    monkeypatch.setattr(app_module.tk, "Toplevel", FakeToplevel)
    monkeypatch.setattr(app_module, "SettingsView", FakeSettingsView)

    app = object.__new__(app_module.BifrostApp)
    app._settings_window = None
    app._settings_view = None
    app.config = None
    app._last_connection_test = ("cfg", True, "Connected")
    app._on_settings_saved = lambda _config: None
    app._test_connection = lambda _config: (True, "ok")

    app_module.BifrostApp._open_settings_dialog(app)
    window = app._settings_window
    view = app._settings_view

    assert view.kwargs["last_test"] == ("cfg", True, "Connected")

    view.kwargs["on_cancel"]()

    assert window.exists is False
    assert app._settings_window is None
    assert app._settings_view is None


def test_test_connection_records_last_result(monkeypatch):
    """Connection test results should be remembered with the config that was tested."""
    import src.db.connection as connection_module

    monkeypatch.setattr(connection_module, "test_connection", lambda _cfg: (True, "Connected"))

    app = object.__new__(app_module.BifrostApp)
    app._last_connection_test = None
    config = app_module.Configuration(server="localhost", database="BifrostDev")

    assert app_module.BifrostApp._test_connection(app, config) == (True, "Connected")
    assert app._last_connection_test == (config, True, "Connected")


def test_tags_dialog_lifecycle_and_data_refresh(monkeypatch):
    """Tags manager should open once, reuse window, and accept data refresh calls."""
    FakeToplevel.instances = []

    monkeypatch.setattr(app_module.tk, "Toplevel", FakeToplevel)
    monkeypatch.setattr(app_module, "TagsView", FakeTagsView)

    app = object.__new__(app_module.BifrostApp)
    app._tags_window = None
    app._tags_view = None
    app.tag_store = object()
    app.matrix = SimpleNamespace(users=["jsmith"], objects=["dbo.Orders"])
    app._views = {}

    app_module.BifrostApp._open_tags_dialog(app)

    assert len(FakeToplevel.instances) == 1
    assert app._tags_view is not None
    assert app._tags_view.users == ["jsmith"]
    assert app._tags_view.objects == ["dbo.Orders"]
    assert app._tags_view.refresh_called is True

    app_module.BifrostApp._update_views_with_data(app, ["mjones"], ["dbo.Customers"])
    assert app._tags_view.last_set_data == (app.tag_store, ["mjones"], ["dbo.Customers"])

    first_window = app._tags_window
    app_module.BifrostApp._open_tags_dialog(app)

    assert len(FakeToplevel.instances) == 1
    assert first_window.lifted is True
    assert first_window.focused is True

    first_window.protocols["WM_DELETE_WINDOW"]()

    assert app._tags_window is None
    assert app._tags_view is None


def test_connection_loss_dialog_actions_route_correctly():
    """Connection-loss choices should route to reconnect, settings, or offline flows."""
    for action in ["reconnect", "settings", "offline"]:
        app = object.__new__(app_module.BifrostApp)
        app._connection_lost_notified = False
        app.matrix = SimpleNamespace(get_staged_changes=lambda: [1, 2])

        calls = {"reconnect": 0, "settings": 0, "status": []}

        app._show_connection_loss_dialog = lambda **_kwargs: action
        app._reconnect_preserving_staged_changes = lambda: calls.__setitem__(
            "reconnect", calls["reconnect"] + 1
        )
        app._open_settings_dialog = lambda: calls.__setitem__(
            "settings", calls["settings"] + 1
        )
        app._update_connection_status = lambda connected: connected
        app.set_status = lambda message: calls["status"].append(message)

        app_module.BifrostApp._handle_connection_loss(app, "network timeout")

        assert app._connection_lost_notified is True
        if action == "reconnect":
            assert calls["reconnect"] == 1
            assert calls["settings"] == 0
        elif action == "settings":
            assert calls["reconnect"] == 0
            assert calls["settings"] == 1
        else:
            assert calls["reconnect"] == 0
            assert calls["settings"] == 0


def test_switch_view_audit_wires_callbacks_and_refreshes(monkeypatch):
    """Switching to audit tab should wire callbacks and auto-refresh when connected."""

    class FakeButton:
        def __init__(self):
            self.styles = []

        def configure(self, **kwargs):
            self.styles.append(kwargs.get("style"))

    class FakeChild:
        def __init__(self):
            self.hidden = False

        def grid_forget(self):
            self.hidden = True

    class FakeContainer:
        def __init__(self):
            self._children = [FakeChild()]

        def winfo_children(self):
            return self._children

    class FakeAuditView:
        def __init__(self):
            self.refresh_calls = 0
            self.set_callbacks_calls = 0

        def grid(self, **_kwargs):
            return None

        def set_callbacks(self, on_fetch=None, on_export=None):
            self.set_callbacks_calls += 1
            self.on_fetch = on_fetch
            self.on_export = on_export

        def refresh(self):
            self.refresh_calls += 1

    monkeypatch.setattr(app_module, "AuditView", FakeAuditView)

    app = object.__new__(app_module.BifrostApp)
    app.current_view = app_module.ViewType.MATRIX
    app.connection = object()
    app._tab_buttons = {
        app_module.ViewType.MATRIX: FakeButton(),
        app_module.ViewType.AUDIT: FakeButton(),
    }
    app._view_container = FakeContainer()
    app._fetch_audit_entries = lambda _filters: []
    app.set_status = lambda _message: None

    fake_view = FakeAuditView()
    app._get_or_create_view = lambda _view_type: fake_view

    app_module.BifrostApp.switch_view(app, app_module.ViewType.AUDIT)

    assert fake_view.set_callbacks_calls == 1
    assert fake_view.refresh_calls == 1
    assert app.current_view == app_module.ViewType.AUDIT
