"""
Synthetic matrix data for tests.

make_snapshot() builds a deterministic MatrixSnapshot shaped like a real work
database: mostly tables, mostly Windows users, and a few service accounts and
broad groups that hold most of the permissions. A few names contain awkward
characters (brackets, quotes, dots, spaces, non-ASCII) to catch quoting bugs.
"""

import random

from src.models.db_object import DatabaseObject, ObjectType
from src.models.permission import STATE_DENY, STATE_GRANT
from src.models.user import DatabaseUser
from src.services.loader import MatrixSnapshot
from src.services.matrix_index import APPLICABLE_MASK, PERM_COUNT

# Names with characters that break naive SQL or CSV handling
AWKWARD_PRINCIPALS = ["CORP\\o'brien", "weird]name", "Zoë Müller", "dot.user", "has space"]
AWKWARD_SCHEMAS = ["Sales Dept", "fin]ance"]
AWKWARD_OBJECTS = ["Order Lines", "it's", "a.b", "close]bracket", "Größe"]

_OBJECT_TYPES = [
    (ObjectType.TABLE, 0.70),
    (ObjectType.VIEW, 0.10),
    (ObjectType.PROCEDURE, 0.15),
    (ObjectType.FUNCTION, 0.05),
]
_PRINCIPAL_TYPES = [("U", 0.70), ("G", 0.20), ("S", 0.10)]


def _pick(rng: random.Random, weighted):
    roll = rng.random()
    total = 0.0
    for value, weight in weighted:
        total += weight
        if roll < total:
            return value
    return weighted[-1][0]


def make_principals(count: int, rng: random.Random) -> list[DatabaseUser]:
    """Return count principals with unique names and principal_ids starting at 5."""
    principals = []
    for i in range(count):
        principal_type = _pick(rng, _PRINCIPAL_TYPES)
        if i < len(AWKWARD_PRINCIPALS):
            name = AWKWARD_PRINCIPALS[i]
        elif principal_type == "U":
            name = f"CORP\\user{i:05d}"
        elif principal_type == "G":
            name = f"CORP\\grp-{i:05d}"
        else:
            name = f"svc_{i:05d}"
        principals.append(
            DatabaseUser(
                login_name=name,
                display_name=name,
                principal_type=principal_type,
                principal_id=5 + i,
            )
        )
    principals.sort(key=lambda u: u.login_name.casefold())
    return principals


def make_objects(count: int, schemas: int, rng: random.Random) -> list[DatabaseObject]:
    """Return count objects spread across schemas, with object_ids starting at 1000."""
    schema_names = [f"sch{i:02d}" for i in range(schemas)]
    for i, awkward in enumerate(AWKWARD_SCHEMAS):
        if i < len(schema_names):
            schema_names[i] = awkward
    objects = []
    for i in range(count):
        object_type = _pick(rng, _OBJECT_TYPES)
        if i < len(AWKWARD_OBJECTS):
            name = AWKWARD_OBJECTS[i]
        else:
            prefix = {
                ObjectType.TABLE: "Table",
                ObjectType.VIEW: "vw_",
                ObjectType.PROCEDURE: "usp_",
                ObjectType.FUNCTION: "fn_",
            }[object_type]
            name = f"{prefix}{i:06d}"
        objects.append(
            DatabaseObject(
                schema_name=schema_names[i % len(schema_names)],
                object_name=name,
                object_type=object_type,
                object_id=1000 + i,
            )
        )
    objects.sort(key=lambda o: (o.schema_name.casefold(), o.object_name.casefold()))
    return objects


def make_snapshot(
    principals: int,
    objects: int,
    explicit: int,
    seed: int = 7,
    deny_ratio: float = 0.02,
    schemas: int = 25,
) -> MatrixSnapshot:
    """
    Build a deterministic snapshot.

    Args:
        principals: Number of principals
        objects: Number of objects
        explicit: Number of explicit GRANT/DENY cells (unique)
        seed: Random seed; the same arguments always give the same snapshot
        deny_ratio: Share of explicit cells that are DENY
        schemas: Number of schemas objects are spread across

    Returns:
        MatrixSnapshot: Principals, objects and permission rows; current_user "CORP\\admin"
    """
    rng = random.Random(seed)
    principal_list = make_principals(principals, rng)
    object_list = make_objects(objects, schemas, rng)

    applicable_perms = [
        [i for i in range(PERM_COUNT) if APPLICABLE_MASK[o.object_type] & (1 << i)]
        for o in object_list
    ]
    capacity = principals * sum(len(perms) for perms in applicable_perms)
    explicit = min(explicit, capacity)

    # 5% of principals (service accounts, broad groups) hold ~60% of the permissions
    heavy = rng.sample(range(principals), max(1, principals // 20))
    cells: set[tuple[int, int, int]] = set()
    attempts = 0
    while len(cells) < explicit and attempts < explicit * 20:
        attempts += 1
        p = rng.choice(heavy) if rng.random() < 0.6 else rng.randrange(principals)
        o = rng.randrange(objects)
        perm = rng.choice(applicable_perms[o])
        cells.add((p, o, perm))

    rows = []
    for p, o, perm in sorted(cells):
        code = STATE_DENY if rng.random() < deny_ratio else STATE_GRANT
        rows.append((principal_list[p].principal_id, object_list[o].object_id, perm, code))

    return MatrixSnapshot(
        principals=tuple(principal_list),
        objects=tuple(object_list),
        permission_rows=tuple(rows),
        current_user="CORP\\admin",
        privileged=False,
    )
