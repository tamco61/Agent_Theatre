"""Одинаковые имена параметров для окружения, локального .env и Kaggle Secrets."""
import os
from pathlib import Path

ALIASES = {'YANDEX_API_KEY':('api_key',), 'YANDEX_FOLDER_ID':('folder_id',),
           'GOOGLE_API_KEY':('GEMINI_API_KEY', 'google_api_key')}


def read_credential(name, env_file=None):
    names = (name,) + ALIASES.get(name, ())
    for label in names:
        if os.environ.get(label, '').strip():
            return os.environ[label].strip()
    if env_file and Path(env_file).is_file():
        values = {}
        for line in Path(env_file).read_text().splitlines():
            line = line.strip().removeprefix('export ')
            if line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() in names:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                values[key.strip()] = value
        for label in names:
            if values.get(label, '').strip():
                return values[label].strip()
    try:
        from kaggle_secrets import UserSecretsClient
        secrets = UserSecretsClient()
    except Exception:
        secrets = None
    if secrets:
        for label in names:
            try:
                value = secrets.get_secret(label)
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise ValueError('Не найден параметр доступа: ' + ' / '.join(names))
