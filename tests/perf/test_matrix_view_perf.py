"""
Performance budgets for the split view (spec-03-split-view.md section 14).

Measured through a real MatrixView (offscreen) on the reference dataset:
1,000 principals × 20,000 objects × 200,000 explicit permissions. Each test
asserts against 3× its budget, like the step 1 tests, and prints the time. Run with:

    pytest -m slow tests/perf -s --no-cov
"""

import dataclasses
import gc
import time
import tracemalloc

import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from src.models.permission import PermissionState
from src.qt.session import Session
from src.qt.views.matrix.jump_dialog import search_jump
from src.qt.views.matrix.matrix_view import MatrixView
from src.services.matrix import CellRef
from src.services.matrix_index import PermissionIndex
from tests.perf.synthetic import make_snapshot
from tests.perf.test_perf import EXPLICIT, OBJECTS, PRINCIPALS, check

pytestmark = pytest.mark.slow


def best_of(fn, repeat: int = 3) -> float:
    """Fastest of `repeat` runs of fn() plus the events it posts, in seconds."""
    best = float("inf")
    for _ in range(repeat):
        gc.collect()
        started = time.perf_counter()
        fn()
        QCoreApplication.processEvents()
        best = min(best, time.perf_counter() - started)
    return best


@pytest.fixture(scope="module")
def loaded():
    snapshot = dataclasses.replace(make_snapshot(PRINCIPALS, OBJECTS, EXPLICIT), privileged=True)
    return snapshot, PermissionIndex.build(snapshot, None)


def make_view(qtbot, tmp_path):
    session = Session()
    view = MatrixView(session, QSettings(str(tmp_path / "perf.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(view)
    view.resize(1400, 900)
    view.show()
    QCoreApplication.processEvents()
    return session, view


@pytest.fixture
def view(qtbot, loaded, tmp_path):
    """The view exists before the data arrives, as in the app."""
    session, view = make_view(qtbot, tmp_path)
    gc.collect()
    started = time.perf_counter()
    session.apply_snapshot(*loaded)
    QCoreApplication.processEvents()
    view.load_seconds = time.perf_counter() - started
    yield view
    session.worker.shutdown(1000)


def repaint(pane) -> None:
    pane.grid.viewport().repaint()


def test_load_on_ui_thread(view):
    # The index is built on the worker; this is the UI-thread part (step 2 follow-up)
    check("Apply snapshot + build visible pane (UI thread)", view.load_seconds, 0.100)


def test_select_principal_all_objects(view):
    pane = view.pane
    principals = iter(range(10, 20))
    seconds = best_of(lambda: (pane.show_entity(next(principals)), repaint(pane)))
    check("Select a principal, All objects (20,000 rows) + paint", seconds, 0.080)


def test_select_busiest_only_with_access(view):
    pane = view.pane
    ix = view.session.matrix.index
    busiest = max(range(len(ix.principals)), key=lambda p: len(ix.objects_by_principal[p]))
    pane.header.segment.set_value("access")
    pane.header._read_controls()
    pane.model.filters = pane.header.filters
    seconds = best_of(lambda: (pane.show_entity(busiest), repaint(pane)))
    check(f"Select busiest principal, Only with access ({pane.model.item_count():,} rows)", seconds, 0.030)


def test_grid_filter_keystroke(view):
    pane = view.pane
    texts = iter(["Table01", "Table012", "Table0123"])

    def keystroke():
        pane.header.search.setText(next(texts))
        pane.header._read_controls()
        pane._on_filters()
        repaint(pane)

    check("Grid filter keystroke (objects)", best_of(keystroke), 0.050)


def test_left_search_keystroke(view):
    pane = view.pane
    texts = iter(["user0", "user00", "user001"])

    def keystroke():
        pane.left.filters.text = next(texts)
        pane.left.refresh()

    check("Left list search keystroke (principals)", best_of(keystroke), 0.020)


def test_paint_one_screen(view):
    check("Paint one screen of grid", best_of(lambda: repaint(view.pane), repeat=5), 0.016)


def test_stage_1000_and_repaint(view):
    pane = view.pane
    ix = view.session.matrix.index
    p = pane.model.entity
    cells = [CellRef(p, o, 0) for o in ix.object_order if ix.is_applicable(o, 0)][:1000]
    started = time.perf_counter()
    view.session.matrix.stage(cells, PermissionState.DENY)
    repaint(pane)
    QCoreApplication.processEvents()
    check("Stage 1,000 cells + repaint affected rows", time.perf_counter() - started, 0.100)


def test_mode_switch_with_reveal(view):
    pane = view.pane
    ix = view.session.matrix.index
    view.set_mode("object", follow=False)  # first switch builds the other pane
    view.set_mode("principal", follow=False)
    pane.grid.setCurrentIndex(pane.model.index_for_row(ix.object_order[500], 1))

    def switch():
        view.set_mode("object" if view.mode == "principal" else "principal")
        view.pane.grid.viewport().repaint()

    check("Mode switch with the focused cell carried over", best_of(switch, repeat=4), 0.080)


def test_jump_keystroke(view):
    ix = view.session.matrix.index
    queries = iter(["t", "ta", "table0004"])
    check("Jump box keystroke", best_of(lambda: search_jump(ix, next(queries))), 0.030)


def test_memory_added_by_view(qtbot, loaded, tmp_path):
    session, view = make_view(qtbot, tmp_path)
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    session.apply_snapshot(*loaded)
    QCoreApplication.processEvents()
    view.set_mode("object", follow=False)  # build both panes
    added_mb = (tracemalloc.get_traced_memory()[0] - before) / 1_000_000
    tracemalloc.stop()
    print(f"\n  {'Memory added by the view (index built beforehand)':<55} {added_mb:9.1f} MB   (budget 50 MB)")
    assert added_mb <= 50
    session.worker.shutdown(1000)
