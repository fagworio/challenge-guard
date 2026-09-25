"""CG-030 — Resolution Budget Guard.

Mesmo sem interagir com o desafio, o ciclo de observacao precisa de limites. O
modo de falha que ele evita nao e "demorou": e o laco que nunca termina, com o
host esperando por uma decisao que nao vem, e um processo que so morre quando
alguem mata.

```text
round 1 -> reobserva -> round 2 -> reobserva -> round 3 -> MAX -> EXPIRED
```

Tres limites, com nomes distintos porque as causas sao distintas:

```text
max_rounds            quantas vezes reobservamos
timeout_seconds       quanto esperamos por UMA acao humana
max_duration_seconds  quanto dura o ciclo inteiro
```

`EXPIRED` nunca e rejeicao: nada foi recusado, o tempo acabou. Por isso a
expiracao vira `HUMAN_OBSERVATION_TIMEOUT` na policy, e nao `PROVIDER_REJECTED`.

`max_duration_seconds` tem de ser >= `timeout_seconds`. Com valores iguais, o
limite de tempo vence a checagem de duracao pela ORDEM das verificacoes — a mesma
armadilha que apareceu no orquestrador do host, e por isso esta documentada e
testada aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: Relogio monotono injetavel. Tempo de parede nao serve para orcamento.
Clock = Callable[[], float]


class BudgetViolation(RuntimeError):
    """Um limite mal declarado, ou um consumo depois de esgotado."""


@dataclass(frozen=True)
class RuntimeLimits:
    max_rounds: int = 3
    timeout_seconds: float = 120.0
    max_duration_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise BudgetViolation("max_rounds must be at least 1")
        if self.timeout_seconds <= 0:
            raise BudgetViolation("timeout_seconds must be positive")
        if self.max_duration_seconds <= 0:
            raise BudgetViolation("max_duration_seconds must be positive")
        if self.max_duration_seconds < self.timeout_seconds:
            raise BudgetViolation("max_duration_seconds must be >= timeout_seconds")

    def describe(self) -> dict[str, float]:
        return {
            "max_rounds": self.max_rounds,
            "timeout_seconds": self.timeout_seconds,
            "max_duration_seconds": self.max_duration_seconds,
        }


@dataclass
class ResolutionBudget:
    """Contador de rounds e de tempo. Nao decide nada — informa."""

    limits: RuntimeLimits = field(default_factory=RuntimeLimits)
    clock: Clock = field(default=lambda: 0.0)
    #: `None` = ainda nao comecou. Um relogio monotonico pode COMECAR em zero, e
    #: usar `0.0` como sentinela fazia o orcamento parecer parado para sempre.
    started_at: float | None = None
    rounds: int = 0
    exhausted_by: str = ""

    def start(self) -> None:
        if self.started_at is None:
            self.started_at = float(self.clock())

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, float(self.clock()) - self.started_at)

    def remaining_seconds(self) -> float:
        if self.started_at is None:
            return float(self.limits.timeout_seconds)
        return max(0.0, float(self.limits.timeout_seconds) - self.elapsed())

    def expired(self) -> bool:
        """True quando QUALQUER limite estourou, nomeando o que estourou.

        Ordem explicita: rounds, tempo de espera, duracao total. Com valores
        iguais de `timeout_seconds` e `max_duration_seconds`, o primeiro vence —
        e `exhausted_by` diz qual foi, em vez de deixar o host adivinhar.
        """
        if self.rounds >= self.limits.max_rounds:
            self.exhausted_by = "max_rounds"
            return True
        elapsed = self.elapsed()
        if self.started_at is not None and elapsed >= float(self.limits.timeout_seconds):
            self.exhausted_by = "timeout_seconds"
            return True
        if self.started_at is not None and elapsed >= float(self.limits.max_duration_seconds):
            self.exhausted_by = "max_duration_seconds"
            return True
        return False

    def consume_round(self) -> int:
        if self.expired():
            raise BudgetViolation(f"round budget exhausted by {self.exhausted_by}")
        self.rounds += 1
        return self.rounds

    def describe(self) -> dict[str, object]:
        return {
            **self.limits.describe(),
            "rounds": self.rounds,
            "elapsed_seconds": round(self.elapsed(), 3),
            "expired": self.expired(),
            "exhausted_by": self.exhausted_by,
        }


__all__ = ["BudgetViolation", "ResolutionBudget", "RuntimeLimits"]
