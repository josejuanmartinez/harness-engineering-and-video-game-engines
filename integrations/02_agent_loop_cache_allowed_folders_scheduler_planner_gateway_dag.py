"""
EXERCISE 02 (DAG variant): Scheduler with dependencies (plan-and-execute / LLMCompiler)

In the previous version the model asked for tools turn by turn and the Scheduler only
ran them in parallel. Here the Planner returns a FULL PLAN as a DAG:

    t1 search_code("stream")        t2 list_files("tests")       <- no deps: in parallel
            │                               │
            ▼                               │
    t3 llm: "from $t1, which file?"         │
            │                               │
            ▼                               ▼
    t4 read_file($t3, 1, 40)        t5 llm: "is there a test for $t3? $t2"

- Planner: asks the LLM for a PlannerOutput via structured output (output_format, Pydantic):
  either kind="plan" with the DAG, or kind="answer" with the final answer. Each task is
  {id, kind: tool|llm, tool, args_json, instruction, depends_on}. "$tN" refers to the
  output of task tN. It is not a tool: the plan IS the Planner's output, not an action.
- Scheduler: validates the DAG (ids, existing deps, known tools, no cycles via Kahn),
  runs each task as soon as its dependencies finish (not in "waves"), substitutes
  the $tN refs, and if a task fails marks everything that depends on it as skipped.
  Returns all results to the Planner, which answers or re-plans.
- Gateway: the same as before, shared by the Planner and the "llm" tasks, so
  the token budget and retries are global.

Self-contained: tools, ToolRegistry and LLMGateway live in this same file.
"""
import inspect
import json
import os
import random
import re
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, get_type_hints

from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import Message, ParsedMessage
from pydantic import BaseModel, Field

ROOT = Path("./").resolve()  # folder the tools may access
MODEL = "claude-haiku-5-5"          # llm tasks (cheap, fast)
PLANNER_MODEL = "claude-sonnet-5-5" # planning a good DAG needs more reasoning
MAX_ROUNDS = 4              # planning rounds (plan -> execute -> see results)
MAX_TASKS_PER_PLAN = 12
MAX_TOKENS_PER_CALL = 3000
MAX_TOTAL_TOKENS = 80000
MAX_OUTPUT_TO_PLANNER = 3000   # chars per task the Planner sees
MAX_OUTPUT_SUBSTITUTED = 20000  # chars per task when substituting $tN
REF = re.compile(r"\$(t\d+)\b")


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
  """Name -> function + schema (the schema is used for the Planner's catalog)."""

  def __init__(self, fns: list[Callable]):
    self._fns = {fn.__name__: fn for fn in fns}
    self.schemas = [self._schema(fn) for fn in fns]

  @staticmethod
  def _schema(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    properties = {name: {"type": JSON_TYPES[hints[name]]} for name in inspect.signature(fn).parameters}
    return {"name": fn.__name__, "description": inspect.getdoc(fn) or "",
            "input_schema": {"type": "object", "properties": properties,
                             "required": list(properties), "additionalProperties": False}}

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
# LLM Gateway: transport + retries + accounting + model routing
# =========================================================================== #
class LLMGateway:
  RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}

  def __init__(self, model: str, max_retries: int = 4, timeout_s: float = 60):
    # max_retries=0 in the SDK: we do the retries here, explicitly.
    self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0, timeout=timeout_s)
    self.model = model
    self.max_retries = max_retries
    self.total_input = self.total_output = self.cache_read = 0

  def complete(self, *, system: str, messages: list, max_tokens: int, tools: list | None = None, **kwargs) -> Message:
    params = self._params(system, messages, max_tokens, kwargs)
    if tools:
      params["tools"] = tools
    return self._with_retries(self.client.messages.create, params)

  def parse(self, *, system: str, messages: list, max_tokens: int, output_format: type, **kwargs) -> ParsedMessage:
    """Structured output: the response comes validated against the Pydantic model in .parsed_output."""
    params = self._params(system, messages, max_tokens, kwargs)
    params["output_format"] = output_format
    return self._with_retries(self.client.messages.parse, params)

  def _params(self, system: str, messages: list, max_tokens: int, kwargs: dict) -> dict:
    # model per call: the gateway also acts as a router (expensive planner, cheap tasks)
    return dict(model=kwargs.pop("model", self.model), system=[{"type": "text", "text": system}],
                messages=messages, max_tokens=max_tokens, **kwargs)

  def _with_retries(self, call: Callable, params: dict):
    for attempt in range(self.max_retries + 1):
      try:
        start = time.perf_counter()
        response = call(**params)
        self._account(response, time.perf_counter() - start)
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

  def _account(self, response: Message, latency_s: float) -> None:
    u = response.usage
    self.total_input += u.input_tokens
    self.total_output += u.output_tokens
    self.cache_read += u.cache_read_input_tokens or 0
    print(f"   [gateway] {response.model} {latency_s:.2f}s  in={u.input_tokens} out={u.output_tokens} "
          f"cache_read={u.cache_read_input_tokens or 0}")

  @property
  def total_tokens(self) -> int:
    return self.total_input + self.total_output


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
  """TaskSpec + execution state (the state belongs to the Scheduler)."""
  spec: TaskSpec
  status: Literal["pending", "running", "ok", "error", "skipped"] = "pending"
  output: str = ""
  duration_s: float = 0.0

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
  assistant_content: list
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

  def plan(self, messages: list) -> Plan:
    response = self.gateway.parse(
      system=self.system, messages=messages, max_tokens=self.max_tokens,
      output_format=PlannerOutput, model=PLANNER_MODEL,
    )
    match response.stop_reason:
      case "max_tokens":
        return Plan("stop", response.content, reason="max_tokens (plan truncated, not executed)")
      case "refusal":
        return Plan("stop", response.content, reason="refusal")

    out: PlannerOutput = response.parsed_output
    if out.kind == "answer":
      return Plan("final", response.content, text=out.answer)
    return Plan("dag", response.content, [Task(spec) for spec in out.tasks])


# =========================================================================== #
# Scheduler: validates and runs the DAG
# =========================================================================== #
class Scheduler:
  LLM_TASK_SYSTEM = "You transform data. Reply with only the requested output: no explanations, no quotes, no markdown."

  def __init__(self, planner: Planner, tools: ToolRegistry, gateway: LLMGateway, max_workers: int = 4):
    self.planner = planner
    self.tools = tools
    self.gateway = gateway
    self.executor = ThreadPoolExecutor(max_workers=max_workers)

  # ---------------- main loop ----------------
  def run(self, user_input: str) -> str:
    messages: list = [{"role": "user", "content": user_input}]
    start_tokens = self.gateway.total_tokens

    for round_ in range(1, MAX_ROUNDS + 1):
      used = self.gateway.total_tokens - start_tokens
      if used >= MAX_TOTAL_TOKENS:
        return f"[stopped] token budget exceeded ({used}/{MAX_TOTAL_TOKENS})"

      plan = self.planner.plan(messages)
      messages.append({"role": "assistant", "content": plan.assistant_content})

      match plan.kind:
        case "final":
          return plan.text
        case "stop":
          return f"[stopped] {plan.reason}"

      print(f"\n=== round {round_}: plan with {len(plan.tasks)} tasks ===")
      try:
        order = self.validate(plan.tasks)
        for t in order:
          print(f"  {t.id} [{t.kind}] {t.tool or t.instruction[:60]!r} deps={t.depends_on}")
        self.execute_dag(plan.tasks)
        feedback = "Results of the plan:\n" + self.summarize(plan.tasks)
      except InvalidPlan as e:
        print(f"  invalid plan: {e}")
        feedback = f"Invalid plan, fix it and send it again: {e}"

      # No tool_use means no tool_result: the results go as a normal user message.
      messages.append({"role": "user", "content": feedback})

    return f"[stopped] max planning rounds reached ({MAX_ROUNDS})"

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
  def execute_dag(self, tasks: list[Task]) -> None:
    by_id = {t.id: t for t in tasks}
    running: dict[Future, Task] = {}
    t0 = time.perf_counter()

    while True:
      # 1) propagate failures: if a dependency failed or was skipped, this task is skipped
      for t in tasks:
        if t.status == "pending":
          bad = [d for d in t.depends_on if by_id[d].status in ("error", "skipped")]
          if bad:
            t.status, t.output = "skipped", f"skipped: dependency {bad} did not succeed"
            print(f"  {t.id} skipped (deps {bad} failed)")

      # 2) launch everything whose dependencies are "ok"
      for t in tasks:
        if t.status == "pending" and all(by_id[d].status == "ok" for d in t.depends_on):
          t.status = "running"
          print(f"  +{time.perf_counter() - t0:5.2f}s start {t.id}")
          running[self.executor.submit(self.run_task, t, by_id)] = t

      if not running:
        break

      # 3) wait for the FIRST one to finish (not the whole wave)
      done, _ = wait(running, return_when=FIRST_COMPLETED)
      for fut in done:
        t = running.pop(fut)
        print(f"  +{time.perf_counter() - t0:5.2f}s end   {t.id} -> {t.status} ({t.duration_s * 1000:.0f}ms)")

  def run_task(self, t: Task, by_id: dict[str, Task]) -> None:
    start = time.perf_counter()
    try:
      if t.kind == "tool":
        args = self.substitute(json.loads(t.args_json), by_id)
        result = self.tools.execute(ToolCall(t.id, t.tool, args))
        t.output, t.status = result.content, ("error" if result.is_error else "ok")
      else:
        prompt = self.substitute(t.instruction, by_id)
        response = self.gateway.complete(
          system=self.LLM_TASK_SYSTEM, messages=[{"role": "user", "content": prompt}], max_tokens=500)
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
# Wiring
# =========================================================================== #
def build_agent() -> Scheduler:
  gateway = LLMGateway(MODEL)
  tools = ToolRegistry([list_files, search_code, read_file])
  planner = Planner(gateway, tools, MAX_TOKENS_PER_CALL)
  return Scheduler(planner, tools, gateway)


def main() -> None:
  agent = build_agent()
  while True:
    try:
      intent = input("What's your question? ").strip()
    except EOFError:
      break
    if not intent or intent.startswith("exit"):
      break
    print("\n" + agent.run(intent) + "\n")


if __name__ == "__main__":
  main()
