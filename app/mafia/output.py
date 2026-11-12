from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import re
import tempfile
from app.journal import EventJournal
from .models import Event
from .rules import RULES, RULES_VERSION, search_public

def atomic(path, text, private=False):
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
        f.write(text)
        temporary = Path(f.name)
    temporary.replace(path)
    if private:
        path.chmod(0o600)

def event_text(event, names):
    text = event['text']
    if event['kind'] == 'speech' and event.get('target_id'):
        text += '\n\nВыставляет на голосование: ' + names[event['target_id']] + '.'
    return text

def render(public):
    names = {p['id']:p['name'] for p in public['players']} | {'host':'Ведущий'}
    lines = ['# Мафия',f"Статус: {public['status']}; победитель: {public['winner'] or 'не определён'}"]
    for e in public['events']:
        lines.append(f"**{names[e['speaker_id']]}:** {event_text(e,names)}")
    return '\n\n'.join(lines)+'\n'

class Writer:
    def __init__(self, directory, template=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True,exist_ok=False,mode=0o700)
        self.journal = EventJournal(self.directory/'private_events.jsonl')
        self.journal.path.touch(mode=0o600)
        self.template = Path(template) if template else None
        self.player_models = {}

    def search(self,query):
        public = json.loads((self.directory/'public.json').read_text())
        # В индекс попадает только публичный файл, никогда private_result/events.
        names = {p['id']:p['name'] for p in public['players']} | {'host':'Ведущий'}
        events = [Event(**e) for e in public['events']]
        return search_public(events,query,names=names)

    def save(self, config, state):
        public = {'rules_version':RULES_VERSION,'status':state.status,'winner':state.winner,'day':state.day,'phase':state.phase,
                  'players':[{'id':p.id,'name':p.name,'style':p.style,'alive':p.alive} for p in state.players],
                  'events':[asdict(e) for e in state.events], 'nominees':list(state.nominees),
                  'limits':{'max_days':config.max_days,'ordinary_speeches_per_day':1},
                  'interrupted':state.status in ('failed','limited')}
        atomic(self.directory/'public.json',json.dumps(public,ensure_ascii=False,indent=2)+'\n')
        atomic(self.directory/'private_result.json',json.dumps({'config':asdict(config),'state':asdict(state)},ensure_ascii=False,indent=2)+'\n',True)
        atomic(self.directory/'public.md',render(public))
        responses = [e.payload for e in self.journal.events if e.kind == 'llm_response']
        usage = Counter()
        for response in responses:
            usage.update({k:v for k,v in response.get('usage',{}).items() if type(v) is int})
        summary = {'rules_version':RULES_VERSION,'status':state.status,'winner':state.winner,'days':state.day,
                   'speeches':sum(e.kind in ('speech','runoff','last_word') for e in state.events),
                   'runoff_speeches':sum(e.kind=='runoff' for e in state.events),
                   'last_words':sum(e.kind=='last_word' for e in state.events),
                   'nominations':sum(e.kind=='speech' and e.target_id is not None for e in state.events),
                   'searches':sum(e.kind=='mafia_search' for e in self.journal.events),
                   'searches_cited':sum(bool(e.payload.get('cited_ids')) for e in self.journal.events if e.kind=='mafia_search_use'),
                   'story_plans':sum(e.kind=='story_plan' for e in state.events),
                   'narrations':sum(e.kind=='narration' for e in state.events),
                   'story_errors':sum(e.kind=='story_error' for e in self.journal.events),
                   'llm_calls':len(responses),'validation_errors':sum(e.kind=='validation_error' for e in self.journal.events),
                   'usage':dict(usage)}
        atomic(self.directory/'summary.json',json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        if self.template and state.status in ('finished','draw','failed','limited'):
            atomic(self.directory/'chat.html',chat_html(public,self.template.read_text()))
        if state.status in ('finished','draw','failed','limited'):
            from .replay import table_html
            provenance = {}
            source = self.directory/'provenance.json'
            if source.exists():
                try:
                    provenance = json.loads(source.read_text())
                except (ValueError, OSError):
                    pass
            if self.player_models:
                provenance = {**provenance, 'models':self.player_models}
            atomic(self.directory/'table.html', table_html(public, provenance))

def chat_html(public, template):
    events, phases = [], sum(e['kind']=='phase' for e in public['events'])
    phase = 0
    names = {p['id']:p['name'] for p in public['players']} | {'host':'Ведущий'}
    by_id = {e['id']:e for e in public['events']}
    for e in public['events']:
        if e['kind'] == 'rules':
            continue  # Полные правила уже доступны в раскрываемом блоке шапки.
        if e['kind']=='phase':
            phase += 1
            events.append({'kind':'stage','number':phase,'title':e['text'],'case':'Роли и ночные действия скрыты.'})
        else:
            target = by_id.get(e['reply_to'])
            events.append({'kind':'message','speaker':e['speaker_id'],'text':event_text(e,names),
                           'label':{'speech':'Реплика','runoff':'Переголосование','last_word':'Последнее слово',
                                    'protocol':'Протокол','best_move':'Тройка подозреваемых',
                                    'story_plan':'План пьесы','narration':'Закадровая ремарка','archive_review':'Проверка архива',
                                    'vote':'Голос','rules':'Правила','winner':'Результат','limit':'Лимит'}.get(e['kind'],'Событие'),
                           'target':'В ответ: '+names[target['speaker_id']] if target else None,
                           'sources':[{'title':cid,'text':by_id[cid]['text']} for cid in e['evidence_ids']]})
    recorded_rules = next((e['text'] for e in public['events'] if e['kind']=='rules'), RULES)
    count = len(public['players'])
    data = {'title':f'Мафия. {count} игроков','main_question':'Кто скрывает роль, а кто ошибается в своих подозрениях?',
            'scenario':recorded_rules,'people':[{'id':p['id'],'name':p['name'],'label':p['style'],
            'criterion':'Роль скрыта. Принадлежность к команде нельзя установить по цвету или имени.'} for p in public['players']],
            'stages':phases,'events':events}
    encoded = json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html = re.sub(r'(<script type="application/json" id="chat-data">).*?(</script>)',lambda m:m[1]+encoded+m[2],template,flags=re.S)
    return html.replace('Распределение бюджета</h2>','Мафия · игровой чат</h2>').replace('3 участника + ведущий',f'{count} игроков + ведущий').replace('Условия мысленного эксперимента','Правила партии').replace('Этап ${event.number}','Фаза ${event.number}')
