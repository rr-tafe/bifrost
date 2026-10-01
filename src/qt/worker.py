"""
Background work for the Qt UI.

DbWorker runs database jobs one at a time, in submission order, on a single
background thread, so the shared pyodbc connection is never used from two
threads at once and the UI thread never blocks on the database.

run_detached() runs work that doesn't need the shared connection (connection
tests, writing CSV files) on its own short-lived thread.

Callbacks (on_done, on_error, on_progress) always run on the UI thread.

Callbacks are kept in a registry on the UI thread and never handed to the
worker thread; the worker only sends back a job id with the result. This
matters: if a callback holding the last reference to a QObject (e.g. a
Session) were released on the worker thread, Qt would destroy that object on
the wrong thread and crash.

Warning:
    A job function runs on a worker thread. It must not touch PermissionMatrix,
    PermissionIndex or any QObject. Pass it plain data and return plain data.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("bifrost.worker")

_SUPERSEDED = object()  # finished payload for a coalesced-away job: drop callbacks silently


class JobCancelledError(Exception):
    """Delivered to on_error when a job is cancelled before it starts."""


@dataclass(frozen=True)
class JobContext:
    """
    Passed to every job function.

    Attributes:
        cancel_event: Set when the job should stop; long jobs check it
        report: Thread-safe; delivers a progress value to on_progress on the UI thread
    """

    cancel_event: threading.Event
    report: Callable[[object], None]


@dataclass(eq=False)
class JobHandle:
    """A submitted job. Call cancel() to ask it to stop."""

    name: str
    job_id: int = 0
    cancel_event: threading.Event = field(default_factory=threading.Event)
    superseded: bool = False
    started: bool = False

    def cancel(self) -> None:
        """Ask the job to stop (queued jobs never start; running jobs see cancel_event)."""
        self.cancel_event.set()


@dataclass
class _Callbacks:
    """UI-thread-only record of a job's callbacks."""

    name: str
    on_done: Callable[[Any], None] | None
    on_error: Callable[[BaseException], None] | None
    on_progress: Callable[[object], None] | None
    fallback_error: Callable[[str, BaseException], None] | None


class _Dispatcher(QObject):
    """
    Lives on the UI thread. Holds job callbacks and runs them when the worker
    thread reports progress or completion.
    """

    progress = Signal(int, object)  # job id, value
    finished = Signal(int, object, object)  # job id, result, error

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, _Callbacks] = {}
        self._ids = itertools.count(1)
        self.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)

    def register(self, callbacks: _Callbacks) -> int:
        """Store callbacks (UI thread) and return a job id."""
        job_id = next(self._ids)
        self._callbacks[job_id] = callbacks
        return job_id

    def _on_progress(self, job_id: int, value: object) -> None:
        callbacks = self._callbacks.get(job_id)
        if callbacks is not None and callbacks.on_progress is not None:
            self._safe(callbacks.on_progress, value)

    def _on_finished(self, job_id: int, result: object, error: object) -> None:
        callbacks = self._callbacks.pop(job_id, None)
        if callbacks is None or result is _SUPERSEDED:
            return
        if error is None:
            if callbacks.on_done is not None:
                self._safe(callbacks.on_done, result)
        elif callbacks.on_error is not None:
            self._safe(callbacks.on_error, error)
        elif callbacks.fallback_error is not None:
            self._safe(lambda e: callbacks.fallback_error(callbacks.name, e), error)
        else:
            logger.error("Job %s failed: %s", callbacks.name, error)

    @staticmethod
    def _safe(fn: Callable[[Any], None], value: object) -> None:
        try:
            fn(value)
        except Exception:
            logger.exception("Callback failed")


_dispatcher: _Dispatcher | None = None


def _get_dispatcher() -> _Dispatcher:
    """Return the UI-thread dispatcher, creating it on first use (must be on the UI thread)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
        app = QCoreApplication.instance()
        if app is not None:
            _dispatcher.moveToThread(app.thread())
    return _dispatcher


def _context(handle: JobHandle, dispatcher: _Dispatcher) -> JobContext:
    job_id = handle.job_id

    def report(value: object) -> None:
        dispatcher.progress.emit(job_id, value)

    return JobContext(cancel_event=handle.cancel_event, report=report)


class DbWorker(QObject):
    """
    Serial job queue on one background thread.

    Signals:
        jobError(str, object): a job failed and had no on_error callback (name, exception)
    """

    jobError = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dispatcher = _get_dispatcher()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bifrost-db")
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._queued: list[JobHandle] = []
        self._running: JobHandle | None = None
        self._pending = 0
        self._closed = False

    def submit(
        self,
        name: str,
        fn: Callable[[JobContext], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[object], None] | None = None,
        coalesce: bool = False,
    ) -> JobHandle:
        """
        Queue a job (call on the UI thread).

        Args:
            name: Job name (for logs and coalescing)
            fn: Runs on the worker thread; receives a JobContext. Must not capture QObjects.
            on_done: Called on the UI thread with fn's return value
            on_error: Called on the UI thread with the exception. If None, the
                jobError signal is emitted instead.
            on_progress: Called on the UI thread with each value fn reports
            coalesce: Replace a queued (not yet running) job with the same name

        Returns:
            JobHandle: Use handle.cancel() to stop it
        """
        dispatcher = self._dispatcher
        handle = JobHandle(name)
        handle.job_id = dispatcher.register(_Callbacks(name, on_done, on_error, on_progress, self._emit_job_error))
        with self._lock:
            if self._closed:
                handle.cancel()
                dispatcher.finished.emit(handle.job_id, None, JobCancelledError(f"{name}: worker is shut down"))
                return handle
            if coalesce:
                for queued in self._queued:
                    if queued.name == name and not queued.superseded:
                        queued.superseded = True
            self._queued.append(handle)
            self._pending += 1
        self._executor.submit(self._run, handle, fn)
        return handle

    def _run(self, handle: JobHandle, fn: Callable[[JobContext], Any]) -> None:
        """Worker thread: run one job and report back by job id."""
        with self._lock:
            self._queued.remove(handle)
            skip = handle.superseded or handle.cancel_event.is_set()
            if not skip:
                handle.started = True
                self._running = handle
        result: Any = None
        error: BaseException | None = None
        if skip:
            if handle.superseded:
                result = _SUPERSEDED
            else:
                error = JobCancelledError(f"{handle.name} was cancelled before it started")
        else:
            started = time.perf_counter()
            try:
                result = fn(_context(handle, self._dispatcher))
            except BaseException as e:  # noqa: BLE001 - delivered to the UI thread
                error = e
            logger.info(
                "Job %s %s in %.0f ms",
                handle.name,
                "failed" if error else "finished",
                (time.perf_counter() - started) * 1000,
            )
        fn = None  # drop job references here, before signalling
        with self._lock:
            self._running = None
            self._pending -= 1
            self._idle.notify_all()
        self._dispatcher.finished.emit(handle.job_id, _SUPERSEDED if handle.superseded else result, error)

    def _emit_job_error(self, name: str, error: BaseException) -> None:
        logger.error("Job %s failed: %s", name, error)
        self.jobError.emit(name, error)

    def is_idle(self) -> bool:
        """True when no job is queued or running."""
        with self._lock:
            return self._pending == 0

    def running_job(self) -> str | None:
        """Name of the job running now, if any."""
        with self._lock:
            return self._running.name if self._running else None

    def wait_idle(self, timeout: float) -> bool:
        """Block until no job is queued or running. Returns False on timeout (for shutdown and tests)."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    def shutdown(self, wait_ms: int = 5000) -> bool:
        """
        Cancel queued jobs, ask the running job to stop, and wait for it.

        Returns:
            bool: True if the worker finished within wait_ms
        """
        with self._lock:
            self._closed = True
            for queued in self._queued:
                queued.superseded = True
            if self._running is not None:
                self._running.cancel()
        finished = self.wait_idle(wait_ms / 1000)
        self._executor.shutdown(wait=False, cancel_futures=True)
        return finished


def run_detached(
    name: str,
    fn: Callable[[JobContext], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    on_progress: Callable[[object], None] | None = None,
) -> JobHandle:
    """
    Run fn on its own daemon thread (for work that doesn't use the shared connection).

    Call on the UI thread. Callbacks run on the UI thread, as with DbWorker.submit().
    """
    dispatcher = _get_dispatcher()
    handle = JobHandle(name)
    handle.started = True
    handle.job_id = dispatcher.register(_Callbacks(name, on_done, on_error, on_progress, None))
    context = _context(handle, dispatcher)
    job_id = handle.job_id

    def run(job: Callable[[JobContext], Any]) -> None:
        result: Any = None
        error: BaseException | None = None
        try:
            result = job(context)
        except BaseException as e:  # noqa: BLE001 - delivered to the UI thread
            error = e
        job = None
        dispatcher.finished.emit(job_id, result, error)

    threading.Thread(target=run, args=(fn,), name=f"bifrost-{name}", daemon=True).start()
    return handle
