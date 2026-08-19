"""Artifact validation against the JSON Schemas in ``schemas/``.

Per spec §6.4: when ``jsonschema`` is importable the schemas are
enforced with it; otherwise a built-in structural validator covers the
subset this project's schemas actually use — ``type`` (including type
lists), ``required``, ``properties``, ``items``, ``enum``, and
``additionalProperties`` given as a schema.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


class SchemaError(Exception):
    pass


def load_schema(kind: str) -> dict:
    path = SCHEMAS_DIR / f"{kind}.schema.json"
    if not path.is_file():
        raise SchemaError(f"unknown schema kind {kind!r} (no {path.name})")
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(type_name: str, data) -> bool:
    if type_name == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    expected = _TYPE_MAP.get(type_name)
    if expected is None:
        return True
    if type_name == "number":
        return isinstance(data, expected) and not isinstance(data, bool)
    if type_name == "boolean":
        return isinstance(data, bool)
    return isinstance(data, expected)


def _check(schema: dict, data, path: str, errors: list[str]) -> None:
    declared = schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        if not any(_type_ok(t, data) for t in types):
            errors.append(
                f"{path}: expected {' or '.join(types)}, "
                f"got {type(data).__name__}"
            )
            return

    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} is not one of {schema['enum']}")

    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required key {key!r}")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in data:
                _check(sub_schema, data[key], f"{path}.{key}", errors)
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, value in data.items():
                if key not in properties:
                    _check(additional, value, f"{path}.{key}", errors)

    if isinstance(data, list) and "items" in schema:
        for index, item in enumerate(data):
            _check(schema["items"], item, f"{path}[{index}]", errors)


def validate(kind: str, data) -> list[str]:
    """Return a list of error strings; empty means valid."""
    schema = load_schema(kind)
    try:
        import jsonschema
    except ImportError:
        errors: list[str] = []
        _check(schema, data, "$", errors)
        return errors
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"$.{'.'.join(str(p) for p in error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(data)
    ]
