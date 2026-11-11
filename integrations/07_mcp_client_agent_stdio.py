"""
EXERCISE 07: agent that uses tools over MCP
Time: 35 min
Stack: MCP Python SDK (ClientSession, stdio_client), Anthropic SDK
Requires: exercises 02 and 06 finished

TASK
Connect the exercise 02 loop to the exercise 06 server. The agent must not
know which tools exist until it discovers them at startup.

REQUIREMENTS
- Start the server over stdio and call session.initialize()
- Convert session.list_tools() to the Anthropic tools format
- Translate each tool_use into session.call_tool() and its result into tool_result
- Connect two servers at once, with name prefixes to avoid collisions
- If a server goes down, the agent keeps going with the other tools
- Allowlist: only approved tools are exposed to the model

TO GO FURTHER
- If you have dozens of tools, try tool search with defer_loading: true
- Measure how many tokens the tool definitions alone consume
- Close the session properly even if the agent fails

QUESTIONS YOU MAY BE ASKED
- What happens to the cache if the tool list changes between requests?
- How would you handle schema changes in a server that several agents depend on?
- Can you trust a tool description that comes from an external server?
"""

from mcp.client import Client as MCPClient
from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
import sys
import os
from pathlib import Path
import asyncio

SERVER = StdioServerParameters(
    command=sys.executable,  # the same python as the venv
    args=[str(Path(__file__).parent / "06_mcp_server_stdio.py")],
    cwd=str(Path(__file__).parent),
)

async def main() -> None:
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    async with stdio_client(SERVER) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        mcp_tools = (await session.list_tools()).tools
        tools = [{"name": t.name, "description": t.description or "",
            "input_schema": t.input_schema} for t in mcp_tools]
        while (s:= input("How can I help you? ").strip()) != "":
            messages = [{"role": "user", "content": s}]
            while True:
                response = await client.messages.create(
                    model="claude-haiku-5-5",
                    max_tokens=10000,
                    tools = tools,
                    messages=messages)
                
                messages.append({"role": "assistant", "content": response.content})                
                results = []
                for content_block in response.content:                     
                    if content_block.type == "text":
                        print(content_block.text)
                    if content_block.type == "tool_use":
                        r = await session.call_tool(content_block.name, content_block.input)
                        results.append({
                            "type": "tool_result", "tool_use_id": content_block.id,
                            "content": "\n".join(c.text for c in r.content if c.type == "text"),
                            "is_error": r.is_error,
                        })
                        messages.append({"role": "user", "content": results})
                if len(results) < 1:
                    break
                

if __name__ == "__main__":
    asyncio.run(main())
