"""Response observer (CG-010).

Converte texto de resposta em conceito normalizado, usando os marcadores do
provider. E o unico lugar onde um texto concreto do provedor pode aparecer.

Regras:

    status HTTP sozinho NUNCA decide
    marcador de provider + contexto podem produzir evidencia
    erros comuns de formulario continuam nao-CAPTCHA

O texto entra, o sinal sai, o texto nao e guardado. O `detail` do sinal e o
TOKEN do marcador (ex.: `error_verifying_application`), nunca a frase.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..providers.base import ChallengeProviderProfile
from ..providers.registry import PROFILES
from ..signals import ChallengeSignal
from .base import ObserverResult


@dataclass(frozen=True)
class ResponseRecord:
    """Uma resposta observada. `text` nunca e persistido."""

    status: int | None = None
    text: str = ""
    url: str = ""


class ResponseObserver:
    name = "response"

    def __init__(self, profiles: tuple[ChallengeProviderProfile, ...] = PROFILES) -> None:
        self._profiles = profiles

    def observe(self, records: list[ResponseRecord]) -> ObserverResult:
        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        for record in records:
            if not record.text:
                # Sem texto nao ha evidencia: um status isolado nao classifica
                # CAPTCHA, e trata-lo como tal produziria falso positivo em
                # qualquer validacao comum de formulario.
                continue
            for profile in self._profiles:
                marker = profile.marker_for(record.text)
                if marker is None:
                    continue
                structure.append(f"resp.{marker.token}")
                signals.append(
                    ChallengeSignal(
                        kind=marker.kind,
                        source=self.name,
                        provider=profile.provider,
                        confidence=marker.confidence,
                        detail=marker.token,
                    )
                )
        if not signals:
            return ObserverResult(source=self.name)
        best = max(signals, key=lambda signal: signal.confidence)
        return ObserverResult(
            source=self.name,
            signals=tuple(signals),
            provider=best.provider,
            confidence=best.confidence,
            structure=tuple(structure),
        )
