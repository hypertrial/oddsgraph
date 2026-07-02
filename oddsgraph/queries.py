from __future__ import annotations

from pathlib import Path

import duckdb


class DuckDB:
    def __init__(self, database: Path | str = ":memory:") -> None:
        self.database = str(database)
        self._conn = duckdb.connect(self.database)

    def close(self) -> None:
        self._conn.close()

    def execute(self, sql: str) -> None:
        self._conn.execute(sql)

    def rows(self, sql: str) -> list[dict[str, object]]:
        rel = self._conn.execute(sql)
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]

    def scalar(self, sql: str) -> str | int | float | None:
        rows = self.rows(sql)
        if not rows:
            return None
        return next(iter(rows[0].values()))


def q(s: str | Path) -> str:
    return str(s).replace("'", "''")
