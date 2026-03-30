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
class State:
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    projects: list[ProjectRecord] = field(default_factory=list)
    last_telegram_update_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_telegram_update_id": self.last_telegram_update_id,
            "projects": [project.to_dict() for project in self.projects],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "State":
        return cls(
            created_at=payload.get("created_at", utc_now_iso()),
            updated_at=payload.get("updated_at", utc_now_iso()),
            last_telegram_update_id=int(payload.get("last_telegram_update_id", 0) or 0),
            projects=[ProjectRecord.from_dict(item) for item in payload.get("projects", [])],
        )
