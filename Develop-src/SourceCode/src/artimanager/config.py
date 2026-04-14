"""Application configuration layer.

All modules access settings through this module.
No module should read raw config files directly.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentOverrideConfig:
    """Settings for a feature-specific provider override."""

    provider: str = ""
    model: str = ""
    api_key_env: str = ""  # env var name, never the actual key

    @property
    def api_key(self) -> str | None:
        """Resolve API key from environment variable."""
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)


@dataclass
class AgentOverridesConfig:
    """Container for optional feature-specific provider overrides."""

    analysis: AgentOverrideConfig | None = None


@dataclass
class AgentConfig:
    """Settings for the default agent provider."""

    provider: str = "mock"
    model: str = ""
    api_key_env: str = ""  # env var name, never the actual key
    overrides: AgentOverridesConfig = field(default_factory=AgentOverridesConfig)

    @property
    def api_key(self) -> str | None:
        """Resolve API key from environment variable."""
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)


@dataclass
class ZoteroConfig:
    """Settings for Zotero integration."""

    library_id: str = ""
    library_type: str = "user"  # "user" | "group"
    api_key_env: str = ""  # env var name, never the actual key

    @property
    def api_key(self) -> str | None:
        """Resolve API key from environment variable."""
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)


@dataclass
class DeepXivConfig:
    """Settings for DeepXiv retrieval backend."""

    enabled: bool = False
    api_token_env: str = ""
    base_url: str = "https://data.rag.ac.cn/arxiv/"
    timeout_seconds: int = 20
    search_mode: str = "hybrid"

    @property
    def api_token(self) -> str | None:
        """Resolve DeepXiv token from environment variable."""
        if not self.api_token_env:
            return None
        return os.environ.get(self.api_token_env)


@dataclass
class OpenAIConfig:
    """Runtime settings for OpenAI provider transports."""

    auth_mode: str = "api_key_env"  # "api_key_env" | "codex_chatgpt"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60
    codex_bin: str = "codex"
    codex_auth_path: str = "~/.codex/auth.json"


@dataclass
class LocalConfig:
    """Runtime settings for local Ollama-compatible provider."""

    endpoint: str = "http://localhost:11434"
    timeout_seconds: int = 60


@dataclass
class AppConfig:
    """Root application configuration."""

    # Paths
    scan_folders: list[str] = field(default_factory=list)
    db_path: str = "artimanager.db"
    notes_root: str = "notes"
    template_path: str = ""  # path to note template; defaults to bundled template

    # Agent
    agent: AgentConfig = field(default_factory=AgentConfig)

    # Zotero
    zotero: ZoteroConfig = field(default_factory=ZoteroConfig)

    # DeepXiv
    deepxiv: DeepXivConfig = field(default_factory=DeepXivConfig)

    # OpenAI runtime options
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)

    # Local runtime options
    local: LocalConfig = field(default_factory=LocalConfig)

    # Logging
    log_level: str = "INFO"

    # Tracking
    tracking_schedule: str = "daily"


def resolve_analysis_agent_config(cfg: AppConfig) -> AgentConfig:
    """Resolve agent config for analysis feature with partial override merge.

    Resolution order:
    1. `[agent.overrides.analysis]` field value when non-empty
    2. fallback to root `[agent]` value for that field
    """
    base = cfg.agent
    override = base.overrides.analysis
    if override is None:
        return AgentConfig(
            provider=base.provider,
            model=base.model,
            api_key_env=base.api_key_env,
        )

    provider = override.provider or base.provider
    model = override.model or base.model
    api_key_env = override.api_key_env or base.api_key_env
    return AgentConfig(
        provider=provider,
        model=model,
        api_key_env=api_key_env,
    )


def _build_agent_config(raw: dict[str, Any]) -> AgentConfig:
    """Build AgentConfig from a raw dict, ignoring unknown keys."""
    top_known = {"provider", "model", "api_key_env"}
    top = {k: v for k, v in raw.items() if k in top_known}

    overrides = AgentOverridesConfig()
    raw_overrides = raw.get("overrides")
    if isinstance(raw_overrides, dict):
        analysis_raw = raw_overrides.get("analysis")
        if isinstance(analysis_raw, dict):
            ov_known = {f.name for f in AgentOverrideConfig.__dataclass_fields__.values()}
            ov_top = {k: v for k, v in analysis_raw.items() if k in ov_known}
            overrides.analysis = AgentOverrideConfig(**ov_top)

    return AgentConfig(**top, overrides=overrides)


def _build_zotero_config(raw: dict[str, Any]) -> ZoteroConfig:
    """Build ZoteroConfig from a raw dict, ignoring unknown keys."""
    known = {f.name for f in ZoteroConfig.__dataclass_fields__.values()}
    return ZoteroConfig(**{k: v for k, v in raw.items() if k in known})


def _build_deepxiv_config(raw: dict[str, Any]) -> DeepXivConfig:
    """Build DeepXivConfig from a raw dict, ignoring unknown keys."""
    known = {f.name for f in DeepXivConfig.__dataclass_fields__.values()}
    return DeepXivConfig(**{k: v for k, v in raw.items() if k in known})


def _build_openai_config(raw: dict[str, Any]) -> OpenAIConfig:
    """Build OpenAIConfig from a raw dict with validation."""
    known = {f.name for f in OpenAIConfig.__dataclass_fields__.values()}
    cfg = OpenAIConfig(**{k: v for k, v in raw.items() if k in known})

    if cfg.auth_mode not in {"api_key_env", "codex_chatgpt"}:
        raise ValueError(
            "Invalid [openai].auth_mode. Expected 'api_key_env' or 'codex_chatgpt'."
        )
    if cfg.auth_mode == "codex_chatgpt":
        if not cfg.codex_bin.strip():
            raise ValueError(
                "[openai].codex_bin must be set when auth_mode='codex_chatgpt'."
            )
        if not cfg.codex_auth_path.strip():
            raise ValueError(
                "[openai].codex_auth_path must be set when auth_mode='codex_chatgpt'."
            )
    return cfg


def _build_local_config(raw: dict[str, Any]) -> LocalConfig:
    """Build LocalConfig from a raw dict, ignoring unknown keys."""
    known = {f.name for f in LocalConfig.__dataclass_fields__.values()}
    return LocalConfig(**{k: v for k, v in raw.items() if k in known})


def load_config(path: str | Path) -> AppConfig:
    """Load configuration from a TOML file.

    Parameters
    ----------
    path:
        Path to a TOML configuration file.

    Returns
    -------
    AppConfig with values from the file, falling back to defaults for
    any missing keys.
    """
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)

    agent_raw = raw.pop("agent", {})
    agent = _build_agent_config(agent_raw) if agent_raw else AgentConfig()

    zotero_raw = raw.pop("zotero", {})
    zotero = _build_zotero_config(zotero_raw) if zotero_raw else ZoteroConfig()

    deepxiv_raw = raw.pop("deepxiv", {})
    deepxiv = _build_deepxiv_config(deepxiv_raw) if deepxiv_raw else DeepXivConfig()

    openai_raw = raw.pop("openai", {})
    openai = _build_openai_config(openai_raw) if openai_raw else OpenAIConfig()

    local_raw = raw.pop("local", {})
    local = _build_local_config(local_raw) if local_raw else LocalConfig()

    # Build top-level config, ignoring unknown keys
    known = {f.name for f in AppConfig.__dataclass_fields__.values()} - {"agent"}
    top = {k: v for k, v in raw.items() if k in known}

    # Keep SourceCode usable without relying on external planning directories.
    if not top.get("template_path"):
        top["template_path"] = str(
            Path(__file__).resolve().parents[2] / "data" / "paper-note-template.md"
        )

    return AppConfig(
        **top,
        agent=agent,
        zotero=zotero,
        deepxiv=deepxiv,
        openai=openai,
        local=local,
    )


def default_config() -> AppConfig:
    """Return a config with all defaults — useful for tests."""
    return AppConfig()
