"""Unit tests for AuditView filter defaults and error messaging."""

import tkinter as tk
from datetime import time

import pytest

from src.ui.views.audit import AuditView


def _create_root_or_skip():
    """Create a Tk root for widget tests, skipping when unavailable."""
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError:
        pytest.skip("Tk display not available in this environment")


def test_audit_view_first_refresh_uses_default_limit_and_then_drops_limit():
    """First refresh should include initial limit; later refreshes should not."""
    root = _create_root_or_skip()
    captured_filters = []

    def on_fetch(filters):
        captured_filters.append(dict(filters))
        return []

    try:
        view = AuditView(root, on_fetch=on_fetch)
        view.refresh()
        view.refresh()

        assert len(captured_filters) == 2
        assert captured_filters[0]["limit"] == view.DEFAULT_INITIAL_LIMIT
        assert "limit" not in captured_filters[1]
    finally:
        root.destroy()


def test_audit_view_to_date_is_inclusive_end_of_day():
    """To-date filter should resolve to end-of-day timestamp."""
    root = _create_root_or_skip()
    try:
        view = AuditView(root, on_fetch=lambda _filters: [])
        view._from_date_var.set("2026-09-01")
        view._to_date_var.set("2026-09-02")

        filters = view._get_filters()

        assert filters["from_date"].time() == time.min
        assert filters["to_date"].time() == time.max
    finally:
        root.destroy()


def test_audit_view_shows_visible_error_message_on_fetch_failure():
    """Fetch failures should display an inline error instead of a silent empty table."""
    root = _create_root_or_skip()

    def on_fetch(_filters):
        raise RuntimeError("query failed")

    try:
        view = AuditView(root, on_fetch=on_fetch)
        view.refresh()

        assert "Failed to load audit entries" in view._message_var.get()
        assert "query failed" in view._message_var.get()
    finally:
        root.destroy()