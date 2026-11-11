"""
EXERCISE 13 (snippet): long-running agent with PROGRESS.md ("clean" context per session)
==============================================================================================
WHAT IT IS
  The pattern used today to let an agent work for hours/days without losing the thread:
  the state does NOT live in the message history, it lives in a small, readable file
  (PROGRESS.md) that the agent itself maintains. Each "session" starts with an empty context,
  loads only that file (+ whatever it decides to read with tools) and, before running out of
  budget, writes down where it left off. It is the same thing a human does with a handoff note.

    PROGRESS.md
      ## Goal        what we want (set by the human; the agent does not touch it)
      ## Done        APPEND-ONLY log, one line per step forward, with session and date
      ## Next        concrete next steps (the agent REWRITES it whole)
      ## Notes       decisions and pitfalls found ("X doesn't work because Y")

  Rules that make it work:
    - Short, incremental lines: the file must fit comfortably in context.
    - Done is append-only (reliable history); Next is rewritten (always fresh).
    - The harness, not the model, decides when the session ends (token budget);
      when it gets close to the limit it forces a checkpoint.
    - Source of truth = files (+ git in a real repo), never the chat memory.

WHAT THE TESTS CHECK
  - That a new session, with no history, picks the work back up with only PROGRESS.md.
  - That the agent writes incremental checkpoints (Done/Next/Notes) via tools.
  - That the harness cuts off on budget and forces the handoff before cutting.
  - That the outer loop ends when the agent marks the goal as complete.

Usage:
  python 13_long_running_progress_file.py "Write a 3-chapter short story in work/story/"
  python 13_long_running_progress_file.py            # resumes with the existing PROGRESS.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import anthropic

client = anthropic.Anthropic()
MODEL = "claude-opus-5-5"
WORK = Path(__file__).parent / "work"
PROGRESS = WORK / "PROGRESS.md"
SESSION_TOKEN_BUDGET = 40_000   # input tokens accumulated per session before forcing a handoff
MAX_SESSIONS = 10

TEMPLATE = "## Goal\n{goal}\n\n## Done\n\n## Next\n- Plan the work and fill this list\n\n## Notes\n"

SYSTEM = """You are a long-running agent. You have NO memory between sessions: the only
state that survives is work/PROGRESS.md and the files in work/. Each session:
1. Read PROGRESS.md (given below) and continue from ## Next.
2. Do one or two concrete steps with the file tools.
3. After each meaningful step call log_done (one short line).
4. Before stopping call set_next with the concrete next steps (rewrite the whole list),
   and add_note for any decision or pitfall a future you must know.
5. Call goal_complete only when ## Goal is fully satisfied."""

TOOLS = [
    {"name": "read_file", "description": "Read a file under work/.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write a file under work/ (overwrites).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "log_done", "description": "Append ONE short line to ## Done.",
     "input_schema": {"type": "object", "properties": {"line": {"type": "string"}}, "required": ["line"]}},
    {"name": "set_next", "description": "Replace ## Next with these concrete steps.",
     "input_schema": {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
                      "required": ["steps"]}},
    {"name": "add_note", "description": "Append a decision/pitfall to ## Notes.",
     "input_schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}},
    {"name": "goal_complete", "description": "Mark the goal as done. Ends the run.",
     "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]


# --- PROGRESS.md: sections as text blocks -------------------------------------------------
def read_sections() -> dict[str, str]:
    out, cur = {}, None
    for line in PROGRESS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def write_sections(s: dict[str, str]) -> None:
    body = "".join(f"## {k}\n{s.get(k, '')}\n\n" for k in ("Goal", "Done", "Next", "Notes"))
    PROGRESS.write_text(body, encoding="utf-8")


def append_to(section: str, line: str) -> None:
    s = read_sections()
    s[section] = (s.get(section, "") + f"\n{line}").strip()
    write_sections(s)


def safe(path: str) -> Path:
    p = (WORK / path).resolve()
    if WORK.resolve() not in p.parents and p != WORK.resolve():
        raise ValueError("path outside work/")
    return p


# --- Tools --------------------------------------------------------------------------------
def run_tool(name: str, args: dict, session: int) -> str:
    stamp = f"[s{session} {datetime.now():%m-%d %H:%M}]"
    if name == "read_file":
        p = safe(args["path"])
        return p.read_text(encoding="utf-8") if p.exists() else "(missing)"
    if name == "write_file":
        p = safe(args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"wrote {len(args['content'])} chars"
    if name == "log_done":
        append_to("Done", f"- {stamp} {args['line']}")
        return "logged"
    if name == "set_next":
        s = read_sections()
        s["Next"] = "\n".join(f"- {x}" for x in args["steps"])
        write_sections(s)
        return "next updated"
    if name == "add_note":
        append_to("Notes", f"- {args['note']}")
        return "noted"
    if name == "goal_complete":
        append_to("Done", f"- {stamp} GOAL COMPLETE: {args['summary']}")
        return "complete"
    return f"unknown tool {name}"


# --- One session = clean context + PROGRESS.md --------------------------------------------
def run_session(n: int) -> bool:
    """Returns True if the agent marked the goal as complete."""
    messages = [{"role": "user", "content":
                 f"Session {n}. Current work/PROGRESS.md:\n\n{PROGRESS.read_text(encoding='utf-8')}"}]
    used, handoff_forced = 0, False
    while True:
        resp = client.messages.create(model=MODEL, max_tokens=4096, system=SYSTEM,
                                      tools=TOOLS, messages=messages)
        used += resp.usage.input_tokens + resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return False                     # the agent ended the session on its own

        results, done = [], False
        for b in resp.content:
            if b.type == "tool_use":
                out = run_tool(b.name, b.input, n)
                print(f"  s{n} {b.name}: {json.dumps(b.input)[:90]}")
                done |= b.name == "goal_complete"
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        if done:
            return True

        if used > SESSION_TOKEN_BUDGET and not handoff_forced:
            # The harness cuts off: asks for the handoff and gives one last turn to write it.
            results.append({"type": "text", "text":
                            "Session budget reached. Now call log_done/set_next/add_note to hand off, then stop."})
            handoff_forced = True
        elif handoff_forced:
            return False
        messages.append({"role": "user", "content": results})


def main() -> None:
    WORK.mkdir(exist_ok=True)
    if len(sys.argv) > 1:
        PROGRESS.write_text(TEMPLATE.format(goal=sys.argv[1]), encoding="utf-8")
    elif not PROGRESS.exists():
        sys.exit("Pass a goal the first time.")

    for n in range(1, MAX_SESSIONS + 1):
        print(f"--- session {n} (fresh context) ---")
        if run_session(n):
            print("goal complete")
            break
    print("\n" + PROGRESS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
