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
    interval_seconds: float = Field(default=2.0, ge=0.25, le=60)
    batch_size: int = Field(default=1, ge=1, le=25)
    fraud_rate: float = Field(default=0.12, ge=0, le=1)


class RetrainRequest(BaseModel):
    reason: str = "manual_retrain"


class MCPToolCall(BaseModel):
    name: Literal["suspend_account", "flag_for_review", "restore_account"]
    arguments: dict[str, Any] = Field(default_factory=dict)
