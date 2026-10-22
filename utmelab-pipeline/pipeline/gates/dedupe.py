"""Question stem canonicalization and fingerprinting."""

import hashlib
import re


def compute_fingerprint(stem: str) -> str:
    """Computes a deterministic SHA-256 fingerprint for a question stem.
    
    Normalizes the text by:
    1. Stripping all HTML tags (e.g. <p>, <br>, <b>).
    2. Stripping non-essential punctuation artifacts.
    3. Collapsing all whitespace into single space.
    4. Lowercasing.
    """
    if not stem:
        return hashlib.sha256(b"").hexdigest()

    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", stem)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip().lower()

    return hashlib.sha256(clean.encode("utf-8")).hexdigest()
