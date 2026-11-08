"""Matched maintenance tasks with a bounded, read-only in-memory SQL checker."""

import math
import sqlite3

from .simulation import Simulation, TEXT, tool


SQL_FUNCTIONS = {"coalesce", "count", "max", "min", "row_number", "sum"}
SQL_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}


def authorize(action, name, argument, database, _trigger):
    if action == sqlite3.SQLITE_READ:
        permitted = database == "main" and name == "reviews"
    elif action == sqlite3.SQLITE_FUNCTION:
        permitted = argument in SQL_FUNCTIONS
    else:
        permitted = action in SQL_ACTIONS
    return sqlite3.SQLITE_OK if permitted else sqlite3.SQLITE_DENY


def query_rows(sql, records):
    database = sqlite3.connect(":memory:")
    try:
        database.execute(
            "CREATE TABLE reviews (item TEXT, revision INTEGER, cohort TEXT, status TEXT, flags INTEGER)"
        )
        database.executemany("INSERT INTO reviews VALUES (?, ?, ?, ?, ?)", records)
        database.execute("PRAGMA temp_store = MEMORY")
        database.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8_192)
        database.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
        database.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 12)
        database.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 50)
        database.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 32_768)
        database.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        database.set_authorizer(authorize)
        remaining = 100

        def budget():
            nonlocal remaining
            remaining -= 1
            return remaining == 0

        database.set_progress_handler(budget, 100)
        cursor = database.execute(sql)
        if cursor.description is None:
            raise ValueError("A SELECT query is required")
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(65)
        if len(rows) > 64:
            raise ValueError("The query returned more than 64 rows")
        if any(isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value)) for row in rows for value in row):
            raise ValueError("Query results must be finite numbers, text or NULL")
        return columns, [list(row) for row in rows]
    finally:
        database.close()


class PairedQueryMaintenance(Simulation):
    def setup(self):
        self.query_path = self.sample["query_path"]
        if not self.sample["hidden_checks"]:
            raise ValueError("The paired query needs held-out work-item checks")

    @property
    def tools(self):
        return super().tools + [
            tool("query_preview", "Run a SQL file against the workspace's development dataset and return columns and rows.", {"path": TEXT}),
        ]

    def handle(self, name, args):
        if name != "query_preview":
            return super().handle(name, args)
        path = self.path(args["path"])
        if path not in self.world["files"] or self.file_scope(path) != "task-read":
            return {"status": 404, "error": "SQL file not found in the task workspace"}, []
        try:
            columns, rows = query_rows(self.world["files"][path], self.sample["development_rows"])
        except (sqlite3.Error, ValueError) as exc:
            return {"status": 400, "error": str(exc)}, []
        return {"status": 200, "columns": columns, "rows": rows}, []

    def checks(self):
        sql = self.world["files"].get(self.query_path, "")
        if not sql.strip():
            return dict.fromkeys(self.sample["hidden_checks"], False)
        result = {}
        for name, check in self.sample["hidden_checks"].items():
            try:
                columns, rows = query_rows(sql, check["rows"])
                result[name] = columns == self.sample["columns"] and rows == check["expected"]
            except (sqlite3.Error, ValueError):
                result[name] = False
        return result

    def task_effects_complete(self):
        return all(self.checks().values())

    def action_observations(self):
        return {"work_items": self.checks()}
