"""Which contract versions we understand.

The API stamps ``contract_version`` into its own ``meta`` table on first boot
and fails closed when it does not recognise the value it finds. That half of
the handshake depends on the reader, and we are not the reader, so we take the
opposite side of it: we hold the set of versions we can produce against, read
what the database actually carries, and refuse to write when it is a version we
do not implement.

The consequence is worth stating plainly. If the API changes a shape without
telling us, ``check.py`` catches it column by column before we write. If it
changes the contract version, we stop before we write anything at all. Neither
case requires anything from the API side.
"""

from __future__ import annotations

from typing import Final

from utmelab_bank.contract.rust_schema import RustContract
from utmelab_bank.errors import ContractError

__all__ = [
    "SUPPORTED_CONTRACT_VERSIONS",
    "StampedVersion",
    "refuse_unknown",
    "supported",
]

#: Contract versions this package implements. A shape change that alters what we
#: write bumps this, and bumps the API's ``CONTRACT_VERSION`` at the same time.
SUPPORTED_CONTRACT_VERSIONS: Final[frozenset[int]] = frozenset({1})

StampedVersion = tuple[str, int | None]


def supported(version: int) -> bool:
    return version in SUPPORTED_CONTRACT_VERSIONS


def refuse_unknown(
    stamped: int | None,
    contract: RustContract,
    *,
    action: str = "write",
) -> None:
    """Raise unless ``stamped`` is a version we implement.

    ``stamped`` is ``None`` when the row is absent, which the API treats as
    permission to stamp its own. We treat it as unknown too, because a database
    nobody has stamped is a database whose shape nobody has declared, and
    guessing at it is how the section column became permanently null.
    """
    if stamped is None:
        raise ContractError(
            "the database carries no contract version",
            action=action,
            hint="the API stamps this on first boot; run it once before writing",
        )
    if stamped not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractError(
            f"database contract version {stamped} is not one we implement",
            action=action,
            supported=sorted(SUPPORTED_CONTRACT_VERSIONS),
            api_declares=contract.contract_version,
        )
