"""Token accounting for every Claude call — ported line-for-line from
growth-os's src/lib/cost.ts (same rates, same run-grouping idea,
Postgres instead of SQLite, contextvars instead of AsyncLocalStorage;
Python's contextvars.ContextVar is the direct equivalent - each asyncio
Task gets its own copy at creation, so concurrent calls don't leak into
each other's run).
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.llm_run import LlmRun


class SpendCeilingExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass(frozen=True)
class Rate:
    input: float
    output: float


# USD per million tokens, matched by model-id prefix. Sonnet 5 list price is
# $3/$15 - the $2/$10 below is Anthropic's introductory rate, which runs
# through 2026-08-31 (same expiry noted in growth-os's cost.ts). Change to
# 3/15 on 2026-09-01 or every cost figure after that date reads ~33% low.
RATES_PER_MTOK: list[tuple[str, Rate]] = [
    ("claude-sonnet-5", Rate(input=2, output=10)),
    ("claude-haiku-4-5", Rate(input=1, output=5)),
]

# Cache writes bill at 1.25x the input rate, cache reads at 0.1x.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def _rate_for(model: str) -> Rate | None:
    for prefix, rate in RATES_PER_MTOK:
        if model.startswith(prefix):
            return rate
    return None


def cost_usd(model: str, usage: Usage) -> float | None:
    """Cost of one call in USD, or None for a model with no rate on file -
    None rather than 0 so an unpriced model shows up as a gap, not a free
    call."""
    rate = _rate_for(model)
    if rate is None:
        return None
    per_token = rate.input / 1_000_000
    return (
        usage.input_tokens * per_token
        + usage.cache_creation_tokens * per_token * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_tokens * per_token * CACHE_READ_MULTIPLIER
        + usage.output_tokens * rate.output / 1_000_000
    )


_run_context: ContextVar[tuple[str, str] | None] = ContextVar("_run_context", default=None)


class run:
    """Groups every call made inside this async context manager under one
    run_id. Nested uses join the outer run rather than starting their own -
    mirrors withRun() wrapping runIdeas/runHooks under one week-plan run."""

    def __init__(self, label: str):
        self.label = label
        self._token = None

    async def __aenter__(self):
        if _run_context.get() is None:
            self._token = _run_context.set((str(uuid.uuid4()), self.label))
        return self

    async def __aexit__(self, *exc):
        if self._token is not None:
            _run_context.reset(self._token)


async def total_spend_usd() -> float:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.coalesce(func.sum(LlmRun.cost_usd), 0.0)))
        return float(result.scalar_one())


async def check_spend_ceiling() -> None:
    """Called before every Claude request, not after - the point is refusing
    the call, not reporting the overspend once it's already happened again."""
    spent = await total_spend_usd()
    if spent >= settings.spend_ceiling_usd:
        raise SpendCeilingExceeded(
            f"Recorded spend (${spent:.2f}) has hit the ${settings.spend_ceiling_usd:.2f} ceiling "
            f"(app.config.settings.spend_ceiling_usd / SPEND_CEILING_USD in .env). "
            f"Raise it deliberately if you mean to keep spending, don't just retry."
        )


async def record_llm_call(role: str, model: str, usage: Usage) -> None:
    """Record one API call. Never raises: a failed cost write must not kill
    a generation the caller is waiting on."""
    try:
        current = _run_context.get()
        run_id, run_label = current if current else (str(uuid.uuid4()), role)
        async with AsyncSessionLocal() as session:
            session.add(
                LlmRun(
                    run_id=run_id,
                    run_label=run_label,
                    role=role,
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_tokens=usage.cache_creation_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cost_usd=cost_usd(model, usage),
                )
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001 - deliberately swallow, see docstring
        print(f"[cost] failed to record LLM call: {e}")


def demo() -> None:
    """Run with `python -m app.services.cost` - asserts the money math,
    same cases as cost.ts's demo()."""

    def assert_(ok: bool, msg: str) -> None:
        if not ok:
            raise AssertionError(msg)

    plain = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert_(cost_usd("claude-sonnet-5", plain) == 12, "sonnet 1M in + 1M out = $2 + $10")
    assert_(
        cost_usd("claude-haiku-4-5-20251001", plain) == 6,
        "date-suffixed haiku id must match by prefix: $1 + $5",
    )
    assert_(cost_usd("some-other-model", plain) is None, "unpriced model returns None, not 0")

    cached = Usage(input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000)
    # $1 * 1.25 write + $1 * 0.1 read
    assert_(cost_usd("claude-haiku-4-5", cached) == 1.35, "cache write 1.25x + read 0.1x")
    print("cost.py self-check passed")


if __name__ == "__main__":
    demo()
