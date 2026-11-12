"""Партия на YandexGPT с отдельными игроками Gemini и одним опциональным GGUF."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from app.llm import YandexGPTModel
from app.mafia.llm import LlamaCppModel
from app.mafia.gemini import GeminiModel
from app.mafia.providers import player_models
from app.mafia.credentials import read_credential
from app.mafia.models import Config
from app.mafia.agent import ModelPlayer
from app.mafia.engine import Game
from app.mafia.story import StoryDirector
from app.mafia.output import Writer

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',type=Path,default=Path('.env'))
    p.add_argument('--seed',type=int,default=17)
    p.add_argument('--max-days',type=int,default=30)
    p.add_argument('--local-player',choices=[f'p{i}' for i in range(1,11)],default='p5')
    p.add_argument('--local-url',help='OpenAI-compatible /v1 endpoint, доступный отсюда')
    p.add_argument('--local-model',default='local')
    p.add_argument('--gemini-players', nargs='*', choices=[f'p{i}' for i in range(1,11)], default=[])
    p.add_argument('--gemini-model',default='gemini-3.5-flash-lite')
    p.add_argument('--no-story',action='store_true',help='Отключить сценариста и рассказчика')
    p.add_argument('--no-archive-review',action='store_true',help='Отключить задания на проверку старых выставлений')
    p.add_argument('--output-dir',type=Path)
    args = p.parse_args()
    config = Config(seed=args.seed,max_days=args.max_days,archive_review=not args.no_archive_review)
    key = read_credential('YANDEX_API_KEY', args.env_file)
    folder = read_credential('YANDEX_FOLDER_ID', args.env_file)
    model = YandexGPTModel('yandexgpt/latest',folder,key,timeout=60,max_output_tokens=1800,temperature=.5,max_retries=2)
    local = LlamaCppModel(args.local_model,args.local_url,options={'max_tokens':512,'temperature':.5}) if args.local_url else None
    gemini = GeminiModel(args.gemini_model, read_credential('GOOGLE_API_KEY', args.env_file), max_retries=5) if args.gemini_players else None
    models = player_models(model, gemini=gemini, gemini_ids=args.gemini_players, local=local, local_id=args.local_player)
    directory = args.output_dir or Path('runs')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-mafia-'+uuid4().hex[:6])
    writer = Writer(directory,Path(__file__).resolve().parents[1]/'assets/chat.html')
    writer.player_models = {pid:getattr(backend,'model',backend.name) for pid,backend in models.items()}
    print('Результаты:',directory.resolve(),flush=True)
    agents = {pid:ModelPlayer(backend,writer.journal,config.attempts) for pid,backend in models.items()}
    director = None if args.no_story else StoryDirector(model,writer.journal,config.attempts)
    game = Game(config,agents,writer,director=director)
    try:
        game.run()
    except (Exception,KeyboardInterrupt):
        print('Партия прервана. Приватная ошибка и частичный публичный результат сохранены.',flush=True)
        return 1
    print((directory/'summary.json').read_text(),flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
