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

#: Blocos que nao descrevem a pagina renderizada.
#:
#: Sem isto, um marcador escrito DENTRO do JavaScript (`innerHTML = '<div
#: class="h-captcha">'`) era lido como se fosse DOM: um falso positivo que nunca
#: desaparecia, porque o texto do script permanece depois de o widget sair. O
#: defeito apareceu num teste com browser real, em que o challenge era removido
#: e a sessao continuava ACTIVE.
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _tag_tokens(html: str) -> list[list[str]]:
    """Tokens estruturais POR TAG: classes, ids e atributos anunciados.

    Agrupados por tag porque o fingerprint precisa da estrutura DO ELEMENTO do
    challenge, nao de um saco de tokens da pagina inteira. E a classe do proprio
    widget que muda entre rodadas (`grid-4x4` -> `grid-5x5`); incluir classes de
    toda a pagina produziria rodada nova a cada mudanca irrelevante.

    Nada de texto: so atributos.
    """
    groups: list[list[str]] = []
    for tag in _TAG.findall(_SCRIPT_OR_STYLE.sub(" ", html or "")):
        lowered = tag.casefold()
        tokens: list[str] = []
        for attribute in ("class", "id", "name"):
            match = re.search(rf'{attribute}\s*=\s*"([^"]*)"', lowered)
            if match:
                tokens.extend(part for part in re.split(r"[\s]+", match.group(1)) if part)
        # Atributos cujo VALOR e sensivel entram apenas como PRESENCA. O sitekey
        # identifica a conta do provedor: saber que o atributo existe e o fato
        # estrutural; guardar o valor nao acrescenta nada e vaza.
        for attribute in ("data-sitekey", "data-hcaptcha-widget-id"):
            if re.search(rf'{attribute}\s*=', lowered):
                tokens.append(attribute)
        groups.append(tokens)
    return groups


class DOMObserver:
    """Detecta a presenca estrutural de um challenge."""

    name = "dom"

    def observe(self, html: str) -> ObserverResult:
        groups = [group for group in _tag_tokens(html) if group]
        if not groups:
            return ObserverResult(source=self.name)
        tokens = [token for group in groups for token in group]

        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        for profile in PROFILES:
            matched = [marker for marker in profile.dom_markers if any(marker in token for token in tokens)]
            if not matched:
                continue
            # A estrutura vem do ELEMENTO que casou, nao da pagina: e ela que
            # muda entre rodadas do widget.
            for group in groups:
                if any(marker in token for marker in matched for token in group):
                    structure.extend(group)
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

        structure = sorted(set(structure))
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
