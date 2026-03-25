import pytest
from chatcc.cost.tracker import CostTracker


def test_initial_cost_zero():
    tracker = CostTracker()
    assert tracker.total_cost == 0.0


def test_track_agent_cost():
    tracker = CostTracker()
    tracker.track_agent(0.001)
    tracker.track_agent(0.002)
    assert tracker.total_agent_cost == pytest.approx(0.003)


def test_track_claude_code_cost():
    tracker = CostTracker()
    tracker.track_claude_code(0.05)
    assert tracker.total_claude_code_cost == pytest.approx(0.05)


def test_budget_warning():
    tracker = CostTracker(budget_limit=1.0)
    tracker.track_claude_code(0.85)
    assert tracker.is_budget_warning is True


def test_no_warning_under_threshold():
    tracker = CostTracker(budget_limit=1.0)
    tracker.track_claude_code(0.5)
    assert tracker.is_budget_warning is False


def test_summary():
    tracker = CostTracker(budget_limit=10.0)
    tracker.track_agent(0.1)
    tracker.track_claude_code(1.5)
    summary = tracker.summary()
    assert "$0.1000" in summary
    assert "$1.5000" in summary
