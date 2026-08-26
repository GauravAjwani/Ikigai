from __future__ import annotations

from google.adk.agents.base_agent import BaseAgent
from google.adk.events.event import Event
from google.genai import types

from precedent.pipeline import run_pipeline
from precedent.schemas import Trigger


class PrecedentAgent(BaseAgent):
    """ADK agent wrapping the staged pipeline. Not a chat loop."""

    async def _run_async_impl(self, ctx):
        text = ""
        if ctx.user_content and ctx.user_content.parts:
            text = ctx.user_content.parts[0].text or ""
        result = await run_pipeline(
            Trigger(text=text, path="search", channel_id="C-PLATFORM")
        )
        payload = result.model_dump_json()
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=payload)]),
        )


root_agent = PrecedentAgent(
    name="precedent",
    description=(
        "Decision memory for Slack. Watches for reopened questions, "
        "retrieves prior decisions across vocabulary, and replies privately."
    ),
)
