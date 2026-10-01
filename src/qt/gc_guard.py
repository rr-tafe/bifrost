"""
Run Python's garbage collector on the UI thread only.

Python's cyclic garbage collector runs on whichever thread happens to allocate
when a threshold is crossed. If it collects a QObject there (for example a
dialog or Session caught in a reference cycle), Qt destroys the object and its
timers on the wrong thread, which crashes later inside Qt's timer handling.

UiThreadGarbageCollector disables automatic collection and instead collects
from a QTimer on the UI thread, using the same thresholds Python would.
"""

from __future__ import annotations

import gc
import logging

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger("bifrost.gc")

CHECK_INTERVAL_MS = 1000


class UiThreadGarbageCollector(QObject):
    """Collects garbage on the UI thread every CHECK_INTERVAL_MS when thresholds are reached."""

    def __init__(self, parent: QObject | None = None, interval_ms: int = CHECK_INTERVAL_MS) -> None:
        super().__init__(parent)
        self._thresholds = gc.get_threshold()
        gc.disable()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def check(self) -> None:
        """Collect the generations whose counts passed their thresholds."""
        counts = gc.get_count()
        for generation in (2, 1, 0):
            threshold = self._thresholds[generation]
            if threshold and counts[generation] > threshold:
                gc.collect(generation)
                return

    def stop(self) -> None:
        """Stop collecting from the timer and give control back to Python."""
        self._timer.stop()
        gc.collect()
        gc.enable()
