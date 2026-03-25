from __future__ import annotations


class CostTracker:
    def __init__(self, budget_limit: float | None = None):
        self.total_agent_cost: float = 0.0
        self.total_claude_code_cost: float = 0.0
        self.budget_limit = budget_limit

    @property
    def total_cost(self) -> float:
        return self.total_agent_cost + self.total_claude_code_cost

    @property
    def is_budget_warning(self) -> bool:
        if not self.budget_limit:
            return False
        return self.total_cost > self.budget_limit * 0.8

    def track_agent(self, cost: float) -> None:
        self.total_agent_cost += cost

    def track_claude_code(self, cost: float) -> None:
        self.total_claude_code_cost += cost

    def summary(self) -> str:
        lines = [
            f"主 Agent 费用: ${self.total_agent_cost:.4f}",
            f"Claude Code 费用: ${self.total_claude_code_cost:.4f}",
            f"总费用: ${self.total_cost:.4f}",
        ]
        if self.budget_limit:
            lines.append(f"预算上限: ${self.budget_limit:.2f}")
            if self.is_budget_warning:
                lines.append("⚠️ 费用已超过预算 80%")
        return "\n".join(lines)
