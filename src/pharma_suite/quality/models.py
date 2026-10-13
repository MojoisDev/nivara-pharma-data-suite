"""Typed envelopes and configuration; raw rows deliberately remain permissive."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DIMENSIONS = (
    "completeness",
    "uniqueness",
    "validity",
    "consistency",
    "referential_integrity",
    "timeliness",
)


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1.0"] = "1.0"
    weights: dict[str, float] = Field(default_factory=lambda: dict.fromkeys(DIMENSIONS, 1.0))
    max_price: float = Field(default=100000, gt=0, allow_inf_nan=False)
    max_quantity: int = Field(default=1000000, gt=0)
    max_import_age_hours: float = Field(default=24, ge=0, allow_inf_nan=False)
    max_feed_lag_days: int = Field(default=2, ge=0)
    max_price_to_list_ratio: float = Field(default=1.2, gt=0, allow_inf_nan=False)

    @field_validator("weights")
    @classmethod
    def valid_weights(cls, value):
        import math

        if (
            set(value) != set(DIMENSIONS)
            or any(not math.isfinite(v) or v < 0 for v in value.values())
            or not sum(value.values())
        ):
            raise ValueError(
                "Supply all six dimension weights, finite and nonnegative, with positive sum"
            )
        return value


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    synthetic: Literal[True] = True
    reference_at: datetime
    source_received_at: str | None
    feed_date: str | None
    snapshot_date: str | None
    data: dict[str, list[dict[str, Any]]]

    @model_validator(mode="after")
    def safe_envelope(self):
        from pharma_suite.generate import TABLE_ORDER

        if set(self.data) - set(TABLE_ORDER):
            raise ValueError("Unknown source entity")
        if self.reference_at.tzinfo is None:
            raise ValueError("reference_at requires an explicit timezone")
        self.reference_at = self.reference_at.astimezone(timezone.utc)
        return self


class Finding(BaseModel):
    rule_id: str
    rule_version: str = "1.0"
    dimension: str
    severity: Literal["critical", "error", "warning"]
    entity: str
    record_ref: str
    field: str
    description: str
    remediation: str
    medicine_ref: str | None = None
    batch_ref: str | None = None


class Report(BaseModel):
    dataset: str
    reference_at: datetime
    dimensions: dict[str, dict[str, Any]]
    rules: dict[str, dict[str, int]]
    overall_score: float | None
    total_records: int
    passed_records: int
    failed_records: int
    severity_counts: dict[str, int]
    findings: list[Finding]
    run_id: int | None = None
    dataset_version: int | None = None
    transitions: dict[str, int] = Field(default_factory=dict)
