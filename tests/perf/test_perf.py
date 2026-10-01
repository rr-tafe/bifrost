"""
Performance budgets for the matrix data layer (spec-01-data-layer.md section 11).

Reference dataset: 1,000 principals × 20,000 objects × 200,000 explicit permissions.
Each test asserts against 3× its budget so slower machines don't flake, and prints
the measured time. Run with:

    pytest -m slow tests/perf -s --no-cov
"""

import gc
import random
import time
import tracemalloc

import pytest

from src.models.permission import PermissionState
from src.services.matrix import CellRef, PermissionMatrix
from src.services.matrix_index import ObjectQuery, PermissionIndex, PrincipalQuery
from tests.perf.synthetic import make_snapshot

pytestmark = pytest.mark.slow

PRINCIPALS = 1_000
OBJECTS = 20_000
EXPLICIT = 200_000
SLACK = 3.0


def best_of(fn, repeat: int = 3, setup=None) -> float:
    """Return the fastest of `repeat` runs of fn(), in seconds. setup() runs untimed before each."""
    best = float("inf")
    for _ in range(repeat):
        if setup is not None:
            setup()
        gc.collect()
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best


def check(name: str, seconds: float, budget: float) -> None:
    print(f"\n  {name:<55} {seconds * 1000:9.1f} ms   (budget {budget * 1000:,.0f} ms)")
    assert seconds <= budget * SLACK, f"{name} took {seconds:.3f}s; budget {budget}s (x{SLACK})"


@pytest.fixture(scope="module")
def snapshot():
    return make_snapshot(PRINCIPALS, OBJECTS, EXPLICIT)


@pytest.fixture(scope="module")
def matrix(snapshot):
    m = PermissionMatrix(None)
    m.apply_snapshot(snapshot)
    return m


def random_cells(matrix: PermissionMatrix, count: int, seed: int = 1, principal: int | None = None) -> list[CellRef]:
    rng = random.Random(seed)
    index = matrix.index
    cells = []
    seen = set()
    while len(cells) < count:
        p = principal if principal is not None else rng.randrange(len(index.principals))
        o = rng.randrange(len(index.objects))
        perm = rng.randrange(8)
        if index.is_applicable(o, perm) and (p, o, perm) not in seen:
            seen.add((p, o, perm))
            cells.append(CellRef(p, o, perm))
    return cells


def test_dataset_shape(snapshot):
    assert len(snapshot.principals) == PRINCIPALS
    assert len(snapshot.objects) == OBJECTS
    assert len(snapshot.permission_rows) == EXPLICIT


def test_index_build(snapshot):
    check("PermissionIndex.build", best_of(lambda: PermissionIndex.build(snapshot)), 1.0)


def test_index_memory(snapshot):
    gc.collect()
    tracemalloc.start()
    index = PermissionIndex.build(snapshot)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del index
    print(f"\n  {'Index memory (tracemalloc peak during build)':<55} {peak / 1e6:9.1f} MB   (budget 150 MB)")
    assert peak <= 150e6 * SLACK


def test_row_state_million_calls(matrix):
    index = matrix.index
    p_count, o_count = len(index.principals), len(index.objects)
    keys = [(i % p_count, (i * 7919) % o_count) for i in range(1_000_000)]
    row_state = index.row_state

    def run():
        for p, o in keys:
            row_state(p, o)

    check("row_state x 1,000,000", best_of(run), 0.5)


def test_query_objects_text(matrix):
    index = matrix.index
    check("query_objects(text='ord')", best_of(lambda: index.query_objects(ObjectQuery(text="ord"))), 0.030)
    check(
        "query_objects(text='table01') (broad match)",
        best_of(lambda: index.query_objects(ObjectQuery(text="table01"))),
        0.030,
    )


def test_query_objects_with_access_for_busiest(matrix):
    index = matrix.index
    busiest = max(range(len(index.principals)), key=lambda p: len(index.objects_by_principal[p]))
    query = ObjectQuery(with_access_for=busiest)
    seconds = best_of(lambda: index.query_objects(query))
    print(f"\n  (busiest principal has {len(index.objects_by_principal[busiest]):,} objects)", end="")
    check("query_objects(with_access_for=busiest)", seconds, 0.010)


def test_query_objects_all(matrix):
    index = matrix.index
    check("query_objects() unfiltered", best_of(lambda: index.query_objects(ObjectQuery())), 0.030)


def test_query_principals(matrix):
    index = matrix.index
    query = PrincipalQuery(text="smi", types=frozenset({"U"}))
    check("query_principals(text='smi', types={'U'})", best_of(lambda: index.query_principals(query)), 0.005)
    broad = PrincipalQuery(text="user0")
    found = len(index.query_principals(broad))
    check(f"query_principals(text='user0') ({found} matches)", best_of(lambda: index.query_principals(broad)), 0.005)


def test_stage_1000_cells(matrix):
    cells = random_cells(matrix, 1_000, seed=2)
    seconds = best_of(lambda: matrix.stage(cells, PermissionState.GRANT), setup=matrix.cancel)
    assert matrix.get_staged_change_count() > 950
    matrix.cancel()
    check("stage 1,000 cells", seconds, 0.050)


def test_stage_20000_cells(matrix):
    cells = random_cells(matrix, 20_000, seed=3)
    seconds = best_of(lambda: matrix.stage(cells, PermissionState.DENY), setup=matrix.cancel)
    matrix.cancel()
    check("stage 20,000 cells", seconds, 1.0)


def test_undo_1000_cell_group(matrix):
    cells = random_cells(matrix, 1_000, seed=4)

    def setup():
        matrix.cancel()
        matrix.stage(cells, PermissionState.GRANT)

    seconds = best_of(matrix.undo, setup=setup)
    matrix.cancel()
    check("undo a 1,000-cell group", seconds, 0.050)


def test_get_staged_changes_1000(matrix):
    matrix.cancel()
    result = matrix.stage(random_cells(matrix, 1_000, seed=5), PermissionState.GRANT)
    seconds = best_of(matrix.get_staged_changes)
    assert len(matrix.get_staged_changes()) == result.changed > 950
    matrix.cancel()
    check("get_staged_changes with 1,000 staged", seconds, 0.020)


def test_apply_snapshot_preserving_1000_staged(snapshot):
    m = PermissionMatrix(None)
    m.apply_snapshot(snapshot)
    cells = random_cells(m, 1_000, seed=6)

    def setup():
        m.cancel()
        m.stage(cells, PermissionState.GRANT)

    seconds = best_of(lambda: m.apply_snapshot(snapshot), setup=setup)
    check("apply_snapshot keeping 1,000 staged changes", seconds, 1.3)
