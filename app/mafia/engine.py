from dataclasses import asdict
from copy import deepcopy
from .models import State, Event
from .rules import RULES, MAFIA_ROLES, make_players, alive, winner, day_order, player_view
from .recovery import finish_day, resume_discussion
from .coordination import MafiaCoordination
from .story import public_scene, current_act, archive_task


class Game:
    def __init__(self, config, agents, writer, director=None):
        self.config, self.agents, self.writer = config, agents, writer
        self.director = director
        self.state = State(make_players(config.seed))
        if set(agents) != {p.id for p in self.state.players}:
            raise ValueError('Требуются агенты p1..p10')

    def emit(self, kind, text, speaker='host', reply_to=None, evidence=(), target_id=None, details=None):
        s = self.state
        s.events.append(Event(f'e{len(s.events)+1}', s.day, s.phase, kind, speaker, text,
                              reply_to, list(evidence), target_id, details or {}))
        self.writer.save(self.config, s)
        if self.director and s.story_plan and (
                (kind == 'phase' and s.phase in ('preparation', 'discussion'))
                or kind in ('elimination', 'night_result', 'winner', 'limit')):
            self.narrate()

    def narrate(self):
        # Художественный сбой не должен отменять принятое игровое решение.
        try:
            scene = public_scene(self.state)
            reply = self.director.narrate(deepcopy(self.state.story_plan), scene)
            self.emit('narration', reply.text, evidence=reply.evidence_ids,
                      details={'act': current_act(scene)})
        except Exception as exc:
            self.writer.journal.emit('story_error', {'error_type': type(exc).__name__,
                                                    'event_id': self.state.events[-1].id})
            self.writer.save(self.config, self.state)

    def view(self, pid):
        return player_view(self.state, pid, self.config.history_limit)

    def lookup(self, pid, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Поиску нужен непустой запрос')
        hits = [asdict(e) for e in self.writer.search(query)]
        self.writer.journal.emit('mafia_search', {'query':query, 'event_ids':[e['id'] for e in hits]}, character_id=pid)
        return hits

    def choose(self, pid, task, allowed, abstain=False):
        choice = self.agents[pid].choose(deepcopy(self.view(pid)), task, list(allowed), abstain)
        if (choice.target_id is None and not abstain) or (choice.target_id is not None and choice.target_id not in allowed):
            raise ValueError('Агент вернул недопустимую цель')
        if not isinstance(choice.reason, str) or not choice.reason.strip():
            raise ValueError('Нет объяснения выбора')
        return choice

    def finish_if_won(self):
        result = winner(self.state)
        if result:
            self.state.winner, self.state.status = result, 'finished'
            self.state.phase = 'finished'
            self.emit('winner', 'Победили мирные.' if result == 'town' else 'Победила мафия.')
        return bool(result)

    def prepare(self):
        s = self.state
        if s.prepared:
            raise ValueError('Подготовительная ночь уже проведена')
        s.phase = 'preparation'
        self.emit('phase', 'Подготовительная ночь: мафия знакомится и договаривается. Убийств и проверок нет.')
        mafia = [p for p in s.players if p.role in MAFIA_ROLES]
        don = next(p for p in mafia if p.role == 'don')
        # Подготовка задаёт общую стратегию; цель уточняется приватно каждую ночь.
        for player in [don] + [p for p in mafia if p != don] + [don]:
            plan = self.agents[player.id].plan(deepcopy(self.view(player.id)))
            if not isinstance(plan.text, str) or not plan.text.strip():
                raise ValueError('Пустая договорка')
            self.writer.journal.emit('mafia_plan', {'text':plan.text}, character_id=player.id)
            for recipient in mafia:
                s.private_notes.setdefault(recipient.id, []).append(f'Договорка, {player.name}: {plan.text}')
            self.writer.save(self.config, s)
        s.prepared = True
        self.writer.save(self.config, s)

    def speech(self, pid):
        s = self.state
        kinds = {'discussion':'speech', 'runoff':'runoff', 'last_word':'last_word'}
        if s.phase not in kinds:
            raise ValueError('Сейчас речей нет')
        if s.phase == 'runoff' and pid not in s.runoff_candidates:
            raise ValueError('Дополнительная речь только для связанных ничьей кандидатов')
        if s.phase == 'last_word' and pid != s.farewell_id:
            raise ValueError('Это не заключительное слово игрока')
        kind = kinds[s.phase]
        if any(e.day == s.day and e.kind == kind and e.speaker_id == pid and
               (kind != 'runoff' or e.details.get('round') == s.vote_round) for e in s.events):
            raise ValueError('Игрок уже использовал это слово')
        found, searched = [], False

        def lookup(query):
            nonlocal searched
            if searched:
                raise ValueError('Доступен один поиск за ход')
            searched = True
            hits = self.lookup(pid, query)
            found.extend(e['id'] for e in hits)
            return hits

        view = self.view(pid)
        if self.config.archive_review and pid == s.first_speaker_id:
            task = archive_task(s, view)
            if task:
                view['archive_task'] = task
        visible = {e['id'] for e in view['history']}
        reply = self.agents[pid].speak(deepcopy(view), lookup)
        if reply.action != 'speak' or not isinstance(reply.text, str) or not reply.text.strip() or reply.query is not None:
            raise ValueError('Агент не произнёс допустимую реплику')
        visible.update(found)
        if reply.reply_to is not None and reply.reply_to not in visible:
            raise ValueError('Ссылка на невидимую реплику')
        if not set(reply.evidence_ids).issubset(visible):
            raise ValueError('Ссылка на невидимое доказательство')
        if view.get('archive_task'):
            required = view['archive_task']['event_id']
            if required not in found or required not in reply.evidence_ids:
                raise ValueError('Архивная проверка требует поиска исходной речи и ссылки на неё')
        if reply.nominate_id is not None:
            if reply.nominate_id not in view['allowed_nomination_ids']:
                raise ValueError('Нельзя выдвинуть эту цель или выдвигать вне обычной речи')
            if reply.nominate_id not in s.nominees:
                s.nominees.append(reply.nominate_id)
        self.emit(kind, reply.text, pid, reply.reply_to, reply.evidence_ids, reply.nominate_id,
                  {'round':s.vote_round} if kind == 'runoff' else None)
        if searched:
            used = [eid for eid in reply.evidence_ids if eid in found]
            self.writer.journal.emit('mafia_search_use', {'found_ids':found, 'cited_ids':used}, character_id=pid)
            by_id = {e.id:e for e in s.events}
            excerpts = ' '.join(f'{eid}: «{by_id[eid].text[:180]}»' for eid in found)
            self.emit('archive_review', f'{view["you"]["name"]}: поиск в публичном архиве; '
                      f'найдено: {", ".join(found) or "нет совпадений"}; '
                      f'в речи использовано: {", ".join(used) or "нет ссылок"}. {excerpts}',
                      reply_to=s.events[-1].id, evidence=used)

    def protocol(self, pid, best_move=False):
        s = self.state
        s.phase = 'best_move' if best_move else 'protocol'
        reply = self.agents[pid].protocol(deepcopy(self.view(pid)), best_move)
        ids = reply.player_ids
        allowed = {p.id for p in s.players}
        if (not isinstance(ids, list) or any(not isinstance(i, str) or i not in allowed for i in ids)
                or len(ids) != len(set(ids)) or (best_move and len(ids) not in (0, 3))):
            raise ValueError('Недопустимые номера протокола')
        if ids:
            names = {p.id:p.name for p in s.players}
            self.emit('best_move' if best_move else 'protocol',
                      ('Тройка подозреваемых: ' if best_move else 'Протокол: ')+', '.join(names[i] for i in ids)+'.',
                      pid, details={'player_ids':ids})

    def eliminate(self, ids, night=False):
        s = self.state
        players = [next(p for p in s.players if p.id == pid) for pid in ids]
        if any(not p.alive for p in players) or len(ids) != len(set(ids)):
            raise ValueError('Недопустимый список выбывающих')
        for p in players:
            p.alive = False
        if players:
            s.quiet_nights = 0
        for p in players:
            self.emit('night_result' if night else 'elimination',
                      f'{p.name} '+('погибает ночью.' if night else 'выбывает по голосованию.')+' Роль не раскрывается.', target_id=p.id)
        previous_phase = s.phase
        for p in players:
            s.farewell_id = p.id
            try:
                if night and s.day == 1:
                    self.protocol(p.id, best_move=True)
                s.phase = 'last_word'
                self.emit('phase', f'{p.name}: заключительное слово.')
                self.speech(p.id)
                self.protocol(p.id)
            finally:
                s.farewell_id = None
                s.phase = previous_phase

    def day(self):
        s = self.state
        s.nominees, s.runoff_candidates, s.ballot_candidates = [], [], []
        s.vote_round, s.ballot_totals, s.current_candidate = 0, {}, None
        s.phase = 'discussion'
        names = {p.id:p.name for p in s.players}
        order = day_order(s)
        s.first_speaker_id = order[0]
        self.emit('phase', f'День {s.day}. Круг по местам: '+' → '.join(names[pid] for pid in order)+'.')
        for pid in order:
            self.speech(pid)
        finish_day(self)

    def night(self):
        s = self.state
        s.phase = 'night'
        self.emit('phase', f'Ночь после дня {s.day}. Публичный чат закрыт.')
        living = alive(s)
        numbers = [p.id for p in s.players]
        decision = MafiaCoordination(self).decide()
        checks = {}
        for p in living:
            if p.role in ('don', 'sheriff'):
                task = 'Проверь, шериф ли выбранный игрок.' if p.role == 'don' else 'Проверь принадлежность выбранного игрока к мафии.'
                checks[p.id] = self.choose(p.id, task+' Можно пропустить: null.', numbers, True)
        self.writer.journal.emit('mafia_night', {'leader_id':s.night_leader_id, 'decision':asdict(decision),
                                               'checks':{pid:asdict(c) for pid,c in checks.items()}})
        # Результаты применяются после всех решений, в том числе для будущей жертвы.
        for pid, check in checks.items():
            if check.target_id is None:
                continue
            actor = next(p for p in s.players if p.id == pid)
            target = next(p for p in s.players if p.id == check.target_id)
            result = ('шериф' if target.role == 'sheriff' else 'не шериф') if actor.role == 'don' else (
                'мафия' if target.role in MAFIA_ROLES else 'не мафия')
            s.private_notes.setdefault(pid, []).append(f'Ночь {s.day}: {target.name} — {result}.')
        victim = next((p for p in living if p.id == decision.target_id), None)
        s.phase = 'dawn'
        if victim:
            self.eliminate([victim.id], night=True)
        else:
            s.quiet_nights += 1
            self.emit('night_result', 'Этой ночью никто не погиб.')
        if not self.finish_if_won() and s.quiet_nights >= 3:
            s.phase, s.status = 'finished', 'draw'
            self.emit('winner', 'Ничья: три ночи и два дня между ними прошли без выбываний.')

    def resume_discussion(self):
        return resume_discussion(self)

    def run(self):
        s = self.state
        if s.status != 'ready':
            raise ValueError('Эту партию уже запускали; создайте новую Game')
        s.status = 'running'
        try:
            if self.director:
                # План создаётся до первого игрового события. Сценарист не видит роли или seed.
                roster = [{'id':p.id, 'name':p.name} for p in s.players]
                plan = self.director.plan(roster)
                s.story_plan = asdict(plan)
                text = f'{plan.title}\n{plan.setting}\nТема: {plan.theme}\n' + '\n'.join(
                    f'{i}. {act.title}: {act.purpose}' for i,act in enumerate(plan.acts,1))
                self.emit('story_plan', text, details={'plan':s.story_plan})
            self.emit('rules', RULES)
            self.prepare()
            for day in range(1, self.config.max_days+1):
                s.day = day
                self.day()
                if s.status in ('finished', 'draw'):
                    break
                self.night()
                if s.status in ('finished', 'draw'):
                    break
            if s.status == 'running':
                s.phase, s.status = 'finished', 'limited'
                self.emit('limit', 'Партия прервана по техническому лимиту дней; игровой результат не определён.')
        except (Exception, KeyboardInterrupt) as exc:
            s.status, s.error = 'failed', str(exc) or type(exc).__name__
            self.writer.save(self.config, s)
            raise
        self.writer.save(self.config, s)
        return s
