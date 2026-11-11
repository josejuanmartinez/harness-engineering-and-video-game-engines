"""
EXERCISE 03: port the agent to the OpenAI API
Time: 30 min
Stack: OpenAI Python SDK (client.responses.create)
Requires: exercise 02 finished

TASK
Reimplement the exercise 02 agent with OpenAI's Responses API, reusing
exactly the same tool functions.

REQUIREMENTS
- Translate the tool definitions to the OpenAI format
- Detect the "function_call" items in response.output
- Return "function_call_output" items linked by call_id
- Manage the history yourself, then try previous_response_id
- Compare both with the same 5 questions: steps, tokens, cost, latency

DIFFERENCES YOU SHOULD BE ABLE TO EXPLAIN
- Tool format and tool schemas in each provider
- Content blocks vs output items
- How a tool error is returned
- Client-side vs server-side state
- Caching: explicit marking with cache_control vs automatic
- Reasoning: thinking/effort in one provider, reasoning models in the other

TO GO FURTHER
- Try the same tool description in both: which one interprets it better?
- Check the current version of the docs: this API changes often

QUESTIONS YOU MAY BE ASKED
- What can be abstracted across providers, and what is better not to abstract?
- How much does switching providers cost in a real product? Think about prompts and evals
"""

import inspect
from typing import get_type_hints
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from openai import Client
from openai.types.responses import Response
import json

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

def main() -> None:
    processing = False
    while not processing:        
        processing = True
        intent = input("What's your question? ")
        if intent.startswith("exit"):
            break
        
        # LOOP
        client = Client(api_key=os.getenv("OPENAI_API_KEY"))
        intent_message = {"role": "user", "content": intent}
        messages = [intent_message]
        response: Response = client.responses.create(
            model="gpt-6-luna",
            input=messages,
            tools=tools_schemas,
            max_output_tokens=1000,
            reasoning={"summary": "auto"},
        )        
        if response.error:
            print(f"Agent stopped due to: {response.error}")
            processing = False
            continue
        
        messages.extend(response.output)
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
            for content_block in response.output:
                print(content_block)
                if content_block.type == "function_call":
                    print(f"-> (... Agent is using tool: {content_block.name} with args: {content_block.arguments=} ...)")
                    tool_blocks.append(content_block)
                elif content_block.type == "message":
                    for c in content_block.content:
                        print(f"-> (... Agent response: {c.text} ...)")
                elif content_block.type == "reasoning":
                    print(f"-> (... Agent is thinking: {"\n".join(content_block.summary)} ...)")
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                tool_results = list(executor.map(lambda content_block: execute_tool(content_block), tool_blocks))                
                    
            if len(tool_results) <= 0:
                break
            else:
                messages.extend(tool_results)
                response: Response = client.responses.create(
                        model="gpt-6-luna",
                        input=messages,
                        tools=tools_schemas,
                        max_output_tokens=1000,
                        reasoning={"summary": "auto"},
                    )      
                token_usage += response.usage.input_tokens + response.usage.output_tokens
                messages.extend(response.output)
                if response.error:
                    print(f"Agent stopped due to: {response.error}")
                    processing = False
                    continue
              
        processing = False

if __name__ == "__main__":
    main()
