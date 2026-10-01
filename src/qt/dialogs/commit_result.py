"""
Commit results: a success summary (5 or more changes) and the partial-failure dialog.

Neither dialog closes itself (WCAG 2.2.1); small successes go to the status bar instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.qt.dialogs.commit_preview import ChangeTableModel, make_change_table
from src.qt.session import describe_change

if TYPE_CHECKING:
    from src.qt.session import CommitReport

SUMMARY_LINES = 5


class CommitSuccessDialog(QDialog):
    """
    "12 changes applied". exec() returns Accepted if the user chose View audit log.
    """

    def __init__(self, report: CommitReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        count = len(report.succeeded)
        self.setWindowTitle("Changes applied")
        layout = QVBoxLayout(self)
        heading = QLabel(f"✓ {count:,} changes applied", self)
        font = heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.2)
        heading.setFont(font)
        layout.addWidget(heading)
        lines = [f"• {describe_change(c)}" for c in report.succeeded[:SUMMARY_LINES]]
        if count > SUMMARY_LINES:
            lines.append(f"and {count - SUMMARY_LINES:,} more")
        body = QLabel("\n".join(lines), self)
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(self)
        view_audit = buttons.addButton("View audit log", QDialogButtonBox.ButtonRole.AcceptRole)
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.setDefault(True)
        view_audit.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PartialFailureDialog(QDialog):
    """
    Some changes failed. Failed changes stay staged.

    After exec(), choice is "keep", "discard_failed" or "view_audit".
    """

    def __init__(self, report: CommitReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = "keep"
        total = len(report.succeeded) + len(report.failed)
        self.setWindowTitle("Some changes failed")
        self.resize(820, 460)
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"⚠ {len(report.succeeded):,} of {total:,} changes applied. "
            f"{len(report.failed):,} failed and are still staged.",
            self,
        )
        heading.setWordWrap(True)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        model = ChangeTableModel(
            [c for c, _ in report.failed], reasons=[reason for _, reason in report.failed], parent=self
        )
        table, _proxy = make_change_table(model, self, "Failed changes")
        layout.addWidget(table, 1)

        if report.succeeded:
            self.toggle = QPushButton(f"Show the {len(report.succeeded):,} changes that were applied", self)
            self.toggle.setCheckable(True)
            self.applied = QListWidget(self)
            self.applied.addItems([describe_change(c) for c in report.succeeded])
            self.applied.setAccessibleName("Applied changes")
            self.applied.hide()
            self.toggle.toggled.connect(self.applied.setVisible)
            layout.addWidget(self.toggle)
            layout.addWidget(self.applied)

        buttons = QDialogButtonBox(self)
        view_audit = buttons.addButton("View audit log", QDialogButtonBox.ButtonRole.ActionRole)
        discard = buttons.addButton("Discard failed", QDialogButtonBox.ButtonRole.DestructiveRole)
        keep = buttons.addButton("Keep for retry", QDialogButtonBox.ButtonRole.AcceptRole)
        keep.setDefault(True)
        view_audit.setEnabled(bool(report.succeeded))
        view_audit.clicked.connect(lambda: self._choose("view_audit"))
        discard.clicked.connect(lambda: self._choose("discard_failed"))
        keep.clicked.connect(lambda: self._choose("keep"))
        layout.addWidget(buttons)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def reject(self) -> None:  # Escape keeps failed changes staged
        self.choice = "keep"
        super().reject()
