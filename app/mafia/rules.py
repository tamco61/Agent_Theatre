"""Игровые механики спортивной мафии; очный тайминг заменён текстовыми ходами."""
import random
import re
from .models import Player
from .story import EDITORIAL_KINDS

RULES_VERSION = 'mafia-coordinated-v1'
MAFIA_ROLES = frozenset(('mafia', 'don'))
RULES = '''10 игроков: дон, 2 мафии, шериф и 6 мирных. Доктора нет. Роли скрыты.
Подготовительная ночь: мафия знакомится и приватно договаривается; убийств и проверок нет.
Днём живые говорят по рассадке. Первый день начинает p1, далее — следующее живое
место после начинавшего предыдущий круг. Перемешивания нет.
В свою обычную речь можно выставить одну живую кандидатуру, включая себя, или никого.
Повторное выставление не меняет порядок кандидатов. Отозвать кандидатуру нельзя.
Без кандидатов голосования нет. В первый день единственная кандидатура не голосуется.
Голосование идёт по порядку выставления. За текущего кандидата все ещё не голосовавшие
решают одновременно: отдать голос ему (можно себе) или ждать следующего. Голоса и итоги
этой кандидатуры публикуются до следующей. Все оставшиеся голоса получает последняя.
До первого голосования дополнительных защит нет. Единственный лидер выбывает.
При ничьей только лидеры получают дополнительные речи по порядку выставления и голосуются
заново. Если ничья сузилась, процедура повторяется для меньшего списка. При повторной ничьей
того же списка все живые решают, вывести ли весь список; нужно строго больше половины.
При трёх живых после повторной ничьей сразу ночь. Вывод всех живых и половины стола
при 10, 8 или 6 живых не голосуется: никто не выбывает.
Выбывающий получает заключительное слово и может оставить протокол номеров; затем
в игре больше не говорит и не действует. Первой ночной жертве доступна тройка подозреваемых.
Каждую ночь мафия обсуждает цель приватно: предложение дона, ответы живых сообщников,
итог дона. Без живого дона ведёт первый живой мафиози по рассадке; оставшийся один
решает сам. Можно учитывать дневные события и менять цель. Движок исполняет один общий
выстрел в живого не из мафии; разногласие предложений не даёт промаха. Итоговый null —
осознанный отказ команды стрелять. Это адаптация, отличающаяся от спортивной стрельбы.
Дон дополнительно проверяет, шериф ли игрок;
шериф проверяет принадлежность к мафии (дон тоже мафия). Можно пропустить проверку.
Обсуждение видит только живая мафия. Проверки приватны и в обсуждение автоматически
не передаются; роль выбывшего не раскрывается.
Мирные побеждают, когда мафии нет; мафия — при паритете или перевесе над остальными.
Три ночи подряд с двумя днями между ними без выбываний дают ничью. Технический лимит
прерывает партию без назначения ничьей или победителя. Очные таймеры и фолы не моделируются.'''

NAMES = [('p1','Алиса','Кратко, проверяет конкретные слова'),
         ('p2','Борис','Прямо, требует объяснять выбор'),
         ('p3','Вера','Сопоставляет голоса и действия'),
         ('p4','Глеб','Предлагает альтернативные объяснения'),
         ('p5','Дина','Задаёт точные неудобные вопросы'),
         ('p6','Егор','Следит за изменениями подозрений'),
         ('p7','Жанна','Спокойно оспаривает слишком уверенные выводы'),
         ('p8','Илья','Проверяет, кому выгодно решение'),
         ('p9','Кира','Сравнивает разные версии событий'),
         ('p10','Лев','Ищет противоречия в объяснениях')]


def make_players(seed):
    roles = ['don', 'mafia', 'mafia', 'sheriff'] + ['civilian'] * 6
    random.Random(seed).shuffle(roles)
    return [Player(*info, role) for info, role in zip(NAMES, roles)]


def alive(state):
    return [p for p in state.players if p.alive]


def day_order(state):
    seats = [p.id for p in state.players]
    start = (seats.index(state.first_speaker_id) + 1) % len(seats) if state.first_speaker_id else 0
    circle = seats[start:] + seats[:start]
    living = {p.id for p in alive(state)}
    return [pid for pid in circle if pid in living]


def winner(state):
    living = alive(state)
    mafia = sum(p.role in MAFIA_ROLES for p in living)
    return 'town' if not mafia else 'mafia' if mafia >= len(living) - mafia else None


def vote_leaders(votes, candidates):
    counts = {pid: sum(target == pid for target in votes.values()) for pid in candidates}
    return [pid for pid in candidates if counts[pid] == max(counts.values())] if counts else []


def resolve_vote(votes):
    candidates = list(dict.fromkeys(pid for pid in votes.values() if pid is not None))
    leaders = vote_leaders(votes, candidates)
    return leaders[0] if len(leaders) == 1 else None


def can_remove_all(living_count, candidate_count):
    return candidate_count < living_count and not (
        living_count in (6, 8, 10) and candidate_count == living_count // 2)


def search_public(events, query, limit=5, names=None):
    events = [e for e in events if e.kind not in EDITORIAL_KINDS]
    ids = set(re.findall(r'\be[0-9]+\b', query.casefold()))
    if ids:
        return [e for e in events if e.id in ids][:limit]
    terms = set(re.findall(r'\w+', query.casefold()))
    names = names or {}
    ranked = [(sum(term in (names.get(e.speaker_id,'')+' '+names.get(e.target_id,'')+' '+e.text+
                (' выдвижение выставляет кандидат' if e.kind=='speech' and e.target_id else '')).casefold()
                for term in terms), i, e) for i,e in enumerate(events)]
    return [e for score,_,e in sorted(ranked,key=lambda x:(x[0],x[1]),reverse=True) if score][:limit]


def player_view(state, player_id, history_limit):
    from dataclasses import asdict
    from copy import deepcopy
    player = next(p for p in state.players if p.id == player_id)
    farewell = state.phase in ('last_word', 'best_move', 'protocol') and state.farewell_id == player_id
    if not player.alive and not farewell:
        raise ValueError('Выбывший игрок не получает ход')
    facts = [e for e in state.events if e.kind not in EDITORIAL_KINDS]
    history = {e.id:e for e in facts[-history_limit:]}
    if state.phase in ('runoff', 'last_word'):
        for e in state.events:
            if e.day == state.day and e.kind == 'speech' and e.target_id == player_id:
                history[e.id] = e
    mafia = player.role in MAFIA_ROLES
    team_night = mafia and state.phase == 'night'
    return {'dramatic_frame': ({k:state.story_plan[k] for k in ('title','setting','theme')}
                              if state.story_plan else None), 'rules': RULES, 'day': state.day, 'phase': state.phase,
            'you': {'id': player.id, 'name': player.name, 'role': player.role, 'style': player.style},
            'players': [{'id':p.id,'name':p.name,'alive':p.alive} for p in state.players],
            'teammates': [p.id for p in state.players if p.role in MAFIA_ROLES and p.id != player.id] if mafia else [],
            'don_id': next((p.id for p in state.players if p.role == 'don'), None) if mafia else None,
            'private_notes': list(state.private_notes.get(player.id, [])),
            'mafia_discussion': deepcopy(state.mafia_discussion) if team_night else [],
            'night_leader_id': state.night_leader_id if team_night else None,
            'day_speeches': [asdict(e) for e in state.events if e.day == state.day and
                            e.kind in ('speech','runoff','last_word')][-12:] if team_night else [],
            'history': [asdict(e) for e in state.events if e.id in history],
            'nominees': list(state.nominees),
            'runoff_candidates': list(state.runoff_candidates),
            'ballot_candidates': list(state.ballot_candidates),
            'current_candidate': state.current_candidate,
            'ballot_totals': dict(state.ballot_totals), 'vote_round': state.vote_round,
            'allowed_nomination_ids': [p.id for p in alive(state)] if state.phase == 'discussion' else [],
            'public_event_count': len(state.events)}
