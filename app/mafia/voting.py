"""Последовательные кандидатуры, переголосования и решение о выводе группы."""
from .rules import alive, vote_leaders, can_remove_all


class Voting:
    def __init__(self, game):
        self.game = game

    def ballot(self, candidates):
        g, s = self.game, self.game.state
        s.phase = 'vote'
        s.vote_round += 1
        s.ballot_candidates = list(candidates)
        s.ballot_totals = {}
        remaining = [p.id for p in alive(s)]
        votes = {}
        names = {p.id:p.name for p in s.players}
        g.emit('phase', f'Голосование, тур {s.vote_round}: '+ ' → '.join(names[pid] for pid in candidates)+'.')
        for index, candidate in enumerate(candidates):
            s.current_candidate = candidate
            last = index == len(candidates)-1
            g.emit('ballot_candidate', f'Кто голосует против {names[candidate]}?'+
                   (' Оставшиеся голоса автоматически засчитываются последнему кандидату.' if last else ''),
                   target_id=candidate, details={'round':s.vote_round})
            # Руки за одну кандидатуру одновременны; её итог виден до следующей.
            choices = {} if last else {
                pid:g.choose(pid, f'Сейчас голосуется {names[candidate]}. Голос за него или null — ждать следующую кандидатуру.',
                             [candidate], True) for pid in remaining}
            selected = list(remaining) if last else [pid for pid in remaining if choices[pid].target_id is not None]
            for pid in selected:
                votes[pid] = candidate
                reason = 'Голос засчитан последней кандидатуре.' if last else choices[pid].reason
                g.emit('vote', f'{names[pid]}: голос за {names[candidate]}. {reason}', pid,
                       target_id=candidate, details={'round':s.vote_round, 'automatic':last})
            remaining = [pid for pid in remaining if pid not in selected]
            s.ballot_totals[candidate] = len(selected)
            g.emit('ballot_result', f'{names[candidate]}: {len(selected)} голосов.', target_id=candidate,
                   details={'round':s.vote_round, 'voter_ids':selected, 'count':len(selected)})
        s.current_candidate = None
        return vote_leaders(votes, candidates)

    def run(self, candidates):
        g, s = self.game, self.game.state
        leaders = self.ballot(candidates)
        while len(leaders) > 1:
            tied = list(leaders)
            s.runoff_candidates = tied
            s.phase = 'runoff'
            g.emit('phase', 'Ничья. Дополнительное слово только связанным кандидатам, по порядку выставления.')
            for pid in tied:
                g.speech(pid)
            leaders = self.ballot(tied)
            if leaders != tied:
                continue  # Единственный лидер или строго меньшая группа.
            living = alive(s)
            if len(living) == 3 or not can_remove_all(len(living), len(tied)):
                g.emit('no_elimination', 'Повторная ничья. Вывод этой группы не голосуется; наступает ночь.')
                return []
            s.phase = 'remove_all'
            g.emit('phase', 'Повторная ничья: вывести всех связанных кандидатов? Нужно строгое большинство живых.')
            choices = {p.id:g.choose(p.id, 'Вывести всех из runoff_candidates? yes — вывести; no — оставить.',
                                    ['yes', 'no']) for p in living}
            for pid, choice in choices.items():
                g.emit('group_vote', ('За вывод группы. ' if choice.target_id == 'yes' else 'Против вывода группы. ')+choice.reason,
                       pid, details={'choice':choice.target_id, 'candidate_ids':tied})
            approved = sum(c.target_id == 'yes' for c in choices.values()) > len(living)/2
            if not approved:
                g.emit('no_elimination', 'Большинства за вывод группы нет; никто не выбывает.')
            return tied if approved else []
        return leaders
