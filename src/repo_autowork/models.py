from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass
class ProjectRecord:
    slug: str
    name: str
    repo_path: str
    origin_url: str = ""
    forge_kind: str = "unknown"
    default_branch: str = "main"
    current_branch: str = "main"
    is_fork: bool = False
    upstream_url: str = ""
    upstream_default_branch: str = ""
    telegram_topic_id: int | None = None
    last_telegram_report_hash: str | None = None
    daily_runs_target: int = 2
    cron_minute: int | None = None
    tg_folder: str = ""
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        return cls(**payload)


@dataclass
class ProjectDispatchOutcome:
    project_slug: str
    update_id: int
    success: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectDispatchOutcome":
        return cls(
            project_slug=payload.get("project_slug", ""),
            update_id=int(payload.get("update_id", 0)),
            success=bool(payload.get("success", False)),
            detail=payload.get("detail", ""),
        )


@dataclass
class TelegramSyncSummary:
    handled: int = 0
    ignored: dict[str, int] = field(default_factory=dict)
    dispatch_outcomes: list[ProjectDispatchOutcome] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "ignored": self.ignored,
            "dispatch_outcomes": [o.to_dict() for o in self.dispatch_outcomes],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TelegramSyncSummary":
        outcomes = [
            ProjectDispatchOutcome.from_dict(o)
            for o in payload.get("dispatch_outcomes", [])
        ]
        return cls(
            handled=int(payload.get("handled", 0)),
            ignored=payload.get("ignored", {}),
            dispatch_outcomes=outcomes,
            timestamp=payload.get("timestamp", ""),
        )


@dataclass
class State:
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    projects: list[ProjectRecord] = field(default_factory=list)
    last_telegram_update_id: int = 0
    last_telegram_sync: TelegramSyncSummary | None = None
    telegram_sync_history: list[TelegramSyncSummary] = field(default_factory=list)

    MAX_SYNC_HISTORY = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_telegram_update_id": self.last_telegram_update_id,
            "last_telegram_sync": self.last_telegram_sync.to_dict() if self.last_telegram_sync else None,
            "telegram_sync_history": [s.to_dict() for s in self.telegram_sync_history],
            "projects": [project.to_dict() for project in self.projects],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "State":
        sync_payload = payload.get("last_telegram_sync")
        history_payload = payload.get("telegram_sync_history", [])
        return cls(
            created_at=payload.get("created_at", utc_now_iso()),
            updated_at=payload.get("updated_at", utc_now_iso()),
            last_telegram_update_id=int(payload.get("last_telegram_update_id", 0) or 0),
            last_telegram_sync=TelegramSyncSummary.from_dict(sync_payload) if sync_payload else None,
            telegram_sync_history=[TelegramSyncSummary.from_dict(s) for s in history_payload],
            projects=[ProjectRecord.from_dict(item) for item in payload.get("projects", [])],
        )

    def append_sync_history(self, summary: TelegramSyncSummary) -> None:
        self.telegram_sync_history.append(summary)
        if len(self.telegram_sync_history) > self.MAX_SYNC_HISTORY:
            self.telegram_sync_history = self.telegram_sync_history[-self.MAX_SYNC_HISTORY:]
