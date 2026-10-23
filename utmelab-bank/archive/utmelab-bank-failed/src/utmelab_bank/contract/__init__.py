"""Everything that reads the API's declared shapes.

Four concerns, kept together so the boundary with another team's code is one
import rather than four scattered calls:

- ``rust_schema`` parses what the API says it reads.
- ``version`` refuses to act on a contract version we do not implement.
- ``check`` probes the live database before we write.
- ``content_hash`` owns the one hash the API joins on.
"""

from __future__ import annotations

from utmelab_bank.contract.check import ShapeReport, check_shapes, read_contract_version
from utmelab_bank.contract.content_hash import content_hash
from utmelab_bank.contract.rust_schema import (
    ReadShape,
    RustContract,
    load_contract,
    parse_schema_rs,
)
from utmelab_bank.contract.version import SUPPORTED_CONTRACT_VERSIONS, refuse_unknown, supported

__all__ = [
    "SUPPORTED_CONTRACT_VERSIONS",
    "ReadShape",
    "RustContract",
    "ShapeReport",
    "check_shapes",
    "content_hash",
    "load_contract",
    "parse_schema_rs",
    "read_contract_version",
    "refuse_unknown",
    "supported",
]
