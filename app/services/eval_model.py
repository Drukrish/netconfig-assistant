"""DeepEval's judge model, wired to Claude directly rather than via
DeepEval's native AnthropicModel or its own default (OpenAI).

Two real problems with the alternatives, found by testing before trusting
either:

1. Leaving `model` unset on any DeepEval metric silently defaults to
   OpenAI - confirmed by reading initialize_model() directly:
   `elif isinstance(model, str) or model is None: return OpenAIModel(...)`.
   An unbudgeted second billing surface this project never signed up for.

2. DeepEval's own native `AnthropicModel` crashed on the first real call:
   `AttributeError: 'ThinkingBlock' object has no attribute 'text'`. Sonnet
   5 runs adaptive thinking by default (the same behaviour that caused
   growth-os's max_tokens truncation bug), and its response content can
   include a ThinkingBlock ahead of the actual text block. DeepEval's
   integration hardcodes `message.content[0].text`, assuming position 0 is
   always text. It isn't.

This wrapper reuses `ai.call_claude`, which was already built correctly for
exactly this: it filters response content by `type == "text"`, not by
position, so it's immune to the bug above. One client, one place that talks
to Anthropic, same as growth-os's "no SDK, one function" pattern - not a
second, differently-behaved path for eval judging.
"""

import json

from deepeval.models.base_model import DeepEvalBaseLLM
from pydantic import BaseModel

from app.services.ai import call_claude

JUDGE_MODEL_NAME = "claude-sonnet-5"


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    first, last = text.find("{"), text.rfind("}")
    if first == -1 or last == -1:
        raise ValueError(f"no JSON object found in judge output: {raw[:200]!r}")
    return json.loads(text[first : last + 1])


class ClaudeJudge(DeepEvalBaseLLM):
    def __init__(self, model_name: str = JUDGE_MODEL_NAME):
        self.model_name = model_name

    def load_model(self):
        return self.model_name

    def get_model_name(self) -> str:
        return self.model_name

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        full_prompt = prompt
        if schema is not None:
            full_prompt += (
                f"\n\nRespond with ONLY a JSON object matching this schema, no prose: "
                f"{schema.model_json_schema()}"
            )
        raw = await call_claude(full_prompt, max_tokens=1500, model=self.model_name)
        if schema is None:
            return raw
        return schema.model_validate(_extract_json(raw))

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        # DeepEval's sync path. Metrics in this project always run in
        # async_mode (see the harness in Week 4), so this exists to satisfy
        # the abstract base class, not because it's expected to run — but it
        # needs to actually work, not just exist, since a metric constructed
        # with async_mode=False (as in a quick manual check) will hit it.
        # get_event_loop() does not create a loop in a fresh thread on this
        # Python version; asyncio.run() does, and is the correct one-shot
        # call for a genuinely synchronous entry point.
        import asyncio

        return asyncio.run(self.a_generate(prompt, schema=schema))


def judge_model() -> ClaudeJudge:
    return ClaudeJudge()
