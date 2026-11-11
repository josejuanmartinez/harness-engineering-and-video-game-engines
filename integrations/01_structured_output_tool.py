"""
EXERCISE 01: classify crash reports with typed output
Time: 20 min
Stack: Anthropic SDK (client.messages.parse), Pydantic

TASK
Read data/crash_reports.jsonl and turn each report into a validated object, without
writing any parser by hand.

REQUIREMENTS
- Pydantic model CrashTriage: subsystem (Literal with the teams from owners.json),
  severity (Literal), summary, likely_cause, confidence (float between 0 and 1)
- Use client.messages.parse and read the result from response.parsed_output
- Never send the "label" field to the model
- Check stop_reason before reading the content ("refusal", "max_tokens")
- Handle errors with a chain of SDK exceptions, from most specific to
  most general: RateLimitError, APIStatusError, APIConnectionError
- Print input and output tokens and compute the cost per report

FOLLOW-UP
- Compare with strict: true on a tool. When would you use each one?
- Process everything with the Batches API and compare cost and latency

QUESTIONS YOU MAY GET
- What does a strict schema guarantee, and what doesn't it? (the shape yes, the truth no)
- Would you retry a failed validation? How many times and with what context?
- Why is forcing a tool to get JSON no longer needed?
"""

import json

from pydantic import BaseModel, Field
from typing import Literal, Optional
from anthropic import Client
from anthropic.types import ParsedMessage
from anthropic import RateLimitError, APIStatusError, APIConnectionError
import os

class CrashTriage(BaseModel):
    subsystem: Literal["unknown","rendering", "animation", "physics", "audio", "online", "tools"] = Field(None, description="Subsystem responsible for the crash")
    severity: Literal["low", "medium", "high", "critical"] = Field(..., description="Severity level of the crash")
    likely_cause: str = Field(..., description="Most probable cause of the crash")
    confidence: Optional[float] = Field(None, description="Confidence level of the triage")

class BashReport(BaseModel):
    id: str = Field(..., description="Unique identifier for the crash report")
    build: str = Field(..., description="Build version of the software")
    platform: str = Field(..., description="Platform on which the crash occurred")
    signal: str = Field(..., description="Signal or exception that caused the crash")
    stack: list[str] = Field(..., description="Stack trace at the time of the crash")
    log: str = Field(..., description="Relevant log messages leading up to the crash")
    occurrences: int = Field(..., description="Number of times this crash has occurred")
    label: CrashTriage = Field(..., description="Additional metadata for triaging the crash report")

schema = CrashTriage.model_json_schema()
schema["additionalProperties"] = False

PROMPT = """You are a crash report triage assistant. Given the following crash report, classify it into the CrashTriage model""";

MAX_RETRIES = 3
def main() -> None:
    with open("./integrations/data/crash_reports.jsonl", "r") as f:
        for line in f:
          if line.strip() == "":
             continue
          try:
            report: ParsedMessage = BashReport.model_validate_json(line)
          except Exception as e:
            print(f"Error validating line: {line}. Error: {e}")
            continue

          X, y = report.model_dump(exclude={"label"}), report.label
          retries = MAX_RETRIES
          errors = []
          finished = False                    
          message = {"role": "user", "content": f"{PROMPT}\n\n{str(X)}"}
          while not finished:
            try:
                messages = [message]
                if len(errors) > 0:
                    for error in errors:
                        error_message = {"role": "user", "content": f"Last attempt failed. Please try again.\n\nError:{str(error)}"}
                        messages.append(error_message)

                classification: ParsedMessage = Client(api_key=os.getenv("ANTHROPIC_API_KEY")).messages.parse(
                    model="claude-haiku-5-5",
                    messages=[message],
                    max_tokens=1000,
                    tools=[{
                        "name": "CrashTriage",
                        "description": "A tool for classifying crash reports into a structured format.",
                        "input_schema":schema,
                        "strict": True
                    }]
                )
            except (RateLimitError, APIStatusError, APIConnectionError) as e:
                print(f"API error for report ID {report.id}: {e}")
                break
            
            match classification.stop_reason:
                case "refusal":
                    print(f"Model refused to classify report ID {report.id}")
                    finished = True
                case "max_tokens":
                    print(f"Model hit max tokens for report ID {report.id}")  
                    finished = True
            
            print(f"Input tokens: {classification.usage.input_tokens}, Output tokens: {classification.usage.output_tokens}\n")
            for content_message in classification.content:
                if content_message.type == "tool_use" and content_message.name == "CrashTriage":
                    try:
                        output = CrashTriage.model_validate(content_message.input)
                        print(output)
                        print()
                        finished = True
                    except Exception as e:
                        print(f"Validation error for report ID {report.id}: {e}")
                        errors.append(e)
                        retries -= 1
                        finished = retries <= 0

if __name__ == "__main__":
    main()
