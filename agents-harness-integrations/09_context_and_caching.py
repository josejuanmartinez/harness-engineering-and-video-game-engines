"""
SUMMARY: TECHNIQUES, GAINS AND RECOMMENDATION
=============================================
Techniques
1. Prompt caching: breakpoint at the end of system (caches tools + system) + automatic
   caching for the tail. Prefix order: tools -> system -> messages.
2. Volatile content last: the time goes as {"role": "system"} after the history.
3. Client-side truncation of old tool_results.
4. Client-side summary once a threshold is crossed (goal, decisions, errors, files).
5. Server compaction (compact_20260112): summarizes and returns a compaction block.
6. Server context editing (clear_tool_uses_20250919): the server empties the
   content of old tool_results (see the next section).

How context editing works (and how it differs from the rest)
  - Who does it: the API server, before the model sees the prompt. Claude
    decides nothing. You set the rules in context_management.edits:
        trigger          how many input tokens before it starts clearing
        keep             how many recent tool uses are kept intact
        clear_at_least   minimum tokens to free each time (if it can't, it doesn't clear)
        exclude_tools    tools whose results are never cleared
        clear_tool_inputs  true: also empties the tool_use arguments
    Beta: context-management-2025-06-27. There is another strategy, clear_thinking_20251015,
    that clears thinking blocks.
  - What it removes: it does NOT remove messages. It replaces the content of old tool_results
    with a placeholder. User messages, Claude's replies and the
    tool_use/tool_result blocks stay in place, so the conversation structure is
    preserved. If the model needs a cleared result, it calls the tool again.
  - Your history doesn't change: you keep sending the full conversation on every
    request and the server edits its own copy on each request. That's why it doesn't count as
    a history edit and doesn't break Opus 5.5's preserved thinking (client-side
    truncation does break it). The response reports what was cleared in
    response.context_management.applied_edits (cleared_input_tokens, cleared_tool_uses).
  - What it costs: the cache is invalidated from the cleared point onward. That's why
    clear_at_least exists: clearing a little isn't worth the cache you lose. Here it's
    5,000 tokens, with trigger 30,000 and keep 3.
  - Versus server compaction: compaction SUMMARIZES (loses detail, keeps
    the thread) and returns a compaction block that must be sent back by appending the
    whole response.content. Its cost goes in usage.iterations, not in the
    top-level fields. Beta: compact-2026-01-12.
  - Versus client-side truncation or summary: there you edit the history yourself, which breaks the
    cache and, on Opus 5.5, invalidates later thinking.
  - Versus the memory tool (memory_20250818): there Claude does decide. It writes notes outside
    the context and reads them when needed; it survives across sessions, but costs
    calls and you have to decide what to store.

Example syntax (Python SDK; the real implementation is in Agent.request/turn)
  1. Prompt caching
        client.messages.create(
            model="claude-opus-5-5", max_tokens=16000,
            tools=TOOLS,                                    # prefix position 0
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],  # caches tools + system
            cache_control={"type": "ephemeral"},            # automatic caching of the tail
            messages=messages,
        )
        # Check: resp.usage.cache_read_input_tokens > 0 from the 2nd request on

  2. Volatile content last (mid-conversation system message, no beta)
        # WRONG: system=f"Time: {now()}\n" + SYSTEM_PROMPT    -> cache_read = 0
        messages.append({"role": "user", "content": question})
        messages.append({"role": "system", "content": f"Current date and time: {now()}"})
        # Must come after a user message; never as messages[0]; never removed afterwards.

  3. Client-side truncation (edits the history: breaks cache and thinking)
        for block in old_user_message["content"]:
            if block["type"] == "tool_result":
                block["content"] = block["content"][:400] + "\n[... truncated]"
        # On Opus 5.5 this is needed to avoid a 400:
        thinking={"type": "adaptive",
                  "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
        betas=["thinking-binding-controls-2026-08-01"]

  4. Client-side summary (simple compaction: the summary replaces the whole history)
        resp = client.messages.create(..., tools=TOOLS, system=SYSTEM,  # same prefix
                                      tool_choice={"type": "none"},
                                      messages=messages + [{"role": "user",
                                                            "content": COMPACTION_INSTRUCTIONS}])
        summary = "".join(b.text for b in resp.content if b.type == "text")
        messages = [{"role": "user", "content": [
            {"type": "text", "text": f"<previous_session_summary>{summary}</previous_session_summary>"},
            {"type": "text", "text": next_question}]}]

  5. Server-side summary
        resp = client.beta.messages.create(
            ..., betas=["compact-2026-01-12"],
            context_management={"edits": [{
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": 50_000},  # default 150K
                "instructions": COMPACTION_INSTRUCTIONS,               # what to keep
            }]},
        )
        messages.append({"role": "assistant", "content": resp.content})  # WHOLE: includes
                                                                         # the compaction block
        extra_cost = [it for it in resp.usage.iterations or [] if it.type == "compaction"]

  6. Server context editing
        resp = client.beta.messages.create(
            ..., betas=["context-management-2025-06-27"],
            context_management={"edits": [{
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": 30_000},
                "keep": {"type": "tool_uses", "value": 3},
                "clear_at_least": {"type": "input_tokens", "value": 5_000},
                # "exclude_tools": ["read_file"], "clear_tool_inputs": True,
            }]},
        )
        for edit in resp.context_management.applied_edits if resp.context_management else []:
            print(edit.cleared_tool_uses, edit.cleared_input_tokens)

  Extra: memory tool (Claude decides; not used in this exercise)
        client.messages.create(..., tools=[{"type": "memory_20250818", "name": "memory"}])
        # Claude requests view/create/str_replace/... on /memories and your code runs them
        # (in Python, a subclass of BetaAbstractMemoryTool).

  Extra: change effort without losing the cache (beta, Opus 5.5)
        messages.append({"role": "system", "content": [], "output_config": {"effort": "high"}})
        betas=["mid-conversation-output-config-2026-07-01"]

Measured gains (Opus 5.5, 2-turn test; baseline and summary were not run)
    strategy          cost $    vs cache_broken  vs cache   cache hit   thinking dropped
    cache_broken      0.1685        -           +72%          0%            5
    cache             0.0980      -42%            -          59%            0
    truncated         0.1044      -38%           +7%         45%            2
    compaction        0.0946      -44%           -3%         66%            0
    context_editing   0.0904      -46%           -8%         66%            0
  - cache_broken is in practice the same as having no cache (cache_read = 0) and it also pays
    for the write (1.25x), so it works as a bound on the baseline: caching properly saves ~40%
    already on turn 2, and the gain grows with each turn because a read costs 0.05x.
  - With 2 turns the context (~9K tokens) doesn't reach the thresholds: compaction,
    context editing and summary hadn't fired yet. Their real gain shows up in
    long conversations; to measure it, run the 15 turns.

Recommendation
  cache + volatile content last + server context editing, with server
  compaction as a safety net for very long sessions.
  - Getting the cache right is the biggest gain and costs nothing.
  - Context editing keeps the conversation structure and doesn't edit your
    history: if the model needs a cleared result, it calls the tool again.
    (Its -8% in the 2-turn test is noise: it hadn't cleared anything yet.)
  - Compaction only when the context doesn't fit even after clearing: it loses detail.
  - Don't truncate or summarize by hand: editing the history breaks the cache from that point and,
    on Opus 5.5, invalidates later thinking (preserved thinking: 400 on new
    accounts, or dropped blocks). Truncating came out 7% more expensive than doing nothing.
  - Pin effort, model and tools for the whole session.

EXERCISE 09: context management and prompt caching
Time: 35 min
Stack: Anthropic SDK (cache_control, usage, compaction, context editing)
Requires: exercise 02 finished

TASK
Measure how much a long conversation with your agent costs and reduce it without losing quality.

REQUIREMENTS
- Log per turn: input_tokens, output_tokens, cache_read_input_tokens,
  cache_creation_input_tokens and estimated cost
- Baseline without cache: 15 turns
- Add cache_control. Remember the prefix order: tools, system and messages
- Break it on purpose: put the current time in the system prompt and watch
  cache_read_input_tokens drop to zero. Fix it by moving volatile content to the end
- Truncate or summarize old tool results and compare the cost
- Compare with server compaction and context editing (both in beta)
- Final table: strategy, cost, latency, quality of the final answer

GOING FURTHER
- Mid-conversation system messages: why do they keep the cache?
- Changing effort mid-conversation: what happens to the cache?
- What information must survive a compaction? Goal, decisions, errors

QUESTIONS YOU MIGHT GET
- What silently invalidates the cache? Unordered JSON, changing tools, dates
- What's the difference between compacting, clearing and using external memory?
- How do you decide what goes into the context at each agent step?

USAGE
    python 09_context_and_caching.py                         # all 7 strategies, 15 turns
    python 09_context_and_caching.py -s baseline cache -t 4  # cheap test
    python 09_context_and_caching.py --list

STRATEGIES (same 15-turn conversation, same agent as ex. 02)
    baseline         no cache_control
    cache_broken     cache_control + time in the system prompt  -> cache_read drops to 0
    cache            cache_control + time as a system message at the end (volatile content last)
    truncated        cache + client-side truncation of tool_results from earlier turns
    summary          cache + client-side compaction (own summary once a threshold is crossed)
    compaction       cache + server compaction (compact_20260112)
    context_editing  cache + server context editing (clear_tool_uses_20250919)

NOTE ON PRESERVED THINKING (Opus 5.5)
    Thinking blocks are bound to the exact prefix (system, tools and earlier
    messages). Editing the history client-side (cache_broken rewrites the system on every
    request; truncated rewrites old tool_results) invalidates later thinking blocks
    and, on accounts created since 2026-08-31, returns a 400. That's why those two
    strategies send prefix_mismatch_behavior="drop_block" and the table counts the
    dropped blocks: it's a hidden cost of editing the history. Server compaction and
    context editing don't count as edits.


SUMMARY: TECHNIQUES AND CONCLUSIONS
===================================
Techniques
1. Prompt caching (cache_control). The cache is a prefix match in the order
   tools -> system -> messages. Explicit breakpoint at the end of system (caches tools +
   system) and top-level automatic caching for the tail of the conversation.
2. Volatile content last. The time doesn't go in system: it goes as a {"role": "system"} message
   appended after the history, which stays append-only.
3. Client-side truncation. Trim the tool_results from earlier turns.
4. Client-side summary. Once a threshold is crossed, a summary (goal, decisions, errors,
   files read) replaces the whole history.
5. Server compaction (compact_20260112). The server summarizes once the threshold is crossed and
   returns a compaction block that must be sent back (append the whole response.content).
6. Server context editing (clear_tool_uses_20250919). The server clears old
   tool_results and keeps the last N. It doesn't summarize.

Conclusions (2-turn test; the 15-turn one hasn't been run)
- The cache is the first lever and it's free: 59-66% hits already on turn 2, and
  a read costs 0.05x on Opus 5.5.
- A single volatile byte at the start breaks everything: with the time in system,
  cache_read = 0 on every request and cost goes up 72% ($0.169 vs $0.098).
  The fix is to move volatile content to the end, not to drop the cache.
- Editing the history client-side costs twice: it invalidates the cache from the edited
  point and, on Opus 5.5, invalidates later thinking (preserved thinking; 400 on
  new accounts, or dropped blocks with drop_block). Truncating saved context, but
  lowered the cache hit rate to 45% and dropped 2 thinking blocks: it cost more than not truncating.
- Server-side features (compaction, context editing) don't count as edits: they keep cache
  and thinking. They're preferable to truncating or summarizing by hand.
- Compacting loses detail but keeps the thread; clearing keeps the structure, and the
  model can call the tool again. What has to survive: goal,
  decisions, errors and what has already been read. That's what grade() measures on turn 15.
- Pin effort, model and tools for the whole session: changing them invalidates the cache.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
ROOT = (HERE.parent / "c").resolve()  # folder the tools can access
EFFORT = "medium"  # fixed for the whole conversation: changing it invalidates the message cache
MAX_TOKENS = 16000
MAX_STEPS_PER_TURN = 8
MAX_TOOL_CHARS = 20_000
RESULTS_FILE = HERE / "09_context_and_caching_results.json"

# $/MTok: (input, output, cache_read). 5-min cache write = 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULT = 1.25

# --------------------------------------------------------------------------------------
# Tools (as in ex. 02, but deterministic: fixed order, sorted outputs)
# --------------------------------------------------------------------------------------


def _safe(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise PermissionError(f"Path outside the allowed folder: {path}")
    return resolved


def list_files(directory: str) -> str:
    base = _safe(directory)
    if not base.is_dir():
        raise FileNotFoundError(f"Not a directory: {directory}")
    rows = [
        f"{p.relative_to(ROOT).as_posix()}\t{p.stat().st_size} bytes"
        for p in sorted(base.rglob("*"))
        if p.is_file()
    ]
    return "\n".join(rows) or "(empty)"


def search_code(pattern: str) -> str:
    regex = re.compile(pattern)
    hits = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in {".cpp", ".h", ".hpp", ".md"}:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{n}: {line.strip()}")
    return "\n".join(hits[:300]) or "(no matches)"


def read_file(path: str) -> str:
    p = _safe(path)
    if not p.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(f"{i:4d} | {line}" for i, line in enumerate(lines, 1))


TOOL_FUNCS = {"list_files": list_files, "read_file": read_file, "search_code": search_code}


def _tool(name: str, description: str, props: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": sorted(props),
            "additionalProperties": False,
        },
        "strict": True,
    }


# Sorted by name and built only once: the tools are at position 0 of the prefix.
TOOLS = sorted(
    [
        _tool(
            "list_files",
            "Recursively lists the files (with their size) of a directory relative to the "
            "repository root. Use it to get your bearings before reading files. Use '.' for the root.",
            {"directory": {"type": "string", "description": "Relative directory, e.g. '.' or '00_review'"}},
        ),
        _tool(
            "read_file",
            "Returns the full contents of a file with line numbers. Use it when "
            "you need the actual code; don't guess content you haven't read.",
            {"path": {"type": "string", "description": "Relative path, e.g. '02_vector.cpp'"}},
        ),
        _tool(
            "search_code",
            "Searches for a regular expression (Python syntax) in every .cpp/.h/.md in the "
            "repository and returns 'path:line: text'. Use it to find where something appears.",
            {"pattern": {"type": "string", "description": "Regular expression"}},
        ),
    ],
    key=lambda t: t["name"],
)

# Stable, with nothing volatile. Together with the tools it must exceed the minimum
# cacheable size (512 tokens on Opus 5.5).
SYSTEM_PROMPT = """You are a C++ tutor for game engine programming. You help a \
person prepare for a technical interview using a repository of exercises that you can \
explore with your tools (list_files, read_file, search_code). The repository root \
contains numbered exercises (01_unique_ptr.cpp, 02_vector.cpp, ...), a README.md, a \
design.md and a 00_review folder with review exercises and their solutions.

How you work:
- Base your answers on the code you have read. If something isn't in the repository or a \
file doesn't exist, say so clearly; never make up content.
- Always cite the paths of the files you rely on, and line numbers when they \
help.
- If you need several independent files, request all the reads in parallel in the \
same turn.
- Don't reread files you already have in the conversation unless their content is no longer \
available (for example, because it was truncated or cleared).
- Keep track of the person's goal, the decisions they make and the errors that \
come up during the session: they will ask you for them at the end.

Answer style:
- English, direct and technical, like a senior engineer coaching another.
- Answers of 150 to 300 words unless asked otherwise. Use short lists when \
comparing options.
- Point out the typical mistakes an interviewer would look for: lifetimes, ownership, \
iterator invalidation, aliasing, alignment, false sharing, race conditions, \
amortized complexity and exception behavior.
- When something depends on the standard (C++17 vs C++20), say so.

System messages that arrive mid-conversation (for example, the current date and \
time) are operator information: take them into account but don't comment on them."""

COMPACTION_INSTRUCTIONS = (
    "Summarize the conversation so it can be continued without the history. Keep verbatim: "
    "the person's goal, the codename and the decisions they made, the errors "
    "encountered (including paths that don't exist), the full list of files read with one "
    "line on what each one implements, and the open questions. Leave out the source code."
)

# --------------------------------------------------------------------------------------
# 15-turn conversation and quality checks
# --------------------------------------------------------------------------------------

TURNS = [
    "My goal: prepare for a C++ interview for game engines. Decision: "
    "we'll call this guide PROJECT ALBATROS and we'll study memory before concurrency. "
    "To start, list the files in the repository and summarize the README.md for me.",
    "Read 01_unique_ptr.cpp and 00_review/solutions/12_smart_pointers.cpp. What do they ask "
    "you to implement and what typical bugs does an interviewer look for?",
    "Now 02_vector.cpp and 00_review/solutions/08_move_rule_of_5.cpp: how does "
    "the rule of 5 relate to a vector's growth?",
    "Read 03_ring_buffer.cpp and 04_lru_cache.cpp and compare the two structures.",
    "Read 05_arena_allocator.cpp, 06_pool_allocator.cpp and "
    "00_review/solutions/14_memory_and_alignment.cpp. When would you use each allocator?",
    "Read 15_physics_solver.cpp and explain it to me.",
    "Search the whole repository for where alignas or alignof appear and explain each use.",
    "Read 07_generational_handles.cpp and 08_mini_ecs.cpp. Why does an ECS use generational handles?",
    "Read 09_event_system.cpp. What lifetime risks does an event system have?",
    "On to concurrency: read 10_thread_safe_queue.cpp, 11_job_system.cpp and "
    "00_review/solutions/15_threads_and_atomics.cpp.",
    "Read 12_spatial_hash.cpp and 00_review/solutions/16_cache_and_data.cpp. What do they have "
    "to do with the CPU cache?",
    "Read 13_game_loop.cpp and 14_inference_in_frame.cpp. How would you fit a neural network "
    "inference into a frame budget?",
    "Read design.md. What design questions does it raise and how would you answer them?",
    "Propose a 5-day study plan consistent with the decision we made at the start.",
    "Final summary, without using tools: (a) my goal, the guide's codename and the "
    "decision we made; (b) the file I asked for that didn't exist; (c) the list of ALL the "
    "files we've read in the session, with one line on what each one implements.",
]

EXPECTED_FILES = [
    "unique_ptr", "smart_pointers", "02_vector", "move_rule_of_5", "ring_buffer",
    "lru_cache", "arena_allocator", "pool_allocator", "memory_and_alignment",
    "generational_handles", "mini_ecs", "event_system", "thread_safe_queue", "job_system",
    "threads_and_atomics", "spatial_hash", "cache_and_data", "game_loop", "inference_in_frame",
    "design.md",
]


def grade(final: str, n_turns: int) -> dict:
    """Quality = facts from old turns that survive until the final answer."""
    if n_turns < len(TURNS):
        return {"score": None, "detail": "incomplete conversation"}
    low = final.lower()
    files_hit = sum(f in low for f in EXPECTED_FILES)
    checks = {
        "codename": "albatros" in low,
        "decision": "memory" in low and "concurrency" in low,
        "missing_file": "physics_solver" in low,
        "files": files_hit / len(EXPECTED_FILES),
    }
    score = (checks["codename"] + checks["decision"] + checks["missing_file"]
             + checks["files"]) / 4
    return {"score": round(score, 3), "detail": checks}


# --------------------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Strategy:
    name: str
    cache: bool = False
    time_in_system: bool = False  # the deliberate bug
    truncate_old: bool = False
    summarize_at: int | None = None  # context tokens that trigger the client-side summary
    server_compaction: bool = False
    server_clear: bool = False

    @property
    def edits_history(self) -> bool:
        return self.time_in_system or self.truncate_old


@dataclass
class Usage:
    requests: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    latency: float = 0.0
    context: int = 0  # prompt size of the last request
    dropped_thinking: int = 0
    cleared_tokens: int = 0
    compactions: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, other: "Usage") -> None:
        for k in ("requests", "input", "output", "cache_read", "cache_write", "cost", "latency",
                  "dropped_thinking", "cleared_tokens", "compactions"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.context = other.context or self.context
        self.notes += other.notes


def cost_of(model: str, inp: int, out: int, read: int, write: int) -> float:
    p_in, p_out, p_read = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (inp * p_in + out * p_out + read * p_read + write * p_in * CACHE_WRITE_MULT) / 1e6


def usage_from(resp, latency: float) -> Usage:
    u = resp.usage
    read = u.cache_read_input_tokens or 0
    write = u.cache_creation_input_tokens or 0
    rec = Usage(requests=1, input=u.input_tokens, output=u.output_tokens, cache_read=read,
                cache_write=write, latency=latency, context=u.input_tokens + read + write)
    rec.cost = cost_of(resp.model, u.input_tokens, u.output_tokens, read, write)
    # Server compaction cost is NOT in the top-level fields.
    for it in u.iterations or []:
        if it.type == "compaction":
            rec.compactions += 1
            rec.notes.append("compaction")
            rec.cost += cost_of(resp.model, it.input_tokens, it.output_tokens,
                                it.cache_read_input_tokens, it.cache_creation_input_tokens)
            rec.input += it.input_tokens
            rec.output += it.output_tokens
            rec.cache_read += it.cache_read_input_tokens
            rec.cache_write += it.cache_creation_input_tokens
    for tr in resp.input_transformations or []:
        if tr.type == "thinking_dropped":
            rec.dropped_thinking += 1
    if resp.context_management:
        for edit in resp.context_management.applied_edits:
            cleared = getattr(edit, "cleared_input_tokens", 0) or 0
            rec.cleared_tokens += cleared
            rec.notes.append(f"clear -{cleared}")
    if resp.model != MODEL:
        rec.notes.append(f"fallback to {resp.model}")
    return rec


STRATEGIES = {
    s.name: s
    for s in [
        Strategy("baseline"),
        Strategy("cache_broken", cache=True, time_in_system=True),
        Strategy("cache", cache=True),
        Strategy("truncated", cache=True, truncate_old=True),
        Strategy("summary", cache=True, summarize_at=40_000),
        Strategy("compaction", cache=True, server_compaction=True),
        Strategy("context_editing", cache=True, server_clear=True),
    ]
}


class Agent:
    def __init__(self, client: anthropic.Anthropic, strategy: Strategy, args: argparse.Namespace):
        self.client = client
        self.s = strategy
        self.args = args
        self.messages: list[dict] = []
        self.carry_summary: str | None = None
        self.truncated_ids: set[str] = set()

    # ---- building the request: tools -> system -> messages -------------------------
    def request(self, messages: list[dict], **extra) -> dict:
        system_text = SYSTEM_PROMPT
        if self.s.time_in_system:
            # DELIBERATE BUG: something that changes on every request at the start of the prefix.
            system_text = f"Current date and time: {now()}\n\n{SYSTEM_PROMPT}"
        system_block: dict = {"type": "text", "text": system_text}
        betas = ["server-side-fallback-2026-07-01"]
        req: dict = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "tools": TOOLS,
            "system": [system_block],
            "messages": messages,
            "output_config": {"effort": EFFORT},
            "fallbacks": "default",
        }
        if self.s.cache:
            # Explicit breakpoint at the end of the static prefix (tools + system) ...
            system_block["cache_control"] = {"type": "ephemeral"}
            # ... and automatic caching for the tail of the conversation, which advances on its own.
            req["cache_control"] = {"type": "ephemeral"}
        edits = []
        if self.s.server_clear:
            betas.append("context-management-2025-06-27")
            edits.append({
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": self.args.clear_trigger},
                "keep": {"type": "tool_uses", "value": 3},
                "clear_at_least": {"type": "input_tokens", "value": 5_000},
            })
        if self.s.server_compaction:
            betas.append("compact-2026-01-12")
            edits.append({
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": self.args.compact_trigger},
                "instructions": COMPACTION_INSTRUCTIONS,
            })
        if edits:
            req["context_management"] = {"edits": edits}
        if self.s.edits_history:
            betas.append("thinking-binding-controls-2026-08-01")
            req["thinking"] = {"type": "adaptive",
                               "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
        req["betas"] = betas
        req.update(extra)
        return req

    def call(self, messages: list[dict], **extra):
        t0 = time.perf_counter()
        resp = self.client.beta.messages.create(**self.request(messages, **extra))
        return resp, usage_from(resp, time.perf_counter() - t0)

    # ---- client-side context management -----------------------------------------
    def truncate_old_tool_results(self) -> int:
        """Trims the tool_results from earlier turns (edits the history)."""
        saved = 0
        for msg in self.messages:
            if msg["role"] != "user" or not isinstance(msg["content"], list):
                continue
            for block in msg["content"]:
                if block.get("type") != "tool_result" or block["tool_use_id"] in self.truncated_ids:
                    continue
                text = block["content"]
                if len(text) > 400:
                    block["content"] = (f"{text[:400]}\n[... truncated: {len(text) - 400} characters "
                                        "omitted. Call the tool again if you need it]")
                    saved += len(text) - 400
                self.truncated_ids.add(block["tool_use_id"])
        return saved

    def summarize(self) -> Usage:
        """Simple client-side compaction: a summary replaces the whole history.

        It's a fork of the agent: same model, tools and system (reads the parent's cache) and the
        summary request at the end. No old thinking is sent back, so it doesn't
        break preserved thinking."""
        resp, rec = self.call(
            self.messages + [{"role": "user", "content": COMPACTION_INSTRUCTIONS}],
            tool_choice={"type": "none"},
        )
        summary = "".join(b.text for b in resp.content if b.type == "text")
        if self.carry_summary:
            summary = f"{self.carry_summary}\n\n{summary}"
        self.carry_summary = summary
        self.messages = []
        rec.compactions = 1
        rec.notes.append("client summary")
        return rec

    # ---- one user turn (loop from ex. 02) ----------------------------------------
    def turn(self, question: str, prev_context: int) -> tuple[Usage, str]:
        total = Usage()
        if self.s.truncate_old and self.messages:
            saved = self.truncate_old_tool_results()
            if saved:
                total.notes.append(f"truncated {saved} chars")
        if self.s.summarize_at and prev_context > self.s.summarize_at:
            total.add(self.summarize())

        content = []
        if self.carry_summary and not self.messages:
            content.append({"type": "text",
                            "text": f"<previous_session_summary>\n{self.carry_summary}\n</previous_session_summary>"})
        content.append({"type": "text", "text": question})
        self.messages.append({"role": "user", "content": content})
        if not self.s.time_in_system:
            # FIX: volatile content goes last, as a mid-conversation system message.
            # It sits after the cached prefix and is never removed (append-only history).
            self.messages.append({"role": "system", "content": f"Current date and time: {now()}"})

        final = ""
        for _ in range(MAX_STEPS_PER_TURN):
            resp, rec = self.call(self.messages)
            total.add(rec)
            # Full content: thinking, tool_use and compaction blocks included.
            self.messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "tool_use":
                calls = [b for b in resp.content if b.type == "tool_use"]
                with ThreadPoolExecutor() as pool:
                    results = list(pool.map(run_tool, calls))
                self.messages.append({"role": "user", "content": results})  # all together
                continue
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason in ("refusal", "max_tokens"):
                total.notes.append(resp.stop_reason)
            final = "".join(b.text for b in resp.content if b.type == "text")
            break
        else:
            total.notes.append("max_steps")
        return total, final


def run_tool(block) -> dict:
    try:
        out = TOOL_FUNCS[block.name](**block.input)
        if len(out) > MAX_TOOL_CHARS:
            out = out[:MAX_TOOL_CHARS] + f"\n[... output trimmed to {MAX_TOOL_CHARS} characters]"
        return {"type": "tool_result", "tool_use_id": block.id, "content": out}
    except Exception as e:  # a failing tool doesn't break the agent
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": f"{type(e).__name__}: {e}", "is_error": True}


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------------------
# Running and reporting
# --------------------------------------------------------------------------------------

ROW = "{:>4} {:>4} {:>8} {:>7} {:>9} {:>9} {:>8} {:>7} {:>8}  {}"


def run_strategy(client, strategy: Strategy, args) -> dict:
    print(f"\n=== {strategy.name} ===")
    print(ROW.format("turn", "req", "input", "output", "c_read", "c_write", "cost$", "lat_s", "ctx", "notes"))
    agent = Agent(client, strategy, args)
    total, turns, final, ctx = Usage(), [], "", 0
    for i, q in enumerate(TURNS[: args.turns], 1):
        rec, final = agent.turn(q, ctx)
        ctx = rec.context
        notes = list(rec.notes)
        if rec.dropped_thinking:
            notes.append(f"thinking dropped {rec.dropped_thinking}")
        print(ROW.format(i, rec.requests, rec.input, rec.output, rec.cache_read, rec.cache_write,
                         f"{rec.cost:.4f}", f"{rec.latency:.1f}", rec.context, ", ".join(notes)))
        total.add(rec)
        turns.append(asdict(rec))
    quality = grade(final, args.turns)
    prompt_tokens = total.input + total.cache_read + total.cache_write
    hit = total.cache_read / prompt_tokens if prompt_tokens else 0.0
    print(f"Total: ${total.cost:.4f}  {total.latency:.1f}s  cache hit {hit:.0%}  quality {quality['score']}")
    if args.verbose and final:
        print(f"--- final answer ---\n{final}\n")
    return {"strategy": strategy.name, "total": asdict(total), "cache_hit": hit,
            "quality": quality, "turns": turns, "final_answer": final}


def print_table(results: list[dict]) -> None:
    base = next((r["total"]["cost"] for r in results if r["strategy"] == "baseline"), None)
    print("\n" + "=" * 100)
    head = "{:<16} {:>9} {:>8} {:>7} {:>9} {:>9} {:>9} {:>8}  {}"
    print(head.format("strategy", "cost $", "vs base", "lat s", "cache hit", "final ctx",
                      "thk drop", "quality", "quality detail"))
    for r in results:
        t, q = r["total"], r["quality"]
        vs = f"{t['cost'] / base - 1:+.0%}" if base else "-"
        detail = ("-" if q["score"] is None else
                  " ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={'yes' if v else 'no'}"
                           for k, v in q["detail"].items()))
        print(head.format(r["strategy"], f"{t['cost']:.4f}", vs, f"{t['latency']:.1f}",
                          f"{r['cache_hit']:.0%}", t["context"], t["dropped_thinking"],
                          "-" if q["score"] is None else f"{q['score']:.2f}", detail))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("USAGE")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-s", "--strategies", nargs="+", default=list(STRATEGIES), choices=list(STRATEGIES))
    ap.add_argument("-t", "--turns", type=int, default=len(TURNS), help="turns to run (max. 15)")
    ap.add_argument("--compact-trigger", type=int, default=50_000, help="server compaction threshold")
    ap.add_argument("--clear-trigger", type=int, default=30_000, help="context editing threshold")
    ap.add_argument("--list", action="store_true", help="show the strategies and exit")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the final answer")
    args = ap.parse_args()
    args.turns = max(1, min(args.turns, len(TURNS)))

    if args.list:
        for s in STRATEGIES.values():
            print(s)
        return

    client = anthropic.Anthropic()
    print(f"Model {MODEL}, effort {EFFORT}, {args.turns} turns, tools root {ROOT}")
    results = []
    for name in args.strategies:
        try:
            results.append(run_strategy(client, STRATEGIES[name], args))
        except anthropic.BadRequestError as e:
            print(f"[{name}] 400: {e.message}")
        except anthropic.RateLimitError as e:
            print(f"[{name}] 429 (rate limit), skipping: {e.message}")
        except anthropic.APIStatusError as e:
            print(f"[{name}] error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError as e:
            print(f"[{name}] connection error: {e}")
    if results:
        print_table(results)
        RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResults in {RESULTS_FILE.name}")


# --------------------------------------------------------------------------------------
# Interview notes (GOING FURTHER / QUESTIONS)
# --------------------------------------------------------------------------------------
# * Mid-conversation system messages: the cache is a prefix match in the order
#   tools -> system -> messages. Changing the top system changes byte N of the prefix and
#   everything after it is reprocessed. A {"role": "system"} appended to the end of messages
#   leaves the prefix intact: you only pay for what's new. Also, the history stays
#   append-only, so earlier thinking blocks remain valid.
# * Changing effort midway: a change in the top-level output_config invalidates the
#   message cache (on some models also tools/system). On Opus 5.5 the way to
#   keep it is a system message with content: [] and output_config.effort (beta
#   mid-conversation-output-config-2026-07-01). Otherwise, pin effort per route.
# * What must survive a compaction: goal, decisions, errors and paths that
#   failed, what has already been read and what's pending. That's exactly what grade() measures: turn
#   15 asks about facts from turns 1 and 6.
# * Silent invalidators: dates/UUIDs in system, json.dumps without sort_keys, sets,
#   tools built per user or in a different order, changing model, effort or thinking, and
#   editing old turns. You spot them by watching cache_read_input_tokens on every request.
# * Compacting (summarize: loses detail, keeps the thread) versus clearing (remove
#   old tool_results: keeps the structure, the model can call the tool again)
#   versus external memory (the agent writes and reads notes outside the context: survives
#   sessions, but costs calls and you have to decide what to store).
# * What goes into each step: stable content first and cached (instructions, tools), the
#   minimum necessary state (goal, decisions), recent results in full and
#   old ones summarized or cleared; volatile content last.


if __name__ == "__main__":
    main()
