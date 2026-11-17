"""
EXERCISE 05: agent with HTTP streaming
Time: 30 min
Stack: Anthropic SDK (client.messages.stream), FastAPI, Server-Sent Events
Startup: call uvicorn.run(app) inside main and run python 05_streaming_api.py
(the name starts with a digit, so "uvicorn 05_streaming_api:app" can't import it).

TASK
Expose the exercise 02 agent on POST /chat and stream over SSE both the text and
the tool events, so a UI can show what it is doing.

REQUIREMENTS
- Custom events: text_delta, tool_start, tool_end, usage, error, done
- Enable eager_input_streaming: true on the tools if you stream their inputs
- In that case, validate the accumulated input yourself before running the tool: it may
  arrive incomplete. Check stop_reason before running it
- If the client disconnects, cancel the pending work
- Test with: curl -N -X POST localhost:8000/chat

TO GO FURTHER
- Show progress with thinking display "summarized"
- Reconnection: how does the client resume a cut-off stream?
- What metrics would you log? Time to first token, total duration, tokens/s

QUESTIONS YOU MAY BE ASKED
- What latency does the user perceive, and what is the real one?
- SSE or WebSocket? Why?
- How do you keep the server from running out of connections with long agents?
"""
import asyncio
import json
import os
import re
import time
from enum import Enum
from pathlib import Path

import uvicorn
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

app = FastAPI()
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 10000          # per model call
MAX_TOTAL_TOKENS = 50000    # accumulated over the whole agent run
MAX_STEPS = 10
ROOT = Path("./").resolve()


# --------------------------------------------------------------------------- #
# API models
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
  message: str = Field(..., description="Intent of the user")


class ContentBlockType(Enum):
  NONE = "unknown"
  THINKING = "thinking"
  TOOL_USE = "tool_use"   # matches the API's block type name
  TEXT = "text"


class ResponseMessage(BaseModel):
  type: ContentBlockType = Field(..., description="Type of content block")
  content: str = Field(..., description="Value of content block (a delta, not the accumulated text)")


def sse(event: str, payload: BaseModel | dict) -> str:
  data = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload, default=str)
  return f"event: {event}\ndata: {data}\n\n"


# --------------------------------------------------------------------------- #
# Tools (same as exercise 02)
# --------------------------------------------------------------------------- #
def check_safe_path(path: str) -> Path:
  resolved = (ROOT / path).resolve()
  if not resolved.is_relative_to(ROOT):
    raise ValueError("Path must stay inside the allowed directory.")
  return resolved


def list_files(directory: str) -> str:
  base = check_safe_path(directory)
  if not base.is_dir():
    raise ValueError(f"{directory} is not a valid directory.")
  return "\n".join(str(p.relative_to(ROOT)) for p in base.rglob("*") if p.is_file())


def search_code(pattern: str) -> str:
  regex = re.compile(pattern)
  matches = []
  for p in ROOT.rglob("*"):
    if p.is_file() and p.suffix in (".py", ".js", ".java", ".cpp", ".c"):
      with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for n, line in enumerate(f, start=1):
          if regex.search(line):
            matches.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
  return "\n".join(matches) or "No matches."


def read_file(path: str, start_line: int, end_line: int) -> str:
  p = check_safe_path(path)
  if not p.is_file():
    raise ValueError(f"{path} is not a valid file.")
  lines = p.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
  if start_line < 1 or end_line > len(lines) or start_line > end_line:
    raise ValueError(f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines).")
  return "".join(lines[start_line - 1:end_line])


# Pydantic models used to validate the streamed (possibly incomplete) tool input.
class ListFilesArgs(BaseModel):
  model_config = ConfigDict(extra="forbid")
  directory: str

class SearchCodeArgs(BaseModel):
  model_config = ConfigDict(extra="forbid")
  pattern: str

class ReadFileArgs(BaseModel):
  model_config = ConfigDict(extra="forbid")
  path: str
  start_line: int
  end_line: int


TOOLS = {
  "list_files": (list_files, ListFilesArgs,
                 "List every file under a directory (relative to the repo root). "
                 "Use it first to discover which files exist."),
  "search_code": (search_code, SearchCodeArgs,
                  "Search a regex across all code files in the repo. "
                  "Use it to find where a concept or symbol appears."),
  "read_file": (read_file, ReadFileArgs,
                "Read lines start_line..end_line (1-based, inclusive) of a file. "
                "Use it once you know which file and lines matter."),
}


def tool_schema(name: str) -> dict:
  _, args_model, description = TOOLS[name]
  schema = args_model.model_json_schema()
  return {
    "name": name,
    "description": description,
    "input_schema": {
      "type": "object",
      "properties": {k: {"type": v["type"]} for k, v in schema["properties"].items()},
      "required": schema.get("required", []),
      "additionalProperties": False,
    },
    # Input arrives token by token without server-side buffering/validation,
    # so we validate it ourselves (see validate_tool_input).
    "eager_input_streaming": True,
  }


TOOL_SCHEMAS = [tool_schema(n) for n in TOOLS]


def validate_tool_input(name: str, raw_json: str) -> dict:
  """Parse + validate the accumulated input_json_delta. Raises ValueError if unusable."""
  if name not in TOOLS:
    raise ValueError(f"Unknown tool: {name}")
  try:
    data = json.loads(raw_json or "{}")
  except json.JSONDecodeError as e:
    raise ValueError(f"Tool input is not valid JSON (possibly truncated): {e}") from e
  try:
    return TOOLS[name][1].model_validate(data).model_dump()
  except ValidationError as e:
    raise ValueError(f"Invalid tool input: {e}") from e


async def run_tool(tool: dict) -> dict:
  """Execute one tool in a worker thread. Never raises: errors become is_error results."""
  start = time.perf_counter()
  try:
    if tool["error"]:
      raise ValueError(tool["error"])
    fn = TOOLS[tool["name"]][0]
    content, is_error = await asyncio.to_thread(fn, **tool["input"]), False
  except Exception as e:
    content, is_error = str(e), True
  return {
    "tool_use_id": tool["id"],
    "name": tool["name"],
    "content": content,
    "is_error": is_error,
    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
  }


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@app.post("/v1/chat")
async def chat(body: ChatRequest, http_request: Request):

  async def event_stream():
    messages = [{"role": "user", "content": body.message}]
    total_in = total_out = 0
    t0 = time.perf_counter()
    first_token_at = None

    try:
      for step in range(1, MAX_STEPS + 1):
        tools_in_turn: dict[int, dict] = {}   # content block index -> tool info

        async with client.messages.stream(
          model=MODEL,
          max_tokens=MAX_TOKENS,
          messages=messages,
          tools=TOOL_SCHEMAS,
        ) as stream:
          async for chunk in stream:
            if await http_request.is_disconnected():
              # Leaving the `async with` closes the upstream connection to Anthropic.
              print("Client disconnected, cancelling.")
              return

            match chunk.type:
              case "content_block_start":
                if chunk.content_block.type == ContentBlockType.TOOL_USE.value:
                  tools_in_turn[chunk.index] = {
                    "id": chunk.content_block.id,
                    "name": chunk.content_block.name,
                    "raw": [],
                    "input": None,
                    "error": None,
                  }
                  yield sse("tool_start", {"id": chunk.content_block.id, "name": chunk.content_block.name})

              case "content_block_delta":
                match chunk.delta.type:
                  case "text_delta":
                    first_token_at = first_token_at or time.perf_counter()
                    yield sse("text_delta", ResponseMessage(type=ContentBlockType.TEXT, content=chunk.delta.text))
                  case "thinking_delta":
                    yield sse("thinking_delta", ResponseMessage(type=ContentBlockType.THINKING, content=chunk.delta.thinking))
                  case "input_json_delta":
                    tool = tools_in_turn[chunk.index]
                    tool["raw"].append(chunk.delta.partial_json)
                    yield sse("tool_input_delta", {"id": tool["id"], "partial_json": chunk.delta.partial_json})

              case "content_block_stop":
                if chunk.index in tools_in_turn:
                  tool = tools_in_turn[chunk.index]
                  try:
                    tool["input"] = validate_tool_input(tool["name"], "".join(tool["raw"]))
                  except ValueError as e:
                    tool["error"] = str(e)

              case "message_delta":
                # Only output_tokens is cumulative here; input comes in the final message.
                yield sse("usage", {"step": step, "output_tokens": chunk.usage.output_tokens})

          final = await stream.get_final_message()

        total_in += final.usage.input_tokens
        total_out += final.usage.output_tokens
        yield sse("usage", {"step": step, "input_tokens": final.usage.input_tokens,
                            "output_tokens": final.usage.output_tokens,
                            "total_input_tokens": total_in, "total_output_tokens": total_out})

        # Full content (text + thinking + tool_use) goes into history.
        messages.append({"role": "assistant", "content": final.content})

        match final.stop_reason:
          case "tool_use":
            pass  # handled below
          case "end_turn" | "stop_sequence":
            break
          case "pause_turn":
            continue  # server paused a long turn; resend so it continues
          case "max_tokens":
            # A tool_use block cut off here has incomplete input: do NOT execute it.
            yield sse("error", {"reason": "max_tokens", "message": "Response truncated by max_tokens.",
                                "unexecuted_tools": [t["name"] for t in tools_in_turn.values()]})
            break
          case "refusal":
            yield sse("error", {"reason": "refusal", "message": "The model refused to continue."})
            break
          case other:
            yield sse("error", {"reason": other, "message": f"Unexpected stop_reason: {other}"})
            break

        # stop_reason == "tool_use": run all tools in parallel, return all results in ONE user message.
        tasks = [asyncio.create_task(run_tool(t)) for t in tools_in_turn.values()]
        results = []
        try:
          for done in asyncio.as_completed(tasks):
            result = await done
            results.append(result)
            yield sse("tool_end", {
              "id": result["tool_use_id"],
              "name": result["name"],
              "is_error": result["is_error"],
              "duration_ms": result["duration_ms"],
              "preview": str(result["content"])[:500],
            })
            if await http_request.is_disconnected():
              print("Client disconnected during tools, cancelling.")
              return
        finally:
          for t in tasks:
            t.cancel()

        messages.append({"role": "user", "content": [
          {"type": "tool_result", "tool_use_id": r["tool_use_id"],
           "content": str(r["content"]), "is_error": r["is_error"]}
          for r in results
        ]})

        if total_in + total_out >= MAX_TOTAL_TOKENS:
          yield sse("error", {"reason": "token_budget", "message": f"Exceeded {MAX_TOTAL_TOKENS} tokens."})
          break
      else:
        yield sse("error", {"reason": "max_steps", "message": f"Stopped after {MAX_STEPS} steps."})

      elapsed = time.perf_counter() - t0
      yield sse("done", {
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "duration_s": round(elapsed, 2),
        "time_to_first_token_s": round(first_token_at - t0, 2) if first_token_at else None,
        "output_tokens_per_s": round(total_out / elapsed, 1) if elapsed else None,
      })

    except asyncio.CancelledError:
      # Starlette cancels the generator when the client goes away.
      print("Stream cancelled.")
      raise
    except Exception as e:
      yield sse("error", {"reason": type(e).__name__, "message": str(e)})

  return StreamingResponse(
    event_stream(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
  )


if __name__ == "__main__":
  uvicorn.run(app, workers=1, host="0.0.0.0", port=8080)
