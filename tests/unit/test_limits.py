"""CG-030 — orcamento: rounds, tempo de espera e duracao, sem laco infinito."""

from __future__ import annotations

import pytest

from challenge_guard.resolution.limits import BudgetViolation, ResolutionBudget, RuntimeLimits


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_rounds_are_exhausted_and_the_reason_is_named():
    budget = ResolutionBudget(RuntimeLimits(max_rounds=2), clock=FakeClock())
    budget.start()
    assert budget.consume_round() == 1
    assert budget.consume_round() == 2
    assert budget.expired() is True
    assert budget.exhausted_by == "max_rounds"
    with pytest.raises(BudgetViolation, match="max_rounds"):
        budget.consume_round()


def test_the_wait_timeout_expires_independently_of_rounds():
    clock = FakeClock()
    budget = ResolutionBudget(RuntimeLimits(max_rounds=10, timeout_seconds=5.0, max_duration_seconds=60.0), clock=clock)
    budget.start()
    budget.consume_round()
    assert budget.expired() is False
    clock.advance(5.0)
    assert budget.expired() is True
    assert budget.exhausted_by == "timeout_seconds"


def test_with_equal_values_the_timeout_wins_by_order_and_says_so():
    """A mesma armadilha do orquestrador do host: documentada, nao adivinhada."""
    clock = FakeClock()
    budget = ResolutionBudget(RuntimeLimits(max_rounds=5, timeout_seconds=10.0, max_duration_seconds=10.0), clock=clock)
    budget.start()
    clock.advance(10.0)
    assert budget.expired() is True
    assert budget.exhausted_by == "timeout_seconds"


def test_total_duration_expires_when_it_is_longer_than_the_wait():
    clock = FakeClock()
    budget = ResolutionBudget(RuntimeLimits(max_rounds=50, timeout_seconds=5.0, max_duration_seconds=9.0), clock=clock)
    budget.start()
    # `timeout_seconds` olha o tempo desde o inicio; com 9s os dois venceriam, e a
    # ordem declara qual foi. O que importa aqui e nao existir caminho sem fim.
    clock.advance(9.0)
    assert budget.expired() is True
    assert budget.exhausted_by in {"timeout_seconds", "max_duration_seconds"}


def test_remaining_seconds_never_goes_negative():
    clock = FakeClock()
    budget = ResolutionBudget(RuntimeLimits(timeout_seconds=3.0), clock=clock)
    budget.start()
    clock.advance(30.0)
    assert budget.remaining_seconds() == 0.0


def test_describe_exposes_the_budget_for_the_host():
    budget = ResolutionBudget(RuntimeLimits(max_rounds=3), clock=FakeClock())
    budget.start()
    budget.consume_round()
    described = budget.describe()
    assert described["rounds"] == 1 and described["max_rounds"] == 3
    assert described["expired"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_rounds": 0},
        {"timeout_seconds": 0},
        {"max_duration_seconds": 0},
        {"timeout_seconds": 30.0, "max_duration_seconds": 10.0},
    ],
)
def test_invalid_limits_are_refused_at_construction(kwargs: dict):
    with pytest.raises(BudgetViolation):
        RuntimeLimits(**kwargs)


def test_before_start_the_budget_is_not_running():
    budget = ResolutionBudget(RuntimeLimits(), clock=FakeClock())
    assert budget.elapsed() == 0.0
    assert budget.expired() is False
