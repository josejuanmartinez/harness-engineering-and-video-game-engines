from datetime import date, datetime

from anthropic import beta_tool


@beta_tool
def now() -> str:
    """Return the current local date and time in ISO format."""
    return datetime.now().isoformat(timespec="seconds")


@beta_tool
def days_between(start: str, end: str) -> str:
    """Number of days from start to end (negative if end is before start).

    Args:
        start: Date in YYYY-MM-DD format.
        end: Date in YYYY-MM-DD format.
    """
    return str((date.fromisoformat(end) - date.fromisoformat(start)).days)


@beta_tool
def weekday(day: str) -> str:
    """Weekday name of a date, e.g. "Monday".

    Args:
        day: Date in YYYY-MM-DD format.
    """
    return date.fromisoformat(day).strftime("%A")


TOOLS = [now, days_between, weekday]
