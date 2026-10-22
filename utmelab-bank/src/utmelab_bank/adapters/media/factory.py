"""Build the media adapters from the settings.

The store and the describer are the two pieces the pipeline needs, and both
read their configuration in one place so a run has a single answer for where
the bytes go and which models witness a figure.

The store is stateless when it is remote: the GitLab API is called directly,
with no clone and no working tree. When no remote is configured the run still
captures, but into a local folder that publishes nothing, so the row keeps its
source url instead of pointing at a host that does not have the file.

The token is the permission. There is no second switch: a token and a repo mean
upload, neither means a local run, and one without the other is a configuration
error.
"""

from __future__ import annotations

from utmelab_bank.config import Settings
from utmelab_bank.domain.ports import MediaStore

from .errors import MediaError
from .gitlab_store import GitLabMediaStore
from .local_store import LocalMediaStore

__all__ = ["create_media_store"]


def create_media_store(settings: Settings) -> MediaStore:
    """The remote store when GitLab is configured, otherwise a local one.

    A token without a repo, or a repo without a token, is a configuration
    error, not a reason to fall back to local. Silent fallback is how a batch
    looks published and is not.
    """
    if not settings.gitlab_token and not settings.gitlab_media_repo:
        return LocalMediaStore(settings.media_repo_path)
    if not settings.gitlab_token or not settings.gitlab_media_repo:
        raise MediaError(
            "media upload needs both a token and a repo",
            hint="set GITLAB_TOKEN and GITLAB_MEDIA_REPO, or neither for a local run",
        )
    return GitLabMediaStore(
        host=settings.gitlab_host,
        project=settings.gitlab_media_repo,
        token=settings.gitlab_token,
        branch=settings.media_branch,
        base_url=settings.media_base,
    )
