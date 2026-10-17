"""Persistence. The only package that contains SQL."""

from __future__ import annotations

from utmelab_bank.store.client import Store, connect
from utmelab_bank.store.fingerprint import normalise_for_compare, stem_fingerprint
from utmelab_bank.store.repository import Repository, Update
from utmelab_bank.store.schema import (
    DDL,
    LANES,
    LANE_TABLES,
    assert_lane_parity,
    ensure_schema,
    lane_of,
    table,
)
from utmelab_bank.store.selectors import (
    Selector,
    SelectorSet,
    all_names,
    describe,
    explain,
    resolve,
)

__all__ = [
    "DDL",
    "LANES",
    "LANE_TABLES",
    "Repository",
    "Selector",
    "SelectorSet",
    "Store",
    "Update",
    "all_names",
    "assert_lane_parity",
    "connect",
    "describe",
    "ensure_schema",
    "explain",
    "lane_of",
    "normalise_for_compare",
    "resolve",
    "stem_fingerprint",
    "table",
]
