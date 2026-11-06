from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import typer

from .agent.core import AgentRunner
from .config import Settings
from .models.schemas import PlanningRequest
from .repositories.database import Database

app = typer.Typer(add_completion=False, help="小影内容任务规划 Agent")


def _settings(db_path: Optional[str] = None) -> Settings:
    settings = Settings.from_env()
    if db_path:
        settings = Settings(settings.agent_mode, settings.openai_api_key, settings.openai_base_url, settings.openai_model, Path(db_path), settings.max_agent_steps, settings.max_tool_calls, settings.tool_timeout_seconds)
    return settings


@app.command("init-db")
def init_db(db_path: Optional[str] = typer.Option(None, "--db")) -> None:
    """初始化 SQLite 数据库。"""
    settings = _settings(db_path)
    db = Database(settings.database_path)
    db.initialize()
    typer.echo(f"数据库已初始化: {settings.database_path}")


@app.command("plan")
def plan(
    topic: str = typer.Option(..., "--topic"),
    budget: Optional[float] = typer.Option(None, "--budget"),
    deadline: Optional[str] = typer.Option(None, "--deadline"),
    task_id: str = typer.Option(..., "--task-id"),
    variant: str = typer.Option("standard", "--variant"),
    fail_material_once: bool = typer.Option(False, "--fail-material-once"),
    db_path: Optional[str] = typer.Option(None, "--db"),
) -> None:
    """执行一次动态规划任务并输出 JSON。"""
    settings = _settings(db_path)
    request = PlanningRequest(task_id=task_id, topic=topic, budget=budget, deadline=deadline, preferences={"variant": variant, "fail_material_once": fail_material_once})
    result = AgentRunner(settings=settings).run(request)
    typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("show-trace")
def show_trace(task_id: str = typer.Argument(...), db_path: Optional[str] = typer.Option(None, "--db")) -> None:
    settings = _settings(db_path)
    db = Database(settings.database_path)
    db.initialize()
    typer.echo(json.dumps(db.get_traces(task_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
