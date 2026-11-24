"""Canonical tables. Bump SCHEMA_VERSION on any change to a table's columns or meaning."""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = 1

# Timestamps are seconds since the Unix epoch (float64), as stored in GrandTour.
# Quaternions are (qx, qy, qz, qw), Hamilton convention.
_KEY = [
    pa.field("mission", pa.string(), nullable=False),
    pa.field("topic", pa.string(), nullable=False),
    pa.field("frame_id", pa.string(), nullable=False),
]

TABLES: dict[str, pa.Schema] = {
    "pose": pa.schema(
        _KEY
        + [
            pa.field("seq", pa.int64()),
            pa.field("t", pa.float64(), nullable=False),
            pa.field("x", pa.float64()),
            pa.field("y", pa.float64()),
            pa.field("z", pa.float64()),
            pa.field("qx", pa.float64()),
            pa.field("qy", pa.float64()),
            pa.field("qz", pa.float64()),
            pa.field("qw", pa.float64()),
        ]
    ),
    "position": pa.schema(
        _KEY
        + [
            pa.field("seq", pa.int64()),
            pa.field("t", pa.float64(), nullable=False),
            pa.field("x", pa.float64()),
            pa.field("y", pa.float64()),
            pa.field("z", pa.float64()),
        ]
    ),
    "static_tf": pa.schema(
        [
            pa.field("mission", pa.string(), nullable=False),
            pa.field("parent", pa.string(), nullable=False),
            pa.field("child", pa.string(), nullable=False),
            pa.field("tx", pa.float64()),
            pa.field("ty", pa.float64()),
            pa.field("tz", pa.float64()),
            pa.field("qx", pa.float64()),
            pa.field("qy", pa.float64()),
            pa.field("qz", pa.float64()),
            pa.field("qw", pa.float64()),
        ]
    ),
}

TIME_SERIES_TABLES = ("pose", "position")


class SchemaError(ValueError):
    pass


def conform(table_name: str, table: pa.Table) -> pa.Table:
    """Checks a table against the contract and returns it in the canonical column order."""
    schema = TABLES[table_name]
    missing = [f.name for f in schema if f.name not in table.column_names]
    extra = [c for c in table.column_names if c not in schema.names]
    if missing or extra:
        raise SchemaError(f"{table_name}: missing columns {missing}, unexpected columns {extra}")
    table = table.select(schema.names)
    try:
        table = table.cast(schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError) as err:
        raise SchemaError(f"{table_name}: {err}") from err
    for field in schema:
        if not field.nullable and table.column(field.name).null_count:
            raise SchemaError(f"{table_name}: nulls in non-nullable column {field.name}")
    return table
