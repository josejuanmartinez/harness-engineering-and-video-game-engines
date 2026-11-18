from anthropic import beta_tool


@beta_tool
def count_words(text: str) -> str:
    """Count the words in a text (split on whitespace).

    Args:
        text: The text to count.
    """
    return str(len(text.split()))


@beta_tool
def reverse(text: str) -> str:
    """Reverse a string character by character.

    Args:
        text: The text to reverse.
    """
    return text[::-1]


@beta_tool
def to_upper(text: str) -> str:
    """Convert a text to upper case.

    Args:
        text: The text to convert.
    """
    return text.upper()


TOOLS = [count_words, reverse, to_upper]
