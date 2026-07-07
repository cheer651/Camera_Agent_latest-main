from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from schemas import FrameAnalysis


class EventStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self.lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    requested_duration INTEGER NOT NULL,
                    camera_ids_json TEXT NOT NULL,
                    error_message TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS camera_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    clip_path TEXT NOT NULL,
                    frames_written INTEGER NOT NULL,
                    fps REAL NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    anomaly_detected INTEGER NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    frame_path TEXT NOT NULL,
                    clip_path TEXT NOT NULL,
                    frame_second REAL NOT NULL,
                    llm_raw TEXT NOT NULL,
                    alert_sent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_date TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    sent_to_feishu INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            event_columns = {
                "event_group_id": "TEXT DEFAULT ''",
                "event_frame_count": "INTEGER NOT NULL DEFAULT 1",
                "representative_count": "INTEGER NOT NULL DEFAULT 1",
                "event_start_second": "REAL NOT NULL DEFAULT 0",
                "event_end_second": "REAL NOT NULL DEFAULT 0",
                "event_duration_seconds": "REAL NOT NULL DEFAULT 0",
                "person_present": "INTEGER NOT NULL DEFAULT 0",
                "person_count": "INTEGER NOT NULL DEFAULT 0",
                "action_type": "TEXT DEFAULT ''",
                "upper_clothing_color": "TEXT DEFAULT ''",
                "lower_clothing_color": "TEXT DEFAULT ''",
                "confidence": "REAL NOT NULL DEFAULT 0",
            }
            existing_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(events)").fetchall()
            }
            for column_name, column_spec in event_columns.items():
                if column_name not in existing_columns:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {column_name} {column_spec}")
            conn.commit()

    def create_task(
        self,
        task_id: str,
        started_at: str,
        status: str,
        trigger_type: str,
        requested_duration: int,
        camera_ids: list[str],
    ) -> None:
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, started_at, finished_at, status, trigger_type,
                    requested_duration, camera_ids_json, error_message
                ) VALUES (?, ?, '', ?, ?, ?, ?, '')
                """,
                (
                    task_id,
                    started_at,
                    status,
                    trigger_type,
                    requested_duration,
                    json.dumps(camera_ids, ensure_ascii=False),
                ),
            )
            conn.commit()

    def update_task(self, task_id: str, status: str, finished_at: str = "", error_message: str = "") -> None:
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, finished_at = ?, error_message = ?
                WHERE task_id = ?
                """,
                (status, finished_at, error_message, task_id),
            )
            conn.commit()

    def add_camera_run(
        self,
        task_id: str,
        camera_id: str,
        camera_name: str,
        clip_path: str,
        frames_written: int,
        fps: float,
        status: str,
        error_message: str = "",
    ) -> None:
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO camera_runs (
                    task_id, camera_id, camera_name, clip_path, frames_written,
                    fps, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    camera_id,
                    camera_name,
                    clip_path,
                    frames_written,
                    fps,
                    status,
                    error_message,
                ),
            )
            conn.commit()

    def get_camera_runs_by_task(self, task_id: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, task_id, camera_id, camera_name, clip_path, frames_written,
                       fps, status, error_message, created_at
                FROM camera_runs
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_event(
        self,
        task_id: str,
        camera_name: str,
        analysis: FrameAnalysis,
        raw_payload: str,
    ) -> int:
        with self.lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    task_id, camera_id, camera_name, event_time, risk_level,
                    anomaly_detected, anomaly_type, description, reason,
                    frame_path, clip_path, frame_second, llm_raw, alert_sent,
                    event_group_id, event_frame_count, representative_count,
                    event_start_second, event_end_second, event_duration_seconds,
                    person_present, person_count, action_type, upper_clothing_color,
                    lower_clothing_color, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    analysis.camera_id,
                    camera_name,
                    analysis.timestamp,
                    analysis.risk_level,
                    int(analysis.anomaly_detected),
                    analysis.anomaly_type,
                    analysis.description,
                    analysis.reason,
                    analysis.frame_path,
                    analysis.clip_path,
                    analysis.frame_second,
                    raw_payload,
                    analysis.event_group_id,
                    analysis.event_frame_count,
                    analysis.representative_count,
                    analysis.event_start_second,
                    analysis.event_end_second,
                    analysis.event_duration_seconds,
                    int(analysis.person_present),
                    analysis.person_count,
                    analysis.action_type,
                    analysis.upper_clothing_color,
                    analysis.lower_clothing_color,
                    analysis.confidence,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def mark_alert_sent(self, event_id: int, sent: bool = True) -> None:
        with self.lock, self._connect() as conn:
            conn.execute(
                "UPDATE events SET alert_sent = ? WHERE event_id = ?",
                (int(sent), event_id),
            )
            conn.commit()

    def list_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                ORDER BY event_time DESC, event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events_for_day(self, summary_date: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                WHERE substr(event_time, 1, 10) = ?
                ORDER BY event_time ASC, event_id ASC
                """,
                (summary_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events_between(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                WHERE substr(event_time, 1, 10) BETWEEN ? AND ?
                ORDER BY event_time ASC, event_id ASC
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_events(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        camera_id: str | None = None,
        risk_level: str | None = None,
        period_range: tuple[int, int] | None = None,
        person_present: bool | None = None,
        action_keywords: list[str] | None = None,
        clothing_keywords: list[str] | None = None,
        description_keywords: list[str] | None = None,
        limit: int | None = None,
        order_desc: bool = False,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if start_date and end_date:
            conditions.append("substr(event_time, 1, 10) BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif start_date:
            conditions.append("substr(event_time, 1, 10) = ?")
            params.append(start_date)

        if camera_id:
            conditions.append("camera_id = ?")
            params.append(camera_id)

        if risk_level:
            normalized = str(risk_level).strip().lower()
            alias_map = {
                "high": ["high", "high risk", "高危", "高风险"],
                "medium": ["medium", "medium risk", "中危", "中风险"],
                "low": ["low", "low risk", "低危", "低风险"],
            }
            aliases = alias_map.get(normalized, [normalized])
            risk_conditions: list[str] = []
            for alias in aliases:
                risk_conditions.append("LOWER(TRIM(risk_level)) = ?")
                params.append(str(alias).strip().lower())
            conditions.append("(" + " OR ".join(risk_conditions) + ")")

        if period_range:
            start_hour, end_hour = period_range
            conditions.append("CAST(substr(event_time, 12, 2) AS INTEGER) >= ?")
            params.append(int(start_hour))
            conditions.append("CAST(substr(event_time, 12, 2) AS INTEGER) < ?")
            params.append(int(end_hour))

        if person_present is not None:
            if person_present:
                conditions.append("(person_present = 1 OR description LIKE ? OR reason LIKE ?)")
                params.extend(["%人%", "%人%"])
            else:
                conditions.append("person_present = 0")

        if action_keywords:
            keyword_conditions: list[str] = []
            for keyword in action_keywords:
                keyword_conditions.append("(action_type = ? OR description LIKE ? OR reason LIKE ?)")
                params.extend([keyword, f"%{keyword}%", f"%{keyword}%"])
            conditions.append("(" + " OR ".join(keyword_conditions) + ")")

        if clothing_keywords:
            keyword_conditions = []
            for keyword in clothing_keywords:
                keyword_conditions.append(
                    "(upper_clothing_color = ? OR lower_clothing_color = ? OR description LIKE ? OR reason LIKE ?)"
                )
                params.extend([keyword, keyword, f"%{keyword}%", f"%{keyword}%"])
            conditions.append("(" + " OR ".join(keyword_conditions) + ")")

        if description_keywords:
            keyword_conditions = []
            for keyword in description_keywords:
                keyword_conditions.append("(description LIKE ? OR reason LIKE ? OR anomaly_type LIKE ?)")
                params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
            conditions.append("(" + " OR ".join(keyword_conditions) + ")")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_clause = "ORDER BY event_time DESC, event_id DESC" if order_desc else "ORDER BY event_time ASC, event_id ASC"
        limit_clause = f"LIMIT {int(limit)}" if limit else ""

        query = f"""
            SELECT *
            FROM events
            {where_clause}
            {order_clause}
            {limit_clause}
        """
        with self.lock, self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def save_summary(self, summary_date: str, title: str, body: str, sent_to_feishu: bool) -> None:
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO summaries (summary_date, title, body, sent_to_feishu)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(summary_date) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    sent_to_feishu = excluded.sent_to_feishu
                """,
                (summary_date, title, body, int(sent_to_feishu)),
            )
            conn.commit()

    def get_summary_by_date(self, summary_date: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM summaries
                WHERE summary_date = ?
                ORDER BY summary_id DESC
                LIMIT 1
                """,
                (summary_date,),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_summary(self) -> dict[str, Any] | None:
        with self.lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM summaries
                ORDER BY summary_date DESC, summary_id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None
