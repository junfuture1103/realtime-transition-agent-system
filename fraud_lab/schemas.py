from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    payload: dict[str, Any]
    source: str = Field(default="manual", max_length=64)


class TransactionLabel(BaseModel):
    label: int | bool
    label_source: str = "human_feedback"


class SimulationRequest(BaseModel):
    count: int = Field(default=20, ge=1, le=250)
    fraud_rate: float = Field(default=0.15, ge=0, le=1)


class BotStartRequest(BaseModel):
    interval_seconds: float = Field(default=1.0, ge=0.05, le=60)
    batch_size: int = Field(default=1, ge=1, le=25)
    fraud_rate: float = Field(default=0.12, ge=0, le=1)
    stream_mode: Literal["dataset", "synthetic"] = "dataset"
    replay_speed: float = Field(
        default=3600.0,
        ge=1,
        le=86400,
        description="Dataset seconds replayed per real second when stream_mode=dataset.",
    )
    admin_password: str | None = Field(default=None, max_length=256)


class BotStopRequest(BaseModel):
    admin_password: str | None = Field(default=None, max_length=256)


class AdminLoginRequest(BaseModel):
    admin_password: str = Field(max_length=256)


class TruthRevealRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1_000_000)
    reveal_all: bool = True
    retrain_after: bool = False
    admin_password: str | None = Field(default=None, max_length=256)


class RetrainRequest(BaseModel):
    reason: str = "manual_retrain"
    admin_password: str | None = Field(default=None, max_length=256)


class MCPToolCall(BaseModel):
    name: Literal["suspend_account", "flag_for_review", "restore_account"]
    arguments: dict[str, Any] = Field(default_factory=dict)
