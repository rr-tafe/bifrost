"""Search box that reports changes after the user pauses typing."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QWidget

DEBOUNCE_MS = 150


class SearchField(QLineEdit):
    """
    QLineEdit with a clear button and a debounced searchChanged signal.

    Signals:
        searchChanged(str): text, emitted DEBOUNCE_MS after the last keystroke
            (immediately when cleared or when Enter is pressed)
    """

    searchChanged = Signal(str)

    def __init__(self, placeholder: str, accessible_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAccessibleName(accessible_name)
        self.setClearButtonEnabled(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)
        self.textChanged.connect(self._on_text_changed)
        self.returnPressed.connect(self._emit)

    def _on_text_changed(self, text: str) -> None:
        if not text:
            self._emit()
        else:
            self._timer.start()

    def _emit(self) -> None:
        self._timer.stop()
        self.searchChanged.emit(self.text())
