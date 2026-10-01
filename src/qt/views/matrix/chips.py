"""
Small filter controls for the matrix view.

ChipButton is a checkable toggle; Segmented is a row of exclusive choices;
MultiSelectChip is a button with a dropdown of checkboxes. All use the platform
style, so High Contrast works, and keep their accessible names in step with
their state ("Users filter, on").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QMenu, QToolButton, QWidget

if TYPE_CHECKING:
    from collections.abc import Iterable


class ChipButton(QToolButton):
    """Checkable toggle chip whose accessible name says whether it is on."""

    def __init__(self, text: str, name: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setText(text)
        self.setCheckable(True)
        self.setToolTip(tooltip or name)
        self.toggled.connect(self._sync_name)
        self._sync_name(False)

    def set_checked_quietly(self, checked: bool) -> None:
        """Set the state without emitting toggled (restoring saved filters)."""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._sync_name(checked)

    def _sync_name(self, checked: bool) -> None:
        self.setAccessibleName(f"{self._name} filter, {'on' if checked else 'off'}")


class Segmented(QWidget):
    """
    Row of exclusive choices.

    Signals:
        changed(str): key of the newly chosen segment (not emitted by set_value)
    """

    changed = Signal(str)

    def __init__(self, choices: Iterable[tuple[str, str]], name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, text in choices:
            button = QToolButton(self)
            button.setText(text)
            button.setCheckable(True)
            button.setAccessibleName(f"{name}: {text}")
            button.setProperty("segment_key", key)
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[key] = button
        first = next(iter(self.buttons))
        self._value = first
        self.buttons[first].setChecked(True)
        self.group.buttonToggled.connect(self._on_toggled)

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, key: str) -> None:
        """Choose a segment without emitting changed."""
        if key not in self.buttons or key == self._value:
            return
        self._value = key
        self.group.blockSignals(True)
        self.buttons[key].setChecked(True)
        self.group.blockSignals(False)

    def _on_toggled(self, button: QToolButton, checked: bool) -> None:
        if checked:
            key = button.property("segment_key")
            if key != self._value:
                self._value = key
                self.changed.emit(key)


class MultiSelectChip(QToolButton):
    """
    Dropdown of checkable options ("Tags ▾", "Schema (2) ▾").

    Signals:
        changed(frozenset): selected keys (not emitted by set_selected)
    """

    changed = Signal(object)

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._selected: frozenset[str] = frozenset()
        self.menu_ = QMenu(self)
        self.setMenu(self.menu_)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._options: list[tuple[str, str]] = []
        self._sync()

    @property
    def selected(self) -> frozenset[str]:
        return self._selected

    def set_options(self, options: Iterable[tuple[str, str]]) -> None:
        """Replace the options: (key, label) pairs. Selected keys that no longer exist are dropped."""
        self._options = list(options)
        keys = {k for k, _ in self._options}
        self._selected = frozenset(k for k in self._selected if k in keys)
        self.menu_.clear()
        if not self._options:
            empty = self.menu_.addAction("No options")
            empty.setEnabled(False)
        for key, label in self._options:
            action = self.menu_.addAction(label)
            action.setCheckable(True)
            action.setChecked(key in self._selected)
            action.toggled.connect(lambda checked, k=key: self._on_action(k, checked))
        if self._selected:
            self.menu_.addSeparator()
            self.menu_.addAction("Clear", self.clear)
        self._sync()

    def set_selected(self, keys: Iterable[str]) -> None:
        """Select keys without emitting changed."""
        self._selected = frozenset(keys)
        self.set_options(self._options)

    def add(self, key: str) -> None:
        """Select one more key and emit changed."""
        if key not in self._selected:
            self._selected = self._selected | {key}
            if key not in {k for k, _ in self._options}:
                self._options.append((key, key))
            self.set_options(self._options)
            self.changed.emit(self._selected)

    def clear(self) -> None:
        if self._selected:
            self._selected = frozenset()
            self.set_options(self._options)
            self.changed.emit(self._selected)

    def _on_action(self, key: str, checked: bool) -> None:
        self._selected = self._selected | {key} if checked else self._selected - {key}
        self._sync()
        self.changed.emit(self._selected)

    def _sync(self) -> None:
        count = len(self._selected)
        self.setText(f"{self._name} ({count}) ▾" if count else f"{self._name} ▾")
        state = f"{count} selected" if count else "none selected"
        self.setAccessibleName(f"{self._name} filter, {state}")
