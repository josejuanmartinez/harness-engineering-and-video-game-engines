from anthropic import beta_tool


@beta_tool
def add(a: float, b: float) -> str:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)


@beta_tool
def multiply(a: float, b: float) -> str:
    """Multiply two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a * b)


@beta_tool
def percentage(value: float, percent: float) -> str:
    """Compute `percent`% of `value`, e.g. percentage(200, 15) -> 30.

    Args:
        value: The base number.
        percent: The percentage to take (0-100).
    """
    return str(value * percent / 100)


TOOLS = [add, multiply, percentage]
