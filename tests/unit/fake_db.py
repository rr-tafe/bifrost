"""
A small fake pyodbc connection for unit tests.

FakeConnection answers the catalog queries the loader runs and records every
statement executed, so tests can check SQL text and parameters without a server.
"""

import pyodbc


class Row(tuple):
    """A tuple that also exposes columns as attributes, like pyodbc.Row."""

    def __new__(cls, names: tuple[str, ...], values: tuple):
        row = super().__new__(cls, values)
        row._names = names
        return row

    def __getattr__(self, name):
        try:
            return self[self._names.index(name)]
        except ValueError:
            raise AttributeError(name) from None


class FakeCursor:
    def __init__(self, connection: "FakeConnection"):
        self.connection = connection
        self._rows: list = []

    def execute(self, sql, params=None):
        conn = self.connection
        conn.executed.append((sql, params))
        if conn.fail_on and conn.fail_on(sql):
            raise pyodbc.Error(*conn.fail_error)
        self._rows = list(conn.respond(sql, params))
        return self

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def close(self):
        pass


class FakeConnection:
    """
    Fake pyodbc connection.

    Attributes:
        principals: (principal_id, name, type) rows
        objects: (object_id, schema_name, object_name, type) rows
        permissions: (grantee_principal_id, major_id, permission_name, state) rows
        flags: (sysadmin, db_owner, control) for fetch_privilege_flags
        held: set of (schema, object, permission_name) the admin holds
        fail_on: optional predicate(sql) -> bool; matching statements raise pyodbc.Error
        fail_error: args for that error (default an ordinary SQL error, not a lost connection)
        executed: every (sql, params) executed
    """

    def __init__(self):
        self.principals: list[tuple] = []
        self.objects: list[tuple] = []
        self.permissions: list[tuple] = []
        self.flags = (0, 0, 0)
        self.held: set[tuple[str, str, str]] = set()
        self.fail_on = None
        self.fail_error = ("42000", "[42000] Statement failed")
        self.executed: list[tuple] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def respond(self, sql, params):
        if "sys.database_principals" in sql and "principal_id" in sql:
            names = ("principal_id", "name", "type")
            return [Row(names, r) for r in self.principals]
        if "FROM sys.objects o" in sql and "o.object_id" in sql:
            names = ("object_id", "schema_name", "object_name", "object_type")
            return [Row(names, r) for r in self.objects]
        if "FROM sys.database_permissions AS p" in sql:
            return [tuple(r) for r in self.permissions]
        if "SYSTEM_USER" in sql:
            return [("CORP\\admin",)]
        if "IS_SRVROLEMEMBER" in sql:
            return [self.flags]
        if "HAS_PERMS_BY_NAME(QUOTENAME" in sql:
            rows = []
            for i in range(0, len(params), 3):
                s, o, perm = params[i : i + 3]
                rows.append((s, o, perm, 1 if (s, o, perm) in self.held else 0))
            return rows
        return []

    def statements(self, prefix: str) -> list[str]:
        """Return executed SQL starting with prefix (after stripping whitespace)."""
        return [sql for sql, _ in self.executed if sql.strip().startswith(prefix)]
