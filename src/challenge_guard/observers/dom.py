"""DOM observer (CG-007).

Somente leitura e somente ESTRUTURA. O observador procura containers e
atributos que anunciam um widget; ele nunca le a pergunta do desafio, o texto
das instrucoes ou qualquer coisa que se pareca com uma resposta.

Marcadores vem do registry de providers, entao nao ha selector especifico de
ATS aqui — e um teste garante que nao passa a haver.
"""

from __future__ import annotations

import re

from ..models import ChallengeType
from ..providers.registry import PROFILES, profile_for
from ..signals import ChallengeSignal, ChallengeSignalKind
from .base import ObserverResult

_TAG = re.compile(r"<[^>]+>")


def _structural_tokens(html: str) -> list[str]:
    """Somente nomes de tag e atributos de classe/id/sitekey — nunca texto."""
    tokens: list[str] = []
    for tag in _TAG.findall(html or ""):
        lowered = tag.casefold()
        for attribute in ("class", "id", "data-sitekey", "data-hcaptcha-widget-id", "name"):
            match = re.search(rf'{attribute}\s*=\s*"([^"]*)"', lowered)
            if match:
                tokens.extend(part for part in re.split(r"[\s]+", match.group(1)) if part)
    return tokens


class DOMObserver:
    """Detecta a presenca estrutural de um challenge."""

    name = "dom"

    def observe(self, html: str) -> ObserverResult:
        tokens = _structural_tokens(html)
        if not tokens:
            return ObserverResult(source=self.name)

        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        for profile in PROFILES:
            matched = [marker for marker in profile.dom_markers if any(marker in token for token in tokens)]
            if not matched:
                continue
            # Um sinal por provider: varios marcadores casando sao corroboracao
            # da MESMA observacao, nao evidencias independentes. Emitir um sinal
            # por marcador inflaria a confianca sem nada ter sido observado a mais.
            structure.extend(matched)
            signals.append(
                ChallengeSignal(
                    kind=ChallengeSignalKind.CHALLENGE_VISIBLE,
                    source=self.name,
                    provider=profile.provider,
                    confidence=0.8,
                    detail=f"dom.{matched[0]}",
                )
            )
        if not signals:
            return ObserverResult(source=self.name, structure=())

        best = max(signals, key=lambda signal: signal.confidence)
        profile = profile_for(best.provider)
        challenge_type = profile.default_type if profile else ChallengeType.UNKNOWN
        if any("g-recaptcha" in token for token in tokens):
            challenge_type = ChallengeType.CHECKBOX
        return ObserverResult(
            source=self.name,
            signals=tuple(signals),
            provider=best.provider,
            challenge_type=challenge_type,
            structure=tuple(structure),
            confidence=best.confidence,
        )
