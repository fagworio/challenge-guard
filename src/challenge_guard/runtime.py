"""CG-025 — `ChallengeRuntime`: a API unica do host.

Antes disto o host montava a composicao a mao: monitor, policy, sessao, limites,
journal. Cada host montava um pouco diferente, e a diferenca so aparecia no dia
em que um deles esquecia o reset depois da navegacao ou nao olhava o orcamento.

O runtime e essa composicao, com uma ordem fixa:

```text
start()       abre/liga o browser (ou aceita uma page) e marca a proveniencia
observe()     uma rodada de observacao -> ChallengeObservation
evaluate()    observa + decide (consome round)
revalidate()  observa DE NOVO, valida progresso e redecide
result()      ChallengeRuntimeResult (conjunto fechado de campos)
close()       detach + desconexao; nunca mata um browser que nao lancou
```

O que ele **nao** faz: interagir com a pagina, resolver desafio, enviar
candidatura. Nao ha metodo para isso, e os guards de arquitetura
(`guards/submission_isolation.py`, `guards/observation.py`) quebram o build se
alguem adicionar um.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Iterable

from .browser.cdp import BrowserSession, CdpEndpoint
from .guards.lifecycle import BrowserLifecycle, LifecycleViolation
from .guards.network_scope import NetworkScope, ScopedNetworkAdapter
from .guards.provenance import ProvenanceJournal
from .guards.sensitive_material import assert_no_sensitive_material
from .models import (
    ChallengeDecision,
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
)
from .monitor import ChallengeMonitor
from .resolution.capabilities import capability_for
from .resolution.limits import ResolutionBudget, RuntimeLimits
from .resolution.validator import ValidationResult, validate_progress

#: Vocabulario FECHADO do resultado. O host mapeia isto para o estado dele; o
#: runtime nao conhece estado de candidatura.
FINAL_STATUSES = frozenset(
    {
        "none",
        "observe",
        "human_required",
        "provider_rejected",
        "resolved_externally",
        "expired",
        "unknown",
    }
)

_DECISION_TO_STATUS = {
    ChallengeDecisionStatus.NONE: "none",
    ChallengeDecisionStatus.OBSERVE: "observe",
    ChallengeDecisionStatus.NEEDS_HUMAN: "human_required",
    ChallengeDecisionStatus.PROVIDER_REJECTED: "provider_rejected",
    ChallengeDecisionStatus.RESOLVED_EXTERNALLY: "resolved_externally",
    ChallengeDecisionStatus.UNKNOWN: "unknown",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ChallengeRuntimeResult:
    """O que o host recebe. Conjunto fechado, sem material do browser."""

    detected: bool
    decision: str
    final_status: str
    reason_token: str
    session_id: str = ""
    provider: str = ""
    challenge_type: str = ""
    phase: str = ""
    rounds: int = 0
    confidence: float = 0.0
    human_required: bool = False
    capability: str = ""
    backend: str = ""
    started_at: str = ""
    finished_at: str = ""
    budget: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.final_status not in FINAL_STATUSES:
            raise ValueError(f"unsupported final status: {self.final_status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        # O resultado e a superficie que o host imprime: material sensivel nao
        # atravessa daqui.
        assert_no_sensitive_material(self, where="runtime_result")

    def to_dict(self) -> dict[str, object]:
        return {
            "detected": self.detected,
            "decision": self.decision,
            "final_status": self.final_status,
            "reason_token": self.reason_token,
            "session_id": self.session_id,
            "provider": self.provider,
            "challenge_type": self.challenge_type,
            "phase": self.phase,
            "rounds": self.rounds,
            "confidence": self.confidence,
            "human_required": self.human_required,
            "capability": self.capability,
            "backend": self.backend,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "budget": dict(self.budget),
        }

    @property
    def needs_human(self) -> bool:
        """`expired` tambem pede uma pessoa: o tempo acabou e ninguem agiu."""
        return self.final_status in {"human_required", "expired"}


class ChallengeRuntime:
    """Composicao publica: browser + monitor + policy + sessao + limites + journal."""

    def __init__(
        self,
        *,
        page: Any | None = None,
        endpoint: CdpEndpoint | str | None = None,
        session: BrowserSession | None = None,
        adapter: Any | None = None,
        monitor: ChallengeMonitor | None = None,
        limits: RuntimeLimits | None = None,
        journal: ProvenanceJournal | None = None,
        confidence_threshold: float = 0.5,
    ) -> None:
        if page is not None and (endpoint is not None or session is not None):
            raise ValueError("pass either a page or a CDP session/endpoint, not both")
        self._page = page
        self._endpoint = (
            endpoint if endpoint is None or isinstance(endpoint, CdpEndpoint) else CdpEndpoint.from_url(str(endpoint))
        )
        self._session = session
        self._adapter = adapter
        self._monitor = monitor or ChallengeMonitor(confidence_threshold=confidence_threshold)
        self._journal = journal or ProvenanceJournal()
        self._lifecycle = BrowserLifecycle()
        self._budget = ResolutionBudget(limits or RuntimeLimits(), clock=time.monotonic)
        self._previous: ChallengeObservation | None = None
        self._validation: ValidationResult | None = None
        self._started = False
        #: O orcamento estourou NESTE ciclo. Flag explicita: o runtime nao
        #: descobre que expirou comparando o TEXTO do motivo da decisao.
        self._timed_out = False
        self._scope = NetworkScope.empty()
        self._scoped: ScopedNetworkAdapter | None = None
        self._last_url = ""

    # -- propriedades ----------------------------------------------------------

    @property
    def monitor(self) -> ChallengeMonitor:
        return self._monitor

    @property
    def journal(self) -> ProvenanceJournal:
        return self._journal

    @property
    def budget(self) -> ResolutionBudget:
        return self._budget

    @property
    def lifecycle(self) -> BrowserLifecycle:
        return self._lifecycle

    @property
    def scope(self) -> NetworkScope:
        return self._scope

    @property
    def scoped_adapter(self) -> ScopedNetworkAdapter | None:
        """O adapter que o observador de fato usa (escopo aplicado)."""
        return self._scoped

    @property
    def session(self) -> BrowserSession | None:
        return self._session

    @property
    def validation(self) -> ValidationResult | None:
        return self._validation

    @property
    def backend(self) -> str:
        if self._session is not None:
            return str(getattr(self._session, "name", type(self._session).__name__))
        if self._page is not None:
            return "page"
        return "core"

    @property
    def started(self) -> bool:
        return self._started

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> "ChallengeRuntime":
        if self._started:
            return self
        self._budget.start()
        self._lifecycle.mark_started(self.backend)
        if self._session is not None:
            self._page = self._session.start()
        self._scope = NetworkScope.from_providers()
        if self._page is not None:
            inner = self._adapter
            if inner is None:
                from .browser.playwright import PlaywrightChallengeAdapter

                inner = PlaywrightChallengeAdapter()
            # CG-028 aplicado: o observador nunca ve um registro fora do escopo
            # declarado. O wrapper e transparente no resto (nome, reset, URL), e
            # por isso o lifecycle e a proveniencia continuam falando do backend
            # real. `NetworkObserver` tambem so sinaliza hosts de provider; a
            # diferenca e que agora isso nao depende de o observador continuar
            # se comportando assim.
            self._scoped = ScopedNetworkAdapter(inner, self._scope)
            self._monitor.attach_adapter(self._scoped, self._page)
            self._lifecycle.mark_attached(self._scoped.name)
        self._started = True
        self._journal.emit(
            "runtime_started",
            backend=self.backend,
            started_at=_now(),
            notes="core" if self._page is None else "browser",
        )
        if self._endpoint is not None:
            # Proveniencia da conexao: host e porta, nunca a URL crua.
            self._journal.emit("runtime_started", backend=self.backend, **self._endpoint.describe())
        return self

    def close(self) -> None:
        """Detach e desconexao. Nunca mata um browser que nao foi lancado aqui.

        Nao ha parametro para fechar o browser remoto: posse e invariante
        (ADR 0007), e o host que lancou e quem desliga.
        """
        self._monitor.detach()
        self._lifecycle.mark_detached()
        if self._session is not None:
            close = getattr(self._session, "close", None)
            if callable(close):
                close()
        self._lifecycle.mark_closed()
        self._journal.emit("runtime_closed", backend=self.backend, finished_at=_now())
        self._started = False

    def __enter__(self) -> "ChallengeRuntime":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def reset(self) -> None:
        """Nova rodada no mesmo browser: descarta dado transitorio."""
        reset = getattr(self._session, "reset", None)
        if callable(reset):
            reset()
        self._monitor.reset()
        self._lifecycle.mark_reset()
        self._previous = None
        self._validation = None

    # -- observacao ------------------------------------------------------------

    def observe(
        self,
        *,
        phase: ChallengePhase = ChallengePhase.PRE_SUBMIT,
        http_status: int | None = None,
        response_texts: Iterable[str] = (),
        dom_html: str | None = None,
        browser_write_sent: bool = False,
        submission_confirmed: bool = False,
    ) -> ChallengeObservation:
        # Ordem das violacoes: "depois de fechar" e mais especifico que "antes de
        # comecar", e as duas sao verdade depois do close. A mensagem precisa
        # dizer o que aconteceu, nao o que parece.
        if self._lifecycle.closed:
            raise LifecycleViolation("observe after close")
        if not self._started:
            raise LifecycleViolation("observe before start")
        self._detect_navigation()
        self._lifecycle.assert_ready_for_observation()
        observation = self._monitor.observe(
            phase=phase,
            http_status=http_status,
            response_texts=response_texts,
            dom_html=dom_html,
            browser_write_sent=browser_write_sent,
            submission_confirmed=submission_confirmed,
        )
        scope_report: dict[str, int] = {}
        if self._scoped is not None:
            scope_report = self._scoped.describe_scope()
        self._journal.emit(
            "observation",
            session_id=observation.session_id,
            provider=observation.provider.value,
            challenge_type=observation.challenge_type.value,
            phase=observation.phase.value,
            detected=observation.detected,
            confidence=observation.confidence,
            round=self._budget.rounds,
            network_read=int(scope_report.get("network_read", 0)),
            network_dropped=int(scope_report.get("network_dropped", 0)),
        )
        return observation

    def evaluate(
        self,
        *,
        phase: ChallengePhase = ChallengePhase.PRE_SUBMIT,
        http_status: int | None = None,
        response_texts: Iterable[str] = (),
        dom_html: str | None = None,
        browser_write_sent: bool = False,
        submission_confirmed: bool = False,
    ) -> ChallengeDecision:
        """Observa uma rodada nova e decide. Consome round do orcamento."""
        if self._budget.expired():
            return self.timed_out()
        self._budget.consume_round()
        observation = self.observe(
            phase=phase,
            http_status=http_status,
            response_texts=response_texts,
            dom_html=dom_html,
            browser_write_sent=browser_write_sent,
            submission_confirmed=submission_confirmed,
        )
        self._previous = observation
        decision = self._monitor.decide(observation, submission_confirmed=submission_confirmed)
        self._record_decision(decision, observation, kind="decision")
        return decision

    def revalidate(
        self,
        *,
        phase: ChallengePhase = ChallengePhase.PRE_SUBMIT,
        http_status: int | None = None,
        response_texts: Iterable[str] = (),
        dom_html: str | None = None,
        browser_write_sent: bool = False,
        submission_confirmed: bool = False,
    ) -> ValidationResult:
        """Observa de novo e valida o progresso. `acao terminou != resolvido`."""
        if self._budget.expired():
            self.timed_out()
            self._validation = ValidationResult(
                progressed=False,
                resolved=False,
                reason_token="human_observation_timeout",
                detected_before=bool(self._previous.detected) if self._previous else False,
                detected_after=bool(self._previous.detected) if self._previous else False,
                write_seen=browser_write_sent,
            )
            return self._validation
        self._budget.consume_round()
        current = self.observe(
            phase=phase,
            http_status=http_status,
            response_texts=response_texts,
            dom_html=dom_html,
            browser_write_sent=browser_write_sent,
            submission_confirmed=submission_confirmed,
        )
        validation = validate_progress(
            previous=self._previous,
            current=current,
            browser_write_sent=browser_write_sent,
            submission_confirmed=submission_confirmed,
        )
        decision = self._monitor.decide(current, submission_confirmed=submission_confirmed)
        self._previous = current
        self._validation = validation
        self._record_decision(decision, current, kind="revalidation", validation=validation)
        return validation

    def timed_out(self) -> ChallengeDecision:
        """O orcamento acabou. Nunca e rejeicao: nada foi recusado, o tempo passou."""
        self._timed_out = True
        decision = self._monitor.timed_out()
        budget = self._budget.describe()
        self._journal.emit(
            "budget_exhausted",
            session_id=self._monitor.session.id if self._monitor.session is not None else "",
            provider=decision.provider.value,
            decision=decision.status.value,
            reason_token=decision.reason_token,
            timed_out=True,
            rounds=int(budget.get("rounds", 0)),
            max_rounds=int(budget.get("max_rounds", 0)),
        )
        return decision

    # -- resultado -------------------------------------------------------------

    def result(self) -> ChallengeRuntimeResult:
        observation = self._monitor.observation
        decision = self._monitor.decision
        if observation is None or decision is None:
            raise ValueError("result requires at least one evaluated observation")
        status = _DECISION_TO_STATUS[decision.status]
        if self._timed_out:
            status = "expired"
        return ChallengeRuntimeResult(
            detected=observation.detected,
            decision=decision.status.value,
            final_status=status,
            reason_token=decision.reason_token,
            session_id=observation.session_id,
            provider=decision.provider.value or observation.provider.value,
            challenge_type=observation.challenge_type.value,
            phase=observation.phase.value,
            rounds=self._budget.rounds,
            confidence=decision.confidence or observation.confidence,
            human_required=decision.human_required,
            # Capacidade e do TIPO observado. `WAIT_EXTERNAL` descreve a fase de
            # espera e fica disponivel para quem quiser descreve-la
            # (`capability_for(..., waiting_for_human=True)`), mas nao substitui a
            # capacidade declarada do desafio.
            capability=capability_for(observation.challenge_type).value,
            backend=self.backend,
            started_at=str(self._journal.events[0].get("started_at", "")) if self._journal.events else "",
            finished_at=_now(),
            budget=self._budget.describe(),
        )

    def handoff(self, page_url: str = "") -> Any:
        """O que a pessoa precisa fazer. Nao muda estado nenhum."""
        return self._monitor.handoff(page_url)

    # -- internos --------------------------------------------------------------

    def _detect_navigation(self) -> None:
        """Navegacao invalida dado transitorio: o guard cobra o reset.

        A URL nao e guardada em lugar nenhum — nem no journal. Ela e comparada e
        descartada, porque URL de candidatura carrega identificador de vaga e
        query com token, e proveniencia nao precisa disso.
        """
        url = self._current_url()
        if not url:
            return
        if self._last_url and url != self._last_url:
            self._lifecycle.mark_navigation()
            self.reset()
        self._last_url = url

    def _current_url(self) -> str:
        adapter = getattr(self._monitor, "adapter", None) or self._adapter
        getter = getattr(adapter, "current_url", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                return ""
        try:
            return str(getattr(self._page, "url", "") or "")
        except Exception:
            return ""

    def _record_decision(
        self,
        decision: ChallengeDecision,
        observation: ChallengeObservation,
        *,
        kind: str,
        validation: ValidationResult | None = None,
    ) -> None:
        self._journal.emit(
            kind,
            session_id=observation.session_id,
            provider=decision.provider.value,
            challenge_type=observation.challenge_type.value,
            phase=observation.phase.value,
            round=self._budget.rounds,
            decision=decision.status.value,
            reason_token=decision.reason_token,
            confidence=decision.confidence,
            detected=observation.detected,
            human_required=decision.human_required,
            capability=capability_for(observation.challenge_type).value,
            notes="validated" if validation is not None and validation.progressed else "",
        )


__all__ = ["ChallengeRuntime", "ChallengeRuntimeResult", "FINAL_STATUSES"]
