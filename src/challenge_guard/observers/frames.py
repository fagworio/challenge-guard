"""Frame observer (CG-008).

Classifica por HOST e forma. Nunca acessa conteudo cross-origin: o que existe
aqui e a URL do frame, se ele esta visivel e o tamanho.

Duas regras que evitam os falsos positivos mais comuns:

    iframe presente != challenge ativo
    widget residual depois de uma submissao confirmada nao rebaixa o resultado

A primeira e resolvida aqui (frame conta como sinal, nao como veredito); a
segunda pertence a policy, que nunca rebaixa `submission_confirmed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import ChallengeType
from ..providers.registry import profile_for, profile_for_host
from ..signals import ChallengeSignal, ChallengeSignalKind
from .base import ObserverResult

#: Abaixo disto o frame e considerado decorativo (selo de 1x1, tracking).
_MIN_CHALLENGE_SIDE = 40


@dataclass(frozen=True)
class FrameInfo:
    url: str
    visible: bool = True
    width: int = 0
    height: int = 0

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").casefold()

    @property
    def path(self) -> str:
        return urlsplit(self.url).path or "/"

    @property
    def sizable(self) -> bool:
        return max(self.width, self.height) >= _MIN_CHALLENGE_SIDE


class FrameObserver:
    name = "frames"

    def observe(self, frames: list[FrameInfo]) -> ObserverResult:
        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        for frame in frames:
            profile = profile_for_host(frame.host)
            if profile is None:
                continue
            # Forma entra no fingerprint sempre; o SINAL exige visibilidade e
            # tamanho plausivel, porque um iframe escondido nao bloqueia nada.
            structure.append(f"{frame.host}{frame.path}")
            if not (frame.visible and frame.sizable):
                continue
            signals.append(
                ChallengeSignal(
                    kind=ChallengeSignalKind.CHALLENGE_VISIBLE,
                    source=self.name,
                    provider=profile.provider,
                    confidence=0.75,
                    detail=f"frame.{profile.provider.value}",
                )
            )
        if not signals:
            return ObserverResult(source=self.name, structure=tuple(structure))
        best = max(signals, key=lambda signal: signal.confidence)
        profile = profile_for(best.provider)
        return ObserverResult(
            source=self.name,
            signals=tuple(signals),
            provider=best.provider,
            challenge_type=profile.default_type if profile else ChallengeType.UNKNOWN,
            structure=tuple(structure),
            confidence=best.confidence,
        )
