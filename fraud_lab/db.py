from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    schema_id TEXT,
                    account_id TEXT NOT NULL,
                    user_id TEXT,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    label INTEGER,
                    label_source TEXT,
                    model_version INTEGER,
                    anomaly_score REAL,
                    risk_label TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    training_status TEXT NOT NULL DEFAULT 'queued'
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_created_at
                    ON transactions(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_transactions_risk_label
                    ON transactions(risk_label);
                CREATE INDEX IF NOT EXISTS idx_transactions_account_id
                    ON transactions(account_id);

                CREATE TABLE IF NOT EXISTS model_updates (
                    version INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    training_rows INTEGER NOT NULL,
                    labeled_rows INTEGER NOT NULL,
                    metrics_json TEXT NOT NULL,
                    robustness_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    notes TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS training_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_id TEXT,
                    model_version INTEGER,
                    transaction_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    label INTEGER,
                    label_source TEXT,
                    details_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_training_events_created_at
                    ON training_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    risk_score REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS security_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    transaction_id TEXT,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    connector TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_security_actions_created_at
                    ON security_actions(created_at DESC);

                CREATE TABLE IF NOT EXISTS red_blue_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    model_version INTEGER,
                    team TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_red_blue_events_created_at
                    ON red_blue_events(created_at DESC);
                """
            )
            self._ensure_column(conn, "transactions", "schema_id", "TEXT")
            self._ensure_column(conn, "training_events", "schema_id", "TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transactions_schema_created_at
                    ON transactions(schema_id, created_at DESC)
                """
            )

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, column_type: str
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def count_transactions(self, schema_id: str | None = None) -> int:
        with self.connect() as conn:
            if schema_id:
                return int(
                    conn.execute(
                        "SELECT COUNT(*) FROM transactions WHERE schema_id = ?", (schema_id,)
                    ).fetchone()[0]
                )
            return int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])

    def count_transactions_after(
        self, created_at: str | None, schema_id: str | None = None
    ) -> int:
        if not created_at:
            return self.count_transactions(schema_id)
        with self.connect() as conn:
            if schema_id:
                return int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM transactions
                        WHERE created_at > ? AND schema_id = ?
                        """,
                        (created_at, schema_id),
                    ).fetchone()[0]
                )
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE created_at > ?", (created_at,)
                ).fetchone()[0]
            )

    def insert_transaction(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO transactions (
                    id, created_at, schema_id, account_id, user_id, source, payload_json, label,
                    label_source, model_version, anomaly_score, risk_label, decision_json,
                    training_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["created_at"],
                    record.get("schema_id"),
                    record["account_id"],
                    record.get("user_id"),
                    record["source"],
                    dumps(record["payload"]),
                    record.get("label"),
                    record.get("label_source"),
                    record.get("model_version"),
                    record.get("anomaly_score"),
                    record["risk_label"],
                    dumps(record["decision"]),
                    record.get("training_status", "queued"),
                ),
            )
        return record

    def list_transactions(
        self, limit: int = 100, schema_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT * FROM transactions
                    WHERE schema_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM transactions
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
        return self._transaction_from_row(row) if row else None

    def update_transaction_label(
        self, transaction_id: str, label: int, label_source: str = "human_feedback"
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE transactions
                SET label = ?, label_source = ?, training_status = 'queued'
                WHERE id = ?
                """,
                (int(label), label_source, transaction_id),
            )
        return self.get_transaction(transaction_id)

    def training_rows(self, limit: int, schema_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT id, payload_json, label, label_source, anomaly_score, decision_json
                    FROM transactions
                    WHERE schema_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, payload_json, label, label_source, anomaly_score, decision_json
                    FROM transactions
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "transaction_id": row["id"],
                    "payload": loads(row["payload_json"], {}),
                    "label": row["label"],
                    "label_source": row["label_source"],
                    "anomaly_score": row["anomaly_score"],
                    "decision": loads(row["decision_json"], {}),
                }
            )
        return result

    def log_model_update(self, update: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_updates (
                    version, created_at, schema_id, training_rows, labeled_rows,
                    metrics_json, robustness_json, artifact_path, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update["version"],
                    update["created_at"],
                    update["schema_id"],
                    update["training_rows"],
                    update["labeled_rows"],
                    dumps(update["metrics"]),
                    dumps(update["robustness"]),
                    update["artifact_path"],
                    update["notes"],
                ),
            )

    def latest_model_update(self, schema_id: str | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            if schema_id:
                row = conn.execute(
                    """
                    SELECT * FROM model_updates
                    WHERE schema_id = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (schema_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM model_updates ORDER BY version DESC LIMIT 1"
                ).fetchone()
        return self._model_update_from_row(row) if row else None

    def list_model_updates(
        self, limit: int = 25, schema_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT * FROM model_updates
                    WHERE schema_id = ?
                    ORDER BY version DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM model_updates ORDER BY version DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._model_update_from_row(row) for row in rows]

    def log_training_event(self, event: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO training_events (
                    created_at, schema_id, model_version, transaction_id, event_type, payload_json,
                    label, label_source, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("created_at", utc_now()),
                    event.get("schema_id"),
                    event.get("model_version"),
                    event.get("transaction_id"),
                    event["event_type"],
                    dumps(event.get("payload", {})),
                    event.get("label"),
                    event.get("label_source"),
                    dumps(event.get("details", {})),
                ),
            )

    def list_training_events(
        self, limit: int = 100, schema_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT * FROM training_events
                    WHERE schema_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM training_events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "schema_id": row["schema_id"],
                "model_version": row["model_version"],
                "transaction_id": row["transaction_id"],
                "event_type": row["event_type"],
                "payload": loads(row["payload_json"], {}),
                "label": row["label"],
                "label_source": row["label_source"],
                "details": loads(row["details_json"], {}),
            }
            for row in rows
        ]

    def upsert_account(
        self, account_id: str, user_id: str | None, status: str, risk_score: float, notes: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO accounts(account_id, user_id, status, risk_score, updated_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, accounts.user_id),
                    status = excluded.status,
                    risk_score = MAX(excluded.risk_score, accounts.risk_score),
                    updated_at = excluded.updated_at,
                    notes = excluded.notes
                """,
                (account_id, user_id, status, float(risk_score), now, notes),
            )
        return self.get_account(account_id) or {
            "account_id": account_id,
            "user_id": user_id,
            "status": status,
            "risk_score": risk_score,
            "updated_at": now,
            "notes": notes,
        }

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def log_security_action(self, action: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO security_actions (
                    created_at, account_id, transaction_id, action_type, reason, status,
                    connector, request_json, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.get("created_at", utc_now()),
                    action["account_id"],
                    action.get("transaction_id"),
                    action["action_type"],
                    action["reason"],
                    action["status"],
                    action["connector"],
                    dumps(action.get("request", {})),
                    dumps(action.get("response", {})),
                ),
            )
            action["id"] = cursor.lastrowid
        return action

    def list_security_actions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM security_actions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "account_id": row["account_id"],
                "transaction_id": row["transaction_id"],
                "action_type": row["action_type"],
                "reason": row["reason"],
                "status": row["status"],
                "connector": row["connector"],
                "request": loads(row["request_json"], {}),
                "response": loads(row["response_json"], {}),
            }
            for row in rows
        ]

    def log_red_blue_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO red_blue_events (
                    created_at, schema_id, model_version, team, event_type,
                    title, description, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("created_at", utc_now()),
                    event["schema_id"],
                    event.get("model_version"),
                    event["team"],
                    event["event_type"],
                    event["title"],
                    event["description"],
                    dumps(event.get("payload", {})),
                ),
            )
            event["id"] = cursor.lastrowid
        return event

    def list_red_blue_events(
        self, limit: int = 100, schema_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT * FROM red_blue_events
                    WHERE schema_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM red_blue_events
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "schema_id": row["schema_id"],
                "model_version": row["model_version"],
                "team": row["team"],
                "event_type": row["event_type"],
                "title": row["title"],
                "description": row["description"],
                "payload": loads(row["payload_json"], {}),
            }
            for row in rows
        ]

    def stats(self, schema_id: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            if schema_id:
                total = conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE schema_id = ?", (schema_id,)
                ).fetchone()[0]
                review = conn.execute(
                    """
                    SELECT COUNT(*) FROM transactions
                    WHERE risk_label = 'review' AND schema_id = ?
                    """,
                    (schema_id,),
                ).fetchone()[0]
                blocked = conn.execute(
                    """
                    SELECT COUNT(*) FROM transactions
                    WHERE risk_label = 'blocked' AND schema_id = ?
                    """,
                    (schema_id,),
                ).fetchone()[0]
                labeled = conn.execute(
                    """
                    SELECT COUNT(*) FROM transactions
                    WHERE label IS NOT NULL AND schema_id = ?
                    """,
                    (schema_id,),
                ).fetchone()[0]
            else:
                total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                review = conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE risk_label = 'review'"
                ).fetchone()[0]
                blocked = conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE risk_label = 'blocked'"
                ).fetchone()[0]
                labeled = conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE label IS NOT NULL"
                ).fetchone()[0]
            accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            suspended = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'suspended'"
            ).fetchone()[0]
        return {
            "transactions": total,
            "review": review,
            "blocked": blocked,
            "labeled": labeled,
            "accounts": accounts,
            "suspended_accounts": suspended,
        }

    def _transaction_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "schema_id": row["schema_id"],
            "account_id": row["account_id"],
            "user_id": row["user_id"],
            "source": row["source"],
            "payload": loads(row["payload_json"], {}),
            "label": row["label"],
            "label_source": row["label_source"],
            "model_version": row["model_version"],
            "anomaly_score": row["anomaly_score"],
            "risk_label": row["risk_label"],
            "decision": loads(row["decision_json"], {}),
            "training_status": row["training_status"],
        }

    def _model_update_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "version": row["version"],
            "created_at": row["created_at"],
            "schema_id": row["schema_id"],
            "training_rows": row["training_rows"],
            "labeled_rows": row["labeled_rows"],
            "metrics": loads(row["metrics_json"], {}),
            "robustness": loads(row["robustness_json"], {}),
            "artifact_path": row["artifact_path"],
            "notes": row["notes"],
        }
