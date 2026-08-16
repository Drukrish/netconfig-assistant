"""The RAG triad, judged by Claude via eval_model.judge_model() — never
DeepEval's own default (silently OpenAI) or its native AnthropicModel
(crashes on Sonnet 5's ThinkingBlock). See eval_model.py's docstring for both
bugs.

Faithfulness: does the answer only claim things the retrieved context
supports? Answer relevancy: does the answer actually address the question
asked? Contextual precision: are the highest-ranked retrieved chunks the
ones actually relevant to the question, not just any relevant chunk buried
in the top-k?

Runs against the live API and DB — real cost, real network calls, same as
every other "verified live" piece of this project. Parametrized over the
reviewed golden set only (conftest.golden_set filters to reviewed: true).
"""

import pytest
from deepeval.metrics import AnswerRelevancyMetric, ContextualPrecisionMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase

from app.services.cost import run as cost_run
from app.services.eval_model import judge_model
from app.services.generator import answer_question

PASS_THRESHOLD = 0.7  # starting point, not yet tuned - see the baseline task


def pytest_generate_tests(metafunc):
    """Needs the golden set at collection time, before fixtures resolve, so
    this re-reads the same file conftest.golden_set does rather than reusing
    it. If nothing's reviewed yet, parametrize with a single sentinel so the
    reason shows up in the test report instead of the suite silently
    collecting zero tests."""
    if "golden_item" not in metafunc.fixturenames:
        return

    import json
    from pathlib import Path

    path = Path(__file__).parent / "golden_set.json"
    reviewed = []
    if path.exists():
        items = json.loads(path.read_text(encoding="utf-8"))
        reviewed = [item for item in items if item.get("reviewed")]

    if reviewed:
        metafunc.parametrize("golden_item", reviewed, ids=[f"item{i['id']}" for i in reviewed])
    else:
        metafunc.parametrize("golden_item", [None], ids=["no_reviewed_golden_items"])


async def test_rag_triad(golden_item, db_session):
    if golden_item is None:
        pytest.skip(
            "golden_set.json has no items marked reviewed: true yet — run "
            "scripts/generate_golden_set.py then review each candidate by hand."
        )

    # Groups generation + all three judge calls under one cost.py run, same
    # idea as growth-os's withRun() — one number for "what did evaluating
    # this golden item cost", not four unrelated rows.
    async with cost_run(f"rag_triad:item{golden_item['id']}"):
        answered = await answer_question(db_session, golden_item["question"])

        if not answered.citation_check.passed:
            pytest.fail(
                f"citation guard rejected the answer before the triad could even "
                f"be judged: {answered.citation_check.reason}"
            )

        retrieval_context = [r.chunk.text for r in answered.retrieved]
        test_case = LLMTestCase(
            input=golden_item["question"],
            actual_output=answered.answer,
            retrieval_context=retrieval_context,
            expected_output=golden_item.get("source_excerpt"),
        )

        judge = judge_model()
        metrics = [
            FaithfulnessMetric(threshold=PASS_THRESHOLD, model=judge, async_mode=True),
            AnswerRelevancyMetric(threshold=PASS_THRESHOLD, model=judge, async_mode=True),
            ContextualPrecisionMetric(threshold=PASS_THRESHOLD, model=judge, async_mode=True),
        ]

        # Deliberately not deepeval.assert_test(): it drives its own internal
        # asyncio runner (nest_asyncio-based), which fights pytest-asyncio's
        # loop-per-test and corrupts every later test's asyncpg connection on
        # the shared engine (confirmed - the first live run of this suite
        # failed test 1 with a cancel-scope RuntimeError, then every
        # remaining test errored on the DB with InterfaceError, not a real
        # failure of the RAG pipeline). a_measure() runs inside the loop
        # pytest-asyncio already owns for this test, so there's no second
        # runner to conflict with.
        failures = []
        for metric in metrics:
            await metric.a_measure(test_case)
            if not metric.success:
                failures.append(f"{metric.__name__} scored {metric.score:.2f} (< {PASS_THRESHOLD}): {metric.reason}")

    assert not failures, "\n".join(failures)
