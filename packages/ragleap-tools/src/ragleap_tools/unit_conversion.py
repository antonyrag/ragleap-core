"""
ragleap_tools.unit_conversion

Common unit conversions (length, weight, temperature). No security
surface - pure arithmetic on a fixed, hardcoded conversion table plus
one explicit temperature formula set. No eval, no dynamic code.
"""

from __future__ import annotations

from typing import Dict

from ragleap_tools.base import Tool, ToolResult

# All factors convert TO the base unit for that category.
_LENGTH_TO_METERS: Dict[str, float] = {
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
}

_WEIGHT_TO_GRAMS: Dict[str, float] = {
    "mg": 0.001, "g": 1.0, "kg": 1000.0,
    "oz": 28.349523125, "lb": 453.59237,
}


def convert_length(value: float, from_unit: str, to_unit: str) -> ToolResult:
    if from_unit not in _LENGTH_TO_METERS or to_unit not in _LENGTH_TO_METERS:
        return ToolResult(success=False, error=f"Unknown length unit. Supported: {sorted(_LENGTH_TO_METERS)}")
    meters = value * _LENGTH_TO_METERS[from_unit]
    return ToolResult(success=True, result=meters / _LENGTH_TO_METERS[to_unit])


def convert_weight(value: float, from_unit: str, to_unit: str) -> ToolResult:
    if from_unit not in _WEIGHT_TO_GRAMS or to_unit not in _WEIGHT_TO_GRAMS:
        return ToolResult(success=False, error=f"Unknown weight unit. Supported: {sorted(_WEIGHT_TO_GRAMS)}")
    grams = value * _WEIGHT_TO_GRAMS[from_unit]
    return ToolResult(success=True, result=grams / _WEIGHT_TO_GRAMS[to_unit])


def convert_temperature(value: float, from_unit: str, to_unit: str) -> ToolResult:
    units = {"c", "f", "k"}
    from_unit, to_unit = from_unit.lower(), to_unit.lower()
    if from_unit not in units or to_unit not in units:
        return ToolResult(success=False, error="Unknown temperature unit. Supported: c, f, k")
    if from_unit == "c":
        celsius = value
    elif from_unit == "f":
        celsius = (value - 32) * 5 / 9
    else:
        celsius = value - 273.15
    if to_unit == "c":
        result = celsius
    elif to_unit == "f":
        result = celsius * 9 / 5 + 32
    else:
        result = celsius + 273.15
        if result < 0:
            return ToolResult(success=False, error="Result below absolute zero - invalid input")
    return ToolResult(success=True, result=result)


CONVERT_LENGTH_TOOL = Tool(
    name="convert_length",
    description="Convert a length value between units (mm, cm, m, km, in, ft, yd, mi).",
    parameters={
        "type": "object",
        "properties": {
            "value": {"type": "number"},
            "from_unit": {"type": "string", "enum": sorted(_LENGTH_TO_METERS)},
            "to_unit": {"type": "string", "enum": sorted(_LENGTH_TO_METERS)},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
    handler=convert_length,
)

CONVERT_WEIGHT_TOOL = Tool(
    name="convert_weight",
    description="Convert a weight value between units (mg, g, kg, oz, lb).",
    parameters={
        "type": "object",
        "properties": {
            "value": {"type": "number"},
            "from_unit": {"type": "string", "enum": sorted(_WEIGHT_TO_GRAMS)},
            "to_unit": {"type": "string", "enum": sorted(_WEIGHT_TO_GRAMS)},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
    handler=convert_weight,
)

CONVERT_TEMPERATURE_TOOL = Tool(
    name="convert_temperature",
    description="Convert a temperature value between Celsius (c), Fahrenheit (f), and Kelvin (k).",
    parameters={
        "type": "object",
        "properties": {
            "value": {"type": "number"},
            "from_unit": {"type": "string", "enum": ["c", "f", "k"]},
            "to_unit": {"type": "string", "enum": ["c", "f", "k"]},
        },
        "required": ["value", "from_unit", "to_unit"],
    },
    handler=convert_temperature,
)
