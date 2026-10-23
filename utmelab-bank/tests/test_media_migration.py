"""Pure checks for the bulk production media migration helpers."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "migrate_all_production_media.py"
    spec = spec_from_file_location("migrate_all_production_media", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_image_is_replaced_without_changing_position() -> None:
    migration = _module()
    source = {
        "text": "Look at the figure.",
        "inline": [
            {
                "start": 0,
                "len": 0,
                "kind": "image",
                "url": "https://myschool.ng/image.png",
                "position": "above",
            }
        ],
    }
    replaced = migration._replace_images(
        source,
        {"https://myschool.ng/image.png": "abc.png"},
        [],
    )
    assert replaced["inline"][0]["url"] == "abc.png"
    assert replaced["inline"][0]["position"] == "above"


def test_filename_replacement_changes_the_content_hash() -> None:
    migration = _module()
    row = (
        "q1",
        "Look at the figure.",
        "[]",
        '[{"id":"a","text":{"text":"one","inline":[]}}]',
        "a",
        None,
        "old",
    )
    updated = {
        "inline": [
            {
                "start": 0,
                "len": 0,
                "kind": "image",
                "url": "abc.png",
                "position": "above",
            }
        ],
        "options": [{"id": "a", "text": {"text": "one", "inline": []}}],
        "explanation": None,
    }
    assert migration._fingerprint(row, updated) != "old"


def test_file_batches_bound_count_and_size() -> None:
    migration = _module()
    files = {f"{index}.png": b"x" for index in range(45)}
    batches = migration._file_batches(files)
    assert [len(batch) for batch in batches] == [20, 20, 5]
    assert {name for batch in batches for name in batch} == set(files)
