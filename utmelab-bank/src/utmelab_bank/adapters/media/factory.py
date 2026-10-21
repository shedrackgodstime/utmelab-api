"""Build the media adapters from the settings.

The store and the describer are the two pieces the pipeline needs, and both
read their configuration in one place so a run has a single answer for where
the bytes go and which models witness a figure.
"""

from __future__ import annotations

from utmelab_bank.config import Settings

from .git_store import GitMediaStore

__all__ = ["create_media_store"]


def create_media_store(settings: Settings) -> GitMediaStore:
    """The GitLab-backed store, opened or closed for pushing as configured."""
    return GitMediaStore(
        settings.media_repo_path,
        remote=settings.media_remote,
        branch=settings.media_branch,
        base_url=settings.media_base,
        upload_enabled=settings.media_upload_enabled,
    )
