"""
EXERCISE 04: model router with fallbacks
Time: 40 min
Stack: Anthropic SDK, OpenAI SDK, asyncio
Requires: exercises 02 and 03 finished

TASK
Write a thin layer the rest of the app uses to call an LLM without knowing which
provider answers. It must pick the model based on the task and survive outages.

REQUIREMENTS
- complete(messages, tools, policy): returns a normalized response with text,
  tool calls, usage, cost, provider and model
- Policies: "cheap" (claude-haiku-5-5), "default" (claude-opus-5-5) and "fallback"
  (switch to OpenAI if Anthropic fails)
- Retry 429, 5xx and connection errors with exponential backoff and jitter, and
  honor retry-after. Keep in mind the SDKs already retry: turn that off or avoid
  multiplying the attempts
- Never retry 400 or 401
- Circuit breaker per provider: after N failures, skip it for a while
- Budget per task: if exceeded, stop and return it as a typed error
- Test the failures with a fake client, without calling the API

TO GO FURTHER
- Fallback in the middle of a stream: what do you do with what was already emitted?
- Fallback in the middle of an agent: what happens to the thinking blocks and the cache?
- Compare with Anthropic's server-side fallbacks parameter, which covers
  refusals (stop_reason "refusal")
- Routing by complexity: do you decide it with rules or with a cheap model?

QUESTIONS YOU MAY BE ASKED
- Do you measure cost per call or per completed task? Why?
- How do you make sure a model change doesn't degrade quality? (exercise 10)
- Build or buy the gateway? Where would you put the control of sensitive data?
"""

from fastapi import FastAPI
import uvicorn
from pydantic import BaseModel, Field
from typing import Literal
from openai import Client
from openai.types import DecisionQuestionInputText
from zmq import Enum
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from openai import Client
from openai.types.responses import Response, ResponseOutputItem
import json
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import openai

from enum import Enum
from functools import lru_cache

import inspect
from typing import get_type_hints

app = FastAPI()
import os

class TaskCostEstimation(BaseModel):
  task: str = Field(..., description="Task to accomplish")
  cost: Literal["low", "medium", "high"] = Field(..., description="Cost of the task: low, medium, high")

class TasksCostsEstimations(BaseModel):
  tasks_costs: list[TaskCostEstimation] = Field(..., description="An array of TaskCostEstimation")

class Request(BaseModel):
  intent: str = Field(..., description="User intent")

class Policy(Enum):
  CHEAP = "gpt-6-luna"
  AVERAGE = "gpt-6-luna"
  EXPENSIVE = "gpt-6-luna"


ROOT = Path("./").resolve()  # Set this to the directory your tools may access.

def schema_from_function(fn):
    params = inspect.signature(fn).parameters
    hints = get_type_hints(fn)

    properties = {
        name: {"type": "string"}  # search_code(pattern: str)
        for name, param in params.items()
        if hints.get(name) is str
    }

    return {
        "type": "function",
        "name": fn.__name__,
        "description": inspect.getdoc(fn) or "",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "strict": True,
    }

def check_safe_path(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Path must stay inside the allowed directory.")

@lru_cache(maxsize=128)
def list_files(directory: str) -> list[str]:
    """List all files in a directory and its subdirectories."""
    check_safe_path(directory)
    if not os.path.isdir(directory):
        raise ValueError(f"{directory} is not a valid directory.")
    file_list = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_list.append(os.path.join(root, file))
    return file_list

def search_code(pattern: str) -> list[str]:
    """Search for a pattern in all code files in the ../c directory."""
    import os
    import re
    matches = []
    for root, _, files in os.walk("./"):
        for file in files:
            if file.endswith((".py", ".js", ".java", ".cpp", ".c")):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, start=1):
                        if re.search(pattern, line):
                            matches.append(f"{file_path}:{line_number}: {line.strip()}")
    return matches

def read_file(path: str, start_line: int, end_line: int) -> str:
    """Read a specific range of lines from a file."""
    check_safe_path(path)
    if not os.path.isfile(path):
        raise ValueError(f"{path} is not a valid file.")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise ValueError(f"Invalid line range: {start_line}-{end_line}.")
        return "".join(lines[start_line - 1:end_line])

tools_schemas = [schema_from_function(fn) for fn in [list_files, search_code, read_file]]

def execute_tool(content_block):
    tool_name = content_block.name
    tool_input = json.loads(content_block.arguments)
    try:
        if tool_name == "list_files":
            result = list_files(**tool_input)
        elif tool_name == "search_code":
            result = search_code(**tool_input)
        elif tool_name == "read_file":
            result = read_file(**tool_input)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
        return {
            "type": "function_call_output",
            "call_id": content_block.call_id,            
            "output": str(result)
        }
    except Exception as e:
        print(e)
        return {
            "type": "function_call_output",
            "call_id": content_block.call_id,            
            "output": str(e)
        }

# max_retries=0: we retry ourselves in with_retries, so the SDK must not retry too
client = Client(api_key=os.environ.get("OPENAI_API_KEY"), max_retries=0)
tools_schemas = [schema_from_function(fn) for fn in [list_files, search_code, read_file]]

# 429, 5xx, connection errors and timeouts (APITimeoutError is a subclass of APIConnectionError).
# 400 (BadRequestError) and 401 (AuthenticationError) are not here, so they are never retried.
RETRYABLE = (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)
MAX_ATTEMPTS = 4
BACKOFF_BASE = 0.5
BACKOFF_CAP = 20.0

def _retry_after(err) -> float | None:
    """Seconds the server asks us to wait (retry-after-ms / retry-after), or None."""
    resp = getattr(err, "response", None)
    if resp is None:
        return None
    if ms := resp.headers.get("retry-after-ms"):
        try:
            return float(ms) / 1000
        except ValueError:
            pass
    if s := resp.headers.get("retry-after"):
        try:
            return float(s)
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(s) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None
    return None

def with_retries(fn):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except RETRYABLE as e:
            # A 429 for "out of credit" won't fix itself, so don't retry it
            if isinstance(e, openai.RateLimitError) and getattr(e, "code", None) == "insufficient_quota":
                raise
            if attempt == MAX_ATTEMPTS:
                raise
            delay = _retry_after(e)
            if delay is None:
                # exponential backoff + full jitter
                delay = random.uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (attempt - 1)))
            delay = min(delay, BACKOFF_CAP)
            print(f"{type(e).__name__}: retry {attempt}/{MAX_ATTEMPTS - 1} in {delay:.1f}s")
            time.sleep(delay)

MAX_TOKENS = 10000
MAX_STEPS = 10
history = []
def complete(messages: list, tools: list, policy: Policy):
  token_usage = 0
  try:
    steps = 0
    history.extend(messages)
    while True:
      if steps >= MAX_STEPS:
          print(f"Agent stopped due to: max_steps ({MAX_STEPS})")
          break
      if token_usage >= MAX_TOKENS:
          print(f"Agent stopped due to: max_tokens ({MAX_TOKENS})")
          break
      steps += 1
      response: Response = with_retries(lambda: client.responses.create(
          model=policy.value,
          input=history,
          tools=tools,
          max_output_tokens=1000,
          max_tool_calls=10
      ))
      token_usage += response.usage.input_tokens + response.usage.output_tokens
      history.extend(response.output)
      message: ResponseOutputItem = None
      tool_results = []
      for message in response.output:      
          print(message.type)
          match message.type:
              case 'reasoning':
                  print("Thinking...")
                  pass
              case 'message':
                  print("\n".join([x.text for x in message.content]))
                  pass
              case "function_call":
                  tool_results = execute_tool(message)
                  history.append(tool_results)
                  pass
      if len(tool_results) < 1:
          break
  except openai.APIError as e:
    # Non-retryable (400, 401, insufficient_quota...) or retries exhausted
    print(f"Agent stopped due to: {type(e).__name__}: {e}")
    raise
          
    
      
    

@app.post("/v1/responses")
def responses(message: Request):
  # Intent
  messages = [{"role": "user", "content": [{"type": "input_text", "text": message.intent}]}]
  model_enum = Policy.CHEAP
  try:
    # Decision
    decision = with_retries(lambda: client.decisions.create(
              model=Policy.CHEAP.value,
              input=messages,
              questions=[{
                "type": "score",
                "name": "score",
                "instructions": "How complex is this task?",
                "levels": [
                  {"label": "cheap", "description": "Low effort, cheap models with low-to-zero reasoning should suffice."},
                  {"label": "average", "description": "Medium effort, average models with mid reasoning should suffice."},
                  {"label": "expensive", "description": "Big effort, big models with reasoning required."}
                ]
              }]
          ))
    probabilities = [p.probability for p in decision.answers[0].probabilities]
    max_prob = max(probabilities)
    item_num = probabilities.index(max_prob)
    model_decision = decision.answers[0].probabilities[item_num].label

    match model_decision:
        case "average": model_enum = Policy.AVERAGE; pass
        case "expensive": model_enum = Policy.EXPENSIVE; pass
        case _ : pass
  except Exception as e:
      print(e)
      print(f"Falling back to {model_enum}")  

  return complete(messages, tools_schemas, model_enum)

  


if __name__ == "__main__":
  uvicorn.run(app, workers=1, host="0.0.0.0", port=8080)
