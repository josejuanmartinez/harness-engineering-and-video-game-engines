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
from anthropic.types.messages import MessageBatch
from anthropic import RateLimitError, APIStatusError, APIConnectionError
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
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

def main() -> None:
    with open("./integrations/data/crash_reports.jsonl", "r") as f:
        reports: Request = []
        for line in f:
          if line.strip() == "":
             continue
          try:
            report: BashReport = BashReport.model_validate_json(line)
            reports.append(Request(
               custom_id=report.id,
               params=MessageCreateParamsNonStreaming(
                model="claude-haiku-5-5",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content":  f"{PROMPT}\n\n{str(report.model_dump(exclude={'label'}))}",
                    }
                ],
            ),
            ))
          except Exception as e:
            print(f"Error validating line: {line}. Error: {e}")
            continue

        client = Client(api_key=os.getenv("ANTHROPIC_API_KEY"))
        try:
          message_batch: MessageBatch = client.messages.batches.create(requests=reports)
          print(message_batch)          
        except (RateLimitError, APIStatusError, APIConnectionError) as e:
          print(f"API error for report ID {report.id}: {e}")
          exit(1)

        while message_batch.processing_status == "in_progress":
            message_batch = client.messages.batches.retrieve(message_batch.id)
            print(f"Batch {message_batch.id} processing status: {message_batch.processing_status}")            
        print(message_batch)
        """
        MessageBatch(id='msgbatch_01VfuhnyiFXgtuH6uwoZ4hv1', archived_at=None, cancel_initiated_at=None, created_at=datetime.datetime(2026, 11, 6, 11, 49, 52, 894778, tzinfo=datetime.timezone.utc), ended_at=datetime.datetime(2026, 11, 6, 11, 53, 32, 622220, tzinfo=TzInfo(0)), expires_at=datetime.datetime(2026, 11, 7, 11, 49, 52, 894778, tzinfo=datetime.timezone.utc), processing_status='ended', request_counts=MessageBatchRequestCounts(canceled=0, errored=0, expired=0, processing=0, succeeded=8), results_url='https://api.anthropic.com/v1/messages/batches/msgbatch_01VfuhnyiFXgtuH6uwoZ4hv1/results', type='message_batch')
        """

if __name__ == "__main__":
    main()
