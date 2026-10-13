"""Non-secret, persisted workflow configuration. SMTP credentials stay in the environment."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutomationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Kolkata"
    daily_cron: str = "0 8 * * *"
    weekly_cron: str = "0 9 * * mon"
    report_dir: str = "data/reports"
    low_stock_units: int = Field(default=100, ge=0)
    near_expiry_days: int = Field(default=90, ge=0, le=730)
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    retry_delay_seconds: float = Field(default=2, ge=0, le=60)
    stop_on_critical: bool = True
    assessment_at: datetime | None = None
    attach_report: bool = True

    @field_validator("daily_cron", "weekly_cron")
    @classmethod
    def valid_cron(cls, value):
        CronTrigger.from_crontab(value)
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("Unknown scheduler timezone") from exc
        return value

    @field_validator("assessment_at")
    @classmethod
    def aware_clock(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Assessment clock requires a timezone")
        return value


def load_config() -> AutomationConfig:
    path = Path(os.getenv("AUTOMATION_CONFIG", "config/automation.json"))
    config = (
        AutomationConfig.model_validate_json(path.read_text())
        if path.exists()
        else AutomationConfig()
    )
    updates = {
        "REPORT_DIR": "report_dir",
        "DAILY_CRON": "daily_cron",
        "WEEKLY_CRON": "weekly_cron",
        "SCHEDULER_TIMEZONE": "timezone",
        "DQ_ASSESSMENT_AT": "assessment_at",
    }
    value = config.model_dump()
    value.update({field: os.environ[key] for key, field in updates.items() if os.environ.get(key)})
    return AutomationConfig.model_validate(value)
