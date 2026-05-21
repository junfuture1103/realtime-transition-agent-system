from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


DATA_DIR = _path_from_env("FRAUD_LAB_DATA_DIR", BASE_DIR / "data")
DB_PATH = _path_from_env("FRAUD_LAB_DB_PATH", DATA_DIR / "fraud_lab.sqlite3")
SCHEMA_PATH = _path_from_env(
    "FRAUD_LAB_SCHEMA_PATH",
    BASE_DIR / "configs" / "schemas" / "kaggle_fraud_transactions.json",
)
MODEL_DIR = _path_from_env("FRAUD_LAB_MODEL_DIR", DATA_DIR / "models")
STATIC_DIR = BASE_DIR / "static"
STREAM_DATASET_MANIFEST = _path_from_env(
    "FRAUD_LAB_STREAM_DATASET_MANIFEST",
    DATA_DIR / "generated" / "realtime_financial_transactions_10000000" / "manifest.json",
)
ADMIN_PASSWORD = os.getenv("FRAUD_LAB_ADMIN_PASSWORD", "")
BOT_AUTO_START = os.getenv("FRAUD_LAB_BOT_AUTO_START", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
BOT_LOOP_DATASET = os.getenv("FRAUD_LAB_BOT_LOOP_DATASET", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
BOT_INTERVAL_SECONDS = float(os.getenv("FRAUD_LAB_BOT_INTERVAL_SECONDS", "1"))
BOT_BATCH_SIZE = int(os.getenv("FRAUD_LAB_BOT_BATCH_SIZE", "1"))
BOT_REPLAY_SPEED = float(os.getenv("FRAUD_LAB_BOT_REPLAY_SPEED", "3600"))


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
