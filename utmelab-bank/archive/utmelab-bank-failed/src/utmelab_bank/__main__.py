"""``python -m utmelab_bank``. The same entry point as the console script."""

from __future__ import annotations

from utmelab_bank.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
