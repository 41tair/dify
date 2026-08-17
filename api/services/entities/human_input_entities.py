"""Shared human-input data transformations."""

import json


def stringify_form_default_values(values: dict[str, object]) -> dict[str, str]:
    """Serialize default values into strings expected by human-input form clients."""
    result: dict[str, str] = {}
    for key, value in values.items():
        match value:
            case None:
                result[key] = ""
            case dict() | list():
                result[key] = json.dumps(value, ensure_ascii=False)
            case _:
                result[key] = str(value)
    return result
