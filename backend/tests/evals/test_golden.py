"""Pytest parametrized entry point for golden eval cases.

Discovers all YAML files in the ``golden/`` directory, runs each through the
eval runner, and asserts all turns pass.  A final summary test checks the
overall pass rate is >= 90%.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tests.conftest import FakeMCPTools
from backend.tests.evals.runner import CaseResult, format_summary, load_cases, run_case

_GOLDEN_DIR = Path(__file__).parent / "golden"
_PASS_RATE_THRESHOLD = 0.90

# Discover cases at import time for parametrize
_golden_cases = load_cases(_GOLDEN_DIR) if _GOLDEN_DIR.exists() else []


def _case_id(case: dict) -> str:
    return case.get("id", "unknown")


@pytest.fixture(scope="module")
def golden_mcp() -> FakeMCPTools:
    """A fresh FakeMCPTools for the golden suite."""

    return FakeMCPTools()


@pytest.mark.parametrize("case", _golden_cases, ids=[_case_id(c) for c in _golden_cases])
async def test_golden_case(case: dict, golden_mcp: FakeMCPTools) -> None:
    """Run one golden conversation case and assert all turns pass."""

    result = await run_case(case, golden_mcp)
    failures: list[str] = []
    for turn in result.turns:
        for f in turn.failures:
            failures.append(f"Turn {turn.turn_index} ({turn.user_message[:40]}): {f}")
    assert not failures, "\n".join(failures)


async def test_golden_suite_pass_rate() -> None:
    """Meta-test: the golden suite must achieve >= 90% case-level pass rate."""

    if not _golden_cases:
        pytest.skip("No golden cases found")

    mcp = FakeMCPTools()
    results: list[CaseResult] = []
    for case in _golden_cases:
        results.append(await run_case(case, mcp))

    summary = format_summary(results, "golden")
    print(summary)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    rate = passed / total

    assert total >= 30, f"Need >= 30 golden cases, found {total}"
    assert rate >= _PASS_RATE_THRESHOLD, (
        f"Golden pass rate {rate:.1%} < {_PASS_RATE_THRESHOLD:.0%} "
        f"({passed}/{total} cases passed)"
    )
