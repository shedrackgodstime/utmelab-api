import asyncio
import json
from pathlib import Path

import pytest

from utmelab_bank.adapters.providers.opencode import (
    CommandResult,
    OpenCodeProvider,
)
from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_bank.domain.models import CatalogSnapshot, MediaAsset, StagingItem
from utmelab_bank.domain.ports import ImageDescriber

from ..conftest import rebuild


class FakeRunner:
    def __init__(
        self,
        stdout: str = "",
        *,
        returncode: int = 0,
        stderr: str = "",
        timeout: bool = False,
    ) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.timeout = timeout
        self.calls: list[tuple[list[str], float]] = []

    async def run(self, argv: list[str], *, timeout: float) -> CommandResult:
        self.calls.append((list(argv), timeout))
        if self.timeout:
            raise TimeoutError
        return CommandResult(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def text_event(text: str) -> str:
    event = {
        "type": "text",
        "timestamp": 1,
        "part": {"type": "text", "text": text},
    }
    return json.dumps(event) + "\n"


def make_provider(
    stdout: str,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> tuple[OpenCodeProvider, FakeRunner]:
    runner = FakeRunner(stdout, returncode=returncode, stderr=stderr)
    return OpenCodeProvider(model="opencode/test", runner=runner, retry_delay=0.0), runner


def test_opencode_matches_the_image_port() -> None:
    provider: ImageDescriber = make_provider("")[0]
    assert isinstance(provider, ImageDescriber)


def test_describe_parses_text_and_attaches_file(tmp_path: Path, media: MediaAsset) -> None:
    path = tmp_path / "figure.png"
    path.write_bytes(b"\x89PNG")
    asset = rebuild(media, storage_url=path.as_uri())
    provider, runner = make_provider(
        text_event('{"description":"A cell","facts":["one cell"],"confidence":0.9}')
    )

    result = asyncio.run(provider.describe(DescribeImageRequest(asset=asset, context="cell")))

    assert result.asset_id == asset.asset_id
    assert result.description == "A cell"
    assert result.facts == ("one cell",)
    assert result.producer.provider == "opencode"
    argv, _ = runner.calls[0]
    assert argv[:5] == ["run", "--format", "json", "-m", "opencode/test"]
    assert "readable labels" in argv[-1]
    assert "Do not infer the answer" in argv[-1]
    assert "-f" in argv
    assert str(path) in argv


def test_a_remote_asset_with_bytes_is_described(media: MediaAsset) -> None:
    """The row carries a served url, not a local path, so the bytes travel.

    The provider writes its own scratch file and hands that to the CLI; it
    never tries to turn ``https://assets...`` back into a file.
    """
    from tests.media_fakes import PNG_1X1
    from utmelab_bank.domain.models import rebuild

    asset = rebuild(
        media,
        storage_url=f"https://assets.utmelab.com/images/{media.asset_id}.png",
    )
    provider, runner = make_provider(
        text_event('{"description":"A cell","facts":[],"confidence":0.9}')
    )

    result = asyncio.run(
        provider.describe(DescribeImageRequest(asset=asset, context="cell", data=PNG_1X1))
    )

    assert result.description == "A cell"
    argv, _ = runner.calls[0]
    attached = argv[argv.index("-f") + 1]
    assert attached.endswith(".png")
    assert attached != asset.storage_url


def test_explain_parses(staging_item: StagingItem) -> None:

    provider, runner = make_provider(text_event('{"key_point":"k","body":"b","confidence":0.8}'))
    result = asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))
    assert result.key_point.text == "k"
    assert result.body.text == "b"
    prompt = runner.calls[0][0][-1]
    assert "every other option" in prompt
    assert "calculation steps" in prompt
    assert "Do not invent" in prompt
    assert '"media_checks": []' in prompt
    assert '"ocr": []' in prompt


def test_tag_parses(catalog: CatalogSnapshot, staging_item: StagingItem) -> None:

    provider, runner = make_provider(
        text_event(
            '{"topic_id":"t1","subtopic_id":"s1","evidence":"What is 2 + 2?","confidence":0.7}'
        )
    )
    result = asyncio.run(provider.tag(TagRequest(item=staging_item, catalog=catalog)))
    assert result.topic_id == "t1"
    assert result.subtopic_id == "s1"
    assert "catalog" in runner.calls[0][0][-1]


def test_verify_parses(staging_item: StagingItem) -> None:

    provider, _ = make_provider(text_event('{"verdict":"pass","reasoning":"r","confidence":0.95}'))
    result = asyncio.run(provider.verify(VerifyAnswerRequest(item=staging_item, catalog=None)))
    assert result.verdict == "pass"


def test_fenced_json_is_accepted(staging_item: StagingItem) -> None:

    fenced = '```json\n{"key_point":"k","body":"b","confidence":0.5}\n```'
    provider, _ = make_provider(text_event(fenced))
    result = asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))
    assert result.confidence == 0.5


def test_nonzero_exit_raises(staging_item: StagingItem) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    runner = FakeRunner("", returncode=2, stderr="boom")
    provider = OpenCodeProvider(model="opencode/test", runner=runner, retry_delay=0.0)
    with pytest.raises(OpenCodeError, match="boom"):
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))


def test_timeout_raises(staging_item: StagingItem) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    runner = FakeRunner(timeout=True)
    provider = OpenCodeProvider(model="opencode/test", runner=runner, retry_delay=0.0)
    with pytest.raises(OpenCodeError, match="timed out"):
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))
    assert len(runner.calls) == 1


def test_a_transient_server_error_is_retried(staging_item: StagingItem) -> None:
    """The free models are a shared queue; a server error is not the row's fault."""
    error_event = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "UnknownError",
                "data": {"message": "Unexpected server error. Check server logs for details."},
            },
        }
    )

    class RecoveringRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, argv: list[str], *, timeout: float) -> CommandResult:
            self.calls += 1
            if self.calls == 1:
                return CommandResult(returncode=1, stdout=error_event, stderr="")
            return CommandResult(
                returncode=0,
                stdout=text_event('{"key_point":"k","body":"b","confidence":0.8}'),
                stderr="",
            )

    runner = RecoveringRunner()
    provider = OpenCodeProvider(model="opencode/test", runner=runner, retries=3, retry_delay=0.0)

    result = asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))

    assert result.key_point.text == "k"
    assert runner.calls == 2


def test_missing_text_event_raises(staging_item: StagingItem) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    provider, _ = make_provider("")
    with pytest.raises(OpenCodeError, match="no text"):
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))


def test_invalid_schema_raises(staging_item: StagingItem) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    provider, _ = make_provider(text_event('{"key_point":"only a key point"}'))
    with pytest.raises(OpenCodeError, match="Explanation"):
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))


def test_remote_asset_is_rejected(media: MediaAsset) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError
    from utmelab_bank.domain.models import rebuild

    asset = rebuild(media, storage_url="https://example.com/figure.png")
    provider, _ = make_provider("")
    with pytest.raises(OpenCodeError, match="local"):
        asyncio.run(provider.describe(DescribeImageRequest(asset=asset)))


def test_missing_asset_file_is_rejected(media: MediaAsset) -> None:
    from utmelab_bank.adapters.providers.opencode import OpenCodeError
    from utmelab_bank.domain.models import rebuild

    asset = rebuild(media, storage_url="file:///nonexistent/figure.png")
    provider, _ = make_provider("")
    with pytest.raises(OpenCodeError, match="does not exist"):
        asyncio.run(provider.describe(DescribeImageRequest(asset=asset)))


def test_error_event_is_surfaced(staging_item: StagingItem) -> None:
    """The CLI reports provider failures as error events. They must not be swallowed."""
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    error_event = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "UnknownError",
                "data": {"message": "usage limit reached"},
            },
        }
    )
    provider, _ = make_provider(error_event)
    with pytest.raises(OpenCodeError, match="usage limit reached"):
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))


def test_v2_quota_error_is_classified_and_not_retried(staging_item: StagingItem) -> None:
    """OpenCode v2 quota events must identify the provider and stop immediately."""
    from utmelab_bank.adapters.providers.opencode import OpenCodeError

    error_event = json.dumps(
        {
            "type": "error",
            "error": {
                "type": "provider.quota",
                "message": "Free usage limit reached",
                "status": 429,
            },
        }
    )
    provider, runner = make_provider(
        json.dumps({"type": "step_start"}) + "\n" + error_event,
        returncode=1,
    )

    with pytest.raises(OpenCodeError) as raised:
        asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))

    error = raised.value
    assert error.provider == "opencode"
    assert error.category == "quota"
    assert error.status == 429
    assert error.retryable is False
    assert "provider=opencode" in str(error)
    assert "category=quota" in str(error)
    assert len(runner.calls) == 1
