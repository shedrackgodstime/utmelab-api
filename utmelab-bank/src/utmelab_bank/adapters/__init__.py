"""Adapters. Each one imports domain and its own external library.

The layout follows what each thing talks to.

- ``database`` is the Turso driver. It serves both databases, so it is not
  under the catalog.
- ``catalog`` reads the production catalog, which is the authority for topic
  placement.
- ``production`` reads the production content, which is the authority for
  what already exists.
- ``store`` is the bank's own tables.
"""

from .catalog import ProductionCatalogReader, SqlClient
from .dedupe_service import DedupeService
from .index_refresh import IndexRefresher
from .database import (
    DatabaseError,
    Result,
    TursoClient,
    bank_client,
    catalog_reader,
    prod_client,
)

__all__ = [
    "DatabaseError",
    "DedupeService",
    "IndexRefresher",
    "ProductionCatalogReader",
    "Result",
    "SqlClient",
    "TursoClient",
    "bank_client",
    "catalog_reader",
    "prod_client",
]
