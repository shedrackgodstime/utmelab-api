"""The command line, the registries, and the media store.

The CLI is the whole promise of the package: a step you can run in a terminal
you can run in a workflow, with the same name and the same flags. These tests
hold it to that.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import blob_path_for, extension_for, is_blob_name, url_for
from utmelab_bank.cli import cli, main
from utmelab_bank.errors import BlobError, SourceError, StoreError
from utmelab_bank.source.myschool.parser import EXAMS, slug_for
from utmelab_bank.task import all_tasks
from utmelab_bank.task import get as get_task


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Commands that need no database
# ---------------------------------------------------------------------------


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "utmelab-bank" in result.output


def test_sources_lists_what_each_one_serves(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["sources"])
    assert result.exit_code == 0
    assert "myschool" in result.output
    assert "jambsyllabus" in result.output


def test_tasks_lists_what_each_one_fills(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["tasks"])
    assert result.exit_code == 0
    for name in all_tasks():
        assert name in result.output


def test_selectors_lists_the_whole_vocabulary(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["selectors"])
    assert result.exit_code == 0
    assert "no description" in result.output
    assert "gated" in result.output


def test_explain_turns_a_phrase_into_plain_english(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["explain", "gated and no subtopic"])
    assert result.exit_code == 0
    assert "selects" in result.output
    assert "subtopic" in result.output


def test_explain_refuses_an_unknown_phrase(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["explain", "not a selector"])
    assert result.exit_code == 1


def test_config_says_where_every_setting_came_from(runner: CliRunner) -> None:
    """A CI typo shows up as a ``default`` line, which is the whole point."""
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 0
    assert "rust schema" in result.output
    assert "var directory" in result.output


def test_config_reports_a_flag_as_a_flag(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["config", "--target", "ready"])
    assert result.exit_code == 0
    assert "flag:ready" in result.output


def test_the_entry_point_returns_an_exit_code() -> None:
    assert main(["--help"]) == 0


# ---------------------------------------------------------------------------
# Refusals before any work starts
# ---------------------------------------------------------------------------


def test_scrape_without_a_subject_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["scrape", "--source", "myschool", "--exam", "jamb"])
    assert result.exit_code != 0
    assert "subject" in result.output.lower()


def test_an_unknown_source_is_refused_before_a_request(runner: CliRunner) -> None:
    result = runner.invoke(
        cli,
        ["scrape", "--source", "nope", "--exam", "jamb", "--subject", "physics", "--dry-run"],
    )
    assert result.exit_code == 2
    assert "unknown source" in result.output


def test_a_refusal_exits_two_so_a_workflow_can_tell_it_from_a_failure(
    runner: CliRunner,
) -> None:
    """0 fine, 1 something failed, 2 refused. A workflow branches on all three."""
    result = runner.invoke(
        cli,
        ["scrape", "--source", "nope", "--exam", "jamb", "--subject", "physics", "--dry-run"],
    )
    assert result.exit_code == 2


def test_an_unknown_task_is_named_with_the_known_ones(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["task", "not-a-task", "--local-database", ":memory:"])
    assert result.exit_code == 2
    assert "unknown task" in result.output


def test_a_database_url_that_is_not_a_url_is_refused(tmp_path: Path) -> None:
    import asyncio

    from utmelab_bank.store.client import Store

    with pytest.raises(StoreError, match="unrecognised database url"):
        asyncio.run(Store.open("htp:/typo"))


# ---------------------------------------------------------------------------
# A task against a real local database
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["", "sqlite:", "file:"])
def test_a_local_database_is_accepted_in_any_spelling(
    runner: CliRunner,
    tmp_path: Path,
    prefix: str,
) -> None:
    """A person will type all three. Creating a file called ``sqlite:x`` is not
    an acceptable way to handle the third."""
    db = tmp_path / "bank.db"
    result = runner.invoke(
        cli,
        ["task", "gate", "--where", "all", "--local-database", f"{prefix}{db}"],
    )
    assert result.exit_code == 0
    assert "gate on work" in result.output
    assert db.is_file()
    assert not list(tmp_path.iterdir()) or all(p.name == "bank.db" for p in tmp_path.iterdir())


def test_the_json_sink_needs_no_database_at_all(runner: CliRunner, repo_root: Path) -> None:
    result = runner.invoke(cli, ["task", "gate", "--sink", "json", "--where", "all"])
    assert result.exit_code == 0
    written = repo_root / "var" / "bank" / "work_questions.json"
    assert not written.exists() or written.is_file()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_jamb_english_resolves_to_the_sites_spelling() -> None:
    """The site calls it english-language. Guessing "use-of-english" produced a
    url that 404s, which is how the largest subject in the bank, 167 questions,
    became unreachable."""
    assert slug_for("jamb", "use-of-english") == "english-language"


def test_waec_english_has_its_own_catalog_slug() -> None:
    assert slug_for("waec", "english-language") == "english-language"


def test_a_subject_the_map_does_not_carry_is_a_refusal() -> None:
    """use-of-english is JAMB. Asking WAEC for it is a mistake, not a lookup."""
    from utmelab_bank.errors import SourceError

    with pytest.raises(SourceError, match="not in the map"):
        slug_for("waec", "use-of-english")


def test_the_slugs_that_used_to_drift_are_mapped() -> None:
    """These three pairs are the drift the archive's importer refused to allow."""
    assert slug_for("jamb", "art") == "fine-arts"
    assert slug_for("jamb", "principles-of-accounts") == "accounts-principles-of-accounts"
    assert slug_for("waec", "financial-accounting") == "accounts-principles-of-accounts"


def test_identity_slugs_still_pass_through() -> None:
    for subject in ("physics", "chemistry", "biology", "government", "arabic", "music"):
        assert slug_for("jamb", subject) == subject


def test_every_subject_the_bank_carries_is_mapped_for_its_exam() -> None:
    """Not a nice-to-have. These are the subjects with questions behind them, and
    the earlier identity map was missing eleven of the twenty five."""
    from utmelab_bank.source.myschool.subjects import load_map

    catalog = json.loads(
        # Vendored from the served catalog (data/subjects.json in the archived
        # utmelab-api-old tree), so this test owns its fixture instead of
        # reading a sibling tree that no longer sits in the repo.
        (Path(__file__).parent / "fixtures" / "catalog_subjects.json").read_text()
    )
    subject_map = load_map()
    for exam in {row["exam"] for row in catalog}:
        code = exam.lower()
        mapped = set(subject_map.exam(code).slugs())
        missing = {row["slug"] for row in catalog if row["exam"] == exam} - mapped
        assert not missing, f"{exam} carries these and the map does not: {sorted(missing)}"


def test_every_exam_is_configured() -> None:
    for exam in ("jamb", "waec", "neco"):
        spec = EXAMS[exam]
        assert spec.default_year >= 2024
        assert spec.listing_url.startswith("https://")


def test_a_syllabus_source_serves_its_own_exam_for_the_catalog() -> None:
    """A syllabus site covers its exam, but for topics rather than questions."""
    from utmelab_bank.source import build_source
    from utmelab_bank.source.base import FetchRequest

    jamb = build_source("jambsyllabus")
    waec = build_source("waecsyllabus")
    assert jamb.supports(FetchRequest(exam="jamb", subject="physics"))
    assert not jamb.supports(FetchRequest(exam="waec", subject="physics"))
    assert waec.supports(FetchRequest(exam="waec", subject="physics"))
    assert jamb.capabilities().catalog
    assert not jamb.capabilities().media


def test_a_syllabus_source_refuses_to_scrape_questions() -> None:
    import asyncio

    from utmelab_bank.config import load
    from utmelab_bank.source import build_source
    from utmelab_bank.source.base import FetchRequest

    with pytest.raises(SourceError, match="fetches the catalog"):
        asyncio.run(
            build_source("jambsyllabus").scrape(
                FetchRequest(exam="jamb", subject="physics"),
                load(),
            )
        )


# ---------------------------------------------------------------------------
# Catalog: reads production, writes the bank, never the reverse
# ---------------------------------------------------------------------------


def test_catalog_reads_production_and_writes_the_bank(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two databases stay separate, and production is opened read only."""
    import asyncio

    from utmelab_bank.store.client import Store

    prod_path = tmp_path / "prod.db"
    bank_path = tmp_path / "bank.db"

    async def seed() -> None:
        prod = await Store.open(f"sqlite:{prod_path}")
        await prod.execute(
            "CREATE TABLE topics (slug TEXT PRIMARY KEY, subject TEXT, exam TEXT, "
            'name TEXT, "order" INTEGER, weight REAL, objectives TEXT)'
        )
        await prod.execute(
            "CREATE TABLE subtopics (slug TEXT PRIMARY KEY, topic TEXT, name TEXT, "
            '"order" INTEGER, objectives TEXT)'
        )
        await prod.execute(
            "INSERT INTO topics VALUES ('algebra', 'mathematics', 'jamb', 'Algebra', 1, 1.0, '[]')"
        )
        await prod.execute(
            "INSERT INTO subtopics VALUES ('linear-equations', 'algebra', "
            "'Linear Equations', 1, '[]')"
        )
        await prod.aclose()

    asyncio.run(seed())
    monkeypatch.setenv("TURSO_DB_URL", f"sqlite:{prod_path}")

    result = runner.invoke(cli, ["catalog", "--local-database", str(bank_path)])
    assert result.exit_code == 0, result.output
    assert "topics: 1" in result.output
    assert "subtopics: 1" in result.output

    async def read() -> tuple[int, int]:
        bank = await Store.open(f"sqlite:{bank_path}")
        try:
            return (
                await bank.count_rows("work_topics"),
                await bank.count_rows("work_subtopics"),
            )
        finally:
            await bank.aclose()

    assert asyncio.run(read()) == (1, 1)


def test_catalog_refuses_without_a_production_url(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["catalog", "--local-database", str(tmp_path / "bank.db")])
    assert result.exit_code == 2
    assert "production" in result.output.lower()


# ---------------------------------------------------------------------------
# The media store
# ---------------------------------------------------------------------------


def test_a_blob_is_written_where_its_hash_says(tmp_path: Path) -> None:
    store = GitStore(root=tmp_path / "media-repo")
    digest, path, url = store.write_blob(b"fake png bytes", ".png")

    assert path.is_file()
    assert path.name == f"{digest}.png"
    assert is_blob_name(path.name)
    assert url == url_for(digest, ".png")
    assert blob_path_for(tmp_path / "media-repo", digest, ".png") == path


def test_writing_the_same_bytes_twice_changes_nothing(tmp_path: Path) -> None:
    """Content addressing is what makes a fetch idempotent."""
    store = GitStore(root=tmp_path / "media-repo")
    first_digest, first_path, _ = store.write_blob(b"same bytes", ".png")
    second_digest, second_path, _ = store.write_blob(b"same bytes", ".png")

    assert first_digest == second_digest
    assert first_path == second_path
    assert len(list((tmp_path / "media-repo" / "media").rglob("*.png"))) == 1


def test_reading_a_blob_that_is_not_there_says_so(tmp_path: Path) -> None:
    store = GitStore(root=tmp_path / "media-repo")
    with pytest.raises(BlobError, match="not in the clone"):
        store.read_blob("c" * 64, ".png")


def test_a_path_escaping_the_clone_is_refused(tmp_path: Path) -> None:
    from utmelab_bank.blob.paths import ensure_inside

    with pytest.raises(BlobError, match="escapes the clone"):
        ensure_inside(tmp_path / "clone", tmp_path / "elsewhere" / "x")


def test_a_digest_that_is_not_a_digest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BlobError, match="not a sha256"):
        blob_path_for(tmp_path, "not-a-hash", ".png")


def test_an_extension_that_is_not_an_extension_is_refused(tmp_path: Path) -> None:
    """The path ends up in a git index, so a traversal here writes outside."""
    with pytest.raises(BlobError, match="not a plain extension"):
        blob_path_for(tmp_path, "a" * 64, "../../etc/passwd")


def test_push_is_closed_until_it_is_opened(tmp_path: Path) -> None:
    store = GitStore(root=tmp_path / "media-repo", remote="")
    assert not store.push_enabled()
    assert not store.push_enabled(config_flag=True)
    with pytest.raises(BlobError, match="push is disabled"):
        store.push()


def test_push_needs_both_the_flag_and_the_remote(tmp_path: Path) -> None:
    with_remote = GitStore(root=tmp_path / "m", remote="git@example.invalid:media.git")
    assert not with_remote.push_enabled()
    assert with_remote.push_enabled(config_flag=True)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_a_blob_is_committed_and_pushed_to_a_remote(tmp_path: Path) -> None:
    """The upload mechanism, proven offline against a local remote.

    Clone, write a content-addressed blob, stage, commit, push, then clone the
    remote again and find the blob there. This is the shape the media upload
    task will drive; proving it here means R7 only has to wire rows to it.
    """
    bare = tmp_path / "media.git"
    _git(tmp_path, "init", "--bare", str(bare))

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "test")
    _git(seed, "config", "user.email", "test@test")
    (seed / "README").write_text("media\n", encoding="utf-8")
    _git(seed, "add", "--all")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "origin", "main")

    store = GitStore(root=tmp_path / "clone", remote=str(bare), branch="main")
    store.ensure_cloned()
    _git(store.root, "config", "user.name", "test")
    _git(store.root, "config", "user.email", "test@test")

    _, blob_path, our_url = store.write_blob(b"hello png", ".png")
    assert store.stage_all() == 1
    assert store.commit("media: add one blob") is not None
    report = store.push(allowed=True)
    assert report.branch == "main"

    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", "main", str(bare), str(verify))
    landed = list((verify / "media").rglob("*.png"))
    assert landed, "the pushed blob is not on the remote"
    assert landed[0] == verify / blob_path.relative_to(store.root)
    assert our_url.startswith("/media/")


def test_gc_keeps_the_hashes_it_is_told_to_keep(tmp_path: Path) -> None:
    store = GitStore(root=tmp_path / "media-repo")
    keep_digest, _, _ = store.write_blob(b"keep me", ".png")
    drop_digest, _, _ = store.write_blob(b"drop me", ".png")

    removed = store.clean_unreferenced({keep_digest}, dry_run=True)
    assert {path.stem for path in removed} == {drop_digest}
    assert store.blob_path(keep_digest, ".png").is_file()
    assert store.blob_path(drop_digest, ".png").is_file()

    store.clean_unreferenced({keep_digest}, dry_run=False)
    assert store.blob_path(keep_digest, ".png").is_file()
    assert not store.blob_path(drop_digest, ".png").is_file()


def test_extension_detection() -> None:
    assert extension_for("https://x/a.php", "image/jpeg") == ".jpg"
    assert extension_for("https://x/a.PNG") == ".png"
    assert extension_for("https://x/a") == ".bin"


# ---------------------------------------------------------------------------
# The workbench and model tasks are declared but not built yet
# ---------------------------------------------------------------------------


def test_every_task_says_which_lane_it_fills() -> None:
    for name in all_tasks():
        task = get_task(name)
        assert task.produces
        assert task.iterates_rows in (True, False)


def test_media_status_values_are_the_documented_set() -> None:
    from utmelab_bank.model.media import MediaStatus

    assert set(MediaStatus.__args__) == {  # type: ignore[attr-defined]
        "discovered",
        "fetched",
        "described",
        "uploaded",
        "failed",
    }
