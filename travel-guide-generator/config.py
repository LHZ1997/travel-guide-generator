"""Configuration management for Travel Guide Generator."""
import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


class LLMConfig:
    """Configuration for a single LLM client."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 60,
        thinking_enabled: bool = True,
        reasoning_effort: str = "high",
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.thinking_enabled = thinking_enabled
        self.reasoning_effort = reasoning_effort

    @classmethod
    def from_dict(cls, data: dict) -> "LLMConfig":
        return cls(
            provider=data.get("provider", "openai"),
            model=data.get("model", "gpt-4o"),
            api_key=data.get("api_key", ""),
            api_base=data.get("api_base"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
            timeout=data.get("timeout", 60),
            thinking_enabled=data.get("thinking_enabled", True),
            reasoning_effort=data.get("reasoning_effort", "high"),
        )

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "thinking_enabled": self.thinking_enabled,
            "reasoning_effort": self.reasoning_effort,
        }


class AppConfig:
    """Application configuration."""

    def __init__(self):
        self.database_uri = os.getenv(
            "DATABASE_URI", f"sqlite:///{INSTANCE_DIR / 'app.db'}"
        )
        self.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
        self.debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"

        # LLM configurations
        self.planner_config = self._load_llm_config("planner")
        self.orchestrator_config = self._load_llm_config("orchestrator")
        self.checker_config = self._load_llm_config("checker")

        # Skill configurations
        self.skill_config = self._load_skill_config()

    def _load_llm_config(self, role: str) -> LLMConfig:
        """Load LLM config from environment or config file."""
        config_file = BASE_DIR / "config.yaml"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            llm_data = data.get("llm", {}).get(role, {})
            if llm_data:
                return LLMConfig.from_dict(llm_data)

        # Fallback to environment variables
        prefix = role.upper()
        return LLMConfig(
            provider=os.getenv(f"{prefix}_PROVIDER", "openai"),
            model=os.getenv(f"{prefix}_MODEL", "gpt-4o"),
            api_key=os.getenv(f"{prefix}_API_KEY", ""),
            api_base=os.getenv(f"{prefix}_API_BASE"),
            temperature=float(os.getenv(f"{prefix}_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv(f"{prefix}_MAX_TOKENS", "4096")),
            thinking_enabled=os.getenv(f"{prefix}_THINKING_ENABLED", "true").lower() == "true",
            reasoning_effort=os.getenv(f"{prefix}_REASONING_EFFORT", "high"),
        )

    def _load_skill_config(self) -> dict:
        """Load skill configurations."""
        config_file = BASE_DIR / "config.yaml"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("skills", {})
        return {}

    def save_llm_config(self, role: str, config: LLMConfig):
        """Save LLM config to config file."""
        config_file = BASE_DIR / "config.yaml"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        if "llm" not in data:
            data["llm"] = {}
        data["llm"][role] = config.to_dict()

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


# Global config instance
app_config = AppConfig()
