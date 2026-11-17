from anthropic import AsyncAnthropic
from anthropic.types import SystemMessageParam, UserMessageParam, Message, ContentBlock
import os
import asyncio
import inspect
from pydantic import TypeAdapter
from type_definitions.data_types import OutputCrash, DAG, DAG_NODE
from tools import tool_definitions, TOOLS_BY_NAME


MAX_TOKENS = 1000

async def schedule(dag: DAG):
    order: list[str] = []
    results: dict[str, str] = {}

    for node in dag.nodes:
        for arg in node.tool_args:
            if arg.startswith("$"):
                if arg not in order:
                    order.append(arg)
        order.append(node.id)

    for o in order:        
        if o in results:
            continue
        node = next(filter(lambda x: x.id == o, dag.nodes))
        tool_name = node.tool_name
        tool = TOOLS_BY_NAME[tool_name]
        params = list(inspect.signature(tool).parameters.values())
        tool_args = []
        for param, arg in zip(params, node.tool_args):
            if arg.startswith("$"):
                tool_args.append(results[arg])  # earlier tool's result: already the right type
            elif param.annotation is str:
                tool_args.append(arg)
            else:
                # "10" -> 10, '{"file": ...}' -> Crash, using the parameter's type annotation
                tool_args.append(TypeAdapter(param.annotation).validate_json(arg))
        results[node.id] = tool(*tool_args)
        print(f"{tool_name} {node.tool_args} {str(results[node.id])[:25]}")

async def llm_planner():
    client = AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    query = input("Please send me your stack trace:\n")

    system = """You are a stack trace analyzer that work in a Plan-And-Execute approach.
            You will get a list of tools that you can use to find old crashes and a new crash.
            Your task will be, by using tools, to be able to assign the owner and a priority,
            by taking a look at old crashes.

            For priority, return a number from 1 to 10, being 10 the highest priority.
            A high priority ticket is a ticket that:
                - either affects core functionality of the project, or
                - happens at start, or
                - happens very frequently

            Your output needs to be a DAG showing which tools to execute, with which parameters.
            In the fashion of ReWoo or LLM Compiler: one line per tool and when tools have dependencies,
            use $ and a number to ask for the result of that other first tool.
            Example:
            DAG=[
                DAG_NODE(id="$1", tool_name="list_files", tool_args=["src"]))
                DAG_NODE(id="$2", tool_name="show_lines_in_file", tool_args=["$1", 100, 200]
                ...
            ]
            """

    messages = [
        UserMessageParam(
            role="user",
            content=query
        )
    ]


    result: list[Message] = await client.messages.parse(
        max_tokens=MAX_TOKENS,
        messages=messages,
        model="claude-sonnet-5-5",
        system=system,
        tools=tool_definitions,
        output_format=DAG
    )

    output_dag : DAG | None = None
    for message in result:
        message_type = message[0]
        message_result = message[1]
        match message_type:
            case "content":
                content_block : ContentBlock = None
                for content_block in message_result:
                    match content_block.type:
                        case "thinking":
                            print("Thinking...")
                        case "text":
                            output_dag = content_block.parsed_output
            case "stop_reason":
                print(f"Stopped. Reason: {message_result}")
    
    await schedule(output_dag)

if __name__ == "__main__":
    asyncio.run(llm_planner())