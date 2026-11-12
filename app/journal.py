"""Журнал пишется после каждого события, в том числе до вызова LLM."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from datetime import datetime, timezone

@dataclass
class PipelineEvent:
    kind: str
    # Например, asdict(BiographySearch(...)), вход/выход LLM или описание ошибки.
    payload: dict[str, object] = field(default_factory=dict)
    scene_id: str | None = None
    character_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EventJournal:
    def __init__(self, path: Path):
        self.path = path
        self.events: list[PipelineEvent] = []

    def emit(self, kind: str, payload: dict, *, scene_id=None, character_id=None) -> None:
        # Снимок защищает прошлые события от последующих изменений списков/словарей.
        payload = json.loads(json.dumps(payload, ensure_ascii=False))
        event = PipelineEvent(kind=kind, payload=payload, scene_id=scene_id, character_id=character_id)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        self.events.append(event)
