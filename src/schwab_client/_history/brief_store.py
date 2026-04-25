"""Brief-run persistence helpers for the history store."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from src.core.errors import ConfigError
from src.core.json_types import JsonValue


class HistoryBriefStoreMixin:
    if TYPE_CHECKING:
        def _connect(self, *, query_only: bool = False) -> sqlite3.Connection: ...

        def _fetch_all(
            self, sql: str, params: list[JsonValue] | tuple[JsonValue, ...]
        ) -> list[dict[str, JsonValue]]: ...

    def create_or_update_brief_run(self, **kwargs: JsonValue) -> int:
        snapshot_id = kwargs.get("snapshot_id")
        snapshot_observed_at = kwargs.get("snapshot_observed_at")
        brief_for_date = kwargs.get("brief_for_date")
        if snapshot_id is None or snapshot_observed_at is None or brief_for_date is None:
            raise ConfigError(
                "brief run requires snapshot_id, snapshot_observed_at, and brief_for_date"
            )

        existing = self.get_brief_run_by_snapshot_id(int(snapshot_id))
        fields = [
            "snapshot_observed_at",
            "brief_for_date",
            "status",
            "context_json",
            "scorecard_json",
            "analysis_json",
            "analysis_raw_response",
            "analysis_model_command",
            "analysis_prompt_version",
            "advisor_run_id",
            "advisor_issue_key",
            "briefing_json",
            "email_subject",
            "email_html",
            "email_text",
            "fallback_mode",
            "last_error",
            "sent_at",
        ]
        payload = {
            field: kwargs[field] if field in kwargs else (existing.get(field) if existing else None)
            for field in fields
        }
        for key in ("context_json", "scorecard_json", "analysis_json", "briefing_json"):
            payload[key] = self._json_dumps(payload.get(key))
        payload.setdefault("status", "captured")
        assignments = ",\n                        ".join(
            f"{field} = excluded.{field}" for field in fields
        )
        sql = f"""
            INSERT INTO brief_runs (
                snapshot_id,
                {', '.join(fields)}
            ) VALUES (
                ?,
                {', '.join(['?'] * len(fields))}
            )
            ON CONFLICT(snapshot_id) DO UPDATE SET
                {assignments},
                updated_at = CURRENT_TIMESTAMP
            """
        with self._connect() as conn:
            conn.execute(sql, [snapshot_id, *[payload[field] for field in fields]])
            conn.commit()
            row = conn.execute(
                "SELECT id FROM brief_runs WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                raise ConfigError("Could not determine brief run id")
            return int(row[0])

    def record_brief_delivery(
        self,
        brief_run_id: int,
        *,
        channel: str,
        recipient_json: dict[str, JsonValue] | list[JsonValue] | None,
        provider: str | None,
        provider_message_id: str | None,
        dry_run: bool,
        status: str,
        error_text: str | None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO brief_deliveries (
                    brief_run_id,
                    channel,
                    recipient_json,
                    provider,
                    provider_message_id,
                    dry_run,
                    status,
                    error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief_run_id,
                    channel,
                    self._json_dumps(recipient_json),
                    provider,
                    provider_message_id,
                    int(bool(dry_run)),
                    status,
                    error_text,
                ),
            )
            conn.commit()
            if cursor.lastrowid is None:
                raise ConfigError("Could not determine brief delivery id")
            return int(cursor.lastrowid)

    def get_brief_run_by_snapshot_id(self, snapshot_id: int) -> dict[str, JsonValue] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM brief_runs WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        return self.get_brief_run(int(row["id"]))

    def get_brief_run(self, run_id: int) -> dict[str, JsonValue] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute("SELECT * FROM brief_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            deliveries = [
                dict(delivery)
                for delivery in conn.execute(
                    "SELECT * FROM brief_deliveries WHERE brief_run_id = ? ORDER BY attempted_at DESC, id DESC",
                    (run_id,),
                ).fetchall()
            ]
        data = dict(row)
        for key in ("context_json", "scorecard_json", "analysis_json", "briefing_json"):
            data[key] = self._json_loads(data.get(key))
        for delivery in deliveries:
            delivery["recipient_json"] = self._json_loads(delivery.get("recipient_json"))
            delivery["dry_run"] = bool(delivery.get("dry_run", 0))
        data["deliveries"] = deliveries
        return data

    def find_latest_brief_for_date(self, brief_for_date: str) -> dict[str, JsonValue] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute(
                "SELECT id FROM brief_runs WHERE brief_for_date = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (brief_for_date,),
            ).fetchone()
        if row is None:
            return None
        return self.get_brief_run(int(row[0]))

    def list_brief_runs(self, *, limit: int = 10) -> list[dict[str, JsonValue]]:
        rows = self._fetch_all(
            """
            SELECT
                id,
                snapshot_id,
                snapshot_observed_at,
                brief_for_date,
                status,
                email_subject,
                fallback_mode,
                advisor_run_id,
                sent_at,
                created_at,
                updated_at,
                last_error
            FROM brief_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            [limit],
        )
        return rows

    def _json_dumps(self, value: JsonValue) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def _json_loads(self, value: JsonValue) -> JsonValue:
        if value in (None, ""):
            return None
        if isinstance(value, dict | list):
            return value
        return json.loads(value)

