"""Художественная рамка и публичные ремарки, без доступа к игровым секретам."""
from dataclasses import dataclass, asdict
from typing import Literal
from pathlib import Path
from app.agents.base import JsonAgent

EDITORIAL_KINDS = frozenset(('story_plan', 'narration', 'archive_review'))


@dataclass
class Act:
    key: Literal['opening', 'pressure', 'crisis', 'ending']
    title: str
    purpose: str


@dataclass
class StoryPlan:
    title: str
    setting: str
    theme: str
    acts: list[Act]


@dataclass
class Narration:
    text: str
    evidence_ids: list[str]


def public_scene(state):
    """Белый список: сюда нельзя передавать asdict(state) или player_view."""
    return {
        'day': state.day, 'phase': state.phase, 'status': state.status,
        'players': [{'id': p.id, 'name': p.name, 'alive': p.alive} for p in state.players],
        'events': [asdict(e) for e in state.events if e.kind not in EDITORIAL_KINDS][-12:],
    }


def current_act(scene):
    if scene['status'] in ('finished', 'draw', 'limited'):
        return 'ending'
    if scene['day'] >= 3 or sum(p['alive'] for p in scene['players']) <= 4:
        return 'crisis'
    return 'pressure' if scene['day'] >= 2 else 'opening'


class StoryDirector:
    def __init__(self, model, journal, attempts=3):
        self.agent = JsonAgent('mafia_story', model, journal, attempts)

    def plan(self, roster):
        def validate(plan):
            if [a.key for a in plan.acts] != ['opening', 'pressure', 'crisis', 'ending']:
                raise ValueError('Нужны четыре действия по порядку: opening, pressure, crisis, ending')
            texts = [plan.title, plan.setting, plan.theme] + [t for a in plan.acts for t in (a.title, a.purpose)]
            if any(not t.strip() or len(t) > 450 for t in texts):
                raise ValueError('Каждое поле должно содержать 1–450 символов')
        return self.agent.ask(StoryPlan, self.prompt('story_plan'), {'cast': roster}, validate)

    def narrate(self, plan, scene):
        key = current_act(scene)
        act = next(a for a in plan['acts'] if a['key'] == key)
        allowed = {e['id'] for e in scene['events']}
        def validate(reply):
            if not reply.text.strip() or len(reply.text) > 450:
                raise ValueError('Ремарка: 1–450 символов')
            if not reply.evidence_ids or not set(reply.evidence_ids) <= allowed:
                raise ValueError('Укажи ID публичных событий, на которых основана ремарка')
            if scene['events'][-1]['id'] not in reply.evidence_ids:
                raise ValueError('Ремарка должна учитывать текущее событие')
        return self.agent.ask(Narration, self.prompt('narrator'),
                              {'setting': plan['setting'], 'theme': plan['theme'],
                               'act': act, 'scene': scene}, validate)

    @staticmethod
    def prompt(name):
        return (Path(__file__).parent/'prompts'/f'{name}.txt').read_text()


def archive_task(state, view):
    """Одно старое выставление вне окна истории, выбранное без знания ролей."""
    if state.day < 2 or state.phase != 'discussion':
        return None
    visible = {e['id'] for e in view['history']}
    candidates = [e for e in state.events if e.kind == 'speech' and e.target_id
                  and e.day < state.day and e.id not in visible]
    if not candidates:
        return None
    living = {p.id for p in state.players if p.alive}
    event = max(candidates, key=lambda e: (e.target_id in living, int(e.id[1:])))
    names = {p.id: p.name for p in state.players}
    return {'event_id': event.id, 'day': event.day, 'author': names[event.speaker_id],
            'nominee': names[event.target_id],
            'task': 'Найди эту речь в файле (включи event_id в query). Восстанови основание '
                    'выставления и сопоставь с последующими событиями. Объясни, '
                    'сохранилась ли сила довода, ослабла или данных недостаточно. '
                    'Ссылайся на найденный event_id в evidence_ids; не считай подозрение фактом.'}
