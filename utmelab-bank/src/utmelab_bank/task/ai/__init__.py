"""AI tasks: describe, explain, tag, verify.

The free half of the bank (gate, dedupe, intake, promote) is proven. These are
the token-spending half, specified one task at a time. ``ai-tag`` is the first,
ported from the proven ``tools/utmetag/`` reference.
"""

from __future__ import annotations

from utmelab_bank.task.ai.describe import AiDescribe, describe_one
from utmelab_bank.task.ai.describe_prompt import build_describe_prompt
from utmelab_bank.task.ai.describe_schema import DescribeOutput, DescribeResult
from utmelab_bank.task.ai.describe_tasks import describe_figure
from utmelab_bank.task.ai.explain import AiExplain, explain_one
from utmelab_bank.task.ai.explain_prompt import build_explain_prompt
from utmelab_bank.task.ai.explain_schema import ExplainOutput, ExplainResult
from utmelab_bank.task.ai.explain_tasks import explain_question
from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.prompt import build_tagging_prompt
from utmelab_bank.task.ai.providers import (
    MockProvider,
    OpenCodeProvider,
    Provider,
    build_provider,
)
from utmelab_bank.task.ai.schema import ModelOutput, TagResult, Underline
from utmelab_bank.task.ai.tag import AiTag, question_from_row, tag_one
from utmelab_bank.task.ai.tasks import snap_underline, tag_question
from utmelab_bank.task.ai.verify import AiVerify, verify_one
from utmelab_bank.task.ai.verify_prompt import build_verify_prompt
from utmelab_bank.task.ai.verify_schema import (
    VERIFY_SCOPES,
    VerifyOutput,
    VerifyResult,
    verify_output_from_text,
)
from utmelab_bank.task.ai.verify_tasks import verify_question

__all__: list[str] = [
    "VERIFY_SCOPES",
    "AiDescribe",
    "AiExplain",
    "AiTag",
    "AiVerify",
    "DescribeOutput",
    "DescribeResult",
    "ExplainOutput",
    "ExplainResult",
    "MockProvider",
    "ModelOutput",
    "OpenCodeProvider",
    "Provider",
    "TagResult",
    "Underline",
    "VerifyOutput",
    "VerifyResult",
    "build_describe_prompt",
    "build_explain_prompt",
    "build_provider",
    "build_tagging_prompt",
    "build_verify_prompt",
    "describe_figure",
    "describe_one",
    "explain_one",
    "explain_question",
    "extract_json",
    "question_from_row",
    "snap_underline",
    "tag_one",
    "tag_question",
    "verify_one",
    "verify_output_from_text",
    "verify_question",
]
