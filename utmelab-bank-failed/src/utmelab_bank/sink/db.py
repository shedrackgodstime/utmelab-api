"""The database sink. The default and the only one that ships anything."""

from __future__ import annotations

from typing import Any

from utmelab_bank.config import Config, Lane
from utmelab_bank.store.repository import Repository

__all__ = ["DbSink"]


class DbSink:
    """Writes through :class:`~utmelab_bank.store.repository.Repository`."""

    name = "db"

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    @classmethod
    def from_config(cls, config: Config, store: Any) -> DbSink:
        return cls(Repository(store, lane=config.lane))

    @property
    def repository(self) -> Repository:
        return self._repo

    async def write(self, logical: str, rows: list[dict[str, Any]]) -> int:
        return await self._repo.insert_many(logical, rows)

    async def read(self, logical: str, where: str = "all") -> list[dict[str, Any]]:
        return await self._repo.rows(logical, where)

    async def close(self) -> None:
        return None


def lane_of(config: Config) -> Lane:
    return config.lane
