from __future__ import annotations

import asyncio
import csv
import io
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from fraud_lab import config
from fraud_lab.dataset_stream import DatasetStream
from fraud_lab.db import Repository, utc_now
from fraud_lab.mcp_connector import LocalMCPConnector, PolicyEngine, handle_json_rpc
from fraud_lab.modeling import FraudModelManager, attacker_intel_from_updates
from fraud_lab.schemas import (
    AdminLoginRequest,
    BotStartRequest,
    BotStopRequest,
    MCPToolCall,
    RetrainRequest,
    SimulationRequest,
    TransactionCreate,
    TransactionLabel,
    TruthRevealRequest,
)
from fraud_lab.simulator import generate_batch, generate_seed_dataset


repository = Repository(config.DB_PATH)
model_manager = FraudModelManager(config.SCHEMA_PATH, config.MODEL_DIR)
connector = LocalMCPConnector(repository)
policy_engine = PolicyEngine(connector)
dataset_stream = DatasetStream(config.STREAM_DATASET_MANIFEST, model_manager.schema.target)
admin_sessions: dict[str, datetime] = {}
ADMIN_SESSION_TTL = timedelta(hours=12)


class RealtimeTransactionBot:
    def __init__(self, stream: DatasetStream) -> None:
        self.stream = stream
        self.running = False
        self.interval_seconds = 1.0
        self.batch_size = 1
        self.fraud_rate = 0.12
        self.stream_mode = "dataset"
        self.replay_speed = 3600.0
        self.label_policy = "unlabeled_stream"
        self.generated = 0
        self.retrain_every_generated = 300
        self.started_at: str | None = None
        self.last_tick_at: str | None = None
        self.last_transaction_id: str | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self, settings: BotStartRequest) -> dict[str, Any]:
        self.interval_seconds = float(settings.interval_seconds)
        self.batch_size = int(settings.batch_size)
        self.fraud_rate = float(settings.fraud_rate)
        self.stream_mode = settings.stream_mode
        self.replay_speed = float(settings.replay_speed)
        self.last_error = None
        if self.stream_mode == "dataset":
            if not self.stream.available:
                self.stream.reload()
            if self.stream.exhausted and config.BOT_LOOP_DATASET:
                self.stream.reset()
            if not self.stream.available:
                raise HTTPException(status_code=404, detail="stream dataset manifest is not available yet")
        if not self.running:
            self.running = True
            self.started_at = utc_now()
            self._task = asyncio.create_task(self._run(), name="realtime-transaction-bot")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self.running = False
        task = self._task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "interval_seconds": self.interval_seconds,
            "batch_size": self.batch_size,
            "fraud_rate": self.fraud_rate,
            "stream_mode": self.stream_mode,
            "replay_speed": self.replay_speed,
            "label_policy": self.label_policy,
            "generated": self.generated,
            "started_at": self.started_at,
            "last_tick_at": self.last_tick_at,
            "last_transaction_id": self.last_transaction_id,
            "last_error": self.last_error,
            "admin_required": bool(config.ADMIN_PASSWORD),
            "dataset": self.stream.status(),
        }

    async def _run(self) -> None:
        try:
            while self.running:
                self.last_tick_at = utc_now()
                try:
                    if self.stream_mode == "dataset":
                        emitted = self._emit_dataset_batch()
                        if emitted == 0 and self.stream.exhausted:
                            if config.BOT_LOOP_DATASET:
                                self.stream.reset()
                                self.last_error = None
                                await asyncio.sleep(self.interval_seconds)
                                continue
                            self.last_error = "dataset exhausted"
                            break
                        self._maybe_retrain_from_stream(emitted, "world_bot_dataset_replay")
                    else:
                        emitted = self._emit_synthetic_batch()
                        self._maybe_retrain_from_stream(emitted, "world_bot_unlabeled_stream")
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - exposed in bot status for lab debugging.
                    self.last_error = str(exc)
                await asyncio.sleep(self.interval_seconds)
        finally:
            self.running = False

    def _emit_synthetic_batch(self) -> int:
        emitted = 0
        for item in generate_batch(self.batch_size, self.fraud_rate):
            transaction, _action = _process_transaction(
                payload=item["payload"],
                source="world_bot",
                label=None,
                label_source=None,
                auto_log_training=True,
            )
            emitted += 1
            self.generated += 1
            self.last_transaction_id = transaction["id"]
        return emitted

    def _maybe_retrain_from_stream(self, emitted: int, reason: str) -> None:
        if emitted <= 0:
            return
        if self.generated % self.retrain_every_generated < emitted:
            _maybe_retrain(reason=reason)

    def _emit_dataset_batch(self) -> int:
        emitted = 0
        for item in self.stream.next_batch(self.batch_size):
            transaction, _action = _process_transaction(
                payload=item["payload"],
                source="world_bot",
                label=None,
                label_source=None,
                auto_log_training=True,
            )
            emitted += 1
            self.generated += 1
            self.last_transaction_id = transaction["id"]
            dataset_time = item["payload"].get("trans_date_trans_time")
            if dataset_time:
                repository.log_dataset_truth_label(
                    {
                        "transaction_id": transaction["id"],
                        "created_at": transaction["created_at"],
                        "schema_id": transaction["schema_id"],
                        "dataset_time": dataset_time,
                        "true_label": item.get("offline_label"),
                        "predicted_label": transaction["decision"].get("predicted_label"),
                        "risk_label": transaction["risk_label"],
                        "anomaly_score": transaction["anomaly_score"],
                        "source": transaction["source"],
                    }
                )
        return emitted


transaction_bot = RealtimeTransactionBot(dataset_stream)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    if config.BOT_AUTO_START:
        try:
            await transaction_bot.start(
                BotStartRequest(
                    interval_seconds=config.BOT_INTERVAL_SECONDS,
                    batch_size=config.BOT_BATCH_SIZE,
                    stream_mode="dataset",
                    replay_speed=config.BOT_REPLAY_SPEED,
                )
            )
        except Exception as exc:  # noqa: BLE001 - visible through /api/health for deployment diagnostics.
            transaction_bot.last_error = f"auto-start failed: {exc}"
    try:
        yield
    finally:
        await transaction_bot.stop()


app = FastAPI(
    title="Realtime Transition Agent Fraud Lab",
    description="Educational AI attack/defense sandbox for fraud detection model drift, logs, and agent actions.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def startup() -> None:
    config.ensure_runtime_dirs()
    repository.init_db()
    _bootstrap_model()


if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "schema_id": model_manager.schema.schema_id,
        "model_version": model_manager.current_version,
        "model_kind": model_manager.model_kind,
        "stats": repository.stats(schema_id=model_manager.schema.schema_id),
        "truth_labels": repository.truth_label_summary(schema_id=model_manager.schema.schema_id),
        "bot": transaction_bot.status(),
    }


@app.get("/api/schema")
def schema() -> dict[str, Any]:
    return model_manager.schema_for_ui()


def _is_valid_admin_token(token: str | None) -> bool:
    if not token:
        return False
    expires_at = admin_sessions.get(token)
    if not expires_at:
        return False
    if expires_at <= datetime.now(timezone.utc):
        admin_sessions.pop(token, None)
        return False
    return True


def _require_admin_password(candidate: str | None, token: str | None = None) -> None:
    if _is_valid_admin_token(token):
        return
    if not config.ADMIN_PASSWORD:
        return
    if not candidate or not secrets.compare_digest(candidate, config.ADMIN_PASSWORD):
        raise HTTPException(status_code=403, detail="invalid admin password")


@app.post("/api/admin/login")
def admin_login(request: AdminLoginRequest) -> dict[str, Any]:
    _require_admin_password(request.admin_password)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + ADMIN_SESSION_TTL
    admin_sessions[token] = expires_at
    return {"token": token, "expires_at": expires_at.isoformat()}


@app.get("/api/transactions")
def transactions(limit: int = 100) -> dict[str, Any]:
    return {
        "items": repository.list_transactions(
            limit=max(1, min(limit, 500)), schema_id=model_manager.schema.schema_id
        )
    }


@app.get("/api/realtime-transactions.csv")
def realtime_transactions_csv(limit: int = 3000) -> Response:
    limit = max(1, min(limit, 3000))
    rows = repository.list_transactions(limit=limit, schema_id=model_manager.schema.schema_id)
    payload_columns = [
        field["name"]
        for field in model_manager.schema.fields
        if field.get("role") != "target"
    ]
    columns = [
        "created_at",
        "transaction_id",
        "account_id",
        "source",
        "model_version",
        "anomaly_score",
        "risk_label",
        "predicted_label",
        "revealed_label",
        "label_source",
        *payload_columns,
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        payload = row.get("payload", {})
        writer.writerow(
            {
                "created_at": row.get("created_at"),
                "transaction_id": row.get("id"),
                "account_id": row.get("account_id"),
                "source": row.get("source"),
                "model_version": row.get("model_version"),
                "anomaly_score": row.get("anomaly_score"),
                "risk_label": row.get("risk_label"),
                "predicted_label": row.get("decision", {}).get("predicted_label"),
                "revealed_label": row.get("label"),
                "label_source": row.get("label_source"),
                **{column: payload.get(column) for column in payload_columns},
            }
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="realtime-transactions.csv"'},
    )


@app.post("/api/transactions")
def create_transaction(request: TransactionCreate) -> dict[str, Any]:
    transaction, action = _process_transaction(
        payload=request.payload,
        source=request.source,
        label=None,
        label_source=None,
    )
    _maybe_retrain()
    return {"transaction": transaction, "action": action}


@app.post("/api/transactions/{transaction_id}/label")
def label_transaction(
    transaction_id: str,
    request: TransactionLabel,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(None, x_admin_token)
    transaction = repository.update_transaction_label(
        transaction_id, int(bool(request.label)), request.label_source
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    repository.log_training_event(
        {
            "model_version": model_manager.current_version,
            "schema_id": model_manager.schema.schema_id,
            "transaction_id": transaction_id,
            "event_type": "feedback_label",
            "payload": transaction["payload"],
            "label": int(bool(request.label)),
            "label_source": request.label_source,
            "details": {"source": "api"},
        }
    )
    _maybe_retrain()
    return {"transaction": transaction}


@app.get("/api/bot/status")
def bot_status(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    _require_admin_password(None, x_admin_token)
    return transaction_bot.status()


@app.post("/api/bot/start")
async def bot_start(
    request: BotStartRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(request.admin_password, x_admin_token)
    return await transaction_bot.start(request)


@app.post("/api/bot/stop")
async def bot_stop(
    request: BotStopRequest = Body(default_factory=BotStopRequest),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(request.admin_password, x_admin_token)
    return await transaction_bot.stop()


@app.get("/api/metrics/stream")
def stream_metrics(seconds: int = 180) -> dict[str, Any]:
    seconds = max(30, min(seconds, 600))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=seconds)
    rows = repository.recent_stream_rows(
        cutoff.isoformat(),
        schema_id=model_manager.schema.schema_id,
        source="world_bot",
    )
    buckets = {
        int((cutoff + timedelta(seconds=offset)).timestamp()): {
            "time": (cutoff + timedelta(seconds=offset)).isoformat(),
            "total": 0,
            "normal": 0,
            "review": 0,
            "blocked": 0,
        }
        for offset in range(seconds + 1)
    }
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except ValueError:
            continue
        epoch = int(created_at.timestamp())
        if epoch not in buckets:
            continue
        risk = row["risk_label"] if row["risk_label"] in {"normal", "review", "blocked"} else "normal"
        buckets[epoch]["total"] += 1
        buckets[epoch][risk] += 1
    values = [buckets[key] for key in sorted(buckets)]
    recent_values = values[-5:] if values else []
    return {
        "window_seconds": seconds,
        "total": sum(item["total"] for item in values),
        "latest_per_second": max((item["total"] for item in recent_values), default=0),
        "buckets": values,
    }


@app.get("/api/metrics/label-comparison")
def label_comparison_metrics(windows: int = 12) -> dict[str, Any]:
    windows = max(1, min(windows, 48))
    summary = repository.truth_label_summary(schema_id=model_manager.schema.schema_id)
    latest = repository.max_revealed_dataset_truth_time(schema_id=model_manager.schema.schema_id)
    if not latest:
        return {
            "reveal_interval_hours": 3,
            "latest_dataset_time": summary["latest_dataset_time"],
            "revealed_before": None,
            "summary": summary,
            "windows": [],
        }
    latest_dt = _parse_datetime(latest)
    rows = repository.label_comparison_windows(
        latest_dt.strftime("%Y-%m-%d %H:%M:%S"),
        limit=windows,
        bucket_seconds=3 * 60 * 60,
        schema_id=model_manager.schema.schema_id,
    )
    for row in rows:
        total = max(1, int(row["total"]))
        row["accuracy"] = round((row["tp"] + row["tn"]) / total, 4)
        row["precision"] = round(row["tp"] / max(1, row["tp"] + row["fp"]), 4)
        row["recall"] = round(row["tp"] / max(1, row["tp"] + row["fn"]), 4)
    return {
        "reveal_interval_hours": 3,
        "latest_dataset_time": latest_dt.isoformat(),
        "revealed_before": latest_dt.isoformat(),
        "summary": summary,
        "windows": rows,
    }


@app.post("/api/simulate")
def simulate(request: SimulationRequest) -> dict[str, Any]:
    created = []
    actions = []
    for item in generate_batch(request.count, request.fraud_rate):
        transaction, action = _process_transaction(
            payload=item["payload"],
            source="simulator",
            label=None,
            label_source=None,
            auto_log_training=True,
        )
        created.append(transaction)
        if action:
            actions.append(action)
    _maybe_retrain(force=True, reason=f"simulator_batch_{request.count}")
    return {"created": created, "actions": actions}


@app.post("/api/admin/retrain")
def retrain(
    request: RetrainRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(request.admin_password, x_admin_token)
    return {"update": _retrain(request.reason)}


@app.post("/api/admin/labels/reveal")
def reveal_truth_labels(
    request: TruthRevealRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(request.admin_password, x_admin_token)
    result = repository.reveal_dataset_truth_labels(
        limit=request.limit,
        schema_id=model_manager.schema.schema_id,
    )
    update = None
    if result["revealed"]:
        repository.log_training_event(
            {
                "model_version": model_manager.current_version,
                "schema_id": model_manager.schema.schema_id,
                "transaction_id": None,
                "event_type": "truth_labels_revealed",
                "payload": {},
                "label": None,
                "label_source": "admin_truth_reveal",
                "details": result,
            }
        )
        if request.retrain_after:
            update = _retrain("admin_truth_reveal")
    return {
        "result": result,
        "summary": repository.truth_label_summary(schema_id=model_manager.schema.schema_id),
        "stats": repository.stats(schema_id=model_manager.schema.schema_id),
        "update": update,
    }


@app.post("/api/admin/model/upload")
async def upload_model_artifact(
    file: UploadFile = File(...),
    notes: str = Form(default="manual_model_upload"),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_password(None, x_admin_token)
    filename = file.filename or "uploaded_model.joblib"
    safe_name = "".join(char if char.isalnum() or char in {".", "_", "-"} else "_" for char in filename)
    upload_dir = config.MODEL_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}_{safe_name}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded model file is empty")
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="uploaded model file is too large")
    upload_path.write_bytes(content)
    try:
        update = model_manager.import_artifact(
            upload_path,
            version=model_manager.current_version + 1,
            reason=notes or "manual_model_upload",
        )
    except Exception as exc:  # noqa: BLE001 - returned as API validation error for admin upload.
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"invalid model artifact: {exc}") from exc
    repository.log_model_update(update)
    _log_red_blue_guidance(update)
    repository.log_training_event(
        {
            "model_version": update["version"],
            "schema_id": update["schema_id"],
            "transaction_id": None,
            "event_type": "model_artifact_uploaded",
            "payload": {},
            "label": None,
            "label_source": "admin_model_upload",
            "details": {"artifact_path": update["artifact_path"], "notes": notes},
        }
    )
    return {"update": update}


@app.get("/api/model/updates")
def model_updates(limit: int = 25) -> dict[str, Any]:
    return {
        "items": repository.list_model_updates(
            limit=max(1, min(limit, 100)), schema_id=model_manager.schema.schema_id
        )
    }


@app.get("/api/model/attacker-intel")
def attacker_intel() -> dict[str, Any]:
    updates = repository.list_model_updates(limit=10, schema_id=model_manager.schema.schema_id)
    return attacker_intel_from_updates(updates)


@app.get("/api/logs/training")
def training_logs(limit: int = 100) -> dict[str, Any]:
    return {
        "items": repository.list_training_events(
            limit=max(1, min(limit, 500)), schema_id=model_manager.schema.schema_id
        )
    }


@app.get("/api/logs/red-blue")
def red_blue_logs(limit: int = 100) -> dict[str, Any]:
    return {
        "items": repository.list_red_blue_events(
            limit=max(1, min(limit, 500)), schema_id=model_manager.schema.schema_id
        )
    }


@app.get("/api/accounts")
def accounts(limit: int = 100) -> dict[str, Any]:
    return {"items": repository.list_accounts(limit=max(1, min(limit, 500)))}


@app.get("/api/actions")
def actions(limit: int = 100) -> dict[str, Any]:
    return {"items": repository.list_security_actions(limit=max(1, min(limit, 500)))}


@app.get("/api/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    return {"tools": connector.list_tools()}


@app.post("/api/mcp/call")
def mcp_call(request: MCPToolCall) -> dict[str, Any]:
    return connector.call_tool(request.name, request.arguments)


@app.post("/mcp")
def mcp_json_rpc(request: dict[str, Any]) -> dict[str, Any]:
    return handle_json_rpc(connector, request)


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bootstrap_model() -> None:
    schema_id = model_manager.schema.schema_id
    latest_any = repository.latest_model_update()
    if latest_any:
        model_manager.metadata["version"] = latest_any["version"]

    if repository.count_transactions(schema_id=schema_id) == 0:
        _seed_transactions()

    latest = repository.latest_model_update(schema_id=schema_id)
    if latest and Path(latest["artifact_path"]).exists():
        model_manager.load_artifact(latest["artifact_path"])
        if model_manager.schema.schema_id == schema_id:
            return
        model_manager.schema = FraudModelManager(config.SCHEMA_PATH, config.MODEL_DIR).schema
        model_manager.pipeline = None
        model_manager.metadata["version"] = latest_any["version"] if latest_any else 0

    _retrain("startup_bootstrap")


def _seed_transactions() -> None:
    for item in generate_seed_dataset():
        _process_transaction(
            payload=item["payload"],
            source="seed",
            label=item["label"],
            label_source=item["label_source"],
            apply_policy=False,
            auto_log_training=False,
        )


def _process_transaction(
    payload: dict[str, Any],
    source: str,
    label: int | bool | None,
    label_source: str | None,
    apply_policy: bool = True,
    auto_log_training: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    extracted_label = int(bool(label)) if label is not None else None
    normalized, score = model_manager.score(payload)
    normalized.pop(model_manager.schema.target, None)
    account_id = model_manager.schema.account_id(normalized)
    transaction = {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "schema_id": model_manager.schema.schema_id,
        "account_id": account_id,
        "source": source,
        "payload": normalized,
        "label": extracted_label,
        "label_source": label_source if extracted_label is not None else None,
        "model_version": score.model_version,
        "anomaly_score": score.score,
        "risk_label": score.risk_label,
        "decision": score.as_decision(),
        "training_status": "queued",
    }
    repository.insert_transaction(transaction)

    if auto_log_training:
        repository.log_training_event(
            {
                "model_version": model_manager.current_version,
                "schema_id": model_manager.schema.schema_id,
                "transaction_id": transaction["id"],
                "event_type": "stream_observed",
                "payload": normalized,
                "label": extracted_label,
                "label_source": transaction["label_source"],
                "details": {
                    "source": source,
                    "score": score.score,
                    "risk_label": score.risk_label,
                    "model_kind": score.model_kind,
                },
            }
        )

    action = policy_engine.apply(transaction) if apply_policy else None
    return transaction, action


def _maybe_retrain(force: bool = False, reason: str = "automatic_stream_batch") -> dict[str, Any] | None:
    latest = repository.latest_model_update(schema_id=model_manager.schema.schema_id)
    retrain_every = int(model_manager.schema.retrain_config.get("retrain_every", 12))
    since = repository.count_transactions_after(
        latest["created_at"] if latest else None, schema_id=model_manager.schema.schema_id
    )
    if force or since >= retrain_every:
        return _retrain(reason)
    return None


def _retrain(reason: str) -> dict[str, Any]:
    rows = repository.training_rows(
        limit=int(model_manager.schema.retrain_config.get("max_recent_samples", 5000)),
        schema_id=model_manager.schema.schema_id,
    )
    update = model_manager.train(rows, reason=reason)
    repository.log_model_update(update)
    _log_red_blue_guidance(update)
    for transaction_id in update.get("used_transaction_ids", [])[:250]:
        row = repository.get_transaction(transaction_id)
        if row:
            repository.log_training_event(
                {
                    "model_version": update["version"],
                    "schema_id": update["schema_id"],
                    "transaction_id": transaction_id,
                    "event_type": "used_for_retrain",
                    "payload": row["payload"],
                    "label": row["label"],
                    "label_source": row["label_source"],
                    "details": {
                        "reason": reason,
                        "artifact_path": update["artifact_path"],
                    },
                }
            )
    return update


def _log_red_blue_guidance(update: dict[str, Any]) -> None:
    schema_id = update["schema_id"]
    version = update["version"]
    top_features = update.get("robustness", {}).get("top_features", [])
    common_payload = {
        "model_version": version,
        "schema_id": schema_id,
        "thresholds": update.get("robustness", {}).get("thresholds", {}),
        "top_features": top_features,
        "source_dataset": model_manager.schema.raw.get("source", {}),
    }
    events = [
        {
            "team": "attack",
            "event_type": "attack_method",
            "title": "Threshold probing",
            "description": "검토/차단 임계값 근처의 amt, 시간대, 위치거리 조합을 반복 생성해 모델 경계가 어디서 움직이는지 관찰한다.",
            "payload": common_payload | {"risk": "경계값을 과도하게 노출하면 우회 거래 분할 전략 학습에 쓰일 수 있음"},
        },
        {
            "team": "attack",
            "event_type": "attack_method",
            "title": "Low-and-slow amount splitting",
            "description": "큰 금액을 여러 정상 범위 거래로 나누고 category와 시간대를 바꿔 score 변화를 비교한다.",
            "payload": common_payload | {"features_to_watch": ["amt", "category", "trans_date_trans_time__hour"]},
        },
        {
            "team": "attack",
            "event_type": "attack_method",
            "title": "Geo-distance evasion",
            "description": "고객 위치와 상점 위치의 거리를 조금씩 줄이면서 customer_merchant_distance_km 파생 피처 민감도를 실험한다.",
            "payload": common_payload | {"features_to_watch": ["lat", "long", "merch_lat", "merch_long"]},
        },
        {
            "team": "attack",
            "event_type": "attack_method",
            "title": "Label-noise poisoning",
            "description": "수동 라벨 피드백으로 정상/사기 라벨을 일부 뒤집어 재학습 후 precision, recall, f1 변화를 확인한다.",
            "payload": common_payload | {"guardrail": "교육용 샌드박스 안에서만 수행"},
        },
        {
            "team": "defense",
            "event_type": "robustness_control",
            "title": "Schema contract and derived feature audit",
            "description": "스키마 타입 검증, 미등록 카테고리 경고, 시간/나이/거리/잔액 파생 피처를 모델 업데이트 로그에 남긴다.",
            "payload": common_payload,
        },
        {
            "team": "defense",
            "event_type": "robustness_control",
            "title": "Class imbalance aware baseline",
            "description": "라벨이 충분하면 class_weight가 적용된 schema-driven random forest를 쓰고, 부족하면 isolation fallback을 사용한다.",
            "payload": common_payload | {"metric_focus": ["recall", "precision", "f1", "roc_auc"]},
        },
        {
            "team": "defense",
            "event_type": "robustness_control",
            "title": "Poisoning and drift monitoring",
            "description": "라벨 출처, pseudo label 수, top feature 변화, 재학습 데이터 수를 공격/방어 로그와 학습 로그에 동시에 기록한다.",
            "payload": common_payload,
        },
        {
            "team": "defense",
            "event_type": "robustness_control",
            "title": "Agent action separation",
            "description": "모델 score와 계정 정지/검토 액션을 분리하고, MCP 스타일 도구 호출을 별도 보안 액션 로그로 감시한다.",
            "payload": common_payload,
        },
    ]
    for event in events:
        repository.log_red_blue_event(
            {
                "schema_id": schema_id,
                "model_version": version,
                **event,
            }
        )
