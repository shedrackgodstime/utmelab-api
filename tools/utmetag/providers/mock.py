"""Deterministic mock provider — no network I/O, for tests and CI smoke runs."""

from __future__ import annotations

import hashlib
import json
import random
import re

from .base import Provider


class MockProvider(Provider):
    def __init__(self, seed_salt: str = ""):
        self.seed_salt = seed_salt
        self.name = "mock"

    async def complete(self, prompt: str) -> str:
        seed = int(hashlib.md5((self.seed_salt + prompt).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Pick a real subtopic slug from the prompt's AVAILABLE SUBTOPICS list.
        subtopic_slug = None
        match = re.search(r"AVAILABLE SUBTOPICS.*?\n((?:  - .+\n)+)", prompt)
        if match:
            slugs = [m.group(1) for m in re.finditer(r"  - (\S+):", match.group(1))]
            if slugs:
                subtopic_slug = rng.choice(slugs)

        # Detect underline references in the STEM only (not the whole prompt).
        underline = None
        stem_match = re.search(r"Question: (.*?)\n\nOPTIONS:", prompt, re.DOTALL)
        stem = stem_match.group(1) if stem_match else ""
        if "underlin" in stem.lower():
            uw = re.search(r"underlined (?:word|portion)[:\s]+([^\.\n]+)", stem, re.IGNORECASE)
            if uw:
                word = uw.group(1).strip().strip('":')
            else:
                words = [w for w in stem.split() if len(w) > 3 and w.isalpha()]
                word = rng.choice(words) if words else None
            if word:
                start = stem.find(word)
                if start >= 0:
                    underline = {"word": word, "start": start, "len": len(word)}

        return json.dumps({
            "subtopic_slug": subtopic_slug,
            "underline": underline,
            "answer_correct": rng.random() > 0.1,
            "explanation_quality": rng.choice(["GOOD", "PARTIAL", "GOOD", "GOOD"]),
            "confidence": round(0.7 + rng.random() * 0.3, 2),
            "reasoning": (
                "Mock response for testing pipeline. Subtopic assigned from "
                "available list. Answer verified against provided solution. "
                "Explanation quality assessed."
            ),
        })

    async def aclose(self) -> None:
        pass
