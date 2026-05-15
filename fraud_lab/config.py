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


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
