"""Tests for SettingsView cancel behavior and connection status retention."""

import tkinter as tk

import pytest

from src.models.config import Configuration
from src.ui.views.settings import SettingsView


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def config():
    return Configuration(server="localhost", port=1433, database="BifrostDev", schema="dbo")


def status_text(view: SettingsView) -> str:
    return view._status_label.cget("text")


def test_cancel_restores_values_and_calls_on_cancel(root, config):
    cancelled = []
    view = SettingsView(root, config=config, on_cancel=lambda: cancelled.append(True))

    view._server_var.set("other-server")
    view._cancel()

    assert view._server_var.get() == "localhost"
    assert cancelled == [True]


def test_last_successful_test_is_shown_on_open(root, config):
    view = SettingsView(root, config=config, last_test=(config, True, "Connected to x/BifrostDev"))

    assert status_text(view) == "✓ Connected to x/BifrostDev"
    assert str(view._status_label.cget("foreground")) == "green"


def test_status_resets_when_parameter_changes_and_returns_when_reverted(root, config):
    view = SettingsView(root, config=config, last_test=(config, True, "Connected"))

    view._database_var.set("OtherDB")
    assert status_text(view) == "○ Not tested"

    view._database_var.set("BifrostDev")
    assert status_text(view) == "✓ Connected"


def test_unparseable_port_does_not_match_tested_port(root, config):
    view = SettingsView(root, config=config, last_test=(config, True, "Connected"))

    view._port_var.set("14x33")

    assert status_text(view) == "○ Not tested"


def test_test_button_result_is_retained(root, config):
    view = SettingsView(root, config=config, on_test=lambda _cfg: (True, "Connected"))
    assert status_text(view) == "○ Not tested"

    view._test_connection()
    view._schema_var.set("audit")
    view._schema_var.set("dbo")

    assert status_text(view) == "✓ Connected"
