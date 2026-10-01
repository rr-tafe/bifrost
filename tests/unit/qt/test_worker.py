"""Tests for DbWorker and run_detached."""

import threading

import pytest

from src.qt.worker import DbWorker, JobCancelledError, run_detached


@pytest.fixture
def worker(qtbot):
    w = DbWorker()
    yield w
    w.shutdown(2000)


def test_jobs_run_in_order_on_one_background_thread(qtbot, worker):
    ui_thread = threading.current_thread()
    ran_on, done = [], []
    for i in range(5):
        worker.submit(
            f"job{i}",
            lambda _ctx, i=i: (ran_on.append(threading.current_thread()), i)[1],
            on_done=lambda value: done.append((value, threading.current_thread())),
        )
    qtbot.waitUntil(lambda: len(done) == 5, timeout=3000)
    assert [v for v, _ in done] == [0, 1, 2, 3, 4]
    assert all(t is ui_thread for _, t in done)
    assert len({t.name for t in ran_on}) == 1
    assert ran_on[0] is not ui_thread
    assert worker.is_idle()


def test_errors_go_to_on_error_or_signal(qtbot, worker):
    errors = []
    worker.submit("bad", lambda _ctx: 1 / 0, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=3000)
    assert isinstance(errors[0], ZeroDivisionError)
    with qtbot.waitSignal(worker.jobError, timeout=3000) as blocker:
        worker.submit("bad2", lambda _ctx: 1 / 0)
    assert blocker.args[0] == "bad2"


def test_progress_is_delivered_in_order(qtbot, worker):
    seen, done = [], []

    def job(ctx):
        for i in range(5):
            ctx.report(i)
        return "ok"

    worker.submit("progress", job, on_done=done.append, on_progress=seen.append)
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    assert seen == [0, 1, 2, 3, 4]


def test_coalesce_replaces_queued_job(qtbot, worker):
    gate = threading.Event()
    done = []
    worker.submit("block", lambda _ctx: gate.wait(2))
    worker.submit("audit", lambda _ctx: "first", on_done=done.append, coalesce=True)
    worker.submit("audit", lambda _ctx: "second", on_done=done.append, coalesce=True)
    gate.set()
    qtbot.waitUntil(lambda: worker.is_idle(), timeout=3000)
    qtbot.wait(50)
    assert done == ["second"]


def test_cancel_queued_job(qtbot, worker):
    gate = threading.Event()
    errors = []
    worker.submit("block", lambda _ctx: gate.wait(2))
    handle = worker.submit("later", lambda _ctx: "never", on_error=errors.append)
    handle.cancel()
    gate.set()
    qtbot.waitUntil(lambda: bool(errors), timeout=3000)
    assert isinstance(errors[0], JobCancelledError)


def test_running_job_sees_cancel_event(qtbot, worker):
    started = threading.Event()
    done = []

    def job(ctx):
        started.set()
        return ctx.cancel_event.wait(2)

    handle = worker.submit("long", job, on_done=done.append)
    assert started.wait(2)
    handle.cancel()
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    assert done == [True]


def test_shutdown_cancels_queued_and_rejects_new(qtbot):
    worker = DbWorker()
    gate = threading.Event()
    done, errors = [], []
    worker.submit("block", lambda ctx: ctx.cancel_event.wait(2) or gate.wait(0))
    worker.submit("queued", lambda _ctx: "never", on_done=done.append)
    assert worker.shutdown(3000)
    worker.submit("after", lambda _ctx: "never", on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=3000)
    assert done == []
    assert isinstance(errors[0], JobCancelledError)


def test_run_detached_calls_back_on_ui_thread(qtbot):
    ui_thread = threading.current_thread()
    results = []
    run_detached("detached", lambda _ctx: threading.current_thread(), on_done=lambda t: results.append((t, threading.current_thread())))
    qtbot.waitUntil(lambda: bool(results), timeout=3000)
    worker_thread, callback_thread = results[0]
    assert worker_thread is not ui_thread
    assert callback_thread is ui_thread
    errors = []
    run_detached("detached-bad", lambda _ctx: 1 / 0, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=3000)
