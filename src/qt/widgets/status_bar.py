"""
The main window's status bar.

Left to right: connection pill (with Reconnect when offline), message area with
progress and Cancel, pending pill, Undo, Discard, Review…, Commit N.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QWidget,
)

from src.qt.theme import Tokens, tokens
from src.qt.widgets.pills import ConnectionPill, PendingPill


class BifrostStatusBar(QStatusBar):
    """
    Status bar with connection state, messages, progress and commit controls.

    Signals:
        cancelRequested: the user clicked Cancel on a running task
    """

    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)

        self.connection_pill = ConnectionPill(self)
        self.reconnect_button = QPushButton("Reconnect", self)
        self.reconnect_button.setAccessibleName("Reconnect to the database")
        self.reconnect_button.hide()

        self.message_label = QLabel("", self)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message_label.setAccessibleName("Status message")
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(160)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Progress")
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setAccessibleName("Cancel the running task")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancelRequested)

        self.pending_pill = PendingPill(self)
        self.undo_button = QPushButton("Undo", self)
        self.discard_button = QPushButton("Discard", self)
        self.review_button = QPushButton("Review…", self)
        self.commit_button = QPushButton("Commit", self)
        self.commit_button.setDefault(False)
        self.undo_button.setAccessibleName("Undo the last change")
        self.discard_button.setAccessibleName("Discard all staged changes")
        self.review_button.setAccessibleName("Review staged changes before committing")

        left = QWidget(self)
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(4, 0, 4, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.connection_pill)
        left_layout.addWidget(self.reconnect_button)
        left_layout.addWidget(self.message_label, 1)
        left_layout.addWidget(self.progress)
        left_layout.addWidget(self.cancel_button)
        self.addWidget(left, 1)

        right = QWidget(self)
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(6)
        for widget in (self.pending_pill, self.undo_button, self.discard_button, self.review_button, self.commit_button):
            right_layout.addWidget(widget)
        self.addPermanentWidget(right)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_transient)
        self._busy_text = ""
        self.set_staged_count(0)
        self.apply_theme()

    # --- Messages ------------------------------------------------------------------

    def show_status(self, text: str, timeout_ms: int = 0) -> None:
        """Show a message. timeout_ms 0 keeps it until replaced."""
        self.message_label.setText(text)
        self.message_label.setToolTip(text)
        if timeout_ms:
            self._message_timer.start(timeout_ms)
        else:
            self._message_timer.stop()

    def _clear_transient(self) -> None:
        self.message_label.setText(self._busy_text)
        self.message_label.setToolTip(self._busy_text)

    def show_busy(self, text: str, progress: tuple[int, int] | None, cancellable: bool = False) -> None:
        """
        Show a long-running task. Empty text clears it.

        Args:
            text: What is running
            progress: (value, maximum) for a determinate bar, or None for indeterminate
            cancellable: Show the Cancel button
        """
        self._busy_text = text
        if not text:
            self.progress.hide()
            self.cancel_button.hide()
            if not self._message_timer.isActive():
                self.message_label.setText("")
            return
        self._message_timer.stop()
        self.message_label.setText(text)
        self.message_label.setToolTip(text)
        if progress is None:
            self.progress.setRange(0, 0)
        else:
            value, maximum = progress
            self.progress.setRange(0, max(maximum, 1))
            self.progress.setValue(min(value, maximum))
        self.progress.show()
        self.cancel_button.setVisible(cancellable)

    # --- Counts --------------------------------------------------------------------

    def set_staged_count(self, count: int) -> None:
        self.pending_pill.set_count(count)
        self.commit_button.setText(f"Commit {count:,}" if count else "Commit")
        self.commit_button.setAccessibleName(
            f"Review and commit {count:,} staged changes" if count else "Commit, no staged changes"
        )
        self.discard_button.setAccessibleName(
            f"Discard {count:,} staged changes" if count else "Discard, no staged changes"
        )

    def apply_theme(self, t: Tokens | None = None) -> None:
        t = t or tokens()
        self.connection_pill.apply_theme(t)
        self.pending_pill.apply_theme(t)
        self.commit_button.setStyleSheet(
            "QPushButton:enabled {"
            f" background: {t.accent}; color: {t.surface}; border: 1px solid {t.accent};"
            " border-radius: 4px; padding: 3px 12px; font-weight: 600; }"
            f"QPushButton:focus {{ border: 2px solid {t.fg}; }}"
        )
