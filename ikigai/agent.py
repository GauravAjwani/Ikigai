from __future__ import annotations

from google.adk.agents.base_agent import BaseAgent
from google.adk.events.event import Event
from google.genai import types

from ikigai.pipeline import run_pipeline
from ikigai.schemas import Trigger


class IkigaiAgent(BaseAgent):
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


root_agent = IkigaiAgent(
    name="ikigai",
    description=(
        "Decision memory for Slack. @Ikigai in a channel replies in public. "
        "A direct message is a private chat."
    ),
)
