#!/usr/bin/env python3
"""Thin entry point for the utmetag SDK.

The implementation lives in the ``utmetag`` package next to this file; this
shim keeps the historical workflow path (``tools/auto_tag_questions.py``) valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utmetag.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
