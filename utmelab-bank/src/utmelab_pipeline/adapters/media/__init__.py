"""Media adapters. Git-backed storage with GitLab remote."""

from .git_store import GitMediaStore

__all__ = ["GitMediaStore"]