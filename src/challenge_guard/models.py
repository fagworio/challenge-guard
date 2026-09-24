"""Modelo de dominio do Challenge Guard (CG-002).

Nenhum tipo aqui depende de browser, de ATS ou de candidatura. O vocabulario e
exclusivamente sobre tecnologias de challenge e sobre o ciclo de vida da
observacao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChallengeProvider(str, Enum):
    """Quem emite o desafio. Nunca o ATS que o hospeda."""

    UNKNOWN = "unknown"
    RECAPTCHA = "recaptcha"
    RECAPTCHA_ENTERPRISE = "recaptcha_enterprise"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"
    GENERIC = "generic"


class ChallengeType(str, Enum):
    """Tipo ESTRUTURAL observado.

    `IMAGE_SELECTION`, `TEXT` e `MATH` descrevem o que foi visto — jamais o que
    deveriamos resolver. Nao existe, e nao deve existir, um tipo "resolvido".
    """

    INVISIBLE = "invisible"
    CHECKBOX = "checkbox"
    IMAGE_SELECTION = "image_selection"
    TEXT = "text"
    MATH = "math"
    PUZZLE = "puzzle"
    RISK_ASSESSMENT = "risk_assessment"
    UNKNOWN = "unknown"

    @property
    def interactive(self) -> bool:
        """True apenas quando progredir exige acao humana explicita.

        `INVISIBLE` e `RISK_ASSESSMENT` avaliam sozinhos e podem liberar sem
        ninguem tocar em nada: exigir um humano por causa deles seria falso
        positivo. `UNKNOWN` tambem nao e tratado como interativo — na duvida o
        guard continua observando em vez de pedir uma pessoa.
        """
        return self in {
            ChallengeType.CHECKBOX,
            ChallengeType.IMAGE_SELECTION,
            ChallengeType.TEXT,
            ChallengeType.MATH,
            ChallengeType.PUZZLE,
        }


class ChallengePhase(str, Enum):
    """Onde, no fluxo do host, o desafio foi observado.

    E o que separa "desafio antes do envio" de "rejeicao anti-bot depois do
    envio" — a mesma tela, com desfechos opostos.
    """

    PAGE_LOAD = "page_load"
    FORM_DISCOVERY = "form_discovery"
    FORM_FILL = "form_fill"
    PRE_SUBMIT = "pre_submit"
    SUBMITTING = "submitting"
    POST_SUBMIT = "post_submit"


class ChallengeSessionStatus(str, Enum):
    DETECTED = "detected"
    ACTIVE = "active"
    ROUND_CHANGED = "round_changed"
    WAITING_FOR_HUMAN = "waiting_for_human"
    DISAPPEARED = "disappeared"
    PROVIDER_REJECTED = "provider_rejected"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class ChallengeDecisionStatus(str, Enum):
    NONE = "none"
    OBSERVE = "observe"
    NEEDS_HUMAN = "needs_human"
    PROVIDER_REJECTED = "provider_rejected"
    RESOLVED_EXTERNALLY = "resolved_externally"
    UNKNOWN = "unknown"


class ReasonToken(str, Enum):
    """Conjunto FECHADO de motivos.

    E o que sobrevive a redacao na auditoria: um motivo novo exige decisao
    explicita, porque e por ele que o host explica o desfecho sem guardar
    payload, token ou texto arbitrario do provedor.
    """

    CHALLENGE_ABSENT = "challenge_absent"
    CHALLENGE_OBSERVED_NON_INTERACTIVE = "challenge_observed_non_interactive"
    CHALLENGE_DETECTED_PRE_SUBMIT = "challenge_detected_pre_submit"
    CHALLENGE_DETECTED_INTERACTIVE = "challenge_detected_interactive"
    CHALLENGE_RESOLVED_EXTERNALLY = "challenge_resolved_externally"
    PROVIDER_REJECTED_SUBMISSION = "provider_rejected_submission"
    CHALLENGE_AFTER_WRITE_AWAITING_EVIDENCE = "challenge_after_write_awaiting_evidence"
    SUBMISSION_CONFIRMED_OVERRIDES_CHALLENGE = "submission_confirmed_overrides_challenge"
    CHALLENGE_AMBIGUOUS = "challenge_ambiguous"


@dataclass(frozen=True)
class ChallengeObservation:
    """Um retrato factual. Nao decide estado da aplicacao."""

    detected: bool
    phase: ChallengePhase
    provider: ChallengeProvider = ChallengeProvider.UNKNOWN
    challenge_type: ChallengeType = ChallengeType.UNKNOWN
    session_id: str = ""
    visible: bool = False
    browser_write_sent: bool = False
    http_status: int | None = None
    dom_signals: tuple[str, ...] = ()
    frame_signals: tuple[str, ...] = ()
    network_signals: tuple[str, ...] = ()
    response_signals: tuple[str, ...] = ()
    challenge_dimensions: tuple[int, int] | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("http_status must be a plausible status code")

    @property
    def evidence_sources(self) -> tuple[str, ...]:
        """Quais observadores contribuiram — sem revelar o que viram."""
        sources = []
        if self.dom_signals:
            sources.append("dom")
        if self.frame_signals:
            sources.append("frames")
        if self.network_signals:
            sources.append("network")
        if self.response_signals:
            sources.append("response")
        return tuple(sources)


@dataclass(frozen=True)
class ChallengeRoundObservation:
    """Cada mudanca estrutural relevante produz uma rodada."""

    session_id: str
    round_number: int
    observed_at: str
    visible: bool
    content_changed: bool
    structure_hash: str
    confidence: float
    evidence_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.round_number < 1:
            raise ValueError("round_number starts at 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass
class ChallengeSession:
    """O desafio como sessao com ciclo de vida, nao como booleano."""

    id: str
    provider: ChallengeProvider
    challenge_type: ChallengeType
    phase: ChallengePhase
    first_seen_at: str
    last_seen_at: str
    status: ChallengeSessionStatus = ChallengeSessionStatus.DETECTED
    rounds_observed: int = 0
    visible: bool = False
    dynamic_content: bool = False
    structure_hash: str = ""
    rounds: list[ChallengeRoundObservation] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status not in {
            ChallengeSessionStatus.COMPLETED,
            ChallengeSessionStatus.DISAPPEARED,
            ChallengeSessionStatus.PROVIDER_REJECTED,
        }

    @property
    def waits_for_human(self) -> bool:
        return self.status is ChallengeSessionStatus.WAITING_FOR_HUMAN


@dataclass(frozen=True)
class ChallengeDecision:
    status: ChallengeDecisionStatus
    provider: ChallengeProvider = ChallengeProvider.UNKNOWN
    reason_token: str = ""
    human_required: bool = False
    retry_allowed: bool = False
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.reason_token not in {token.value for token in ReasonToken}:
            raise ValueError(f"unsupported reason token: {self.reason_token}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
