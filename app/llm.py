"""Сменный интерфейс LLM: Chat Completions и YandexGPT через Responses SDK."""

import json
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .deadline import with_deadline


@dataclass
class Completion:
    text: str
    usage: dict = field(default_factory=dict)


class ChatModel(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, messages: list[dict[str, str]]) -> Completion: ...


@dataclass
class YandexGPTModel:
    """Подключение текстовой модели как в Agent_Artist; SDK загружается при вызове."""

    model: str
    project: str
    api_key: str = field(repr=False)
    max_output_tokens: int = 3000
    temperature: float = 0.2
    timeout: float = 180
    max_retries: int = 0
    _client: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.model, self.project, self.api_key)):
            raise ValueError("Нужны модель, идентификатор каталога и API-ключ Yandex")
        if self.max_output_tokens < 1 or self.timeout <= 0:
            raise ValueError("Лимит токенов и timeout должны быть положительными")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries должен быть неотрицательным целым")

    @property
    def name(self) -> str:
        return self.model if self.model.startswith("gpt://") else f"gpt://{self.project}/{self.model}"

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise RuntimeError("Установите зависимости: python3 -m pip install -r requirements.txt") from None
            self._client = OpenAI(
                api_key=self.api_key, project=self.project,
                base_url="https://ai.api.cloud.yandex.net/v1", timeout=self.timeout, max_retries=self.max_retries,
            )
        return self._client

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        return self._request(messages)

    def complete_json(self, messages: list[dict[str, str]], schema: dict, name: str) -> Completion:
        return self._request(messages, {
            "type": "json_schema", "name": name, "schema": schema, "strict": True,
        })

    def _request(self, messages: list[dict[str, str]], text_format: dict | None = None) -> Completion:
        client = self._get_client()
        options = {"text": {"format": text_format}} if text_format else {}
        try:
            response = with_deadline(lambda: client.responses.create(
                model=self.name, input=messages, temperature=self.temperature,
                max_output_tokens=self.max_output_tokens, **options,
            ), self.timeout * (self.max_retries + 1) + 2 * self.max_retries)
        except Exception as exc:
            # Не переносим потенциально чувствительное тело ошибки SDK в журнал.
            status = getattr(exc, "status_code", None)
            code = f"HTTP {status}" if type(status) is int else type(exc).__name__
            raise RuntimeError(f"Yandex AI Studio: {code}; проверьте доступ и настройки") from None
        if response.status == "incomplete":
            raise RuntimeError("Ответ YandexGPT обрезан: увеличьте max_output_tokens")
        if response.status != "completed":
            raise RuntimeError("YandexGPT не завершил генерацию ответа")
        if not isinstance(response.output_text, str) or not response.output_text.strip():
            raise RuntimeError("YandexGPT вернул пустой текст ответа")
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        return Completion(response.output_text, usage)


@dataclass
class ChatCompletionsModel:
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key: str = field(default="", repr=False)
    timeout: float = 120
    # Например, max_completion_tokens для OpenAI или max_tokens для локального сервера.
    options: dict = field(default_factory=dict)
    # Аналог project в OpenAI SDK, нужен в том числе для Yandex AI Studio.
    project: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Укажите идентификатор модели")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("base_url должен быть HTTP(S)-адресом API")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Передавайте ключ через api_key, а не через URL")
        if self.timeout <= 0:
            raise ValueError("timeout должен быть положительным")
        if {"model", "messages", "stream"} & self.options.keys():
            raise ValueError("options не должен переопределять model, messages или stream")

    @property
    def name(self) -> str:
        return self.model

    def complete(self, messages: list[dict[str, str]]) -> Completion:
        payload = {"model": self.model, "messages": messages, **self.options}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.project:
            headers["OpenAI-Project"] = self.project
        request = Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except HTTPError as exc:
            # Не сохраняем заголовки авторизации или потенциально чувствительное тело ошибки.
            raise RuntimeError(f"LLM API: HTTP {exc.code}; проверьте endpoint, модель и ключ") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("LLM API недоступен или превышено время ожидания") from exc
        try:
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise RuntimeError("Ответ LLM обрезан: увеличьте лимит выходных токенов")
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty content")
            return Completion(text=text, usage=body.get("usage", {}))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("LLM API вернул ответ без текстового choices[0].message.content") from exc
