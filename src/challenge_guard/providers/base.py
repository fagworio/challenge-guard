"""Perfil declarativo de um provedor de challenge.

Aqui — e so aqui — vivem os textos concretos e os hosts concretos. A policy
nunca ve isto; ela recebe o sinal ja normalizado.

O registry nao conhece ATS. Nome de plataforma de recrutamento — ou de empresa —
nao pertence a este pacote: um board que troque de anti-bot nao deve exigir
edicao no dominio. Um teste varre todo o src/ e quebra o build se algum
aparecer, inclusive em comentario.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import ChallengeProvider, ChallengeType
from ..signals import ChallengeSignalKind


@dataclass(frozen=True)
class ResponseMarker:
    """Texto observavel numa resposta, e o conceito que ele significa."""

    token: str
    phrase: str
    kind: ChallengeSignalKind
    confidence: float


@dataclass(frozen=True)
class ChallengeProviderProfile:
    provider: ChallengeProvider

    #: Tipo estrutural tipico, usado quando o DOM nao distingue melhor.
    default_type: ChallengeType = ChallengeType.UNKNOWN

    #: Hosts de iframe do desafio (comparados por host, nao por URL inteira).
    frame_hosts: tuple[str, ...] = ()

    #: Hosts que o widget precisa alcancar para funcionar. Sao REQUISITOS
    #: informados ao host, nao concessao de acesso.
    runtime_hosts: tuple[str, ...] = ()

    #: Marcadores estruturais de DOM (classes, atributos). Nunca conteudo.
    dom_markers: tuple[str, ...] = ()

    #: Textos de resposta -> conceito normalizado.
    response_markers: tuple[ResponseMarker, ...] = ()

    #: Hosts que hospedam o proprio widget (selo/badge).
    widget_hosts: tuple[str, ...] = field(default=())

    def marker_for(self, text: str) -> ResponseMarker | None:
        """Primeiro marcador que casa com o texto, ou None."""
        haystack = (text or "").casefold()
        for marker in self.response_markers:
            if marker.phrase in haystack:
                return marker
        return None
