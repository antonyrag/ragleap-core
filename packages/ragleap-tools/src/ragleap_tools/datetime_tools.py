"""
ragleap_tools.datetime_tools

Current time and date-math tools. No real security surface - pure
computation on caller-supplied strings/numbers, no filesystem or
network access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ragleap_tools.base import Tool, ToolResult


def get_current_datetime(tz_offset_hours: float = 0.0) -> ToolResult:
    try:
        tz = timezone(timedelta(hours=tz_offset_hours))
        now = datetime.now(tz)
        return ToolResult(success=True, result=now.isoformat())
    except (ValueError, OverflowError) as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def add_to_date(iso_datetime: str, days: int = 0, hours: int = 0, minutes: int = 0) -> ToolResult:
    try:
        dt = datetime.fromisoformat(iso_datetime)
        result = dt + timedelta(days=days, hours=hours, minutes=minutes)
        return ToolResult(success=True, result=result.isoformat())
    except (ValueError, OverflowError) as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def date_difference(iso_datetime_a: str, iso_datetime_b: str) -> ToolResult:
    try:
        a = datetime.fromisoformat(iso_datetime_a)
        b = datetime.fromisoformat(iso_datetime_b)
        delta = a - b
        return ToolResult(success=True, result={
            "total_seconds": delta.total_seconds(),
            "days": delta.days,
        })
    except (ValueError, OverflowError) as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


CURRENT_DATETIME_TOOL = Tool(
    name="get_current_datetime",
    description="Get the current date and time, optionally in a given UTC offset.",
    parameters={
        "type": "object",
        "properties": {
            "tz_offset_hours": {"type": "number", "description": "UTC offset in hours, e.g. -5 or 5.5. Defaults to 0 (UTC)."},
        },
        "required": [],
    },
    handler=get_current_datetime,
)

ADD_TO_DATE_TOOL = Tool(
    name="add_to_date",
    description="Add (or subtract, with negative values) days/hours/minutes to an ISO 8601 datetime.",
    parameters={
        "type": "object",
        "properties": {
            "iso_datetime": {"type": "string", "description": "ISO 8601 datetime, e.g. '2026-09-14T12:00:00'."},
            "days": {"type": "integer", "description": "Days to add (negative to subtract)."},
            "hours": {"type": "integer", "description": "Hours to add (negative to subtract)."},
            "minutes": {"type": "integer", "description": "Minutes to add (negative to subtract)."},
        },
        "required": ["iso_datetime"],
    },
    handler=add_to_date,
)

DATE_DIFFERENCE_TOOL = Tool(
    name="date_difference",
    description="Compute the difference between two ISO 8601 datetimes (a - b).",
    parameters={
        "type": "object",
        "properties": {
            "iso_datetime_a": {"type": "string", "description": "First ISO 8601 datetime."},
            "iso_datetime_b": {"type": "string", "description": "Second ISO 8601 datetime."},
        },
        "required": ["iso_datetime_a", "iso_datetime_b"],
    },
    handler=date_difference,
)
