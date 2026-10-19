"""Typed errors, one family per layer.

The old Python in this repository raised bare ``RuntimeError`` and swallowed
failures with ``except Exception: pass``. That made a broken migration look
like a clean run. Every failure here carries a code, so a task can record it
without parsing prose, and ``is_retryable`` is the only thing that decides
whether a row gets another attempt.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "AiError",
    "BankError",
    "BlobError",
    "ConfigError",
    "ContractError",
    "GitAuthError",
    "GitPublishError",
    "RowFailed",
    "SourceError",
    "StoreError",
    "TaskError",
]


class BankError(Exception):
    """Base for everything this package raises on purpose.

    ``code`` is the stable identifier written to a row's ``error`` column and
    surfaced in a run summary. ``detail`` is for a human. Never parse ``detail``.
    """

    code: str = "bank_error"
    retryable: bool = False

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context

    def __str__(self) -> str:
        if not self.context:
            return self.detail
        pairs = ", ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
        return f"{self.detail} ({pairs})"

    @property
    def is_retryable(self) -> bool:
        """Whether another attempt could plausibly succeed."""
        return self.retryable


class ConfigError(BankError):
    """A setting is missing or unusable."""

    code = "config_error"


class ContractError(BankError):
    """The database does not match what the API declares it reads."""

    code = "contract_mismatch"
    retryable = False


class StoreError(BankError):
    """A read or write against the bank database failed."""

    code = "store_error"
    retryable = True


class SourceError(BankError):
    """A source refused, timed out, or returned something unparseable."""

    code = "source_error"
    retryable = True


class TaskError(BankError):
    """A task could not run at all, as opposed to one row failing."""

    code = "task_error"
    retryable = False


class RowFailed(BankError):
    """One row failed. Carries the reason into the run's error column.

    Retryable by default, because the common causes are a timeout, a rate
    limit, or a model that returned prose instead of json.
    """

    code = "row_failed"
    retryable = True


class BlobError(BankError):
    """The media clone could not be read, written, or pushed."""

    code = "blob_error"
    retryable = True


class GitAuthError(BlobError):
    """GitLab refused the credential.

    Not retryable, and that is the whole point of the class. A rejected token
    will be rejected identically on the next attempt, so retrying it spends the
    run's budget to arrive at the same failure. Everything else about a push,
    from a declined hook to a dropped connection, is worth trying again.
    """

    code = "git_auth_failed"
    retryable = False


class GitPublishError(BlobError):
    """The remote did not end up holding what we said it would.

    The hardest failure to notice is the one where every command succeeded and
    the bytes are still not there: a commit that wrote nothing, a push with
    nothing staged to send, a remote that never moved. Reporting that as
    published is worse than crashing, because the bank then points questions at
    a path nothing serves and never selects those rows again.
    """

    code = "git_not_published"
    retryable = True


class AiError(BankError):
    """A model call failed or returned something we cannot use."""

    code = "ai_error"
    retryable = True


class TransientAiError(AiError):
    """A model call failed in a way another attempt should fix."""

    code = "ai_transient"
    retryable = True


#: Codes a row may be retried on. Anything not listed is a permanent refusal
#: and the run should stop rather than spin.
RETRYABLE_CODES: Final[frozenset[str]] = frozenset(
    {
        StoreError.code,
        SourceError.code,
        BlobError.code,
        # A publish that did not land is worth another attempt: the common
        # causes are a concurrent run and a dropped connection, and both clear.
        GitPublishError.code,
        AiError.code,
        TransientAiError.code,
        RowFailed.code,
    }
)
