"""Tests for the configuration layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from artimanager.config import (
    AppConfig,
    AgentConfig,
    default_config,
    load_config,
    resolve_analysis_agent_config,
)


class TestDefaultConfig:
    def test_returns_app_config(self) -> None:
        cfg = default_config()
        assert isinstance(cfg, AppConfig)

    def test_default_values(self) -> None:
        cfg = default_config()
        assert cfg.scan_folders == []
        assert cfg.db_path == "artimanager.db"
        assert cfg.notes_root == "notes"
        assert cfg.log_level == "INFO"
        assert cfg.agent.provider == "mock"
        assert cfg.deepxiv.enabled is False
        assert cfg.openai.auth_mode == "api_key_env"
        assert cfg.local.endpoint == "http://localhost:11434"


class TestLoadConfig:
    def test_load_minimal(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text('db_path = "my.db"\n')
        cfg = load_config(toml)
        assert cfg.db_path == "my.db"
        # Unspecified fields keep defaults
        assert cfg.log_level == "INFO"
        assert cfg.template_path.endswith("data/paper-note-template.md")
        assert Path(cfg.template_path).exists()

    def test_load_with_agent_section(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            'db_path = "test.db"\n'
            "[agent]\n"
            'provider = "claude"\n'
            'model = "claude-sonnet-4-20250514"\n'
            'api_key_env = "MY_KEY"\n'
        )
        cfg = load_config(toml)
        assert cfg.agent.provider == "claude"
        assert cfg.agent.model == "claude-sonnet-4-20250514"
        assert cfg.agent.api_key_env == "MY_KEY"

    def test_load_scan_folders(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text('scan_folders = ["/a", "/b"]\n')
        cfg = load_config(toml)
        assert cfg.scan_folders == ["/a", "/b"]

    def test_unknown_keys_ignored(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text('db_path = "x.db"\nunknown_key = 42\n')
        cfg = load_config(toml)
        assert cfg.db_path == "x.db"

    def test_load_with_analysis_override(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[agent]\n"
            'provider = "mock"\n'
            'model = "base-model"\n'
            'api_key_env = "BASE_KEY"\n'
            "[agent.overrides.analysis]\n"
            'provider = "claude"\n'
            'model = "claude-model"\n'
            'api_key_env = "ANALYSIS_KEY"\n'
        )
        cfg = load_config(toml)
        assert cfg.agent.provider == "mock"
        assert cfg.agent.overrides.analysis is not None
        assert cfg.agent.overrides.analysis.provider == "claude"
        assert cfg.agent.overrides.analysis.model == "claude-model"
        assert cfg.agent.overrides.analysis.api_key_env == "ANALYSIS_KEY"

    def test_analysis_override_defaults_to_none(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text("[agent]\nprovider = 'mock'\n")
        cfg = load_config(toml)
        assert cfg.agent.overrides.analysis is None

    def test_load_with_partial_analysis_override(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[agent]\n"
            'provider = "mock"\n'
            'model = "base-model"\n'
            'api_key_env = "BASE_KEY"\n'
            "[agent.overrides.analysis]\n"
            'model = "analysis-model"\n'
        )
        cfg = load_config(toml)
        assert cfg.agent.overrides.analysis is not None
        assert cfg.agent.overrides.analysis.provider == ""
        assert cfg.agent.overrides.analysis.model == "analysis-model"
        assert cfg.agent.overrides.analysis.api_key_env == ""

    def test_load_with_deepxiv_section(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[deepxiv]\n"
            "enabled = true\n"
            'api_token_env = "DEEPXIV_TOKEN"\n'
            'base_url = "https://example.deepxiv.local/arxiv/"\n'
            "timeout_seconds = 11\n"
            'search_mode = "hybrid"\n'
        )
        cfg = load_config(toml)
        assert cfg.deepxiv.enabled is True
        assert cfg.deepxiv.api_token_env == "DEEPXIV_TOKEN"
        assert cfg.deepxiv.base_url == "https://example.deepxiv.local/arxiv/"
        assert cfg.deepxiv.timeout_seconds == 11
        assert cfg.deepxiv.search_mode == "hybrid"

    def test_load_with_openai_and_local_sections(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[openai]\n"
            'auth_mode = "codex_chatgpt"\n'
            'base_url = "https://proxy.example/v1"\n'
            "timeout_seconds = 17\n"
            'codex_bin = "codex"\n'
            'codex_auth_path = "~/.codex/auth.json"\n'
            "[local]\n"
            'endpoint = "http://localhost:11434"\n'
            "timeout_seconds = 31\n"
        )
        cfg = load_config(toml)
        assert cfg.openai.auth_mode == "codex_chatgpt"
        assert cfg.openai.base_url == "https://proxy.example/v1"
        assert cfg.openai.timeout_seconds == 17
        assert cfg.openai.codex_bin == "codex"
        assert cfg.local.endpoint == "http://localhost:11434"
        assert cfg.local.timeout_seconds == 31

    def test_invalid_openai_auth_mode_fails_early(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[openai]\n"
            'auth_mode = "oauth"\n'
        )
        with pytest.raises(ValueError, match="Invalid \\[openai\\]\\.auth_mode"):
            load_config(toml)

    def test_codex_auth_mode_requires_codex_fields(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[openai]\n"
            'auth_mode = "codex_chatgpt"\n'
            'codex_bin = ""\n'
            'codex_auth_path = ""\n'
        )
        with pytest.raises(ValueError, match="codex_bin"):
            load_config(toml)


class TestAgentConfigApiKey:
    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_KEY_VAR", "secret123")
        ac = AgentConfig(api_key_env="TEST_KEY_VAR")
        assert ac.api_key == "secret123"

    def test_api_key_missing_env(self) -> None:
        ac = AgentConfig(api_key_env="NONEXISTENT_VAR_12345")
        assert ac.api_key is None

    def test_api_key_no_env_configured(self) -> None:
        ac = AgentConfig()
        assert ac.api_key is None


class TestDeepXivConfigToken:
    def test_token_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("DEEPXIV_TOKEN", "dx-secret")
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[deepxiv]\n"
            "enabled = true\n"
            'api_token_env = "DEEPXIV_TOKEN"\n'
        )
        cfg = load_config(toml)
        assert cfg.deepxiv.api_token == "dx-secret"

    def test_token_missing_env(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[deepxiv]\n"
            "enabled = true\n"
            'api_token_env = "DEEPXIV_MISSING_TOKEN"\n'
        )
        cfg = load_config(toml)
        assert cfg.deepxiv.api_token is None


class TestResolveAnalysisAgentConfig:
    def test_falls_back_to_root_when_no_override(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[agent]\n"
            'provider = "mock"\n'
            'model = "root-model"\n'
            'api_key_env = "ROOT_KEY"\n'
        )
        cfg = load_config(toml)
        resolved = resolve_analysis_agent_config(cfg)
        assert resolved.provider == "mock"
        assert resolved.model == "root-model"
        assert resolved.api_key_env == "ROOT_KEY"

    def test_partially_overrides_root(self, tmp_path: Path) -> None:
        toml = tmp_path / "config.toml"
        toml.write_text(
            "[agent]\n"
            'provider = "mock"\n'
            'model = "root-model"\n'
            'api_key_env = "ROOT_KEY"\n'
            "[agent.overrides.analysis]\n"
            'model = "analysis-model"\n'
        )
        cfg = load_config(toml)
        resolved = resolve_analysis_agent_config(cfg)
        assert resolved.provider == "mock"
        assert resolved.model == "analysis-model"
        assert resolved.api_key_env == "ROOT_KEY"
