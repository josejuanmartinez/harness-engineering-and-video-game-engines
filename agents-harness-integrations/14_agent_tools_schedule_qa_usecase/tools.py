import inspect
import re
from pathlib import Path

from anthropic.types import ToolParam
from anthropic.types.tool_param import InputSchema
from pydantic import TypeAdapter
from type_definitions.data_types import Crash

# Every path the model passes is resolved relative to ROOT and must stay inside it.
ROOT = (Path(__file__).parent / "data").resolve()
MAX_GREP_RESULTS = 100
MAX_LINES = 200


def _safe_path(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"Path '{path}' is outside the allowed directory.")
    return resolved


def list_files(folder: str) -> list[str]:
    """List all the files in a folder, including those in its subfolders.

    Args:
        folder: Folder path relative to the project root, e.g. "src" or "crashes".

    Returns:
        Sorted list of file paths relative to the project root, e.g. ["src/audio/AudioMixer.cpp", ...].

    Raises:
        ValueError: If the folder is outside the project root or is not a directory.
    """
    base = _safe_path(folder)
    if not base.is_dir():
        raise ValueError(f"'{folder}' is not a directory.")
    return sorted(p.relative_to(ROOT).as_posix() for p in base.rglob("*") if p.is_file())


def show_lines_in_file(file: str, line_from: str|int, line_to: str|int) -> list[str]:
    """Return a range of lines of a file, from line_from to line_to, both included.

    Requires:
        Call list_files OR safe_grep first, to find the file path (and, with safe_grep, the line numbers).

    Args:
        file: File path relative to the project root, e.g. "src/audio/AudioMixer.cpp".
        line_from: First line to return (1-based).
        line_to: Last line to return (1-based, inclusive). At most 200 lines are returned per call.

    Returns:
        List of lines, each prefixed with its line number, e.g. ["10: Voice& v = voices_[activeVoices_++];"].

    Raises:
        ValueError: If the file is outside the project root, does not exist, or the range is invalid.
    """
    path = _safe_path(file)
    if not path.is_file():
        raise ValueError(f"'{file}' is not a file.")
    if type(line_from) == str:
        line_from = int(line_from)
    if type(line_to) == str:
            line_to = int(line_to)
    if line_from < 1 or line_to < line_from:
        raise ValueError(f"Invalid line range {line_from}-{line_to}.")
    line_to = min(line_to, line_from + MAX_LINES - 1)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [f"{n}: {lines[n - 1]}" for n in range(line_from, min(line_to, len(lines)) + 1)]


def safe_grep(path: str, pattern: str) -> list[str]:
    """Search a file, or every file in a folder and its subfolders, for a regular expression.

    Args:
        path: File or folder path relative to the project root, e.g. "src".
        pattern: Python regular expression to search for, e.g. "playSound".

    Returns:
        List of matches as "path:line: text", e.g. ["src/audio/AudioMixer.cpp:8: void AudioMixer::playSound(...) {"].
        At most 100 matches are returned.

    Raises:
        ValueError: If the path is outside the project root or the pattern is not a valid regex.
    """
    # "Safe": pure Python regex, no shell, confined to ROOT, capped output.
    base = _safe_path(path)
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")
    files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
    matches = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{f.relative_to(ROOT).as_posix()}:{n}: {line.strip()}")
                if len(matches) >= MAX_GREP_RESULTS:
                    return matches + [f"... truncated at {MAX_GREP_RESULTS} results"]
    return matches


def find_folder_with_crashes() -> str:
    """Find the folder that holds the previous crash dumps.

    Requires:
        Call list_files OR safe_grep first.

    Returns:
        Folder path relative to the project root, e.g. "crashes".

    Raises:
        ValueError: If no folder with crash dumps is found.
    """
    # A crash folder is one containing JSON files that parse as Crash; pick the one with the most.
    counts: dict[Path, int] = {}
    for p in ROOT.rglob("*.json"):
        try:
            Crash.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        counts[p.parent] = counts.get(p.parent, 0) + 1
    if not counts:
        raise ValueError("No folder with crash dumps found.")
    return max(counts, key=counts.get).relative_to(ROOT).as_posix()


def count_duplicates(error: Crash, folder: str) -> int:
    """Count how many previous crash dumps are duplicates of a crash. Use it to judge how frequent a crash is.

    A duplicate has the same file and the same stack trace; the assigned team is ignored.

    Requires:
        Call find_folder_with_crashes first, to get the folder argument.

    Args:
        error: The crash to look for.
        folder: Folder with the previous crash dumps, as returned by find_folder_with_crashes.

    Returns:
        Number of duplicates found in the folder.

    Raises:
        ValueError: If the folder is outside the project root.
    """
    # Duplicate = same crash location and same stack trace (team is ignored).
    count = 0
    for p in _safe_path(folder).glob("*.json"):
        try:
            other = Crash.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue  # skip malformed dumps
        if other.file == error.file and other.stacktrace == error.stacktrace:
            count += 1
    return count


def calculate_priority(duplicates: int) -> int:
    """Calculate the priority of a crash, from 1 (lowest) to 10 (highest), based on how often it happened before.

    Requires:
        Call count_duplicates first, to get the duplicates argument.

    Args:
        duplicates: Number of previous duplicates of the crash, as returned by count_duplicates.

    Returns:
        Priority from 1 to 10: 1 for a new crash, +2 per duplicate, capped at 10.

    Raises:
        ValueError: If duplicates is negative.
    """
    if duplicates < 0:
        raise ValueError(f"Invalid duplicates count {duplicates}.")
    return min(10, 1 + 2 * duplicates)


def find_owner(error: Crash, folder: str) -> str:
    """Find the team that owns a crash, from the teams assigned to previous crashes in the same source file.

    Requires:
        Call find_folder_with_crashes first, to get the folder argument.

    Args:
        error: The crash to find the owner of.
        folder: Folder with the previous crash dumps, as returned by find_folder_with_crashes.

    Returns:
        Team name assigned most often to previous crashes in the same file (line number ignored), e.g. "Audio".

    Raises:
        ValueError: If the folder is outside the project root, or no previous crash in that file has a team.
    """
    # Same file = crash location without the ":line" suffix; dumps with no team ("None") don't vote.
    source_file = error.file.rsplit(":", 1)[0]
    votes: dict[str, int] = {}
    for p in _safe_path(folder).glob("*.json"):
        try:
            other = Crash.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue  # skip malformed dumps
        if other.file.rsplit(":", 1)[0] == source_file and other.assigned_team != "None":
            votes[other.assigned_team] = votes.get(other.assigned_team, 0) + 1
    if not votes:
        raise ValueError(f"No previous crash with a team found for '{source_file}'.")
    return max(votes, key=votes.get)


def _get_input_schema(fn) -> InputSchema:
    """Build the JSON input schema of a function from its type-annotated parameters.

    Args:
        fn: The function to describe.

    Returns:
        JSON schema object with one property per parameter. Parameters without a default are required.

    Raises:
        TypeError: If a parameter has no type annotation.
    """
    properties = {}
    required = []
    for name, param in inspect.signature(fn).parameters.items():
        if param.annotation is inspect.Parameter.empty:
            raise TypeError(f"Parameter '{name}' of {fn.__name__} has no type annotation.")
        # TypeAdapter turns any annotation (str, int, list[str], a BaseModel, ...) into JSON schema
        properties[name] = TypeAdapter(param.annotation).json_schema()
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

TOOLS = [list_files, show_lines_in_file, safe_grep, find_folder_with_crashes, count_duplicates,
         calculate_priority, find_owner]
tool_definitions = [
    ToolParam(input_schema=_get_input_schema(x), name=x.__name__, description=inspect.getdoc(x) or "", type="custom")
    for x in TOOLS
]
TOOLS_BY_NAME = {fn.__name__: fn for fn in TOOLS}

