"""
Structured output support for ragleap-rag - validates model responses
against a user-supplied JSON schema. Uses the `jsonschema` library if
the [structured] extra is installed for real schema validation;
otherwise falls back to a basic top-level type check only, and flags
that limitation explicitly rather than pretending full validation ran.
"""
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def parse_and_validate(raw_text: str, schema: Dict) -> Tuple[Optional[Any], bool, str]:
    """
    Parse raw_text as JSON and validate against schema. Never raises -
    a malformed response results in (None, False, method).

    Returns (parsed_object_or_None, is_valid, validation_method), where
    validation_method is "jsonschema" (real validation ran) or
    "basic_type_check_only" (jsonschema not installed - only the
    top-level type was checked, nested structure was NOT verified).
    """
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return None, False, ("jsonschema" if HAS_JSONSCHEMA else "basic_type_check_only")

    if HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=parsed, schema=schema)
            return parsed, True, "jsonschema"
        except jsonschema.ValidationError as e:
            logger.warning(f"Structured output failed schema validation: {e.message}")
            return parsed, False, "jsonschema"
        except jsonschema.SchemaError as e:
            logger.error(f"Invalid JSON schema passed to response_format=: {e.message}")
            return parsed, False, "jsonschema"
    else:
        expected_type = schema.get("type")
        type_map = {"object": dict, "array": list, "string": str, "number": (int, float), "boolean": bool}
        is_valid = isinstance(parsed, type_map[expected_type]) if expected_type in type_map else True
        return parsed, is_valid, "basic_type_check_only"


def parse_and_validate_object(obj: Any, schema: Dict) -> Tuple[Any, bool, str]:
    """
    Same as parse_and_validate(), but for providers (Anthropic tool-use)
    that hand back an already-parsed object instead of a raw JSON string.
    """
    if HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=obj, schema=schema)
            return obj, True, "jsonschema"
        except jsonschema.ValidationError as e:
            logger.warning(f"Structured output failed schema validation: {e.message}")
            return obj, False, "jsonschema"
        except jsonschema.SchemaError as e:
            logger.error(f"Invalid JSON schema passed to response_format=: {e.message}")
            return obj, False, "jsonschema"
    else:
        expected_type = schema.get("type")
        type_map = {"object": dict, "array": list, "string": str, "number": (int, float), "boolean": bool}
        is_valid = isinstance(obj, type_map[expected_type]) if expected_type in type_map else True
        return obj, is_valid, "basic_type_check_only"
