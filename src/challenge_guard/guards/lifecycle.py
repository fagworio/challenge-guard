"""CG-026 — Browser Lifecycle Guard.

O ciclo de vida de um browser observado e onde os defeitos silenciosos moram.
Cada invariante abaixo existe porque a ausencia dela ja produziu um defeito
concreto em algum lugar:

```text
start uma vez        duas conexoes = dois donos da mesma pagina
attach uma vez       listener duplicado = o mesmo sinal contado duas vezes
navegacao -> reset   resposta da pagina ANTERIOR classificando a sessao atual
detach sempre        adapter antigo anexado a uma page que nao existe mais
close idempotente    fechar duas vezes derrubando um browser que nao e nosso
```

Este guard nao observa, nao decide e nao conhece challenge: ele so recusa a
sequencia invalida, com um erro que diz qual passo faltou. Estado explicito em vez
de bandeiras espalhadas — o defeito que ele previne aparece como excecao no
ponto do erro, e nao como classificacao errada tres camadas depois.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleViolation(RuntimeError):
    """Uma sequencia de lifecycle invalida foi tentada."""


class LifecycleState(str, Enum):
    NEW = "new"
    STARTED = "started"
    ATTACHED = "attached"
    CLOSED = "closed"


@dataclass
class BrowserLifecycle:
    """Maquina de estados explicita do browser e do adapter.

    `mark_navigation()`/`mark_reset()` existem para a invariante mais importante:
    dado transitorio (resposta, status, buffer) tem de ser descartado quando a
    pagina navega. O guard nao descarta nada — ele cobra que quem descarta o
    tenha feito, e `reset_pending` denuncia o contrario.
    """

    state: LifecycleState = LifecycleState.NEW
    adapter_name: str = ""
    session_name: str = ""
    starts: int = 0
    attaches: int = 0
    detaches: int = 0
    closes: int = 0
    navigations: int = 0
    resets: int = 0
    history: list[str] = field(default_factory=list)

    # -- transicoes ------------------------------------------------------------

    def mark_started(self, session_name: str = "") -> None:
        if self.state is LifecycleState.CLOSED:
            raise LifecycleViolation("session is closed; a new start requires a new session object")
        if self.state is not LifecycleState.NEW:
            raise LifecycleViolation(f"start called twice (state={self.state.value})")
        self.starts += 1
        self.session_name = session_name or self.session_name
        self.state = LifecycleState.STARTED
        self.history.append("start")

    def mark_attached(self, adapter_name: str = "") -> None:
        if self.state is LifecycleState.CLOSED:
            raise LifecycleViolation("session is closed; cannot attach an adapter")
        if self.state is LifecycleState.NEW:
            raise LifecycleViolation("attach before start: there is no page to observe")
        if self.state is LifecycleState.ATTACHED and adapter_name and self.adapter_name and adapter_name != self.adapter_name:
            # Dois adapters no mesmo monitor: o segundo sobrescreveria o primeiro
            # sem remover os listeners dele.
            raise LifecycleViolation(
                f"adapter {adapter_name!r} cannot replace {self.adapter_name!r}; detach first"
            )
        if self.state is not LifecycleState.ATTACHED:
            self.attaches += 1
            self.history.append("attach")
        self.adapter_name = adapter_name or self.adapter_name
        self.state = LifecycleState.ATTACHED

    def mark_detached(self) -> None:
        """Idempotente de proposito: `detach` no `finally` nunca pode falhar.

        Conta apenas o detach que TINHA o que destacar. Um segundo detach e
        no-op — inclusive no contador, para que `detaches` continue servindo de
        evidencia.
        """
        if self.state is LifecycleState.ATTACHED:
            self.detaches += 1
            self.history.append("detach")
            self.state = LifecycleState.STARTED
        self.adapter_name = ""

    def mark_navigation(self, url: str = "") -> None:
        if self.state is LifecycleState.NEW:
            raise LifecycleViolation("navigation before start")
        self.navigations += 1
        self.history.append("navigation")

    def mark_reset(self) -> None:
        self.resets += 1
        self.history.append("reset")

    def mark_closed(self) -> None:
        """Idempotente: fechar duas vezes nao pode ser erro nem efeito."""
        if self.state is LifecycleState.CLOSED:
            return
        self.closes += 1
        self.history.append("close")
        self.state = LifecycleState.CLOSED
        self.adapter_name = ""

    # -- invariantes consultaveis ---------------------------------------------

    @property
    def started(self) -> bool:
        return self.state in {LifecycleState.STARTED, LifecycleState.ATTACHED}

    @property
    def attached(self) -> bool:
        return self.state is LifecycleState.ATTACHED

    @property
    def closed(self) -> bool:
        return self.state is LifecycleState.CLOSED

    @property
    def reset_pending(self) -> bool:
        """Houve navegacao sem reset depois: dado transitorio potencialmente velho."""
        return self.navigations > self.resets

    def describe(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "session": self.session_name,
            "adapter": self.adapter_name,
            "starts": self.starts,
            "attaches": self.attaches,
            "detaches": self.detaches,
            "closes": self.closes,
            "navigations": self.navigations,
            "resets": self.resets,
            "reset_pending": self.reset_pending,
        }

    def assert_ready_for_observation(self) -> None:
        if self.state is LifecycleState.NEW:
            raise LifecycleViolation("observe before start")
        if self.state is LifecycleState.CLOSED:
            raise LifecycleViolation("observe after close")
        if self.reset_pending:
            raise LifecycleViolation(
                "navigation without reset: transient data from the previous page would be observed"
            )


__all__ = ["BrowserLifecycle", "LifecycleState", "LifecycleViolation"]
