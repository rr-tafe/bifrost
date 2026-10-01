"""Shown once per connection loss: Reconnect now, Open settings, or Stay offline."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


class ConnectionLostDialog(QDialog):
    """After exec(), choice is "reconnect", "settings" or "offline"."""

    def __init__(self, target: str, error: str, staged: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = "offline"
        self.setWindowTitle("Connection lost")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Lost the connection to {target}", self)
        font = heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        heading.setFont(font)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        kept = f"Your {staged:,} staged changes are kept." if staged else "You have no staged changes."
        layout.addWidget(QLabel(kept, self))
        detail = QLabel(error, self)
        detail.setWordWrap(True)
        detail.setAccessibleName("Error details")
        layout.addWidget(detail)

        buttons = QDialogButtonBox(self)
        reconnect = buttons.addButton("Reconnect now", QDialogButtonBox.ButtonRole.AcceptRole)
        settings = buttons.addButton("Open settings", QDialogButtonBox.ButtonRole.ActionRole)
        offline = buttons.addButton("Stay offline", QDialogButtonBox.ButtonRole.RejectRole)
        reconnect.setDefault(True)
        reconnect.clicked.connect(lambda: self._choose("reconnect"))
        settings.clicked.connect(lambda: self._choose("settings"))
        offline.clicked.connect(lambda: self._choose("offline"))
        layout.addWidget(buttons)
        reconnect.setFocus()

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def reject(self) -> None:  # Escape = stay offline
        self.choice = "offline"
        super().reject()
