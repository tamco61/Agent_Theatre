"""JSON-схемы и строгая сборка dataclasses из ответов LLM."""

import json
import types
from dataclasses import MISSING, fields, is_dataclass
from typing import Literal, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")


def schema_for(annotation: object) -> dict:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return {"anyOf": [schema_for(item) for item in args]}
    if origin is Literal:
        # Явный type необходим для строгого структурированного вывода модели.
        kinds = {type(value) for value in args}
        return {**(schema_for(type(args[0])) if len(kinds) == 1 else {}), "enum": list(args)}
    if is_dataclass(annotation):
        hints = get_type_hints(annotation)
        return {
            "type": "object",
            "properties": {f.name: schema_for(hints[f.name]) for f in fields(annotation)},
            "required": [f.name for f in fields(annotation)
                         if (f.default is MISSING and f.default_factory is MISSING)
                         or f.metadata.get("llm_required", False)],
            "additionalProperties": False,
        }
    if origin is list:
        return {"type": "array", "items": schema_for(args[0])}
    if origin is dict:
        return {"type": "object", "additionalProperties": schema_for(args[1])}
    return {"type": {str: "string", int: "integer", float: "number",
                     bool: "boolean", type(None): "null"}[annotation]}


def decode(annotation: type[T], value: object, path: str = "response") -> T:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for variant in args:
            try:
                return decode(variant, value, path)
            except ValueError:
                pass
        raise ValueError(f"{path}: значение не соответствует ни одному допустимому типу")
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in args):
            raise ValueError(f"{path}: ожидается одно из {args}")
        return value
    if is_dataclass(annotation):
        if not isinstance(value, dict):
            raise ValueError(f"{path}: ожидается объект")
        hints = get_type_hints(annotation)
        unknown = set(value) - set(hints)
        if unknown:
            raise ValueError(f"{path}: неизвестные поля {sorted(unknown)}")
        result = {}
        for item in fields(annotation):
            if item.name in value:
                result[item.name] = decode(hints[item.name], value[item.name], f"{path}.{item.name}")
            elif item.default is MISSING and item.default_factory is MISSING:
                raise ValueError(f"{path}: отсутствует поле {item.name}")
        return annotation(**result)
    if origin is list:
        if not isinstance(value, list):
            raise ValueError(f"{path}: ожидается список")
        return [decode(args[0], item, f"{path}[{i}]") for i, item in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: ожидается словарь")
        return {decode(args[0], key, path): decode(args[1], item, f"{path}.{key}")
                for key, item in value.items()}
    if type(value) is not annotation:
        raise ValueError(f"{path}: ожидается {annotation.__name__}")
    return value


def parse_response(text: str, output_type: type[T]) -> T:
    # Некоторые локальные модели оборачивают JSON в Markdown.
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        if "\n" not in text:
            raise ValueError("После открывающей Markdown-ограды ожидается перенос строки")
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return decode(output_type, json.loads(text))
