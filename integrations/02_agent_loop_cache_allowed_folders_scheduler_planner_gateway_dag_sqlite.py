"""
EXERCISE 02 (DAG + SQLite variant): DURABLE plan-and-execute

Same as _dag.py (Planner -> DAG -> Scheduler, shared Gateway), but the agent's state
lives in SQLite instead of in memory. That gives:

- Traceability: every plan (per round) and every task is stored with its already
  resolved args, its output, status, duration and whether it came from the cache. Every
  LLM call is logged with model, purpose, tokens and latency.
- Recovery: if the process dies halfway through a DAG, `--resume <run_id>` reloads the
  plan, keeps the tasks in ok/error/skipped and relaunches only the pending/running ones.
  No LLM call that was already made is repeated.
- Savings: besides not repeating work on resume, read-only tools are cached
  by (tool, args, file fingerprint) across different runs.
- Observability: `--show <run_id>` shows the plan's progress, task by task, and the
  usage per model. `--list` lists the runs.

The message history the Planner sees is NOT stored separately: it is rebuilt from
the question + plans + task results (a single source of truth).

Usage:
  python 02_..._dag_sqlite.py "Which exercise covers streaming?"
  CRASH_AFTER_TASKS=2 python 02_..._dag_sqlite.py "..."   # simulates a crash halfway through the DAG
  python 02_..._dag_sqlite.py --resume <run_id>
  python 02_..._dag_sqlite.py --show <run_id>
  python 02_..._dag_sqlite.py --list
"""
import argparse
import hashlib
import inspect
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, get_type_hints

from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import Message, ParsedMessage
from pydantic import BaseModel, Field

ROOT = Path("./").resolve()  # folder the tools may access
DB_PATH = ".agent_runs.sqlite"
MODEL = "claude-haiku-5-5"          # llm tasks (cheap, fast)
PLANNER_MODEL = "claude-sonnet-5-5" # planning a good DAG needs more reasoning
MAX_ROUNDS = 4              # planning rounds (plan -> execute -> see results)
MAX_TASKS_PER_PLAN = 12
MAX_TOKENS_PER_CALL = 3000
MAX_TOTAL_TOKENS = 80000    # per run, also counting what was spent before a resume
MAX_OUTPUT_TO_PLANNER = 3000   # chars per task the Planner sees
MAX_OUTPUT_SUBSTITUTED = 20000  # chars per task when substituting $tN
CACHE_TTL_S = 600
REF = re.compile(r"\$(t\d+)\b")


def now() -> float:
  return time.time()


# =========================================================================== #
# Tools
# =========================================================================== #
def check_safe_path(path: str) -> Path:
  resolved = (ROOT / path).resolve()
  if not resolved.is_relative_to(ROOT):
    raise ValueError("Path must stay inside the allowed directory.")
  return resolved


def list_files(directory: str) -> str:
  """List every file under a directory (relative to the repo root). Use it first to discover which files exist."""
  base_dir = check_safe_path(directory)
  if not base_dir.is_dir():
    raise ValueError(f"{directory} is not a valid directory.")
  return "\n".join(str(p.relative_to(ROOT)) for p in base_dir.rglob("*") if p.is_file())


def search_code(pattern: str) -> str:
  """Search a regex across all code files in the repo. Use it to find where a concept or symbol appears."""
  regex = re.compile(pattern)
  matches = []
  for p in ROOT.rglob("*"):
    if p.is_file() and p.suffix in (".py", ".js", ".java", ".cpp", ".c"):
      with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for n, line in enumerate(f, start=1):
          if regex.search(line):
            matches.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
  return "\n".join(matches[:200]) or "No matches."


def read_file(path: str, start_line: int, end_line: int) -> str:
  """Read lines start_line..end_line (1-based, inclusive) of a file. Use it once you know which file and lines matter."""
  p = check_safe_path(path)
  if not p.is_file():
    raise ValueError(f"{path} is not a valid file.")
  lines = p.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
  if start_line < 1 or end_line > len(lines) or start_line > end_line:
    raise ValueError(f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines).")
  return "".join(lines[start_line - 1:end_line])


def read_file_fingerprint(args: dict) -> str:
  """Fingerprint to invalidate the read_file cache if the file changes."""
  try:
    st = check_safe_path(args["path"]).stat()
    return f"{st.st_mtime_ns}:{st.st_size}"
  except Exception:
    return "missing"


JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class ToolCall:
  id: str
  name: str
  input: dict


@dataclass
class ToolResult:
  call: ToolCall
  content: str
  is_error: bool
  duration_s: float


class ToolRegistry:
  """Name -> function + schema + whether it is read-only (cacheable and safe to re-run)."""

  def __init__(self, fns: list[Callable], read_only: set[str], fingerprints: dict[str, Callable] | None = None):
    self._fns = {fn.__name__: fn for fn in fns}
    self.schemas = [self._schema(fn) for fn in fns]
    self.read_only = read_only
    self.fingerprints = fingerprints or {}

  @staticmethod
  def _schema(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    properties = {name: {"type": JSON_TYPES[hints[name]]} for name in inspect.signature(fn).parameters}
    return {"name": fn.__name__, "description": inspect.getdoc(fn) or "",
            "input_schema": {"type": "object", "properties": properties,
                             "required": list(properties), "additionalProperties": False}}

  def cache_key(self, name: str, args: dict) -> str | None:
    if name not in self.read_only:
      return None  # tools with side effects are never cached
    fp = self.fingerprints.get(name, lambda a: "")(args)
    raw = json.dumps([name, args, fp], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

  def execute(self, call: ToolCall) -> ToolResult:
    start = time.perf_counter()
    try:
      fn = self._fns.get(call.name)
      if fn is None:
        raise ValueError(f"Unknown tool: {call.name}")
      content, is_error = str(fn(**call.input)), False
    except Exception as e:  # a failing tool does NOT crash the agent
      content, is_error = f"{type(e).__name__}: {e}", True
    return ToolResult(call, content, is_error, time.perf_counter() - start)


# =========================================================================== #
# RunStore: all durable state in SQLite
# =========================================================================== #
class RunStore:
  SCHEMA = """
  CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, question TEXT NOT NULL,
    status TEXT NOT NULL,                  -- running | done | stopped | failed
    final_answer TEXT, stop_reason TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL, updated_at REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS plans (
    run_id TEXT NOT NULL, round INTEGER NOT NULL,
    planner_model TEXT NOT NULL,
    raw TEXT NOT NULL,                     -- raw Planner output (what the model saw)
    status TEXT NOT NULL,                  -- executing | done | invalid
    error TEXT, created_at REAL NOT NULL, finished_at REAL,
    PRIMARY KEY (run_id, round)
  );
  CREATE TABLE IF NOT EXISTS tasks (
    run_id TEXT NOT NULL, round INTEGER NOT NULL, task_id TEXT NOT NULL,
    kind TEXT NOT NULL, tool TEXT, args_json TEXT, instruction TEXT, depends_on TEXT NOT NULL,
    status TEXT NOT NULL,                  -- pending | running | ok | error | skipped
    resolved_input TEXT,                   -- args/prompt with the $tN refs already substituted
    output TEXT, from_cache INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
    started_at REAL, ended_at REAL, duration_ms REAL,
    PRIMARY KEY (run_id, round, task_id)
  );
  CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, round INTEGER, purpose TEXT,   -- planner | task:<id>
    model TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
    latency_ms REAL, created_at REAL
  );
  CREATE TABLE IF NOT EXISTS tool_cache (
    key TEXT PRIMARY KEY, tool TEXT, output TEXT NOT NULL, created_at REAL NOT NULL
  );
  """

  def __init__(self, path: str):
    # One thread writes at a time (lock); llm tasks log their calls from workers.
    self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    self.conn.row_factory = sqlite3.Row
    self.lock = threading.Lock()
    with self.lock:
      self.conn.execute("PRAGMA journal_mode=WAL")
      self.conn.executescript(self.SCHEMA)

  def _exec(self, sql: str, params: tuple = ()) -> None:
    with self.lock:
      self.conn.execute(sql, params)

  def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with self.lock:
      return self.conn.execute(sql, params).fetchall()

  def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = self._all(sql, params)
    return rows[0] if rows else None

  # --- runs ---
  def create_run(self, question: str) -> str:
    run_id = uuid.uuid4().hex[:8]
    self._exec("INSERT INTO runs (run_id, question, status, created_at, updated_at) VALUES (?, ?, 'running', ?, ?)",
               (run_id, question, now(), now()))
    return run_id

  def get_run(self, run_id: str) -> sqlite3.Row | None:
    return self._one("SELECT * FROM runs WHERE run_id = ?", (run_id,))

  def finish_run(self, run_id: str, status: str, final_answer: str | None = None, stop_reason: str | None = None):
    self._exec("UPDATE runs SET status=?, final_answer=?, stop_reason=?, updated_at=? WHERE run_id=?",
               (status, final_answer, stop_reason, now(), run_id))

  def list_runs(self, limit: int = 20) -> list[sqlite3.Row]:
    return self._all("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))

  # --- llm calls / tokens ---
  def log_llm_call(self, tag: dict, response: Message, latency_s: float):
    u = response.usage
    self._exec(
      "INSERT INTO llm_calls (run_id, round, purpose, model, input_tokens, output_tokens, cache_read_tokens, latency_ms, created_at)"
      " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
      (tag.get("run_id"), tag.get("round"), tag.get("purpose"), response.model, u.input_tokens, u.output_tokens,
       u.cache_read_input_tokens or 0, latency_s * 1000, now()))
    if tag.get("run_id"):
      self._exec("UPDATE runs SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, updated_at=?"
                 " WHERE run_id = ?", (u.input_tokens, u.output_tokens, now(), tag["run_id"]))

  # --- plans / tasks ---
  def save_plan(self, run_id: str, round_: int, raw: str, tasks: list["Task"], status: str, error: str | None = None):
    with self.lock:
      self.conn.execute("BEGIN")
      self.conn.execute(
        "INSERT INTO plans (run_id, round, planner_model, raw, status, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, round_, PLANNER_MODEL, raw, status, error, now()))
      for t in tasks:
        self.conn.execute(
          "INSERT INTO tasks (run_id, round, task_id, kind, tool, args_json, instruction, depends_on, status)"
          " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
          (run_id, round_, t.id, t.kind, t.tool, t.args_json, t.instruction, json.dumps(t.depends_on)))
      self.conn.execute("COMMIT")

  def finish_plan(self, run_id: str, round_: int):
    self._exec("UPDATE plans SET status='done', finished_at=? WHERE run_id=? AND round=?", (now(), run_id, round_))

  def load_plans(self, run_id: str) -> list[sqlite3.Row]:
    return self._all("SELECT * FROM plans WHERE run_id=? ORDER BY round", (run_id,))

  def update_task(self, run_id: str, round_: int, t: "Task"):
    self._exec(
      "UPDATE tasks SET status=?, resolved_input=?, output=?, from_cache=?, attempts=?, started_at=?, ended_at=?,"
      " duration_ms=? WHERE run_id=? AND round=? AND task_id=?",
      (t.status, t.resolved_input, t.output, int(t.from_cache), t.attempts, t.started_at, t.ended_at,
       t.duration_s * 1000, run_id, round_, t.id))

  def load_tasks(self, run_id: str, round_: int) -> list["Task"]:
    rows = self._all("SELECT * FROM tasks WHERE run_id=? AND round=? ORDER BY rowid", (run_id, round_))
    return [Task(
      spec=TaskSpec(id=r["task_id"], kind=r["kind"], tool=r["tool"] or "", args_json=r["args_json"] or "{}",
                    instruction=r["instruction"] or "", depends_on=json.loads(r["depends_on"])),
      status=r["status"], output=r["output"] or "", duration_s=(r["duration_ms"] or 0) / 1000,
      resolved_input=r["resolved_input"], from_cache=bool(r["from_cache"]), attempts=r["attempts"],
      started_at=r["started_at"], ended_at=r["ended_at"],
    ) for r in rows]

  # --- tool cache ---
  def cache_get(self, key: str) -> str | None:
    row = self._one("SELECT output, created_at FROM tool_cache WHERE key=?", (key,))
    if row and now() - row["created_at"] < CACHE_TTL_S:
      return row["output"]
    return None

  def cache_put(self, key: str, tool: str, output: str):
    self._exec("INSERT OR REPLACE INTO tool_cache (key, tool, output, created_at) VALUES (?, ?, ?, ?)",
               (key, tool, output, now()))


# =========================================================================== #
# LLM Gateway: transport + retries + accounting + model routing
# =========================================================================== #
class LLMGateway:
  RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}

  def __init__(self, model: str, listener: Callable[[dict, Message, float], None] | None = None,
               max_retries: int = 4, timeout_s: float = 60):
    # max_retries=0 in the SDK: we do the retries here, explicitly.
    self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0, timeout=timeout_s)
    self.model = model
    self.listener = listener   # e.g. RunStore.log_llm_call: the gateway knows nothing about SQLite
    self.max_retries = max_retries

  def complete(self, *, system: str, messages: list, max_tokens: int, tools: list | None = None,
               tag: dict | None = None, **kwargs) -> Message:
    params = self._params(system, messages, max_tokens, kwargs)
    if tools:
      params["tools"] = tools
    return self._with_retries(self.client.messages.create, params, tag or {})

  def parse(self, *, system: str, messages: list, max_tokens: int, output_format: type,
            tag: dict | None = None, **kwargs) -> ParsedMessage:
    """Structured output: the response comes validated against the Pydantic model in .parsed_output."""
    params = self._params(system, messages, max_tokens, kwargs)
    params["output_format"] = output_format
    return self._with_retries(self.client.messages.parse, params, tag or {})

  def _params(self, system: str, messages: list, max_tokens: int, kwargs: dict) -> dict:
    # model per call: the gateway also acts as a router (expensive planner, cheap tasks)
    return dict(model=kwargs.pop("model", self.model), system=[{"type": "text", "text": system}],
                messages=messages, max_tokens=max_tokens, **kwargs)

  def _with_retries(self, call: Callable, params: dict, tag: dict):
    for attempt in range(self.max_retries + 1):
      try:
        start = time.perf_counter()
        response = call(**params)
        latency = time.perf_counter() - start
        u = response.usage
        print(f"   [gateway] {tag.get('purpose', '?')} {response.model} {latency:.2f}s "
              f"in={u.input_tokens} out={u.output_tokens} cache_read={u.cache_read_input_tokens or 0}")
        if self.listener:
          self.listener(tag, response, latency)
        return response
      except (RateLimitError, APIConnectionError, APIStatusError) as e:
        status = getattr(e, "status_code", None)
        retryable = isinstance(e, APIConnectionError) or status in self.RETRYABLE_STATUS
        if not retryable or attempt == self.max_retries:
          raise
        delay = self._retry_delay(e, attempt)
        print(f"   [gateway] {type(e).__name__} (status={status}), retry {attempt + 1} in {delay:.1f}s")
        time.sleep(delay)
    raise RuntimeError("unreachable")

  @staticmethod
  def _retry_delay(e: Exception, attempt: int) -> float:
    response = getattr(e, "response", None)
    retry_after = response.headers.get("retry-after") if response is not None else None
    if retry_after:
      try:
        return float(retry_after)
      except ValueError:
        pass
    return min(30, 2 ** attempt) * random.uniform(0.5, 1.5)  # exponential backoff + jitter


# =========================================================================== #
# Types
# =========================================================================== #
class TaskSpec(BaseModel):
  """What the Planner decides: what to do and what it depends on."""
  id: str = Field(description="t1, t2, ...")
  kind: Literal["tool", "llm"]
  tool: str = Field(description="Tool name for kind=tool, empty string for kind=llm")
  args_json: str = Field(description="JSON object with the tool arguments, as a string. '{}' for kind=llm")
  instruction: str = Field(description="For kind=llm; empty string for kind=tool")
  depends_on: list[str] = Field(description="Ids of the tasks that must finish before this one")


class PlannerOutput(BaseModel):
  """Structured output of the Planner: either a plan or the final answer."""
  kind: Literal["plan", "answer"]
  tasks: list[TaskSpec] = Field(description="The DAG when kind=plan; empty list when kind=answer")
  answer: str = Field(description="Final answer for the user when kind=answer; empty string when kind=plan")


@dataclass
class Task:
  """TaskSpec + execution state (the state belongs to the Scheduler, and is persisted)."""
  spec: TaskSpec
  status: Literal["pending", "running", "ok", "error", "skipped"] = "pending"
  output: str = ""
  duration_s: float = 0.0
  resolved_input: str | None = None
  from_cache: bool = False
  attempts: int = 0
  started_at: float | None = None
  ended_at: float | None = None

  @property
  def id(self) -> str: return self.spec.id
  @property
  def kind(self) -> str: return self.spec.kind
  @property
  def tool(self) -> str: return self.spec.tool
  @property
  def args_json(self) -> str: return self.spec.args_json
  @property
  def instruction(self) -> str: return self.spec.instruction
  @property
  def depends_on(self) -> list[str]: return self.spec.depends_on


@dataclass
class Plan:
  kind: Literal["dag", "final", "stop"]
  raw: str                       # exact text the Planner returned
  tasks: list[Task] = field(default_factory=list)
  text: str = ""
  reason: str = ""


class InvalidPlan(ValueError):
  pass


# =========================================================================== #
# Planner: produces the DAG with structured output (output_format)
# =========================================================================== #
PLANNER_SYSTEM = """\
You answer questions about the files in the current repository. You cannot call tools directly: \
you reply with kind="plan" and a DAG of tasks, then you receive every task's result.
kind="tool" runs `tool` with `args_json`. kind="llm" is a small LLM step that follows `instruction`, \
e.g. to extract a path or line numbers from an earlier output.
Reference the output of an earlier task with $tN inside args_json or instruction, and list it in \
depends_on. If an argument value is exactly "$tN", it is replaced by that task's output, so make the \
producing llm task return only the bare value.
Put everything you can predict in ONE plan, chaining steps with depends_on and $tN references instead \
of waiting for another round. Tasks with no dependency between them must not depend on each other, so \
they run in parallel. After seeing the results, either send another plan (only if something is missing \
or failed) or reply with kind="answer".
Only state facts found in task results, cite file paths, and say so if the answer is not in the repository.

Example of chaining in a single plan (find a file, then read it, without a second round):
  t1 tool search_code {{"pattern": "retry"}} deps=[]
  t2 llm "From these matches return only the path of the main file: $t1" deps=[t1]
  t3 tool read_file {{"path": "$t2", "start_line": 1, "end_line": 30}} deps=[t2]
  t4 tool list_files {{"directory": "tests"}} deps=[]   <- independent, runs in parallel with t1

Available tools:
{catalog}"""


def tool_catalog(tools: ToolRegistry) -> str:
  lines = []
  for s in tools.schemas:
    args = ", ".join(f"{k}: {v['type']}" for k, v in s["input_schema"]["properties"].items())
    lines.append(f"- {s['name']}({args}): {s['description']}")
  return "\n".join(lines)


class Planner:
  def __init__(self, gateway: LLMGateway, tools: ToolRegistry, max_tokens: int):
    self.gateway = gateway
    self.max_tokens = max_tokens
    self.system = PLANNER_SYSTEM.format(catalog=tool_catalog(tools))

  def plan(self, messages: list, tag: dict) -> Plan:
    response = self.gateway.parse(
      system=self.system, messages=messages, max_tokens=self.max_tokens,
      output_format=PlannerOutput, model=PLANNER_MODEL, tag=tag,
    )
    raw = "".join(b.text for b in response.content if b.type == "text")
    match response.stop_reason:
      case "max_tokens":
        return Plan("stop", raw, reason="max_tokens (plan truncated, not executed)")
      case "refusal":
        return Plan("stop", raw, reason="refusal")

    out: PlannerOutput = response.parsed_output
    if out.kind == "answer":
      return Plan("final", raw, text=out.answer)
    return Plan("dag", raw, [Task(spec) for spec in out.tasks])


# =========================================================================== #
# Scheduler: validates, runs and persists the DAG; resumes half-finished runs
# =========================================================================== #
class Scheduler:
  LLM_TASK_SYSTEM = "You transform data. Reply with only the requested output: no explanations, no quotes, no markdown."

  def __init__(self, planner: Planner, tools: ToolRegistry, gateway: LLMGateway, store: RunStore, max_workers: int = 4):
    self.planner = planner
    self.tools = tools
    self.gateway = gateway
    self.store = store
    self.executor = ThreadPoolExecutor(max_workers=max_workers)
    crash = os.getenv("CRASH_AFTER_TASKS")
    self.crash_after = int(crash) if crash else None   # to demonstrate resuming

  # ---------------- history: DERIVED from the stored state ----------------
  def rebuild_messages(self, run: sqlite3.Row, plans: list[sqlite3.Row]) -> list:
    messages: list = [{"role": "user", "content": run["question"]}]
    for p in plans:
      if p["status"] == "executing":
        break  # half-finished round: it is completed before calling the Planner again
      messages.append({"role": "assistant", "content": p["raw"]})
      if p["status"] == "invalid":
        messages.append({"role": "user", "content": f"Invalid plan, fix it and send it again: {p['error']}"})
      else:
        tasks = self.store.load_tasks(run["run_id"], p["round"])
        messages.append({"role": "user", "content": "Results of the plan:\n" + self.summarize(tasks)})
    return messages

  # ---------------- main loop ----------------
  def run(self, question: str | None = None, resume_run_id: str | None = None) -> str:
    if resume_run_id:
      run = self.store.get_run(resume_run_id)
      if run is None:
        return f"[error] run {resume_run_id} not found"
      if run["status"] != "running":
        return f"[run {resume_run_id} already {run['status']}]\n{run['final_answer'] or run['stop_reason'] or ''}"
      run_id = resume_run_id
      print(f"Resuming run {run_id}: {run['question']!r}")
    else:
      run_id = self.store.create_run(question)
      run = self.store.get_run(run_id)
      print(f"Run {run_id} (resume with --resume {run_id}, inspect with --show {run_id})")

    plans = self.store.load_plans(run_id)
    messages = self.rebuild_messages(run, plans)
    round_ = len(plans)

    # Interrupted round: complete it, keeping what was already done.
    if plans and plans[-1]["status"] == "executing":
      tasks = self.store.load_tasks(run_id, round_)
      for t in tasks:
        if t.status == "running":
          # It was cut off halfway: run it again. Safe because the tools are read-only; with
          # side-effecting tools you would need an idempotency key per task.
          t.status = "pending"
          self.store.update_task(run_id, round_, t)
      done = sum(t.status in ("ok", "error", "skipped") for t in tasks)
      print(f"\n=== round {round_} (resumed): {done}/{len(tasks)} tasks already finished ===")
      self.execute_dag(run_id, round_, tasks)
      self.store.finish_plan(run_id, round_)
      messages.append({"role": "assistant", "content": plans[-1]["raw"]})
      messages.append({"role": "user", "content": "Results of the plan:\n" + self.summarize(tasks)})

    while round_ < MAX_ROUNDS:
      run = self.store.get_run(run_id)
      used = run["input_tokens"] + run["output_tokens"]
      if used >= MAX_TOTAL_TOKENS:
        reason = f"token budget exceeded ({used}/{MAX_TOTAL_TOKENS})"
        self.store.finish_run(run_id, "stopped", stop_reason=reason)
        return f"[stopped] {reason}"

      round_ += 1
      plan = self.planner.plan(messages, tag={"run_id": run_id, "round": round_, "purpose": "planner"})

      match plan.kind:
        case "final":
          self.store.finish_run(run_id, "done", final_answer=plan.text)
          return plan.text
        case "stop":
          self.store.finish_run(run_id, "stopped", stop_reason=plan.reason)
          return f"[stopped] {plan.reason}"

      messages.append({"role": "assistant", "content": plan.raw})
      print(f"\n=== round {round_}: plan with {len(plan.tasks)} tasks ===")
      try:
        order = self.validate(plan.tasks)
      except InvalidPlan as e:
        print(f"  invalid plan: {e}")
        self.store.save_plan(run_id, round_, plan.raw, plan.tasks, status="invalid", error=str(e))
        messages.append({"role": "user", "content": f"Invalid plan, fix it and send it again: {e}"})
        continue

      # The plan is saved BEFORE running anything: if the process dies, it can be resumed.
      self.store.save_plan(run_id, round_, plan.raw, plan.tasks, status="executing")
      for t in order:
        print(f"  {t.id} [{t.kind}] {t.tool or t.instruction[:60]!r} deps={t.depends_on}")
      self.execute_dag(run_id, round_, plan.tasks)
      self.store.finish_plan(run_id, round_)
      messages.append({"role": "user", "content": "Results of the plan:\n" + self.summarize(plan.tasks)})

    reason = f"max planning rounds reached ({MAX_ROUNDS})"
    self.store.finish_run(run_id, "stopped", stop_reason=reason)
    return f"[stopped] {reason}"

  # ---------------- validation: ids, deps, tools, cycles ----------------
  def validate(self, tasks: list[Task]) -> list[Task]:
    if not tasks:
      raise InvalidPlan("the plan has no tasks")
    if len(tasks) > MAX_TASKS_PER_PLAN:
      raise InvalidPlan(f"too many tasks ({len(tasks)} > {MAX_TASKS_PER_PLAN})")
    by_id = {t.id: t for t in tasks}
    if len(by_id) != len(tasks):
      raise InvalidPlan("duplicate task ids")
    tool_names = {s["name"] for s in self.tools.schemas}
    for t in tasks:
      missing = [d for d in t.depends_on if d not in by_id]
      if missing:
        raise InvalidPlan(f"{t.id} depends on unknown tasks {missing}")
      undeclared = set(REF.findall(t.args_json + " " + t.instruction)) - set(t.depends_on)
      if undeclared:
        raise InvalidPlan(f"{t.id} references {sorted(undeclared)} but does not list them in depends_on")
      if t.kind == "tool":
        if t.tool not in tool_names:
          raise InvalidPlan(f"{t.id} uses unknown tool {t.tool!r}")
        try:
          if not isinstance(json.loads(t.args_json), dict):
            raise ValueError
        except ValueError:
          raise InvalidPlan(f"{t.id} args_json is not a JSON object")

    # Kahn: topological order; if not all of them can be ordered, there is a cycle.
    indegree = {t.id: len(t.depends_on) for t in tasks}
    dependents = {t.id: [] for t in tasks}
    for t in tasks:
      for d in t.depends_on:
        dependents[d].append(t.id)
    queue = [tid for tid, n in indegree.items() if n == 0]
    order = []
    while queue:
      tid = queue.pop(0)
      order.append(by_id[tid])
      for nxt in dependents[tid]:
        indegree[nxt] -= 1
        if indegree[nxt] == 0:
          queue.append(nxt)
    if len(order) != len(tasks):
      cyclic = [tid for tid, n in indegree.items() if n > 0]
      raise InvalidPlan(f"dependency cycle among {cyclic}")
    return order

  # ---------------- execution: each task starts when its deps finish ----------------
  def execute_dag(self, run_id: str, round_: int, tasks: list[Task]) -> None:
    by_id = {t.id: t for t in tasks}
    running: dict[Future, Task] = {}
    finished_here = 0
    t0 = time.perf_counter()

    while True:
      # 1) propagate failures: if a dependency failed or was skipped, this task is skipped
      for t in tasks:
        if t.status == "pending":
          bad = [d for d in t.depends_on if by_id[d].status in ("error", "skipped")]
          if bad:
            t.status, t.output = "skipped", f"skipped: dependency {bad} did not succeed"
            self.store.update_task(run_id, round_, t)
            print(f"  {t.id} skipped (deps {bad} failed)")

      # 2) launch everything whose dependencies are "ok"
      for t in tasks:
        if t.status == "pending" and all(by_id[d].status == "ok" for d in t.depends_on):
          t.status, t.started_at, t.attempts = "running", now(), t.attempts + 1
          self.store.update_task(run_id, round_, t)   # "running" is stored: it shows up in --show
          print(f"  +{time.perf_counter() - t0:5.2f}s start {t.id}")
          running[self.executor.submit(self.run_task, run_id, round_, t, by_id)] = t

      if not running:
        break

      # 3) wait for the FIRST one to finish (not the whole wave)
      done, _ = wait(running, return_when=FIRST_COMPLETED)
      for fut in done:
        t = running.pop(fut)
        t.ended_at = now()
        self.store.update_task(run_id, round_, t)
        cached = " (cache)" if t.from_cache else ""
        print(f"  +{time.perf_counter() - t0:5.2f}s end   {t.id} -> {t.status}{cached} ({t.duration_s * 1000:.0f}ms)")
        finished_here += 1
        if self.crash_after is not None and finished_here >= self.crash_after:
          print(f"\n  !!! simulated crash after {finished_here} tasks (CRASH_AFTER_TASKS) !!!")
          os._exit(1)  # hard kill: no finally, nothing gets closed

  def run_task(self, run_id: str, round_: int, t: Task, by_id: dict[str, Task]) -> None:
    start = time.perf_counter()
    t.from_cache = False
    try:
      if t.kind == "tool":
        args = self.substitute(json.loads(t.args_json), by_id)
        t.resolved_input = json.dumps(args, ensure_ascii=False)
        key = self.tools.cache_key(t.tool, args)
        cached = self.store.cache_get(key) if key else None
        if cached is not None:
          t.output, t.status, t.from_cache = cached, "ok", True
        else:
          result = self.tools.execute(ToolCall(t.id, t.tool, args))
          t.output, t.status = result.content, ("error" if result.is_error else "ok")
          if key and not result.is_error:
            self.store.cache_put(key, t.tool, result.content)
      else:
        prompt = self.substitute(t.instruction, by_id)
        t.resolved_input = prompt
        response = self.gateway.complete(
          system=self.LLM_TASK_SYSTEM, messages=[{"role": "user", "content": prompt}], max_tokens=500,
          tag={"run_id": run_id, "round": round_, "purpose": f"task:{t.id}"})
        t.output = "".join(b.text for b in response.content if b.type == "text").strip()
        t.status = "ok"
    except Exception as e:
      t.output, t.status = f"{type(e).__name__}: {e}", "error"
    t.duration_s = time.perf_counter() - start

  @staticmethod
  def substitute(value, by_id: dict[str, Task]):
    """Replaces $tN with the output of tN. If the value is exactly "$tN", it replaces it whole
    (and converts it to int if the output is a number, for args like start_line)."""
    if isinstance(value, dict):
      return {k: Scheduler.substitute(v, by_id) for k, v in value.items()}
    if isinstance(value, list):
      return [Scheduler.substitute(v, by_id) for v in value]
    if isinstance(value, str):
      whole = REF.fullmatch(value.strip())
      if whole:
        out = by_id[whole.group(1)].output[:MAX_OUTPUT_SUBSTITUTED].strip()
        return int(out) if out.isdigit() else out
      return REF.sub(lambda m: by_id[m.group(1)].output[:MAX_OUTPUT_SUBSTITUTED], value)
    return value

  @staticmethod
  def summarize(tasks: list[Task]) -> str:
    return json.dumps([
      {"id": t.id, "status": t.status, "output": t.output[:MAX_OUTPUT_TO_PLANNER]
       + ("... [truncated]" if len(t.output) > MAX_OUTPUT_TO_PLANNER else "")}
      for t in tasks
    ], ensure_ascii=False, indent=1)


# =========================================================================== #
# Observability: --show / --list
# =========================================================================== #
def show_run(store: RunStore, run_id: str) -> None:
  run = store.get_run(run_id)
  if run is None:
    print(f"run {run_id} not found")
    return
  print(f"run {run_id}  status={run['status']}  tokens in={run['input_tokens']} out={run['output_tokens']}")
  print(f"question: {run['question']}")
  for p in store.load_plans(run_id):
    tasks = store.load_tasks(run_id, p["round"])
    done = sum(t.status in ("ok", "error", "skipped") for t in tasks)
    print(f"\n round {p['round']}  plan={p['status']}  progress={done}/{len(tasks)}"
          + (f"  error={p['error']}" if p["error"] else ""))
    for t in tasks:
      if p["status"] == "invalid":
        t.status = "not-run"  # the plan was rejected during validation: it never ran
      what = t.tool if t.kind == "tool" else "llm"
      flags = (" cache" if t.from_cache else "") + (f" attempts={t.attempts}" if t.attempts > 1 else "")
      print(f"   {t.id:<4} {what:<12} {t.status:<8} {t.duration_s * 1000:7.0f}ms  deps={t.depends_on}{flags}")
      if t.resolved_input:
        print(f"        input: {t.resolved_input[:100]}")
  print("\n llm calls:")
  for r in store._all("SELECT purpose, model, input_tokens, output_tokens, cache_read_tokens, latency_ms"
                      " FROM llm_calls WHERE run_id=? ORDER BY id", (run_id,)):
    print(f"   {r['purpose']:<10} {r['model']:<20} in={r['input_tokens']:<6} out={r['output_tokens']:<5}"
          f" cache_read={r['cache_read_tokens']:<5} {r['latency_ms']:.0f}ms")
  if run["final_answer"]:
    print(f"\n answer: {run['final_answer'][:300]}")
  elif run["stop_reason"]:
    print(f"\n stopped: {run['stop_reason']}")


def list_runs(store: RunStore) -> None:
  for r in store.list_runs():
    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
    print(f"{r['run_id']}  {started}  {r['status']:<8} tokens={r['input_tokens'] + r['output_tokens']:<6} {r['question'][:60]}")


# =========================================================================== #
# Wiring
# =========================================================================== #
def build_agent(store: RunStore) -> Scheduler:
  gateway = LLMGateway(MODEL, listener=store.log_llm_call)
  tools = ToolRegistry([list_files, search_code, read_file],
                       read_only={"list_files", "search_code", "read_file"},
                       fingerprints={"read_file": read_file_fingerprint})
  planner = Planner(gateway, tools, MAX_TOKENS_PER_CALL)
  return Scheduler(planner, tools, gateway, store)


def main() -> None:
  parser = argparse.ArgumentParser(description="Durable plan-and-execute agent")
  parser.add_argument("question", nargs="?")
  parser.add_argument("--resume", metavar="RUN_ID")
  parser.add_argument("--show", metavar="RUN_ID")
  parser.add_argument("--list", action="store_true")
  parser.add_argument("--db", default=DB_PATH)
  args = parser.parse_args()
  sys.stdout.reconfigure(line_buffering=True)  # so the trace is not lost if the process dies

  store = RunStore(args.db)
  if args.list:
    return list_runs(store)
  if args.show:
    return show_run(store, args.show)

  agent = build_agent(store)
  if args.resume:
    print("\n" + agent.run(resume_run_id=args.resume) + "\n")
    return
  if args.question:
    print("\n" + agent.run(question=args.question) + "\n")
    return
  while True:
    try:
      intent = input("What's your question? ").strip()
    except EOFError:
      break
    if not intent or intent.startswith("exit"):
      break
    print("\n" + agent.run(question=intent) + "\n")


if __name__ == "__main__":
  main()
