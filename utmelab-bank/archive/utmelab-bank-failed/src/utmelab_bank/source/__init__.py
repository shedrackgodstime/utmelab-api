"""Plugins: where raw material comes from.

Adding a source means writing a module and adding one line to
:data:`_SOURCES`. Nothing else changes, and nothing else needs to.
"""

from __future__ import annotations

from typing import Final

from utmelab_bank.errors import SourceError
from utmelab_bank.source.base import FetchRequest, Source, SourceCapabilities
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.source.myschool import MyschoolSource

__all__ = [
    "FetchRequest",
    "MyschoolSource",
    "PoliteSession",
    "Source",
    "SourceCapabilities",
    "all_sources",
    "build_source",
    "get",
    "register",
]

_SOURCES: Final[dict[str, Source]] = {}


def register(source: Source) -> Source:
    """Add a source to the registry."""
    if source.name in _SOURCES:
        raise SourceError("duplicate source name", name=source.name)
    _SOURCES[source.name] = source
    return source


def get(name: str) -> Source:
    try:
        return _SOURCES[name]
    except KeyError as exc:
        raise SourceError("unknown source", name=name, known=all_sources()) from exc


def all_sources() -> tuple[str, ...]:
    return tuple(sorted(_SOURCES))


def build_source(name: str, strategy: str | None = None) -> Source:
    """The source for a name, with a strategy where the name is not enough.

    ``myschool`` can be read two ways and the api is the default, because the
    html listing carries no question links at all. ``--strategy html`` is there
    for parity with the earlier harvesters.
    """
    if strategy is None:
        return get(name)
    if name != MyschoolSource.name:
        raise SourceError("that source has no strategy", name=name, strategy=strategy)
    return MyschoolSource(strategy=strategy)


register(MyschoolSource())
