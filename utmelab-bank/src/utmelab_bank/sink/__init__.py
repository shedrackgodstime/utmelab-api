"""Where rows land. The guard that keeps generated data out of the repository.

A task never opens a file and never builds a statement. It hands rows to a
sink. That is what makes ``--sink json`` a real development mode rather than a
second code path threaded through every task, and it is the mechanism behind the
one rule this project cannot bend: no generated data is ever committed.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.sink.base import Sink
from utmelab_bank.sink.db import DbSink
from utmelab_bank.sink.json import JsonSink

__all__ = ["Sink", "DbSink", "JsonSink", "build_sink"]


def build_sink(config: Config, store: Any) -> Sink:
    """The sink the config asks for.

    ``db`` is the default and the only one that ships. ``json`` must be asked
    for by name, which is why it is a flag rather than a fallback when the
    database is unreachable.
    """
    if config.sink == "json":
        return JsonSink.from_config(config)
    return DbSink.from_config(config, store)
