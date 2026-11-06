from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from .models.schemas import AgentMode

PROJECT_ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    agent_mode: AgentMode = AgentMode.MOCK
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    database_path: Path = PROJECT_ROOT / "data" / "xiaoying.db"
    max_agent_steps: int = 16
    max_tool_calls: int = 24
    tool_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        mode = AgentMode.REAL if os.getenv("AGENT_MODE", "mock").lower() == "real" else AgentMode.MOCK
        path = Path(os.getenv("DATABASE_PATH", str(cls.database_path)))
        if not path.is_absolute(): path = PROJECT_ROOT / path
        return cls(mode, os.getenv("OPENAI_API_KEY") or None, os.getenv("OPENAI_BASE_URL") or None, os.getenv("OPENAI_MODEL", "gpt-4o-mini"), path, int(os.getenv("MAX_AGENT_STEPS", "16")), int(os.getenv("MAX_TOOL_CALLS", "24")), float(os.getenv("TOOL_TIMEOUT_SECONDS", "10")))
