"""Shared fixtures for the Week 4 eval suite. db_session hits the real
Postgres+pgvector container (docker compose up -d must be running — no mock,
per this project's "never claim it works without a live check" rule).
golden_set loads tests/golden_set.json if present; tests that need it skip
with a clear message otherwise, rather than failing confusingly.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"


@pytest.fixture
async def db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(scope="session")
def golden_set() -> list[dict]:
    if not GOLDEN_SET_PATH.exists():
        pytest.skip(
            f"{GOLDEN_SET_PATH} not found — run "
            "`python -m scripts.generate_golden_set` first."
        )
    items = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    reviewed = [item for item in items if item.get("reviewed")]
    if not reviewed:
        pytest.skip(
            f"{GOLDEN_SET_PATH} exists but nothing is marked reviewed:true yet — "
            "these are unverified LLM-generated candidates, not trusted ground "
            "truth. Review each item by hand, then flip reviewed to true."
        )
    return reviewed
