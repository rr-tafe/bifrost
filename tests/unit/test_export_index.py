"""Tests for export_permissions_from_index(): same output as the legacy exporter, plus cancel and progress."""

import threading

import pytest

from src.models.permission import PermissionState, PermissionType
from src.services import export as export_module
from src.services.export import export_permissions_csv, export_permissions_from_index
from src.services.matrix import PermissionMatrix
from tests.perf.synthetic import make_snapshot


@pytest.fixture
def matrix() -> PermissionMatrix:
    m = PermissionMatrix(None)
    m.apply_snapshot(make_snapshot(principals=15, objects=40, explicit=150, seed=11))
    first = m.users[0].login_name
    obj = m.objects[0]
    m.stage_change(first, obj.schema_name, obj.object_name, PermissionType.ALTER, PermissionState.DENY)
    return m


@pytest.mark.parametrize("include_none", [False, True])
def test_matches_legacy_export(tmp_path, matrix, include_none):
    legacy = tmp_path / "legacy.csv"
    new = tmp_path / "new.csv"
    assert export_permissions_csv(legacy, matrix.users, matrix.objects, matrix.assignments, include_none) is None
    assert export_permissions_from_index(new, matrix.index, include_none) is None
    assert new.read_text(encoding="utf-8") == legacy.read_text(encoding="utf-8")


def test_handles_awkward_names(tmp_path, matrix):
    path = tmp_path / "out.csv"
    export_permissions_from_index(path, matrix.index, include_none=True)
    text = path.read_text(encoding="utf-8")
    assert "Zoë Müller" in text
    assert '"Sales Dept"' not in text  # spaces don't need quoting
    assert "it's" in text


def test_progress_and_cancel(tmp_path, matrix, monkeypatch):
    monkeypatch.setattr(export_module, "EXPORT_PROGRESS_EVERY", 100)
    calls = []
    path = tmp_path / "out.csv"
    export_permissions_from_index(path, matrix.index, include_none=True, progress_callback=lambda n, t: calls.append((n, t)))
    total = calls[-1][1]
    assert calls[-1][0] == total
    assert [n for n, _ in calls[:-1]] == list(range(100, total + 1, 100))[: len(calls) - 1]

    cancel = threading.Event()
    cancel.set()
    error = export_permissions_from_index(path, matrix.index, include_none=True, cancel=cancel)
    assert error == "Export cancelled"
    assert not path.exists()


def test_write_error(tmp_path, matrix):
    folder = tmp_path / "dir"
    folder.mkdir()
    error = export_permissions_from_index(folder, matrix.index)
    assert error is not None
