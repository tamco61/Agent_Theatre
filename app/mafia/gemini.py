"""Gemini generateContent: тот же интерфейс решений, без отдельного SDK."""
from dataclasses import dataclass, field
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.llm import Completion


@dataclass
class GeminiModel:
    model: str
    api_key: str = field(repr=False)
    timeout: float = 60
    max_output_tokens: int = 1800
    temperature: float = 0.5
    max_retries: int = 2

    def __post_init__(self):
        self.model = self.model.removeprefix('models/')
        if not re.fullmatch(r'[a-zA-Z0-9._-]+', self.model) or not self.api_key.strip():
            raise ValueError('Нужны идентификатор Gemini и API-ключ')
        if self.timeout <= 0 or self.max_output_tokens < 1 or type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError('Неверные лимиты Gemini')

    @property
    def name(self):
        return 'google/' + self.model

    def complete(self, messages):
        return self._request(messages)

    def complete_json(self, messages, schema, name):
        return self._request(messages, schema)

    def _request(self, messages, schema=None):
        contents, system = [], []
        for message in messages:
            role, text = message['role'], message['content']
            if not isinstance(text, str):
                raise ValueError('Gemini: сообщения должны быть текстовыми')
            if role == 'system':
                system.append(text)
            elif role in ('user', 'assistant'):
                contents.append({'role':'model' if role == 'assistant' else 'user', 'parts':[{'text':text}]})
            else:
                raise ValueError('Gemini: неподдерживаемая роль сообщения')
        config = {'temperature':self.temperature, 'maxOutputTokens':self.max_output_tokens}
        if schema is not None:
            config.update(responseMimeType='application/json', responseJsonSchema=schema)
        payload = {'contents':contents, 'generationConfig':config}
        if system:
            payload['systemInstruction'] = {'parts':[{'text':'\n'.join(system)}]}
        request = Request('https://generativelanguage.googleapis.com/v1beta/models/' + self.model + ':generateContent',
                          data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={'Content-Type':'application/json', 'x-goog-api-key':self.api_key}, method='POST')
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = json.load(response)
                break
            except HTTPError as exc:
                status = exc.code
                try:
                    delay = float(exc.headers.get('Retry-After', 2 ** (attempt + 1)))
                except (TypeError, ValueError):
                    delay = 2 ** (attempt + 1)
                exc.close()
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(max(0, min(delay, 30)))
                    continue
                # Тело HTTP-ошибки и заголовки не переносятся в игровой журнал.
                if status in (500, 502, 503, 504):
                    raise RuntimeError(f'Gemini API: HTTP {status}; сервис временно недоступен после {attempt+1} попыток; состояние партии сохранено') from None
                raise RuntimeError(f'Gemini API: HTTP {status}; проверьте доступ, модель и квоты') from None
            except (URLError, TimeoutError):
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt + 1), 30))
                    continue
                raise RuntimeError('Gemini API недоступен или превышено время ожидания') from None
        try:
            candidate = body['candidates'][0]
            if candidate.get('finishReason') != 'STOP':
                raise RuntimeError('Gemini не завершила ответ: проверьте лимит токенов и ограничения модели')
            text = ''.join(part.get('text', '') for part in candidate['content']['parts'] if not part.get('thought'))
            if not text.strip():
                raise ValueError('empty content')
            usage = body.get('usageMetadata', {})
            return Completion(text, {
                'input_tokens':usage.get('promptTokenCount', 0),
                'output_tokens':usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0),
                'total_tokens':usage.get('totalTokenCount', 0),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError('Gemini вернула ответ без завершённого текста') from None
