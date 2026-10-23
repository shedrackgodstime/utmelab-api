"""Harvesters registry and factory."""

from typing import Dict, List, Type
from pipeline.sources.base import BaseHarvester, RawOption, RawQuestionPayload
from pipeline.sources.jamb import JambHarvester
from pipeline.sources.neco import NecoHarvester
from pipeline.sources.waec import WaecHarvester

HARVESTER_REGISTRY: Dict[str, Type[BaseHarvester]] = {
    "jamb": JambHarvester,
    "myschool_jamb": JambHarvester,
    "waec": WaecHarvester,
    "myschool_waec": WaecHarvester,
    "neco": NecoHarvester,
    "myschool_neco": NecoHarvester,
}


def get_harvester(name: str, **kwargs) -> BaseHarvester:
    """Returns an instantiated harvester from the registry."""
    key = name.lower().strip()
    if key not in HARVESTER_REGISTRY:
        raise ValueError(
            f"Unknown harvester '{name}'. Available: {list(HARVESTER_REGISTRY.keys())}"
        )
    return HARVESTER_REGISTRY[key](**kwargs)


def list_harvesters() -> List[str]:
    return sorted(list(HARVESTER_REGISTRY.keys()))


__all__ = [
    "BaseHarvester",
    "RawOption",
    "RawQuestionPayload",
    "JambHarvester",
    "WaecHarvester",
    "get_harvester",
    "list_harvesters",
]
