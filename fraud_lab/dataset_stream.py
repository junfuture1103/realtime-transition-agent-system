from __future__ import annotations

import csv
import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


class DatasetStream:
    def __init__(self, manifest_path: Path, target_field: str) -> None:
        self.manifest_path = Path(manifest_path)
        self.target_field = target_field
        self.manifest: dict[str, Any] = {}
        self.shards: list[Path] = []
        self.file_index = 0
        self.emitted = 0
        self.exhausted = False
        self.last_dataset_time: datetime | None = None
        self.next_dataset_time: datetime | None = None
        self._handle: TextIO | None = None
        self._reader: csv.DictReader[str] | None = None
        self._peeked: dict[str, Any] | None = None
        self.reload()

    @property
    def available(self) -> bool:
        return bool(self.shards) and all(path.exists() for path in self.shards[:1])

    def reload(self) -> None:
        self.close()
        self.manifest = {}
        self.shards = []
        self.file_index = 0
        self.emitted = 0
        self.exhausted = False
        self.last_dataset_time = None
        self.next_dataset_time = None
        self._peeked = None
        if not self.manifest_path.exists():
            return

        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        raw_shards = [Path(item) for item in self.manifest.get("shards", [])]
        base_dir = self.manifest_path.parent
        self.shards = [path if path.exists() else base_dir / path.name for path in raw_shards]

    def close(self) -> None:
        if self._handle:
            self._handle.close()
        self._handle = None
        self._reader = None

    def reset(self) -> None:
        self.reload()

    def next_batch(self, limit: int) -> list[dict[str, Any]]:
        limit = max(1, limit)
        rows: list[dict[str, Any]] = []
        for _ in range(limit):
            row = self._next_row()
            if row is None:
                break
            rows.append(row)
        self._prime_next_dataset_time()
        return rows

    def delay_after_batch(self, replay_speed: float, max_wait_seconds: float) -> float:
        replay_speed = max(1.0, float(replay_speed))
        max_wait_seconds = max(0.25, float(max_wait_seconds))
        if not self.last_dataset_time or not self.next_dataset_time:
            return max_wait_seconds
        gap = (self.next_dataset_time - self.last_dataset_time).total_seconds()
        if gap <= 0:
            return 0.25
        return max(0.25, min(max_wait_seconds, gap / replay_speed))

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.manifest_path),
            "available": self.available,
            "manifest_path": str(self.manifest_path),
            "rows": self.manifest.get("rows"),
            "shard_count": self.manifest.get("shard_count", len(self.shards)),
            "file_index": self.file_index,
            "emitted": self.emitted,
            "exhausted": self.exhausted,
            "dataset_time": self.last_dataset_time.isoformat() if self.last_dataset_time else None,
            "next_dataset_time": self.next_dataset_time.isoformat() if self.next_dataset_time else None,
            "label_policy": self.manifest.get(
                "label_policy",
                "Offline labels are removed before operational replay.",
            ),
        }

    def _next_row(self) -> dict[str, Any] | None:
        if self._peeked is not None:
            row = self._peeked
            self._peeked = None
        else:
            row = self._read_row()
        if row is None:
            return None
        payload = row["payload"]
        self.last_dataset_time = self._parse_payload_time(payload)
        self.emitted += 1
        return row

    def _read_row(self) -> dict[str, Any] | None:
        while True:
            if not self._reader and not self._open_next_shard():
                self.exhausted = True
                return None
            assert self._reader is not None
            try:
                raw = next(self._reader)
            except StopIteration:
                self.close()
                continue
            return self._normalize_row(raw)

    def _peek_next_row(self) -> dict[str, Any] | None:
        if self._peeked is None:
            self._peeked = self._read_row()
        return self._peeked

    def _prime_next_dataset_time(self) -> None:
        row = self._peek_next_row()
        self.next_dataset_time = self._parse_payload_time(row["payload"]) if row else None

    def _open_next_shard(self) -> bool:
        if self.file_index >= len(self.shards):
            return False
        path = self.shards[self.file_index]
        self.file_index += 1
        if path.suffix == ".gz":
            self._handle = gzip.open(path, "rt", newline="", encoding="utf-8")
        else:
            self._handle = path.open("r", newline="", encoding="utf-8")
        self._reader = csv.DictReader(self._handle)
        return True

    def _normalize_row(self, raw: dict[str, str]) -> dict[str, Any]:
        label = raw.get(self.target_field)
        payload = {key: self._coerce(value) for key, value in raw.items() if key != self.target_field}
        return {
            "payload": payload,
            "offline_label": int(label) if label not in (None, "") else None,
        }

    def _coerce(self, value: str) -> Any:
        if value == "":
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _parse_payload_time(self, payload: dict[str, Any]) -> datetime | None:
        value = payload.get("trans_date_trans_time")
        if not value:
            return None
        text = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
