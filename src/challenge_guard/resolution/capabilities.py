"""CG-032 — Capability Guard: comportamento explicito por tipo de desafio.

Um unico valor `SUPPORTED` foi recusado de proposito. Ele sugeriria que a
biblioteca faz o desafio andar — e ela nunca faz. O que existe sao cinco
capacidades, todas sobre **observar e esperar**:

```text
OBSERVE_ONLY        o guard continua olhando; nada foi pedido a ninguem
WAIT_EXTERNAL       alguem (a pessoa) esta agindo FORA do guard; ele revalida
HUMAN_REQUIRED      progredir exige acao humana explicita
PROVIDER_SUPPORTED  o provedor decide sozinho (invisivel / risk assessment)
UNSUPPORTED         o guard nao sabe descrever isto; nao finge que sabe
```

Nenhuma delas significa "resolvido", e nenhuma autoriza interacao. O teste
`test_no_capability_implies_solving` existe para que um valor novo nao entre sem
que alguem perceba — a lista e a matriz sao conjuntos fechados.
"""

from __future__ import annotations

from enum import Enum

from ..models import ChallengeType


class ChallengeCapability(str, Enum):
    OBSERVE_ONLY = "observe_only"
    WAIT_EXTERNAL = "wait_external"
    HUMAN_REQUIRED = "human_required"
    PROVIDER_SUPPORTED = "provider_supported"
    UNSUPPORTED = "unsupported"


#: Tipos em que progredir exige uma pessoa tocando no desafio.
_HUMAN_TYPES = frozenset(
    {
        ChallengeType.CHECKBOX,
        ChallengeType.IMAGE_SELECTION,
        ChallengeType.TEXT,
        ChallengeType.MATH,
        ChallengeType.PUZZLE,
    }
)

#: Tipos em que o proprio provedor avalia e libera sem interacao. O guard apenas
#: observa — e `PROVIDER_SUPPORTED` NAO quer dizer "o guard resolve".
_SELF_ASSESSING = frozenset({ChallengeType.INVISIBLE, ChallengeType.RISK_ASSESSMENT})


def capability_for(
    challenge_type: ChallengeType | object,
    *,
    waiting_for_human: bool = False,
) -> ChallengeCapability:
    """Capacidade do guard para este tipo, dado o momento do ciclo.

    `waiting_for_human=True` descreve o ciclo em que a pessoa ja foi avisada e o
    guard esta reobservando — a capacidade vira `WAIT_EXTERNAL`, que e um estado
    de ESPERA, nao de acao.
    """
    if waiting_for_human:
        return ChallengeCapability.WAIT_EXTERNAL
    if not isinstance(challenge_type, ChallengeType):
        return ChallengeCapability.UNSUPPORTED
    if challenge_type in _HUMAN_TYPES:
        return ChallengeCapability.HUMAN_REQUIRED
    if challenge_type in _SELF_ASSESSING:
        return ChallengeCapability.PROVIDER_SUPPORTED
    if challenge_type is ChallengeType.UNKNOWN:
        return ChallengeCapability.OBSERVE_ONLY
    return ChallengeCapability.UNSUPPORTED


def capability_matrix() -> dict[str, str]:
    """A matriz inteira, para documentacao e para o teste de cobertura."""
    return {challenge_type.value: capability_for(challenge_type).value for challenge_type in ChallengeType}


__all__ = ["ChallengeCapability", "capability_for", "capability_matrix"]
