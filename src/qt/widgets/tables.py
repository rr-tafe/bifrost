"""Shared table setup."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTableView

ROW_PADDING = 8


def compact_rows(table: QTableView) -> None:
    """Size rows to the font plus a little padding (the platform default is tall)."""
    table.verticalHeader().setDefaultSectionSize(table.fontMetrics().height() + ROW_PADDING)
