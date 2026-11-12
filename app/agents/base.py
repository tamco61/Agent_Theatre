"""Общий цикл запроса JSON, проверки и ограниченного исправления ответа."""

import json
from typing import Callable, TypeVar

from app.journal import EventJournal
from app.llm import ChatModel
from app.serialization import parse_response, schema_for

T = TypeVar("T")


class JsonAgent:
    def __init__(self, role: str, model: ChatModel, journal: EventJournal, attempts: int = 3):
        self.role = role
        self.model = model
        self.journal = journal
        self.attempts = attempts

    def ask(self, output_type: type[T], instruction: str, context: dict,
            validate: Callable[[T], None] | None = None, *, scene_id=None, character_id=None,
            schema_override: dict | None = None) -> T:
        schema = schema_for(output_type) if schema_override is None else schema_override
        complete_json = getattr(self.model, "complete_json", None)
        structured = callable(complete_json)
        system = instruction if structured else instruction + "\nВерни только JSON по этой схеме:\n" + json.dumps(schema, ensure_ascii=False)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, separators=(",", ":"))},
        ]
        base_messages = list(messages)
        metadata = {"scene_id": scene_id, "character_id": character_id}
        last_error = None
        for attempt in range(1, self.attempts + 1):
            self.journal.emit("llm_request", {
                "agent": self.role, "model": self.model.name, "attempt": attempt, "messages": messages,
                "response_type": output_type.__name__, "schema": schema,
            }, **metadata)
            try:
                if structured:
                    reply = complete_json(messages, schema, output_type.__name__)
                else:
                    reply = self.model.complete(messages)
            except Exception as exc:
                self.journal.emit("llm_error", {"agent": self.role, "error": str(exc)}, **metadata)
                raise
            self.journal.emit("llm_response", {
                "agent": self.role, "model": self.model.name, "text": reply.text, "usage": reply.usage,
            }, **metadata)
            try:
                result = parse_response(reply.text, output_type)
                if validate:
                    validate(result)
                return result
            except ValueError as exc:
                last_error = exc
                self.journal.emit("validation_error", {"agent": self.role, "error": str(exc)}, **metadata)
                messages = base_messages + [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"Исправь ответ. Ошибка: {exc}. Верни полный JSON заново."},
                ]
        raise ValueError(f"{self.role}: невалидный ответ после {self.attempts} попыток: {last_error}")
