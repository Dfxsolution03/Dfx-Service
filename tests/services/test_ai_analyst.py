"""DFX Backend Tests — Phase 2A: DFX Insight Engine (deterministic).

Pure, no-database tests for the formatting/rule helpers and the response schema.
The full analyze() path needs Postgres (TEST_DATABASE_URL), so it is not
exercised here.
"""
import pytest

from datetime import date

from app.schemas.report import AiAnalysisResponse, AiRecommendedAction, DateRangeInfo
from app.services.ai_analyst_service import AiAnalystService, _inr, _pct, _dir


def _rng():
    return DateRangeInfo(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31), label="This Month")


def test_formatting_helpers():
    assert _inr(125000) == "₹125,000"
    assert _pct(18.34) == "18.3%"
    assert _dir(5) == "increased"
    assert _dir(-2) == "decreased"


def test_empty_is_unavailable_with_insufficient_note():
    resp = AiAnalystService._empty("BUSINESS", _rng(), "No completed sales in this period.")
    assert resp.available is False
    assert resp.note.startswith("Insufficient data")
    assert resp.recommended_actions == []


def test_build_orders_actions_and_caps_lists():
    actions = [
        AiRecommendedAction(priority="LOW", title="c", explanation="c"),
        AiRecommendedAction(priority="HIGH", title="a", explanation="a"),
        AiRecommendedAction(priority="MEDIUM", title="b", explanation="b"),
    ]
    resp = AiAnalystService._build(
        "BUSINESS", _rng(), "summary",
        findings=[f"f{i}" for i in range(9)],
        opportunities=["o"], risks=["r"], actions=actions,
    )
    assert resp.available is True
    assert [a.priority for a in resp.recommended_actions] == ["HIGH", "MEDIUM", "LOW"]
    assert len(resp.key_findings) == 5  # capped
    assert resp.model == "DFX Insight Engine"


def test_summary_line_business_includes_growth_and_profit():
    line = AiAnalystService._summary_line("Business", "This Month", 200000, 18.0, 12, gold=15.5, profit=40000)
    assert "₹200,000" in line and "increased 18.0%" in line and "profit ₹40,000" in line


def test_summary_line_scheme_outstanding():
    line = AiAnalystService._summary_line("Scheme", "This Year", 500000, None, 30, outstanding=12000)
    assert "collections" in line and "₹12,000 outstanding" in line
    assert "increased" not in line  # None growth → no comparison stated


def test_recommended_action_metric_optional():
    a = AiRecommendedAction(priority="HIGH", title="t", explanation="e")
    assert a.metric is None
    d = AiAnalysisResponse(domain="SCHEME", range=_rng(), available=True, recommended_actions=[a]).model_dump(mode="json")
    assert d["recommended_actions"][0]["title"] == "t"
