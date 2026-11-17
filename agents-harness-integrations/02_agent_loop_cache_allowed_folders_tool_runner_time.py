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
from unittest import runner

from anthropic import Client
from anthropic.types import ParsedMessage, Message
from anthropic.types import ToolResultBlockParam, ToolUseBlockParam
from anthropic import RateLimitError, APIStatusError, APIConnectionError, beta_tool
import inspect
from typing import get_type_hints
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time
from zmq import Enum
from functools import lru_cache

MAX_STEPS = 10
MAX_TOKENS = 10000

ROOT = Path("./").resolve()  # Set this to the directory your tools may access.

def check_safe_path(path: str) -> Path:
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("Path must stay inside the allowed directory.")

@beta_tool
def list_files(directory: str) -> list[str]:
    """List all files in a directory and its subdirectories.
    
    Args:
        directory (str): The directory to list files from.
    """
    start = time.perf_counter()
    check_safe_path(directory)
    if not os.path.isdir(directory):
        raise ValueError(f"{directory} is not a valid directory.")
    file_list = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_list.append(os.path.join(root, file))
    elapsed = time.perf_counter() - start
    print(f"Elapsed: {elapsed:.3f} seconds")
    return "\n".join(file_list)

@beta_tool
def search_code(pattern: str) -> list[str]:
    """Search for a pattern in all code files in the ./ directory.
    
    Args:
        pattern (str): The pattern to search for.
    """
    import os
    import re
    start = time.perf_counter()
    matches = []
    for root, _, files in os.walk("./"):
        for file in files:
            if file.endswith((".py", ".js", ".java", ".cpp", ".c")):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, start=1):
                        if re.search(pattern, line):
                            matches.append(f"{file_path}:{line_number}: {line.strip()}")
    
    elapsed = time.perf_counter() - start
    print(f"Elapsed: {elapsed:.3f} seconds")
    return "\n".join(matches)

@beta_tool
def read_file(path: str, start_line: int, end_line: int) -> str:
    """Read a specific range of lines from a file.
    
    Args:
        path (str): The path to the file.
        start_line (int): The line to start reading from.
        end_line (int): The line to stop reading at.
    """
    start = time.perf_counter()
    check_safe_path(path)
    if not os.path.isfile(path):
        raise ValueError(f"{path} is not a valid file.")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise ValueError(f"Invalid line range: {start_line}-{end_line}.")
        
        elapsed = time.perf_counter() - start
        print(f"Elapsed: {elapsed:.3f} seconds")
        return "".join(lines[start_line - 1:end_line])


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
        runner = client.beta.messages.tool_runner(
            model="claude-haiku-5-5",
            messages=messages,
            tools=[list_files, search_code, read_file],
            max_tokens=1000
        )        
        steps = 0
        message = None
        for message in runner:            
            if steps >= MAX_STEPS:
                print(f"Agent stopped due to: max_steps ({MAX_STEPS})")
                break
            token_usage = message.usage.input_tokens + message.usage.output_tokens
            
            if token_usage >= MAX_TOKENS:
                print(f"Agent stopped due to: max_tokens ({MAX_TOKENS})")
                break
            steps += 1
            for content_block in message.content:
                if content_block.type == "tool_use":
                    tool_name = content_block.name
                    tool_input = content_block.input
                    print(f"Step {steps}: Tool use: {tool_name} with input {tool_input}")
                elif content_block.type == "tool_result":
                    print(f"Step {steps}: Tool result: {content_block.content}")  
                elif content_block.type == "message":
                    print(f"Step {steps}: Message: {content_block.content}")
                elif content_block.type == "pause_turn":
                    print(f"Step {steps}: Pause turn: {content_block.content}")
                elif content_block.type == "refusal":
                    print(f"Step {steps}: Refusal: {content_block.content}")
                elif content_block.type == "thinking":
                    print(f"Step {steps}: Thinking: {content_block.thinking}")
                elif content_block.type == "text":
                    print(f"Step {steps}: Text: {content_block.text}")
        processing = False

if __name__ == "__main__":
    main()
