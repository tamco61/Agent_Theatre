"""Автономный визуальный повтор: только публичные события и названия моделей."""
import json
from pathlib import Path


def model_label(raw):
    raw = raw if isinstance(raw, str) else ''
    if 'yandexgpt' in raw.casefold():
        return {'provider':'yandex', 'model':'YandexGPT', 'model_detail':'YandexGPT · yandexgpt/latest'}
    if 'gemini' in raw.casefold():
        name = raw.rsplit('/', 1)[-1]
        return {'provider':'gemini', 'model':name.replace('gemini-', 'Gemini ').replace('-flash-lite',' Flash-Lite'),
                'model_detail':name}
    if raw.casefold().endswith('.gguf'):
        name = raw.replace('\\','/').rsplit('/',1)[-1]
        label = 'Qwen3.5 · 9B' if 'qwen3.5-9b' in name.casefold() else name.removesuffix('.gguf')
        return {'provider':'local', 'model':label, 'model_detail':name}
    return {'provider':'other', 'model':raw.rsplit('/',1)[-1] or 'Модель не указана',
            'model_detail':raw.rsplit('/',1)[-1] or 'Нет данных о модели'}


def table_html(public, provenance=None):
    models = (provenance or {}).get('models', {})
    if not isinstance(models, dict):
        models = {}
    people = [{'id':p['id'], 'name':p['name'], 'style':p.get('style',''), 'seat':i+1,
               **model_label(models.get(p['id']))} for i,p in enumerate(public['players'])]
    events = []
    public_details = {'round','count','voter_ids','player_ids','automatic','choice','candidate_ids'}
    for event in public['events']:
        if event['kind'] in ('rules','notice'):
            continue
        events.append({key:event.get(key) for key in
                       ('id','day','phase','kind','speaker_id','text','reply_to','target_id')} |
                      {'details':{key:value for key,value in event.get('details',{}).items() if key in public_details}})
    data = {'players':people, 'events':events,
            'rules':next((e['text'] for e in public['events'] if e['kind']=='rules'),'')}
    encoded = json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template = (Path(__file__).parent/'templates/table.html').read_text()
    return template.replace('__MAFIA_DATA__', encoded)
