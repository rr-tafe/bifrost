"""Tests for UiThreadGarbageCollector."""

import gc

from src.qt.gc_guard import UiThreadGarbageCollector


def test_disables_automatic_gc_and_collects_on_check(qtbot):
    gc.enable()
    guard = UiThreadGarbageCollector(interval_ms=60_000)
    try:
        assert not gc.isenabled()
        cycle = []
        cycle.append(cycle)
        del cycle
        for _ in range(gc.get_threshold()[0] + 10):
            [].append([])  # allocate container objects to raise the generation-0 count
            junk = [[]]
            junk.append(junk)
        before = gc.get_count()[0]
        guard.check()
        assert gc.get_count()[0] < before
    finally:
        guard.stop()
    assert gc.isenabled()
