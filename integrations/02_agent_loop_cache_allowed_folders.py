"""
EXERCISE 02: agent with a manual loop
Time: 40 min
Stack: Anthropic SDK (client.messages.create), no frameworks

TASK
Write an agent loop by hand, without LangChain or similar. The agent answers
questions about the files in ../c, for example: "which exercises deal with
concurrency and which file covers them?".

TOOLS
- list_files(directory), search_code(pattern), read_file(path, start_line, end_line)
- All with strict: true, additionalProperties: false and a description that says
  when to use it
- Restrict paths to the ../c folder

REQUIREMENTS
- while stop_reason == "tool_use": execute and continue
- Append the full response.content to the history, not just the text
- Run parallel tools at the same time (ThreadPoolExecutor)
- Return ALL tool_result blocks in a single user message
- A failing tool returns is_error: true; the agent must not crash
- Stop conditions: max steps and max accumulated tokens
- Handle "max_tokens", "refusal" and "pause_turn"
- Print the trajectory: step, tool, arguments, duration

TRY IT
- A question with no answer in the repo: it must say so, not make it up
- A read_file on a file that does not exist
- ../../.env as a path: it must refuse

FOLLOW-UP
- Rewrite it with client.beta.messages.tool_runner and @beta_tool
- What do you lose and what do you gain? Also compare with the Claude Agent SDK
- Add a tool that returns a huge output: truncation and pagination

QUESTIONS YOU MAY GET
- How do you detect that the agent is going in circles without progressing?
- Why does splitting tool_results across several messages hurt parallelism?
- How many tools are too many? One generic bash tool or several specific ones?
"""
from anthropic import Client
from anthropic.types import ParsedMessage, Message
from anthropic.types import ToolResultBlockParam, ToolUseBlockParam
from anthropic import RateLimitError, APIStatusError, APIConnectionError
import inspect
from typing import get_type_hints
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from zmq import Enum
from functools import lru_cache

MAX_STEPS = 10
MAX_TOKENS = 10000

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
        "name": fn.__name__,
        "description": inspect.getdoc(fn) or "",
        "input_schema": {
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

def execute_tool(content_block: ToolUseBlockParam) -> ToolResultBlockParam:
    tool_name = content_block.name
    tool_input = content_block.input
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
            "tool_use_id": content_block.id,
            "type": "tool_result",
            "content": str(result),
            "is_error": False,
        }
    except Exception as e:
        return {
            "tool_use_id": content_block.id,
            "type": "tool_result",
            "content": str(e),
            "is_error": True,
        }

def main() -> None:
    processing = False
    while not processing:        
        processing = True
        intent = input("What's your question? ")
        if intent.startswith("exit"):
            break
        
        # LOOP
        client = Client(api_key=os.getenv("ANTHROPIC_API_KEY"))
        intent_message = {"role": "user", "content": intent}
        messages = [intent_message]
        response: Message = client.messages.create(
            model="claude-haiku-5-5",
            messages=messages,
            tools=tools_schemas,
            max_tokens=1000
        )        
        if response.stop_reason in ["refusal", "max_tokens"]:
            print(f"Agent stopped due to: {response.stop_reason}")
        messages.append({
            "role": "assistant",
            "content": response.content,  # includes thinking and tool_use blocks
        })
        steps = 0
        token_usage = response.usage.input_tokens + response.usage.output_tokens
        while True:
          if steps >= MAX_STEPS:
              print(f"Agent stopped due to: max_steps ({MAX_STEPS})")
              break
          if token_usage >= MAX_TOKENS:
              print(f"Agent stopped due to: max_tokens ({MAX_TOKENS})")
              break
          steps += 1
          tool_blocks = []
          tool_results = []
          for content_block in response.content:
              if content_block.type == "tool_use":
                  print(f"-> (... Agent is using tool: {content_block.name} with args: {content_block.input} ...)")
                  tool_blocks.append(content_block)
              elif content_block.type == "text":
                  print(f"-> (... Agent response: {content_block.text} ...)")
                  messages.append({
                      "role": "assistant",
                      "content": content_block.text,  # includes thinking and tool_use blocks
                  })
              elif content_block.type == "thinking":
                  print(f"-> (... Agent is thinking: {content_block.thinking} ...)")                            
                  messages.append({
                      "role": "assistant",
                      "content": content_block.thinking,  # includes thinking and tool_use blocks
                  })

              with ThreadPoolExecutor(max_workers=4) as executor:
                tool_results = list(executor.map(lambda content_block: execute_tool(content_block), tool_blocks))
                
          if len(tool_results) <= 0:
              break
          else:
              messages.append({
                  "role": "user",
                  "content": tool_results,  # includes thinking and tool_use blocks
              })
              response = client.messages.create(
                  model="claude-haiku-5-5",
                  messages=messages,
                  tools=tools_schemas,
                  max_tokens=1000
              )
              token_usage += response.usage.input_tokens + response.usage.output_tokens
              messages.append({
                  "role": "assistant",
                  "content": response.content,  # includes thinking and tool_use blocks
              })
              if response.stop_reason in ["refusal", "max_tokens"]:
                  print(f"Agent stopped due to: {response.stop_reason}")
                  break        
        processing = False

if __name__ == "__main__":
    main()
