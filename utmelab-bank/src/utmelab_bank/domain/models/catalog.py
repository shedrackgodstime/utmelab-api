"""The production catalog is the authority for topic placement.

The canonical definitions live in ``common.py``. This module re-exports them so
existing import paths keep working while there is only ever one class object
per model in the whole program.
"""

from .common import CatalogRef, CatalogSnapshot, CatalogSubtopic, CatalogTopic

__all__ = [
    "CatalogRef",
    "CatalogSnapshot",
    "CatalogSubtopic",
    "CatalogTopic",
]
