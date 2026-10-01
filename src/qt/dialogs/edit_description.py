"""Edit an object's MS_Description (FR-023). Saved immediately; not staged or audited."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

MAX_LENGTH = 7_500


class EditDescriptionDialog(QDialog):
    """After exec(), text holds the new description ("" removes it)."""

    def __init__(self, full_name: str, text: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Description of {full_name}")
        self.setMinimumSize(480, 300)
        layout = QVBoxLayout(self)
        note = QLabel("Descriptions save immediately. They aren't staged or audited.", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(text or "")
        self.editor.setAccessibleName(f"Description of {full_name}")
        self.editor.setTabChangesFocus(True)
        layout.addWidget(self.editor, 1)
        self.counter = QLabel("", self)
        layout.addWidget(self.counter)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.save_button = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.editor.textChanged.connect(self._update_counter)
        self._update_counter()

    @property
    def text(self) -> str:
        return self.editor.toPlainText()

    def _update_counter(self) -> None:
        length = len(self.text)
        self.counter.setText(f"{length:,} of {MAX_LENGTH:,} characters")
        self.save_button.setEnabled(length <= MAX_LENGTH)
