"""Excel reading through pandas with the fastest available engine (V62.6.209).

pandas parses every sheet the same way regardless of engine; only the cell reader differs.
python-calamine (Rust) reads cells ~8x faster than openpyxl and returns identical frames
for the workbook shapes used here (verified by tests). If calamine is not installed or
fails on a particular file, the same call is retried with openpyxl.
"""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import pandas as pd

log = logging.getLogger("eko.excel")

try:
    import python_calamine  # noqa: F401
    ENGINE = "calamine"
except ImportError:  # pinned dependency; fall back gracefully on older installs
    ENGINE = "openpyxl"


def _source(src):
    return BytesIO(src) if isinstance(src, (bytes, bytearray)) else src


def read_excel(src, **kwargs) -> pd.DataFrame:
    """Drop-in for ``pd.read_excel``; ``src`` may be bytes, a path or a file object."""
    kwargs.pop("engine", None)
    if ENGINE != "openpyxl":
        try:
            return pd.read_excel(_source(src), engine=ENGINE, **kwargs)
        except Exception as exc:  # retry with the reference engine; real errors re-raise from there
            log.info("calamine could not read workbook (%s); retrying with openpyxl", type(exc).__name__)
            if hasattr(src, "seek"):
                src.seek(0)
    return pd.read_excel(_source(src), engine="openpyxl", **kwargs)


def excel_file(src) -> pd.ExcelFile:
    """Drop-in for ``pd.ExcelFile`` (sheet names, ``.parse``)."""
    if ENGINE != "openpyxl":
        try:
            return pd.ExcelFile(_source(src), engine=ENGINE)
        except Exception as exc:
            log.info("calamine could not open workbook (%s); retrying with openpyxl", type(exc).__name__)
            if hasattr(src, "seek"):
                src.seek(0)
    return pd.ExcelFile(_source(src), engine="openpyxl")


def engine_name() -> str:
    return ENGINE


__all__ = ["read_excel", "excel_file", "engine_name", "ENGINE", "Path"]
