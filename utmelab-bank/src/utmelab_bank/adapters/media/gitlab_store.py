"""A stateless GitLab store for figures, over the Repository Files API.

No clone, no working tree, no git binary. The bank writes a content-addressed
file and reads it back over HTTPS, so a run on a fresh runner has nothing to
set up and nothing to clean up.

Three rules, carried over from the clone store because they earned their keep:

**A failed request raises.** The caller decides whether to retry; a 401 and a
502 are not the same thing.

**An empty answer is not a message.** The response body and the status are
read together, because GitLab reports different failures in different places.

**Nothing is published until the remote says so.** After a create, the raw
file is read back and hashed. A 201 only proves the request was accepted.

The file name is the record. The store only answers whether it can serve that
name; the serving layer builds the public url, so the host is configuration
and not a column.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from utmelab_bank.domain.models import MediaAsset

from .errors import MediaAuthError, MediaError, MediaPublishError
from .info import dimensions
from .paths import extension_for, name_for, path_for, sha256_of

__all__ = ["GitLabMediaStore"]


class GitLabMediaStore:
    """GitLab's repository files, addressed by content."""

    def __init__(
        self,
        *,
        host: str,
        project: str,
        token: str,
        branch: str = "main",
        base_url: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not host or not project or not token:
            raise MediaError(
                "the GitLab store needs a host, a project and a token",
                hint="set GITLAB_HOST, GITLAB_MEDIA_REPO and GITLAB_TOKEN",
            )
        self.host = host
        self.project = project
        self.branch = branch
        self.base_url = base_url.rstrip("/")
        self._token_value = token
        self._api = f"https://{host}/api/v4/projects/{quote(project, safe='')}"
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "UTME-Lab-MediaStore/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- the MediaStore port ----------------------------------------------

    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: str | None = None,
    ) -> MediaAsset:
        """Write one blob if it is not already there, then prove it is there."""
        if not data:
            raise MediaError("refusing to store empty bytes")
        extension = extension_for(source_url or "", mime, data)
        digest = sha256_of(data)
        name = name_for(digest, extension)

        if not await self.exists(name):
            await self._create(name, data)
            await self._verify(name, data)

        width, height = dimensions(data)
        return MediaAsset(
            asset_id=digest,
            mime=mime,
            byte_size=len(data),
            width=width,
            height=height,
            storage_url=name,
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            required=True,
            readable=True,
        )

    async def read(self, name: str) -> bytes:
        response = await self._request("GET", self._file_url(name, raw=True))
        if response.status_code == 404:
            raise MediaError("media asset not found", name=name)
        self._raise_for(response, "read")
        return response.content

    async def exists(self, name: str) -> bool:
        response = await self._request("GET", self._file_url(name))
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        self._raise_for(response, "look up")
        return False

    def can_serve(self, name: str) -> bool:
        """Whether a public host is configured for the recorded name."""
        return bool(self.base_url)

    # -- the GitLab calls -------------------------------------------------

    def _file_url(self, name: str, *, raw: bool = False) -> str:
        path = quote(self._path(name), safe="")
        suffix = "/raw" if raw else ""
        return f"{self._api}/repository/files/{path}{suffix}?ref={quote(self.branch, safe='')}"

    @staticmethod
    def _path(name: str) -> str:
        digest, _, suffix = name.partition(".")
        return path_for(digest, f".{suffix}")

    async def _create(self, name: str, data: bytes) -> None:
        body: dict[str, object] = {
            "branch": self.branch,
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            "commit_message": f"add figure {name}",
        }
        response = await self._request(
            "POST",
            f"{self._api}/repository/files/{quote(self._path(name), safe='')}",
            json=body,
        )
        # Another runner may have created the same content a moment ago. The
        # name is the hash, so that is not a conflict; it is the same file.
        if response.status_code == 400 and "already exists" in response.text.lower():
            return
        self._raise_for(response, "create")

    async def _verify(self, name: str, data: bytes) -> None:
        served = await self.read(name)
        if sha256_of(served) != sha256_of(data):
            raise MediaPublishError(
                "gitlab returned different bytes than the ones we sent",
                name=name,
            )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method,
                url,
                headers={"PRIVATE-TOKEN": self._token_value},
                json=json,
            )
        except httpx.HTTPError as exc:
            raise MediaError("the gitlab request failed", error=str(exc)) from exc

    def _raise_for(self, response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        context: dict[str, Any] = {"status": response.status_code, "action": action}
        if response.status_code in (401, 403):
            raise MediaAuthError(
                "gitlab refused the credential",
                **context,
                hint=(
                    "use a project access token with the api scope, or a fine-grained "
                    "PAT with Repository: Read and Repository: Create"
                ),
                detail=response.text[:400],
            )
        raise MediaError(
            f"gitlab could not {action} the figure",
            **context,
            detail=response.text[:400],
        )
