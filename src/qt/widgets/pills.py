"""
Small status pills for the status bar.

Each pill states its meaning in text as well as colour (FR-024), and draws a
visible focus ring when focused with the keyboard.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from src.qt.theme import Tokens, tokens


def _pill_style(fg: str, bg: str, border: str, focus: str) -> str:
    return (
        "QPushButton {"
        f" color: {fg}; background: {bg}; border: 1px solid {border};"
        " border-radius: 10px; padding: 2px 10px; font-weight: 600;"
        "}"
        f"QPushButton:focus {{ border: 2px solid {focus}; }}"
        f"QPushButton:hover {{ border-color: {focus}; }}"
    )


class ConnectionPill(QPushButton):
    """
    Shows connection state: "● sql01/FinanceDW as CORP\\aadmin", "Connecting…", "Offline", …

    Clicking it opens connection settings (wired by the main window).
    """

    # state -> colour token (text always states the state too)
    KINDS = {
        "connected": "grant",
        "busy": "staged",
        "offline": "muted",
        "failed": "deny",
        "none": "muted",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self._kind = "none"
        self.setToolTip("Connection settings")
        self.set_state("none", "Not connected")

    @property
    def kind(self) -> str:
        return self._kind

    def set_state(self, kind: str, text: str) -> None:
        """Set the pill's state ("connected", "busy", "offline", "failed", "none") and text."""
        self._kind = kind if kind in self.KINDS else "none"
        self.setText(f"● {text}")
        self.setAccessibleName(f"Connection: {text}. Open connection settings")
        self.apply_theme()

    def apply_theme(self, t: Tokens | None = None) -> None:
        t = t or tokens()
        colour = getattr(t, self.KINDS[self._kind])
        self.setStyleSheet(_pill_style(colour, t.surface, t.line, t.accent))


class PendingPill(QPushButton):
    """Shows "No pending changes" or "12 pending"; clicking toggles the pending tray."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self._count = 0
        self.set_count(0)

    @property
    def count(self) -> int:
        return self._count

    def set_count(self, count: int) -> None:
        self._count = count
        self.setText(f"{count:,} pending" if count else "No pending changes")
        self.setAccessibleName(
            f"{count:,} staged changes. Show or hide the pending changes list" if count else "No staged changes"
        )
        self.apply_theme()

    def apply_theme(self, t: Tokens | None = None) -> None:
        t = t or tokens()
        if self._count:
            self.setStyleSheet(_pill_style(t.staged, t.staged_bg, t.staged, t.accent))
        else:
            self.setStyleSheet(_pill_style(t.muted, t.surface, t.line_soft, t.accent))
