"""
EXERCISE 06: MCP server for studio tools
Time: 35 min
Stack: MCP Python SDK (from mcp.server.fastmcp import FastMCP), MCP Inspector
Test with: npx @modelcontextprotocol/inspector python 06_mcp_server.py

TASK
Build an MCP server that simulates the studio tools over the data in
data/. No need to connect to a real Perforce or Jira.

SURFACE
- Tools: search_crashes(query), get_crash(id), get_owner(subsystem),
  create_ticket(title, body, owner) (simulated write)
- Resource: crash://{id}, to read a report as context
- Prompt: triage_crash(id), with the triage template

REQUIREMENTS
- stdio transport, then Streamable HTTP
- Tools return errors that are useful to the model, not Python tracebacks
- Never write logs to stdout with stdio: they break the protocol. Use stderr
- Mark which tools are read-only and which have side effects (annotations)
- create_ticket is idempotent: repeating the call doesn't create a duplicate
- Test it in MCP Inspector and connect it to Claude Code

TO GO FURTHER
- Authentication over HTTP: which identity does the tool use? The user's or the service's?
- Pagination of large results
- Try the API's MCP connector (mcp_servers and mcp_toolset) with the HTTP server

QUESTIONS YOU MAY BE ASKED
- What's the difference between tools, resources and prompts? Who controls each one?
- stdio or HTTP? When do you choose each one in a studio?
- When would you use MCP, and when a tool defined directly in your code?
- What are the risks of installing a third-party MCP server?
"""
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

# Logs ALWAYS go to stderr: with the stdio transport, stdout is the protocol channel.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mcpserver_crashes")

# Paths relative to the script, not to the directory it is launched from
# (Inspector and Claude Code may start it from another cwd).
DATA_DIR = Path(__file__).resolve().parent / "data"
CRASHES_FILE = DATA_DIR / "crash_reports.jsonl"
OWNERS_FILE = DATA_DIR / "owners.json"
TICKETS_FILE = DATA_DIR / "tickets.json"  # simulated "Jira"

Subsystem = Literal["unknown", "rendering", "animation", "physics", "audio", "online", "tools"]

mcp = MCPServer(
    name="mcpserver_crashes",
    title="MCP Server for Crashes",
    instructions=(
        "Tools to investigate game crash reports. Typical flow: search_crashes -> "
        "get_crash -> get_owner(subsystem) -> create_ticket(owner=team)."
    ),
)


# ---------- Models (they generate each tool's outputSchema) ----------

class CrashTriage(BaseModel):
    subsystem: Optional[Subsystem] = Field(None, description="Subsystem responsible for the crash")
    severity: Literal["low", "medium", "high", "critical"] = Field(..., description="Severity level of the crash")
    likely_cause: str = Field(..., description="Most probable cause of the crash")
    confidence: Optional[float] = Field(None, description="Confidence level of the triage")


class CrashReport(BaseModel):
    id: str = Field(..., description="Unique identifier for the crash report")
    build: str = Field(..., description="Build version of the software")
    platform: str = Field(..., description="Platform on which the crash occurred")
    signal: str = Field(..., description="Signal or exception that caused the crash")
    stack: list[str] = Field(..., description="Stack trace at the time of the crash")
    log: str = Field(..., description="Relevant log messages leading up to the crash")
    occurrences: int = Field(..., description="Number of times this crash has occurred")
    label: Optional[CrashTriage] = Field(None, description="Existing triage label, if any")


class CrashSummary(BaseModel):
    id: str
    build: str
    platform: str
    signal: str
    occurrences: int
    top_frame: str = Field(..., description="First frame of the stack trace")


class SearchResult(BaseModel):
    total: int = Field(..., description="Total number of matches")
    offset: int
    results: list[CrashSummary]
    next_offset: Optional[int] = Field(None, description="Pass as offset to get the next page; null if no more")


class Owner(BaseModel):
    subsystem: str
    team: str
    lead: str
    paths: list[str]


class Ticket(BaseModel):
    key: str = Field(..., description="Ticket key, e.g. CRASH-3f2a9c1b")
    title: str
    body: str
    owner: str
    created_at: str
    created: bool = Field(..., description="False if the ticket already existed (idempotent call)")


# ---------- Data access ----------

def _load_crashes() -> list[CrashReport]:
    try:
        with CRASHES_FILE.open(encoding="utf-8") as f:
            return [CrashReport.model_validate_json(line) for line in f if line.strip()]
    except FileNotFoundError:
        logger.error("Crash file not found: %s", CRASHES_FILE)
        raise ToolError("The crash database is not available right now. Try again later.")


def _load_owners() -> dict:
    try:
        return json.loads(OWNERS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("Owners file not found: %s", OWNERS_FILE)
        raise ToolError("The ownership registry is not available right now. Try again later.")


def _load_tickets() -> dict:
    if not TICKETS_FILE.exists():
        return {}
    return json.loads(TICKETS_FILE.read_text(encoding="utf-8"))


# ---------- Tools ----------

@mcp.tool(annotations=ToolAnnotations(
    title="Search crash reports", readOnlyHint=True, openWorldHint=False))
def search_crashes(
    query: Annotated[str, Field(description="Case-insensitive regex searched in signal, stack, log, platform and build, e.g. 'ACCESS_VIOLATION' or 'Engine/Physics/'")],
    limit: Annotated[int, Field(ge=1, le=50, description="Max results per page")] = 10,
    offset: Annotated[int, Field(ge=0, description="Number of results to skip (pagination)")] = 0,
) -> SearchResult:
    """Search crash reports with a regular expression. Returns short summaries
    sorted by occurrences (most frequent first); use get_crash(id) for the full report."""
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error as e:
        raise ToolError(f"Invalid regular expression '{query}': {e}. Escape special characters like ( ) [ ] . * with a backslash.")

    matches = [
        c for c in _load_crashes()
        if pattern.search(" ".join([c.id, c.build, c.platform, c.signal, c.log, *c.stack]))
    ]
    matches.sort(key=lambda c: c.occurrences, reverse=True)
    page = matches[offset:offset + limit]
    next_offset = offset + limit if offset + limit < len(matches) else None
    logger.info("search_crashes query=%r -> %d matches", query, len(matches))

    return SearchResult(
        total=len(matches),
        offset=offset,
        next_offset=next_offset,
        results=[
            CrashSummary(id=c.id, build=c.build, platform=c.platform, signal=c.signal,
                         occurrences=c.occurrences, top_frame=c.stack[0] if c.stack else "")
            for c in page
        ],
    )


@mcp.tool(annotations=ToolAnnotations(
    title="Get crash report", readOnlyHint=True, openWorldHint=False))
def get_crash(
    id: Annotated[str, Field(description="Crash report id, e.g. 'CR-1001'")],
) -> CrashReport:
    """Get the full crash report by id: build, platform, signal, stack trace, log,
    occurrences and existing triage label."""
    crash_id = id.strip().upper()
    for crash in _load_crashes():
        if crash.id.upper() == crash_id:
            return crash
    raise ToolError(f"No crash report with id '{id}'. Use search_crashes to find valid ids (format 'CR-1234').")


@mcp.tool(annotations=ToolAnnotations(
    title="Get subsystem owner", readOnlyHint=True, openWorldHint=False))
def get_owner(
    subsystem: Annotated[Subsystem, Field(description="Subsystem responsible for the crash")],
) -> Owner:
    """Get the team, lead and code paths that own a subsystem. Use the returned
    team as the owner in create_ticket."""
    owners = _load_owners()
    if subsystem not in owners:
        raise ToolError(
            f"Subsystem '{subsystem}' has no owner. Known subsystems: {', '.join(owners)}. "
            "If the subsystem is unknown, infer it from the stack paths (e.g. Engine/Render/ -> rendering)."
        )
    return Owner(subsystem=subsystem, **owners[subsystem])


@mcp.tool(annotations=ToolAnnotations(
    title="Create Jira ticket", readOnlyHint=False, destructiveHint=False,
    idempotentHint=True, openWorldHint=True))
def create_ticket(
    title: Annotated[str, Field(min_length=5, max_length=200, description="Short title, e.g. '[rendering] Null PSO after cache miss (CR-1001)'")],
    body: Annotated[str, Field(min_length=10, description="Crash id, severity, likely cause and stack excerpt")],
    owner: Annotated[str, Field(description="Owning team exactly as returned by get_owner, e.g. 'Rendering'")],
) -> Ticket:
    """Create a Jira ticket (simulated) assigned to a team. Idempotent: the same
    title + owner returns the existing ticket instead of creating a duplicate."""
    teams = {o["team"] for o in _load_owners().values()}
    if owner not in teams:
        raise ToolError(f"Unknown team '{owner}'. Valid teams: {', '.join(sorted(teams))}. Call get_owner(subsystem) first.")

    # Idempotency key: hash of normalized title + owner.
    norm_title = " ".join(title.lower().split())
    key = "CRASH-" + hashlib.sha256(f"{norm_title}|{owner}".encode()).hexdigest()[:8]

    tickets = _load_tickets()
    if key in tickets:
        logger.info("create_ticket: %s already exists, not duplicating", key)
        return Ticket(**tickets[key], created=False)

    tickets[key] = {
        "key": key, "title": title, "body": body, "owner": owner,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    TICKETS_FILE.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("create_ticket: created %s for %s", key, owner)
    return Ticket(**tickets[key], created=True)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
