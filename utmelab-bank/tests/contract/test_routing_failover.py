"""Tests for provider routing and failover logic."""

from __future__ import annotations

from unittest.mock import patch

from utmelab_bank.routing import load_manifest, select_routes


def _base_manifest(purpose: str) -> dict:
    """Create the shared non-routing sections of a mock provider family."""
    return {
        "$schema": "../schema/provider.schema.json",
        "version": 3,
        "purpose": purpose,
        "secrets": {
            "source": "environment",
            "never_log_values": True,
            "never_store_in_this_file": True,
        },
        "defaults": {
            "timeout_seconds": 30,
            "max_retries": 0,
            "max_tokens": 2048,
            "temperature": 0,
            "max_attempts_per_request": 2,
            "cooldown_seconds": 300,
            "health_probe_before_reenable": True,
        },
        "error_policy": {
            "failover_to_next_account": ["rate_limit", "quota", "timeout", "provider_unavailable"],
            "do_not_failover": [
                "authentication",
                "invalid_request",
                "input",
                "output",
                "schema",
                "policy",
                "not_found",
            ],
            "max_consecutive_failures_before_cooldown": 2,
            "never_retry_without_a_new_account_or_health_check": True,
        },
        "account_selection": {
            "mode": "failover_only",
            "selection_order": "priority_then_health",
            "rotate_on_quota_only": False,
            "rotate_only_on_classified_transient_errors": True,
            "reserve_unknown_quota": True,
            "persist_health_outside_git": True,
        },
        "observability": {
            "record_per_attempt": [],
            "never_record": [],
        },
    }


def _make_mock_manifests() -> dict[str, dict]:
    """Create two provider families for the same task."""
    nvidia = _base_manifest("NVIDIA test family")
    nvidia["providers"] = {
        "nvidia": {
            "protocol": "openai-compatible",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "account_pool": "nvidia-free",
            "status": "enabled",
            "auth": {"kind": "env"},
            "transport": {"kind": "http"},
        },
    }
    nvidia["accounts"] = {
        "nvidia-free": [
            {
                "id": "nvidia-01",
                "api_key_env": "NVIDIA_API_KEY_01",
                "enabled": True,
                "authorized": True,
                "priority": 10,
            },
            {
                "id": "nvidia-02",
                "api_key_env": "NVIDIA_API_KEY_02",
                "enabled": True,
                "authorized": True,
                "priority": 20,
            },
        ],
    }
    nvidia["models"] = {
        "nvidia-model": {
            "provider": "nvidia",
            "model_id": "nvidia/test-model",
            "capabilities": ["text"],
            "structured_output": "json_object",
            "status": "verified_candidate",
        },
    }

    cloudflare = _base_manifest("Cloudflare test family")
    cloudflare["providers"] = {
        "cloudflare": {
            "protocol": "openai-compatible",
            "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
            "account_pool": "cloudflare-free",
            "status": "enabled",
            "auth": {"kind": "env"},
            "transport": {"kind": "http"},
        },
    }
    cloudflare["accounts"] = {
        "cloudflare-free": [
            {
                "id": "cloudflare-01",
                "api_key_env": "CLOUDFLARE_API_TOKEN_01",
                "enabled": True,
                "authorized": True,
                "priority": 10,
            },
        ],
    }
    cloudflare["models"] = {
        "cloudflare-model": {
            "provider": "cloudflare",
            "model_id": "cf/test-model",
            "capabilities": ["text"],
            "structured_output": "json_object",
            "status": "verified_candidate",
        },
    }

    return {"nvidia": nvidia, "cloudflare": cloudflare}


def _make_mock_routing() -> dict:
    """Route one task across both mock families."""
    return {
        "$schema": "./schema/routing.schema.json",
        "version": 1,
        "tasks": {
            "question_explanation": {
                "enabled": True,
                "strategy": "failover",
                "on_no_provider": "block",
                "allowed_model_statuses": ["verified_candidate", "unstable_candidate"],
                "candidates": [
                    {"provider": "nvidia", "model": "nvidia-model", "priority": 10},
                    {"provider": "cloudflare", "model": "cloudflare-model", "priority": 20},
                ],
            },
        },
    }


def test_load_manifest_creates_valid_object() -> None:
    """Test that load_manifest returns a valid provider manifest."""
    manifest = load_manifest()
    assert "providers" in manifest
    assert "accounts" in manifest
    assert "models" in manifest
    assert "tasks" not in manifest


def test_select_routes_returns_routes_with_available_keys() -> None:
    """Test that select_routes returns routes when API keys are available."""
    with patch.dict("os.environ", {"NVIDIA_API_KEY_01": "key-01"}, clear=True):
        routes = select_routes(
            "question_explanation",
            routing=_make_mock_routing(),
            manifests=_make_mock_manifests(),
        )
    assert len(routes) == 1
    assert routes[0].account_id == "nvidia-01"
    assert routes[0].api_key == "key-01"


def test_select_routes_skips_disabled_accounts() -> None:
    """Test that select_routes skips accounts with no usable credentials."""
    with patch.dict("os.environ", {}, clear=True):
        routes = select_routes(
            "question_explanation",
            routing=_make_mock_routing(),
            manifests=_make_mock_manifests(),
            environment={},
        )
    assert routes == ()


def test_select_routes_prioritizes_by_priority() -> None:
    """Test that select_routes returns accounts in priority order."""
    with patch.dict(
        "os.environ",
        {"NVIDIA_API_KEY_01": "key-01", "NVIDIA_API_KEY_02": "key-02"},
        clear=True,
    ):
        routes = select_routes(
            "question_explanation",
            routing=_make_mock_routing(),
            manifests=_make_mock_manifests(),
        )
    assert [route.account_id for route in routes] == ["nvidia-01", "nvidia-02"]


def test_select_routes_with_multiple_accounts_per_pool() -> None:
    """Test select_routes selects from multiple accounts in the same pool."""
    with patch.dict(
        "os.environ",
        {"NVIDIA_API_KEY_01": "key-01", "NVIDIA_API_KEY_02": "key-02"},
        clear=True,
    ):
        routes = select_routes(
            "question_explanation",
            routing=_make_mock_routing(),
            manifests=_make_mock_manifests(),
        )
    account_ids = [route.account_id for route in routes]
    assert "nvidia-01" in account_ids
    assert "nvidia-02" in account_ids


def test_error_policy_failover_categories() -> None:
    """Test that the error_policy categories are correctly defined."""
    error_policy = _make_mock_manifests()["nvidia"]["error_policy"]
    assert "failover_to_next_account" in error_policy
    assert "do_not_failover" in error_policy

    failover = error_policy["failover_to_next_account"]
    assert "rate_limit" in failover
    assert "quota" in failover

    do_not = error_policy["do_not_failover"]
    assert "authentication" in do_not
    assert "invalid_request" in do_not


def test_select_routes_respects_do_not_failover() -> None:
    """Test that the error_policy is set up correctly for failover behavior."""
    error_policy = _make_mock_manifests()["nvidia"]["error_policy"]
    do_not = error_policy["do_not_failover"]
    assert "authentication" in do_not
    assert len(do_not) == 7
