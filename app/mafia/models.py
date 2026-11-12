from dataclasses import dataclass, field
from typing import Literal

Role = Literal['mafia', 'don', 'sheriff', 'civilian']

@dataclass
class Config:
    seed: int = 17
    max_days: int = 30
    history_limit: int = 16
    attempts: int = 3
    archive_review: bool = False

    def __post_init__(self):
        for name in ('max_days', 'history_limit', 'attempts'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name}: требуется положительное целое число')
        if type(self.archive_review) is not bool:
            raise ValueError('archive_review: требуется bool')
        if type(self.seed) is not int:
            raise ValueError('seed: требуется целое число')

@dataclass
class Player:
    id: str
    name: str
    style: str
    role: Role
    alive: bool = True

@dataclass
class Speech:
    action: Literal['speak', 'search']
    text: str | None
    reply_to: str | None
    query: str | None
    evidence_ids: list[str]
    nominate_id: str | None = field(default=None, metadata={'llm_required': True})

@dataclass
class Choice:
    target_id: str | None
    reason: str

@dataclass
class Plan:
    text: str

@dataclass
class Protocol:
    player_ids: list[str]

@dataclass
class Event:
    id: str
    day: int
    phase: str
    kind: str
    speaker_id: str
    text: str
    reply_to: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    target_id: str | None = None
    details: dict = field(default_factory=dict)

@dataclass
class State:
    players: list[Player]
    day: int = 0
    phase: str = 'ready'
    status: str = 'ready'
    winner: str | None = None
    events: list[Event] = field(default_factory=list)
    private_notes: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None
    nominees: list[str] = field(default_factory=list)
    first_speaker_id: str | None = None
    runoff_candidates: list[str] = field(default_factory=list)
    ballot_candidates: list[str] = field(default_factory=list)
    current_candidate: str | None = None
    ballot_totals: dict[str, int] = field(default_factory=dict)
    vote_round: int = 0
    farewell_id: str | None = None
    prepared: bool = False
    quiet_nights: int = 0
    story_plan: dict | None = None
    mafia_discussion: list[dict] = field(default_factory=list)
    night_leader_id: str | None = None

