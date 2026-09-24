"""Sinais normalizados com proveniencia.

Observadores veem coisas concretas — um container no DOM, um iframe, um POST
para o runtime do provedor, um texto de resposta. A policy nao pode conhecer
esses detalhes: ela raciocina sobre conceitos.

O sinal e a fronteira entre os dois mundos:

    raw response
        -> ResponseObserver
        -> provider profile   (onde os textos concretos vivem)
        -> ChallengeSignal(kind=VERIFICATION_REJECTED)
        -> policy
        -> PROVIDER_REJECTED

`detail` carrega um TOKEN curto e controlado (o id do marcador que casou),
nunca o texto do provedor: um campo livre viraria, na pratica, um lugar para
despejar payload na evidencia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .models import ChallengeProvider


class ChallengeSignalKind(str, Enum):
    """Conceitos que a policy entende. Conjunto fechado."""

    #: Estrutura de challenge visivel (widget, container, iframe de desafio).
    CHALLENGE_VISIBLE = "challenge_visible"
    #: Trafego de METADADOS para o runtime do provedor.
    CHALLENGE_TRAFFIC = "challenge_traffic"
    #: O provedor pediu explicitamente que um challenge seja completado.
    CHALLENGE_REQUIRED = "challenge_required"
    #: O provedor recusou por nao conseguir verificar a origem do envio.
    VERIFICATION_REJECTED = "verification_rejected"
    #: Avaliacao de risco puramente automatica, sem interacao.
    RISK_ASSESSMENT_ONLY = "risk_assessment_only"


_SAFE_DETAIL = re.compile(r"^[a-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class ChallengeSignal:
    kind: ChallengeSignalKind
    source: str
    provider: ChallengeProvider = ChallengeProvider.UNKNOWN
    confidence: float = 0.0
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("a signal must name its source")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.detail and not _SAFE_DETAIL.match(self.detail):
            raise ValueError(
                "signal detail must be a short controlled token, never provider text"
            )

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind.value, self.source)


def strongest(signals: tuple[ChallengeSignal, ...], kind: ChallengeSignalKind) -> ChallengeSignal | None:
    """O sinal de maior confianca para um conceito, ou None."""
    matching = [signal for signal in signals if signal.kind is kind]
    if not matching:
        return None
    return max(matching, key=lambda signal: signal.confidence)


def has_kind(signals: tuple[ChallengeSignal, ...], *kinds: ChallengeSignalKind) -> bool:
    wanted = set(kinds)
    return any(signal.kind in wanted for signal in signals)


def independent_sources(signals: tuple[ChallengeSignal, ...]) -> tuple[str, ...]:
    """Fontes que emitiram sinal, cada uma contando UMA vez.

    Existe porque varios marcadores do mesmo observer foram, por um momento,
    tratados como evidencias independentes: dois seletores de DOM casando
    inflavam a confianca sem nada a mais ter sido observado.
    """
    return tuple(dict.fromkeys(signal.source for signal in signals if signal.source))


def source_votes(signals: tuple[ChallengeSignal, ...]) -> dict[str, ChallengeSignal]:
    """O sinal mais forte de cada fonte — um voto por fonte, no maximo."""
    votes: dict[str, ChallengeSignal] = {}
    for signal in signals:
        current = votes.get(signal.source)
        if current is None or signal.confidence > current.confidence:
            votes[signal.source] = signal
    return votes


def corroborated_confidence(signals: tuple[ChallengeSignal, ...]) -> float:
    """Confianca considerando corroboracao, nao volume.

    Deliberadamente simples: o maior voto manda, e cada fonte independente
    adicional acrescenta pouco. Nao e uma formula para maximizar numero — e para
    impedir que 15 sinais do mesmo observer valham 15 provas.
    """
    votes = source_votes(signals)
    if not votes:
        return 0.0
    best = max(signal.confidence for signal in votes.values())
    return min(1.0, best + 0.05 * (len(votes) - 1))
