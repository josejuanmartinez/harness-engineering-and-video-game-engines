"""
EXERCISE 15: autodiscovery of tools by catalogues
Stack: Anthropic SDK (messages.create with forced tool_choice, beta tool_runner), importlib

THE IDEA
With dozens of tools you don't want to send every definition on every request:
it costs tokens, hurts the cache and makes the model pick worse. Instead, group
the tools into CATALOGUES. Only a cheap index (name + description per catalogue)
is shown to the model first:

    1. The user writes a request.
    2. catalogue.json is loaded: [{name, description, module}, ...]
    3. ROUTING call: the model sees only the names + descriptions and must
       return ONE catalogue name (forced tool_choice + enum, so it can't invent one).
    4. The chosen catalogue's module is imported DYNAMICALLY from its file path
       (importlib) and its TOOLS list is read.
    5. AGENT call: tool_runner runs the loop with only those tools.

    Adding a new catalogue = drop a .py with a TOOLS list + one entry in the JSON.
    No change to this file.

QUESTIONS YOU MAY BE ASKED
- What if the request needs tools from two catalogues? (return a list of names)
- Executing a module named by a JSON file = running arbitrary code. How do you
  restrict it? (fixed base folder, path must resolve inside it, allowlist)
- How does this compare to Anthropic's tool search / defer_loading?
"""

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

from anthropic import Anthropic

BASE = Path(__file__).parent.resolve()
CATALOGUE_FILE = BASE / "catalogue.json"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 1000


def load_catalogue() -> list[dict]:
    return json.loads(CATALOGUE_FILE.read_text(encoding="utf-8"))


def choose_catalogue(client: Anthropic, catalogue: list[dict], query: str) -> str:
    """Routing step: the model only sees names + descriptions and picks one."""
    names = [c["name"] for c in catalogue] + ["none"]
    index = "\n".join(f"- {c['name']}: {c['description']}" for c in catalogue)
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=f"Pick the tool catalogue that can solve the user's request.\n"
               f"Available catalogues:\n{index}\nAnswer 'none' if no catalogue fits.",
        tools=[{
            "name": "select_catalogue",
            "description": "Select the catalogue whose tools solve the request.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "enum": names}},
                "required": ["name"],
            },
        }],
        tool_choice={"type": "tool", "name": "select_catalogue"},
        messages=[{"role": "user", "content": query}],
    )
    return next(b.input["name"] for b in response.content if b.type == "tool_use")


def load_tools(entry: dict) -> list:
    """Import the catalogue's module from its file and return its TOOLS list."""
    path = (BASE / entry["module"]).resolve()
    if not path.is_relative_to(BASE / "catalogues"):
        raise ValueError(f"Module '{entry['module']}' is outside the catalogues folder.")
    spec = importlib.util.spec_from_file_location(f"catalogue_{entry['name']}", path)
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TOOLS


def main() -> None:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    catalogue = load_catalogue()

    while (query := input("How can I help you? ").strip()) != "":
        name = choose_catalogue(client, catalogue, query)
        print(f"[catalogue] {name}")
        if name == "none":
            print("No catalogue can solve that request.")
            continue

        entry = next(c for c in catalogue if c["name"] == name)
        tools = load_tools(entry)
        print(f"[tools] {[t.name for t in tools]}")

        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=[{"role": "user", "content": query}],
        )
        for message in runner:
            for block in message.content:
                match block.type:
                    case "tool_use":
                        print(f"Calling tool {block.name} {block.input}")
                    case "text":
                        print(block.text)


if __name__ == "__main__":
    main()
