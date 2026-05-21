from __future__ import annotations

import json
import sqlite3
import uuid
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

                CREATE TABLE IF NOT EXISTS dataset_truth_labels (
                    transaction_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    schema_id TEXT,
                    dataset_time TEXT NOT NULL,
                    true_label INTEGER NOT NULL,
                    predicted_label INTEGER,
                    risk_label TEXT NOT NULL,
                    anomaly_score REAL,
                    source TEXT NOT NULL,
                    revealed_at TEXT,
                    reveal_batch_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_dataset_truth_dataset_time
                    ON dataset_truth_labels(dataset_time);
                """
            )
            self._ensure_column(conn, "transactions", "schema_id", "TEXT")
            self._ensure_column(conn, "training_events", "schema_id", "TEXT")
            self._ensure_column(conn, "dataset_truth_labels", "revealed_at", "TEXT")
            self._ensure_column(conn, "dataset_truth_labels", "reveal_batch_id", "TEXT")
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

    def list_transactions_with_truth(
        self, limit: int = 100, schema_id: str | None = None, source: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id and source:
                rows = conn.execute(
                    """
                    SELECT
                        t.*,
                        CASE
                            WHEN d.revealed_at IS NOT NULL THEN d.true_label
                            ELSE NULL
                        END AS truth_label,
                        d.revealed_at AS truth_revealed_at,
                        d.reveal_batch_id AS truth_reveal_batch_id,
                        d.dataset_time AS truth_dataset_time
                    FROM transactions t
                    LEFT JOIN dataset_truth_labels d ON d.transaction_id = t.id
                    WHERE t.schema_id = ? AND t.source = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, source, limit),
                ).fetchall()
            elif schema_id:
                rows = conn.execute(
                    """
                    SELECT
                        t.*,
                        CASE
                            WHEN d.revealed_at IS NOT NULL THEN d.true_label
                            ELSE NULL
                        END AS truth_label,
                        d.revealed_at AS truth_revealed_at,
                        d.reveal_batch_id AS truth_reveal_batch_id,
                        d.dataset_time AS truth_dataset_time
                    FROM transactions t
                    LEFT JOIN dataset_truth_labels d ON d.transaction_id = t.id
                    WHERE t.schema_id = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (schema_id, limit),
                ).fetchall()
            elif source:
                rows = conn.execute(
                    """
                    SELECT
                        t.*,
                        CASE
                            WHEN d.revealed_at IS NOT NULL THEN d.true_label
                            ELSE NULL
                        END AS truth_label,
                        d.revealed_at AS truth_revealed_at,
                        d.reveal_batch_id AS truth_reveal_batch_id,
                        d.dataset_time AS truth_dataset_time
                    FROM transactions t
                    LEFT JOIN dataset_truth_labels d ON d.transaction_id = t.id
                    WHERE t.source = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        t.*,
                        CASE
                            WHEN d.revealed_at IS NOT NULL THEN d.true_label
                            ELSE NULL
                        END AS truth_label,
                        d.revealed_at AS truth_revealed_at,
                        d.reveal_batch_id AS truth_reveal_batch_id,
                        d.dataset_time AS truth_dataset_time
                    FROM transactions t
                    LEFT JOIN dataset_truth_labels d ON d.transaction_id = t.id
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            item = self._transaction_from_row(row)
            item["truth_label"] = row["truth_label"]
            item["truth_revealed_at"] = row["truth_revealed_at"]
            item["truth_reveal_batch_id"] = row["truth_reveal_batch_id"]
            item["truth_dataset_time"] = row["truth_dataset_time"]
            result.append(item)
        return result

    def iter_transactions_with_truth(
        self,
        *,
        limit: int | None = None,
        schema_id: str | None = None,
        source: str | None = None,
        revealed_only: bool = False,
        oldest_first: bool = False,
    ) -> Iterable[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if schema_id:
            clauses.append("t.schema_id = ?")
            params.append(schema_id)
        if source:
            clauses.append("t.source = ?")
            params.append(source)
        if revealed_only:
            clauses.append("d.revealed_at IS NOT NULL")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = (
            "COALESCE(d.dataset_time, t.created_at) ASC, t.created_at ASC"
            if oldest_first
            else "t.created_at DESC"
        )
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(max(1, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.*,
                    CASE
                        WHEN d.revealed_at IS NOT NULL THEN d.true_label
                        ELSE NULL
                    END AS truth_label,
                    d.revealed_at AS truth_revealed_at,
                    d.reveal_batch_id AS truth_reveal_batch_id,
                    d.dataset_time AS truth_dataset_time
                FROM transactions t
                LEFT JOIN dataset_truth_labels d ON d.transaction_id = t.id
                {where_clause}
                ORDER BY {order_by}
                {limit_clause}
                """,
                params,
            )
            for row in rows:
                item = self._transaction_from_row(row)
                item["truth_label"] = row["truth_label"]
                item["truth_revealed_at"] = row["truth_revealed_at"]
                item["truth_reveal_batch_id"] = row["truth_reveal_batch_id"]
                item["truth_dataset_time"] = row["truth_dataset_time"]
                yield item

    def latest_truth_revealed_at(
        self, schema_id: str | None = None, source: str | None = None
    ) -> str | None:
        clauses = ["revealed_at IS NOT NULL"]
        params: list[Any] = []
        if schema_id:
            clauses.append("schema_id = ?")
            params.append(schema_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT MAX(revealed_at)
                FROM dataset_truth_labels
                WHERE {' AND '.join(clauses)}
                """,
                params,
            ).fetchone()
        return row[0] if row and row[0] else None

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

    def log_dataset_truth_label(self, record: dict[str, Any]) -> None:
        if record.get("true_label") is None:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dataset_truth_labels (
                    transaction_id, created_at, schema_id, dataset_time, true_label,
                    predicted_label, risk_label, anomaly_score, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["transaction_id"],
                    record["created_at"],
                    record.get("schema_id"),
                    record["dataset_time"],
                    int(record["true_label"]),
                    record.get("predicted_label"),
                    record["risk_label"],
                    record.get("anomaly_score"),
                    record.get("source", "world_bot"),
                ),
            )

    def max_dataset_truth_time(self, schema_id: str | None = None) -> str | None:
        with self.connect() as conn:
            if schema_id:
                row = conn.execute(
                    """
                    SELECT MAX(dataset_time) FROM dataset_truth_labels
                    WHERE schema_id = ?
                    """,
                    (schema_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT MAX(dataset_time) FROM dataset_truth_labels").fetchone()
        return row[0] if row and row[0] else None

    def max_revealed_dataset_truth_time(self, schema_id: str | None = None) -> str | None:
        with self.connect() as conn:
            if schema_id:
                row = conn.execute(
                    """
                    SELECT MAX(dataset_time) FROM dataset_truth_labels
                    WHERE schema_id = ? AND revealed_at IS NOT NULL
                    """,
                    (schema_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT MAX(dataset_time) FROM dataset_truth_labels
                    WHERE revealed_at IS NOT NULL
                    """
                ).fetchone()
        return row[0] if row and row[0] else None

    def reveal_dataset_truth_labels(
        self,
        limit: int | None = None,
        schema_id: str | None = None,
    ) -> dict[str, Any]:
        revealed_at = utc_now()
        reveal_batch_id = str(uuid.uuid4())
        with self.connect() as conn:
            params: list[Any] = []
            schema_clause = ""
            if schema_id:
                schema_clause = "AND schema_id = ?"
                params.append(schema_id)
            limit_clause = ""
            if limit is not None:
                limit_clause = "LIMIT ?"
                params.append(max(1, min(int(limit), 1_000_000)))
            rows = conn.execute(
                f"""
                SELECT transaction_id, true_label, dataset_time, predicted_label
                FROM dataset_truth_labels
                WHERE revealed_at IS NULL {schema_clause}
                ORDER BY dataset_time ASC, created_at ASC
                {limit_clause}
                """,
                params,
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    UPDATE transactions
                    SET label = ?, label_source = ?, training_status = 'queued'
                    WHERE id = ?
                    """,
                    (int(row["true_label"]), "admin_truth_reveal", row["transaction_id"]),
                )
                conn.execute(
                    """
                    UPDATE dataset_truth_labels
                    SET revealed_at = ?, reveal_batch_id = ?
                    WHERE transaction_id = ?
                    """,
                    (revealed_at, reveal_batch_id, row["transaction_id"]),
                )
        return {
            "revealed": len(rows),
            "revealed_at": revealed_at,
            "reveal_batch_id": reveal_batch_id,
            "latest_dataset_time": rows[-1]["dataset_time"] if rows else None,
        }

    def truth_label_summary(self, schema_id: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            schema_clause = "WHERE schema_id = ?" if schema_id else ""
            params = (schema_id,) if schema_id else ()
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_truth,
                    SUM(CASE WHEN revealed_at IS NOT NULL THEN 1 ELSE 0 END) AS revealed,
                    SUM(CASE WHEN revealed_at IS NULL THEN 1 ELSE 0 END) AS unrevealed,
                    MAX(dataset_time) AS latest_dataset_time,
                    MAX(CASE WHEN revealed_at IS NOT NULL THEN dataset_time ELSE NULL END) AS latest_revealed_dataset_time
                FROM dataset_truth_labels
                {schema_clause}
                """,
                params,
            ).fetchone()
        return {
            "total_truth": int(row["total_truth"] or 0),
            "revealed": int(row["revealed"] or 0),
            "unrevealed": int(row["unrevealed"] or 0),
            "latest_dataset_time": row["latest_dataset_time"],
            "latest_revealed_dataset_time": row["latest_revealed_dataset_time"],
        }

    def label_comparison_windows(
        self,
        reveal_before: str,
        limit: int = 12,
        bucket_seconds: int = 10_800,
        schema_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 48))
        bucket_seconds = max(60, bucket_seconds)
        with self.connect() as conn:
            params: list[Any] = [bucket_seconds, bucket_seconds, reveal_before]
            schema_clause = ""
            if schema_id:
                schema_clause = "AND schema_id = ?"
                params.append(schema_id)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT
                    ((CAST(strftime('%s', dataset_time) AS INTEGER) / ?) * ?) AS bucket_epoch,
                    COUNT(*) AS total,
                    SUM(CASE WHEN true_label = 1 THEN 1 ELSE 0 END) AS actual_fraud,
                    SUM(CASE WHEN true_label = 0 THEN 1 ELSE 0 END) AS actual_normal,
                    SUM(CASE WHEN COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS predicted_fraud,
                    SUM(CASE WHEN true_label = 1 AND COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS tp,
                    SUM(CASE WHEN true_label = 0 AND COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS fp,
                    SUM(CASE WHEN true_label = 1 AND COALESCE(predicted_label, 0) = 0 THEN 1 ELSE 0 END) AS fn,
                    SUM(CASE WHEN true_label = 0 AND COALESCE(predicted_label, 0) = 0 THEN 1 ELSE 0 END) AS tn
                FROM dataset_truth_labels
                WHERE dataset_time <= ? AND revealed_at IS NOT NULL {schema_clause}
                GROUP BY bucket_epoch
                ORDER BY bucket_epoch DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        result = []
        for row in reversed(rows):
            epoch = int(row["bucket_epoch"])
            result.append(
                {
                    "bucket_start": datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
                    "bucket_end": datetime.fromtimestamp(epoch + bucket_seconds, timezone.utc).isoformat(),
                    "total": int(row["total"] or 0),
                    "actual_fraud": int(row["actual_fraud"] or 0),
                    "actual_normal": int(row["actual_normal"] or 0),
                    "predicted_fraud": int(row["predicted_fraud"] or 0),
                    "tp": int(row["tp"] or 0),
                    "fp": int(row["fp"] or 0),
                    "fn": int(row["fn"] or 0),
                    "tn": int(row["tn"] or 0),
                }
            )
        return result

    def recent_stream_rows(
        self,
        cutoff: str,
        schema_id: str | None = None,
        source: str = "world_bot",
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if schema_id:
                rows = conn.execute(
                    """
                    SELECT created_at, risk_label, anomaly_score
                    FROM transactions
                    WHERE created_at >= ? AND schema_id = ? AND source = ?
                    ORDER BY created_at ASC
                    """,
                    (cutoff, schema_id, source),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT created_at, risk_label, anomaly_score
                    FROM transactions
                    WHERE created_at >= ? AND source = ?
                    ORDER BY created_at ASC
                    """,
                    (cutoff, source),
                ).fetchall()
        return [dict(row) for row in rows]

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
            detected = int(review or 0) + int(blocked or 0)
            truth_params: list[Any] = []
            truth_schema_clause = ""
            if schema_id:
                truth_schema_clause = "AND schema_id = ?"
                truth_params.append(schema_id)
            truth = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS revealed,
                    SUM(CASE WHEN true_label = 1 THEN 1 ELSE 0 END) AS actual_fraud,
                    SUM(CASE WHEN COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS predicted_fraud,
                    SUM(CASE WHEN true_label = 1 AND COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS tp,
                    SUM(CASE WHEN true_label = 0 AND COALESCE(predicted_label, 0) = 1 THEN 1 ELSE 0 END) AS fp,
                    SUM(CASE WHEN true_label = 1 AND COALESCE(predicted_label, 0) = 0 THEN 1 ELSE 0 END) AS fn,
                    SUM(CASE WHEN true_label = 0 AND COALESCE(predicted_label, 0) = 0 THEN 1 ELSE 0 END) AS tn
                FROM dataset_truth_labels
                WHERE revealed_at IS NOT NULL {truth_schema_clause}
                """,
                truth_params,
            ).fetchone()
            accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            suspended = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'suspended'"
            ).fetchone()[0]
        revealed = int(truth["revealed"] or 0)
        actual_fraud = int(truth["actual_fraud"] or 0)
        predicted_fraud = int(truth["predicted_fraud"] or 0)
        tp = int(truth["tp"] or 0)
        fp = int(truth["fp"] or 0)
        fn = int(truth["fn"] or 0)
        tn = int(truth["tn"] or 0)
        return {
            "transactions": total,
            "review": review,
            "blocked": blocked,
            "detected": detected,
            "detection_rate": round(detected / max(1, int(total or 0)), 4),
            "labeled": labeled,
            "accounts": accounts,
            "suspended_accounts": suspended,
            "revealed_truth": revealed,
            "actual_fraud": actual_fraud,
            "predicted_fraud": predicted_fraud,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "true_negatives": tn,
            "model_accuracy": round((tp + tn) / max(1, revealed), 4),
            "fraud_recall": round(tp / max(1, actual_fraud), 4),
            "attack_success_rate": round(fn / max(1, actual_fraud), 4),
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
