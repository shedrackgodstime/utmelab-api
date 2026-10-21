"""The GitLab store: content-addressed names, no clone, no working tree."""

from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import unquote

import httpx
import pytest

from tests.media_fakes import PNG_1X1
from utmelab_bank.adapters.media import GitLabMediaStore, MediaAuthError, MediaError
from utmelab_bank.adapters.media.paths import sha256_of

BASE = "https://assets.utmelab.com/images"


class FakeGitLab:
    """The slice of the Repository Files API the store uses."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.auth_fail = False
        self.server_error = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if self.auth_fail:
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        if self.server_error:
            return httpx.Response(502, text="bad gateway")

        path = unquote(request.url.path)
        marker = "/repository/files/"
        if marker not in path:
            return httpx.Response(404)
        tail = path.split(marker, 1)[1]

        if request.method == "POST":
            body = json.loads(request.content)
            data = base64.b64decode(body["content"])
            if tail in self.files:
                return httpx.Response(400, json={"message": "A file with this name already exists"})
            self.files[tail] = data
            return httpx.Response(201, json={"file_path": tail})

        raw = tail.endswith("/raw")
        file_path = tail.removesuffix("/raw")
        if file_path not in self.files:
            return httpx.Response(404, json={"message": "404 File Not Found"})
        if raw:
            return httpx.Response(200, content=self.files[file_path])
        return httpx.Response(200, json={"file_path": file_path})

    def posts(self) -> int:
        return sum(1 for method, _ in self.calls if method == "POST")


def make_store(fake: FakeGitLab, *, base: str = BASE) -> GitLabMediaStore:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return GitLabMediaStore(
        host="gitlab.com",
        project="group/media",
        token="tok",
        base_url=base,
        client=client,
    )


def test_put_writes_the_name_and_proves_the_bytes() -> None:
    fake = FakeGitLab()
    store = make_store(fake)

    async def run() -> tuple[str, str]:
        asset = await store.put(PNG_1X1, mime="image/png", source_url="https://s/x.png")
        assert not asset.storage_url.startswith("https://")
        assert asset.storage_url == f"{sha256_of(PNG_1X1)}.png"
        assert str(asset.source_url) == "https://s/x.png"
        assert fake.files[f"images/{asset.storage_url}"] == PNG_1X1
        assert await store.read(asset.storage_url) == PNG_1X1
        assert await store.exists(asset.storage_url) is True
        return asset.storage_url, store.served_url(asset.storage_url) or ""

    name, served = asyncio.run(run())
    asyncio.run(store.close())

    assert served == f"{BASE}/{name}"
    assert fake.posts() == 1


def test_put_is_idempotent() -> None:
    fake = FakeGitLab()
    store = make_store(fake)

    async def run() -> tuple[str, str]:
        first = await store.put(PNG_1X1, mime="image/png")
        second = await store.put(PNG_1X1, mime="image/png")
        return first.storage_url, second.storage_url

    first, second = asyncio.run(run())
    asyncio.run(store.close())

    assert first == second
    assert fake.posts() == 1


def test_a_refused_credential_is_not_retryable() -> None:
    fake = FakeGitLab()
    fake.auth_fail = True
    store = make_store(fake)

    with pytest.raises(MediaAuthError) as caught:
        asyncio.run(store.put(PNG_1X1, mime="image/png"))
    asyncio.run(store.close())

    assert caught.value.is_retryable is False


def test_a_server_error_is_retryable() -> None:
    fake = FakeGitLab()
    fake.server_error = True
    store = make_store(fake)

    with pytest.raises(MediaError) as caught:
        asyncio.run(store.put(PNG_1X1, mime="image/png"))
    asyncio.run(store.close())

    assert caught.value.is_retryable is True


def test_a_missing_file_reads_as_not_found() -> None:
    store = make_store(FakeGitLab())

    with pytest.raises(MediaError, match="not found"):
        asyncio.run(store.read("0" * 64 + ".png"))
    asyncio.run(store.close())


def test_without_a_base_there_is_no_served_url() -> None:
    store = make_store(FakeGitLab(), base="")
    assert store.served_url("0" * 64 + ".png") is None
    asyncio.run(store.close())
