"""Ограниченное приватное обсуждение и одно итоговое решение команды."""
from dataclasses import asdict
from .rules import alive, MAFIA_ROLES


class MafiaCoordination:
    def __init__(self, game):
        self.game = game

    def decide(self):
        g, s = self.game, self.game.state
        team = [p for p in alive(s) if p.role in MAFIA_ROLES]
        if not team:
            raise ValueError('Нет живой мафии для ночного обсуждения')
        leader = next((p for p in team if p.role == 'don'), team[0])
        allowed = [p.id for p in alive(s) if p.role not in MAFIA_ROLES]
        s.mafia_discussion = []
        s.night_leader_id = leader.id

        def post(player, stage, task):
            choice = g.choose(player.id, task+' Опирайся на day_speeches и mafia_discussion. '
                              'reason — 1–2 коротких предложения. null — осознанное предложение не стрелять.',
                              allowed, True)
            message = {'speaker_id':player.id, 'stage':stage, **asdict(choice)}
            s.mafia_discussion.append(message)
            g.writer.journal.emit('mafia_coordination', {'day':s.day, 'leader_id':leader.id, **message},
                                  character_id=player.id)
            g.writer.save(g.config, s)
            return choice

        if len(team) == 1:
            decision = post(leader, 'final', 'Ты единственный живой мафиози. Утверди общий выстрел этой ночи.')
        else:
            post(leader, 'proposal', 'Ты ведёшь обсуждение. Предложи выстрел с учётом дневных событий.')
            for player in team:
                if player.id != leader.id:
                    post(player, 'response', 'Ответь на предложение ведущего: поддержи цель выстрела или предложи другую с причиной.')
            decision = post(leader, 'final', 'Прочитай ответы сообщников и утверди окончательный общий выстрел. '
                            'Можешь изменить первоначальную цель; именно этот выбор исполнит движок.')

        target = next((p.name for p in s.players if p.id == decision.target_id), None)
        summary = (f'Ночь {s.day}: команда выбрала {target}.' if target else
                   f'Ночь {s.day}: команда решила не стрелять.') + ' ' + decision.reason
        for player in team:
            s.private_notes.setdefault(player.id, []).append(summary)
        g.writer.save(g.config, s)
        return decision
