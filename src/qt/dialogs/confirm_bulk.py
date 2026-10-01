"""FR-030: confirm before staging 5 or more changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from src.qt.views.matrix.bulk import BulkSummary


class ConfirmBulkDialog(QDialog):
    """
    "Stage 231 changes?" with the counts and a "Don't ask again" checkbox.

    Cancel is the default button and Escape cancels. After exec(), dont_ask says
    whether the checkbox was ticked (only meaningful when accepted).
    """

    def __init__(self, sentence: str, summary: BulkSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        count = summary.changed
        self.setWindowTitle(f"Stage {count:,} changes?")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        heading = QLabel(f"{sentence}.", self)
        heading.setWordWrap(True)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.counts = QLabel(summary.counts_text(), self)
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        self.split = QLabel(f"Changes: {summary.split_text()}", self)
        self.split.setVisible(sum(1 for n in (summary.grants, summary.denies, summary.revokes) if n) > 1)
        layout.addWidget(self.split)
        layout.addWidget(QLabel("You can undo this with Ctrl+Z before committing.", self))

        self.dont_ask_box = QCheckBox("Don't ask again until Bifrost restarts", self)
        layout.addWidget(self.dont_ask_box)

        buttons = QDialogButtonBox(self)
        self.cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.stage_button = buttons.addButton(f"Stage {count:,} changes", QDialogButtonBox.ButtonRole.AcceptRole)
        self.stage_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.cancel_button.setFocus()

    @property
    def dont_ask(self) -> bool:
        return self.dont_ask_box.isChecked()


def confirm_bulk(parent: QWidget, sentence: str, summary: BulkSummary) -> tuple[bool, bool]:
    """Show the dialog. Returns (accepted, don't ask again)."""
    dialog = ConfirmBulkDialog(sentence, summary, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return accepted, accepted and dialog.dont_ask
