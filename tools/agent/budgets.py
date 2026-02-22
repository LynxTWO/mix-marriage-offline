"""Budget enforcement for the agent REPL harness.

Hard caps prevent runaway graph builds and unbounded file reads.
Every charge_* method raises BudgetExceededError on first violation.

Usage::

    cfg = BudgetConfig(max_file_reads=60)
    b = Budgets(cfg)
    b.charge_file_read(line_count=200)   # raises if limit hit
    if b.is_exceeded:
        ...  # never reached after raise, but useful for post-checks
"""

from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass
class BudgetConfig:
    """Configurable hard-stop limits for one harness run.

    All limits are inclusive: a limit of N allows N units and stops on N+1.
    """

    max_steps: int = 40
    """Maximum number of logical operations (list_files, grep, etc.)."""

    max_file_reads: int = 60
    """Maximum number of individual file reads."""

    max_total_lines: int = 4000
    """Maximum cumulative lines read across all files."""

    max_grep_hits: int = 300
    """Maximum cumulative grep result lines."""

    max_graph_nodes_summary: int = 200
    """Cap for graph-node summary display (not a hard stop, just display cap)."""


@dataclasses.dataclass
class BudgetState:
    """Mutable runtime counters updated as the harness runs."""

    steps: int = 0
    file_reads: int = 0
    total_lines: int = 0
    grep_hits: int = 0
    graph_nodes: int = 0
    exceeded: Optional[str] = None
    """Name of the first budget that was exceeded, or None."""


class BudgetExceededError(RuntimeError):
    """Raised when a hard budget cap is hit.

    Attributes:
        budget_name: The name of the exceeded budget (e.g. ``"max_file_reads"``).
        value: The actual value that triggered the cap.
        limit: The configured cap.
    """

    def __init__(self, budget_name: str, value: int, limit: int) -> None:
        self.budget_name = budget_name
        self.value = value
        self.limit = limit
        super().__init__(
            f"Budget exceeded: {budget_name} reached {value} (limit {limit})"
        )


class Budgets:
    """Tracks and enforces hard budget caps across one harness run.

    All charge_* methods raise :class:`BudgetExceededError` on first violation.
    Once exceeded, ``is_exceeded`` is True and ``state.exceeded`` holds the name.

    Example::

        b = Budgets(BudgetConfig(max_file_reads=5))
        for path in many_files:
            b.charge_file_read(len(path.read_text().splitlines()))
    """

    def __init__(self, config: Optional[BudgetConfig] = None) -> None:
        self.config = config or BudgetConfig()
        self.state = BudgetState()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check(self, name: str, value: int, limit: int) -> None:
        """Mark exceeded and raise if value exceeds limit."""
        if value > limit:
            if self.state.exceeded is None:
                self.state.exceeded = name
            raise BudgetExceededError(name, value, limit)

    # ------------------------------------------------------------------
    # Charge methods
    # ------------------------------------------------------------------

    def charge_step(self) -> None:
        """Increment the logical-step counter and enforce the cap."""
        self.state.steps += 1
        self._check("max_steps", self.state.steps, self.config.max_steps)

    def charge_file_read(self, line_count: int) -> None:
        """Charge one file read plus its line count against both caps."""
        self.state.file_reads += 1
        self.state.total_lines += line_count
        self._check("max_file_reads", self.state.file_reads, self.config.max_file_reads)
        self._check("max_total_lines", self.state.total_lines, self.config.max_total_lines)

    def charge_grep_hits(self, count: int) -> None:
        """Charge *count* grep result lines."""
        self.state.grep_hits += count
        self._check("max_grep_hits", self.state.grep_hits, self.config.max_grep_hits)

    def set_graph_nodes(self, count: int) -> None:
        """Record the final graph-node count (display cap only, no hard stop)."""
        self.state.graph_nodes = count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def is_exceeded(self) -> bool:
        """True if any hard budget was hit during this run."""
        return self.state.exceeded is not None

    def summary(self) -> dict:
        """Return a dict snapshot of current budget state (stable key order)."""
        return dataclasses.asdict(self.state)
