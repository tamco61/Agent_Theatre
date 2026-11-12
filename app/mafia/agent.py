from dataclasses import asdict
from pathlib import Path
from app.agents.base import JsonAgent
from .models import Speech, Choice, Plan, Protocol

class ModelPlayer:
    def __init__(self, model, journal, attempts=3):
        self.agent = JsonAgent('mafia_player', model, journal, attempts)

    def speak(self, view, lookup):
        prompt = (Path(__file__).parent/'prompts/player.txt').read_text()
        task = {
            'runoff':'Ты связан ничьей голосов. Дополнительная короткая речь перед переголосованием. nominate_id=null.',
            'last_word':'Ты выбываешь. Заключительное слово: оставь свою версию живым; новых выдвижений нет. nominate_id=null.',
            'discussion':'Твоя обычная речь. Обоснуй подозрение; можешь выставить одного живого, включая себя, или никого.'
        }[view['phase']]
        context = {**view, 'task':task,
                   'search_available': True, 'search_results': []}
        for step in range(2):
            def validate(reply):
                if reply.action == 'search':
                    if step or not reply.query or not reply.query.strip():
                        raise ValueError('Доступен один непустой поисковый запрос за ход')
                    if reply.text is not None or reply.reply_to is not None or reply.evidence_ids or reply.nominate_id is not None:
                        raise ValueError('При search заполни только query; text, reply_to, nominate_id=null, evidence_ids=[]')
                    return
                archive = view.get('archive_task')
                if archive and (not step or archive['event_id'] not in {e['id'] for e in context['search_results']}
                                or archive['event_id'] not in reply.evidence_ids):
                    raise ValueError('Сначала найди архивную речь по event_id, затем используй её в evidence_ids')
                if not reply.text or not reply.text.strip() or reply.query is not None:
                    raise ValueError('При speak нужны text и query=null')
                visible = {e['id'] for e in context['history'] + context['search_results']}
                if reply.reply_to is not None and reply.reply_to not in visible:
                    raise ValueError('reply_to должен быть ID доступного публичного события')
                if not set(reply.evidence_ids).issubset(visible):
                    raise ValueError('В evidence_ids допустимы только доступные публичные события')
                if reply.nominate_id is not None and reply.nominate_id not in view['allowed_nomination_ids']:
                    raise ValueError('Выдвинуть можно живого только в обычной речи; иначе nominate_id=null')
            reply = self.agent.ask(Speech, prompt, context, validate, character_id=view['you']['id'])
            if reply.action == 'speak':
                return reply
            context.update(search_available=False, search_results=lookup(reply.query),
                           task='Поиск выполнен. Теперь обязательно speak. '+task)
        raise RuntimeError('Исчерпан бюджет поиска')

    def plan(self, view):
        def validate(reply):
            if not reply.text.strip():
                raise ValueError('Пустая договорка')
        return self.agent.ask(Plan, (Path(__file__).parent/'prompts/plan.txt').read_text(), view,
                              validate, character_id=view['you']['id'])

    def protocol(self, view, best_move=False):
        def validate(reply):
            ids = reply.player_ids
            if (len(ids) != len(set(ids)) or any(pid not in allowed for pid in ids)
                    or (best_move and len(ids) not in (0,3))):
                raise ValueError('Нужны уникальные номера; для тройки ровно три или пустой список')
        allowed = [p['id'] for p in view['players']]
        return self.agent.ask(Protocol,
                              'Ты выбывающий игрок. Верни только список player_ids из allowed_ids. '
                              'Это твоя версия, а не установленные роли. Можно отказаться: [].',
                              {**view, 'task':'Назови тройку подозреваемых (три номера).' if best_move else
                               'Оставь протокол подозреваемых после заключительного слова.', 'allowed_ids':allowed},
                              validate, character_id=view['you']['id'])

    def choose(self, view, task, allowed, abstain=False):
        def validate(choice):
            if (choice.target_id is None and not abstain) or (choice.target_id is not None and choice.target_id not in allowed):
                raise ValueError(f'Выбери один ID из {allowed}' + (' или null' if abstain else ''))
            if not choice.reason.strip():
                raise ValueError('Объясни выбор')
        return self.agent.ask(Choice, (Path(__file__).parent/'prompts/choice.txt').read_text(),
                              {**view,'task':task,'allowed_target_ids':allowed,'can_abstain':abstain},
                              validate, character_id=view['you']['id'])
