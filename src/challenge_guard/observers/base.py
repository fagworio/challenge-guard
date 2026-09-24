"""Contrato dos observadores.

Um observador transforma algo concreto (HTML, frames, metadata de rede, texto de
resposta) em sinais normalizados. Ele nao decide nada e nao guarda conteudo do
desafio: o que nao vira sinal nao sobrevive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import ChallengeProvider, ChallengeType
from ..signals import ChallengeSignal


@dataclass(frozen=True)
class ObserverResult:
    """O que um observador viu, ja normalizado."""

    source: str
    signals: tuple[ChallengeSignal, ...] = ()
    provider: ChallengeProvider = ChallengeProvider.UNKNOWN
    challenge_type: ChallengeType = ChallengeType.UNKNOWN
    #: Sinais estruturais para o fingerprint (forma, nunca conteudo).
    structure: tuple[str, ...] = ()
    confidence: float = 0.0
    notes: tuple[str, ...] = field(default=())

    @property
    def detected(self) -> bool:
        return bool(self.signals)


class ChallengeObserver(Protocol):
    name: str

    def observe(self, subject: object) -> ObserverResult: ...


def merge(results: list[ObserverResult]) -> ObserverResult:
    """Combina observadores independentes numa unica visao.

    O provider e escolhido pela maior confianca entre os que identificaram algo,
    e a estrutura e a uniao ordenada — ordem nao e estrutura.
    """
    sources: list[str] = []
    signals: list[ChallengeSignal] = []
    structure: set[str] = set()
    notes: list[str] = []
    provider = ChallengeProvider.UNKNOWN
    challenge_type = ChallengeType.UNKNOWN
    best = -1.0
    confidence = 0.0
    for result in results:
        if not result.signals and not result.structure:
            continue
        sources.append(result.source)
        signals.extend(result.signals)
        structure.update(result.structure)
        notes.extend(result.notes)
        confidence = max(confidence, result.confidence)
        if result.provider is not ChallengeProvider.UNKNOWN and result.confidence > best:
            provider = result.provider
            challenge_type = result.challenge_type
            best = result.confidence
    return ObserverResult(
        source="+".join(dict.fromkeys(sources)),
        signals=tuple(signals),
        provider=provider,
        challenge_type=challenge_type,
        structure=tuple(sorted(structure)),
        confidence=confidence,
        notes=tuple(notes),
    )
