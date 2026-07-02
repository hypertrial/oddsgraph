from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .queries import q


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + q(value) + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "1e308"
        return repr(value)
    return str(value)


def values_rows_sql(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    return ", ".join(
        "(" + ", ".join(sql_literal(row.get(col)) for col in columns) + ")"
        for row in rows
    )


def create_table_from_rows_sql(
    table: str,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    empty_types: Mapping[str, str],
) -> str:
    if rows:
        return (
            f"CREATE TABLE {table} AS SELECT * FROM "
            f"(VALUES {values_rows_sql(rows, columns)}) AS t({', '.join(columns)})"
        )
    nulls = ", ".join(f"NULL::{empty_types[col]} AS {col}" for col in columns)
    return f"CREATE TABLE {table} AS SELECT {nulls} WHERE false"
