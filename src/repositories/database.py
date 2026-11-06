from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.schemas import AgentMode, PlanningRequest, StepStatus, TaskStatus, TaskStep, TraceEvent


class Database:
    """Small transactional SQLite repository used by both Mock and Real runners."""

    def __init__(self, path: str | Path = "data/xiaoying.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA journal_mode=WAL")

    def initialize(self) -> None:
        with self._lock, self.conn:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY, topic TEXT NOT NULL, request_json TEXT NOT NULL,
              status TEXT NOT NULL, mode TEXT NOT NULL, message TEXT DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
              task_id TEXT NOT NULL, step_id TEXT NOT NULL, step_name TEXT NOT NULL,
              description TEXT NOT NULL, dependencies_json TEXT NOT NULL, tool_name TEXT NOT NULL,
              estimated_cost REAL NOT NULL, actual_cost REAL, estimated_duration REAL NOT NULL,
              status TEXT NOT NULL, result_json TEXT, error TEXT, updated_at TEXT NOT NULL,
              PRIMARY KEY(task_id, step_id), FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS tool_results (
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, step_id TEXT NOT NULL,
              tool_name TEXT NOT NULL, arguments_json TEXT NOT NULL, result_json TEXT NOT NULL,
              created_at TEXT NOT NULL, FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS traces (
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, step TEXT NOT NULL,
              mode TEXT NOT NULL, event_json TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS proposals (
              proposal_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, proposal_json TEXT NOT NULL,
              created_at TEXT NOT NULL, FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_trace_task ON traces(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_results_task ON tool_results(task_id, id);
            """)

    def close(self) -> None:
        self.conn.close()

    def create_or_get_task(self, request: PlanningRequest, mode: AgentMode) -> sqlite3.Row:
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO tasks(task_id,topic,request_json,status,mode,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (request.task_id, request.topic, payload, TaskStatus.PLANNING.value, mode.value, "", now, now),
            )
        return self.get_task(request.task_id)

    def get_task(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()

    def update_task(self, task_id: str, status: TaskStatus, message: str = "") -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE tasks SET status=?, message=?, updated_at=? WHERE task_id=?", (status.value, message, datetime.now(timezone.utc).isoformat(), task_id))

    def update_task_request(self, task_id: str, request: PlanningRequest) -> None:
        """Replace the request only when a NEEDS_INFO task is completed by the caller."""
        payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        with self._lock, self.conn:
            self.conn.execute("UPDATE tasks SET topic=?, request_json=?, updated_at=? WHERE task_id=?", (request.topic, payload, datetime.now(timezone.utc).isoformat(), task_id))

    @staticmethod
    def _request_fingerprint(request: PlanningRequest) -> str:
        payload = request.model_dump(mode="json")
        # Fault-injection switches are execution controls, not business input.
        preferences = dict(payload.get("preferences") or {})
        for key in ("fail_material_once", "force_material_failure", "fail_script_once", "force_script_failure", "force_save_failure", "partial_material"):
            preferences.pop(key, None)
        payload["preferences"] = preferences
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def request_matches(self, row: sqlite3.Row, request: PlanningRequest) -> bool:
        stored = json.loads(row["request_json"])
        stored_preferences = dict(stored.get("preferences") or {})
        for key in ("fail_material_once", "force_material_failure", "fail_script_once", "force_script_failure", "force_save_failure", "partial_material"):
            stored_preferences.pop(key, None)
        stored["preferences"] = stored_preferences
        return self._request_fingerprint(request) == json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def request_fills_missing_info(self, row: sqlite3.Row, request: PlanningRequest) -> bool:
        """Allow a NEEDS_INFO task to receive values that were previously absent."""
        stored = json.loads(row["request_json"])
        if stored.get("task_id") != request.task_id or stored.get("topic") != request.topic:
            return False
        if stored.get("budget") is not None and stored.get("budget") != request.budget:
            return False
        if stored.get("deadline") is not None and stored.get("deadline") != request.model_dump(mode="json").get("deadline"):
            return False
        stored_preferences = dict(stored.get("preferences") or {})
        current_preferences = dict(request.preferences or {})
        for key in ("fail_material_once", "force_material_failure", "fail_script_once", "force_script_failure", "force_save_failure", "partial_material"):
            stored_preferences.pop(key, None)
            current_preferences.pop(key, None)
        return stored_preferences == current_preferences

    def upsert_step(self, task_id: str, step: TaskStep) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute("""INSERT INTO steps(task_id,step_id,step_name,description,dependencies_json,tool_name,estimated_cost,actual_cost,estimated_duration,status,result_json,error,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,step_id) DO UPDATE SET step_name=excluded.step_name,description=excluded.description,dependencies_json=excluded.dependencies_json,tool_name=excluded.tool_name,estimated_cost=excluded.estimated_cost,actual_cost=excluded.actual_cost,estimated_duration=excluded.estimated_duration,status=excluded.status,result_json=excluded.result_json,error=excluded.error,updated_at=excluded.updated_at""",
                (task_id, step.step_id, step.step_name, step.description, json.dumps(step.dependencies), step.tool_name, step.estimated_cost, step.actual_cost, step.estimated_duration, step.status.value, json.dumps(step.result, ensure_ascii=False) if step.result is not None else None, step.error, now))

    def get_steps(self, task_id: str) -> list[TaskStep]:
        rows = self.conn.execute("SELECT * FROM steps WHERE task_id=? ORDER BY rowid", (task_id,)).fetchall()
        return [TaskStep(step_id=r["step_id"], step_name=r["step_name"], description=r["description"], dependencies=json.loads(r["dependencies_json"]), tool_name=r["tool_name"], estimated_cost=r["estimated_cost"], actual_cost=r["actual_cost"], estimated_duration=r["estimated_duration"], status=StepStatus(r["status"]), result=json.loads(r["result_json"]) if r["result_json"] else None, error=r["error"]) for r in rows]

    def add_tool_result(self, task_id: str, step_id: str, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        with self._lock, self.conn:
            self.conn.execute("INSERT INTO tool_results(task_id,step_id,tool_name,arguments_json,result_json,created_at) VALUES(?,?,?,?,?,?)", (task_id, step_id, tool_name, json.dumps(arguments, ensure_ascii=False), json.dumps(result, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))

    def record_tool_execution(self, task_id: str, step: TaskStep, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Atomically persist the terminal step state and its tool observation."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute("""INSERT INTO steps(task_id,step_id,step_name,description,dependencies_json,tool_name,estimated_cost,actual_cost,estimated_duration,status,result_json,error,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,step_id) DO UPDATE SET step_name=excluded.step_name,description=excluded.description,dependencies_json=excluded.dependencies_json,tool_name=excluded.tool_name,estimated_cost=excluded.estimated_cost,actual_cost=excluded.actual_cost,estimated_duration=excluded.estimated_duration,status=excluded.status,result_json=excluded.result_json,error=excluded.error,updated_at=excluded.updated_at""",
                (task_id, step.step_id, step.step_name, step.description, json.dumps(step.dependencies), step.tool_name, step.estimated_cost, step.actual_cost, step.estimated_duration, step.status.value, json.dumps(step.result, ensure_ascii=False) if step.result is not None else None, step.error, now))
            self.conn.execute("INSERT INTO tool_results(task_id,step_id,tool_name,arguments_json,result_json,created_at) VALUES(?,?,?,?,?,?)", (task_id, step.step_id, step.tool_name, json.dumps(arguments, ensure_ascii=False), json.dumps(result, ensure_ascii=False), now))

    def add_trace(self, event: TraceEvent) -> None:
        with self._lock, self.conn:
            self.conn.execute("INSERT INTO traces(task_id,step,mode,event_json,created_at) VALUES(?,?,?,?,?)", (event.task_id, event.step, event.mode.value, json.dumps(event.model_dump(mode="json"), ensure_ascii=False), event.created_at.isoformat()))

    def get_traces(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT event_json FROM traces WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_proposal(self, task_id: str, proposal: dict[str, Any]) -> tuple[str, bool]:
        """Return proposal id and whether a new row was inserted."""
        proposal_id = f"proposal-{uuid.uuid4().hex[:12]}"
        with self._lock, self.conn:
            cursor = self.conn.execute("INSERT OR IGNORE INTO proposals(proposal_id,task_id,proposal_json,created_at) VALUES(?,?,?,?)", (proposal_id, task_id, json.dumps(proposal, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            existing = self.conn.execute("SELECT proposal_id FROM proposals WHERE task_id=?", (task_id,)).fetchone()
        if existing is None:
            raise RuntimeError(f"task_id 不存在: {task_id}")
        return str(existing[0]), cursor.rowcount == 1

    def get_proposal(self, task_id: str) -> tuple[str, dict[str, Any]] | None:
        row = self.conn.execute("SELECT proposal_id,proposal_json FROM proposals WHERE task_id=?", (task_id,)).fetchone()
        return (str(row[0]), json.loads(row[1])) if row else None

    def count_proposals(self, task_id: str | None = None) -> int:
        if task_id is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM proposals WHERE task_id=?", (task_id,)).fetchone()[0])
