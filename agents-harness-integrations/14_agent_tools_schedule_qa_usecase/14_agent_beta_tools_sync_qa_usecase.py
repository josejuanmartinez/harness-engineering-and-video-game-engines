from anthropic.types import  UserMessageParam, Message, ContentBlock
import os
from type_definitions.data_types import OutputCrash
from tools import TOOLS
from anthropic import Client
import json

MAX_TOKENS = 1000

def llm_planner():
    client = Client(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    query = input("Please send me your stack trace:\n")

    system = """You are a stack trace analyzer.
            You will get a list of tools that you can use to find old crashes and a new crash.
            Your task will be, by using tools, to be able to assign the owner and a priority,
            by taking a look at old crashes.

            For priority, return a number from 1 to 10, being 10 the highest priority.
            A high priority ticket is a ticket that:
                - either affects core functionality of the project, or
                - happens at start, or
                - happens very frequently
            """

    messages = [
        UserMessageParam(
            role="user",
            content=query
        )
    ]


    result: list[Message] = client.beta.messages.tool_runner(
        max_tokens=MAX_TOKENS,
        messages=messages,
        model="claude-sonnet-5-5",
        system=system,
        tools=TOOLS,
        output_format=OutputCrash
    )

    for message in result:
        if message.content:
            for content_block in message.content:
                match content_block.type:
                    case "thinking":
                        print("Thinking...")
                    case "tool_use":
                        print(f"Calling tool {content_block.name} {content_block.input}")                    
                    case "text":
                        print(content_block.text)
                    case "stop_reason":
                        print(f"Stopped. Reason: {message_result}")

if __name__ == "__main__":
    llm_planner()