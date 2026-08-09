"""Columnar index over normalized VRF readings.

Readings are written to a partitioned Parquet dataset (partitioned by
system/unit) and queried through DuckDB. This scales to large multi-day,
multi-system log sets without a database server and keeps queries fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import duckdb
import pandas as pd


@dataclass
class UnitInfo:
    system_id: str
    unit_id: str
    unit_role: str
    n_rows: int
    start: pd.Timestamp
    end: pd.Timestamp


class IndexStore:
    """Reads/writes the Parquet index and exposes convenience queries."""

    def __init__(self, root: str):
        self.root = root
        self.parquet_dir = os.path.join(root, "readings")

    # -- writing -----------------------------------------------------------
    def build(self, df: pd.DataFrame) -> "IndexStore":
        """Write normalized readings to the partitioned Parquet index."""
        os.makedirs(self.parquet_dir, exist_ok=True)
        con = duckdb.connect()
        try:
            con.register("df", df)
            # partition by system/unit; DuckDB writes hive-style folders
            con.execute(
                f"""
                COPY (SELECT * FROM df)
                TO '{self.parquet_dir}'
                (FORMAT PARQUET, PARTITION_BY (system_id, unit_id),
                 OVERWRITE_OR_IGNORE TRUE);
                """
            )
        finally:
            con.close()
        return self

    # -- reading -----------------------------------------------------------
    def _glob(self) -> str:
        return os.path.join(self.parquet_dir, "**", "*.parquet")

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect()

    def units(self) -> list[UnitInfo]:
        con = self._connect()
        try:
            rows = con.execute(
                f"""
                SELECT system_id, unit_id, any_value(unit_role) AS unit_role,
                       count(*) AS n, min(timestamp) AS start, max(timestamp) AS end
                FROM read_parquet('{self._glob()}', hive_partitioning=true)
                GROUP BY system_id, unit_id
                ORDER BY system_id, unit_id;
                """
            ).fetchall()
        finally:
            con.close()
        return [
            UnitInfo(r[0], r[1], r[2], r[3], pd.Timestamp(r[4]), pd.Timestamp(r[5]))
            for r in rows
        ]

    def systems(self) -> list[str]:
        con = self._connect()
        try:
            rows = con.execute(
                f"""
                SELECT DISTINCT system_id
                FROM read_parquet('{self._glob()}', hive_partitioning=true)
                ORDER BY system_id;
                """
            ).fetchall()
        finally:
            con.close()
        return [r[0] for r in rows]

    def read(
        self,
        system_id: Optional[str] = None,
        unit_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Read readings, optionally filtered to one system/unit."""
        clauses = []
        if system_id is not None:
            clauses.append(f"system_id = '{system_id}'")
        if unit_id is not None:
            clauses.append(f"unit_id = '{unit_id}'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        con = self._connect()
        try:
            df = con.execute(
                f"""
                SELECT * FROM read_parquet('{self._glob()}', hive_partitioning=true)
                {where}
                ORDER BY unit_id, timestamp;
                """
            ).df()
        finally:
            con.close()
        if "timestamp" in df:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def query(self, sql: str) -> pd.DataFrame:
        """Run arbitrary SQL against the index. Use ``readings`` as the table."""
        con = self._connect()
        try:
            con.execute(
                f"""
                CREATE VIEW readings AS
                SELECT * FROM read_parquet('{self._glob()}', hive_partitioning=true);
                """
            )
            return con.execute(sql).df()
        finally:
            con.close()

    def exists(self) -> bool:
        return os.path.isdir(self.parquet_dir) and any(
            f.endswith(".parquet")
            for _, _, files in os.walk(self.parquet_dir)
            for f in files
        )
