"""Perfil declarativo de um provedor de challenge.

Aqui — e so aqui — vivem os textos concretos e os hosts concretos. A policy
nunca ve isto; ela recebe o sinal ja normalizado.

O registry nao conhece ATS. Nome de plataforma de recrutamento — ou de empresa —
nao pertence a este pacote: um board que troque de anti-bot nao deve exigir
edicao no dominio. Um teste varre todo o src/ e quebra o build se algum
aparecer, inclusive em comentario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dataclasses import dataclass
from enum import Enum

from ..models import ChallengeProvider, ChallengeType
from ..signals import ChallengeSignalKind


class EvidenceLevel(str, Enum):
    """De onde veio o padrao. Metadado de manutencao/auditoria.

    NAO altera a policy: um padrao INFERRED nao vira classificacao forte por
    vontade propria. A distincao serve para saber, depois, o que veio de
    producao, o que veio de fixture e o que foi suposto.
    """

    OBSERVED = "observed"
    FIXTURE = "fixture"
    INFERRED = "inferred"


_MARKER_TOKEN = re.compile(r"^[a-z0-9_]{3,48}$")


@dataclass(frozen=True)
class ResponseMarker:
    """Texto observavel numa resposta, e o conceito que ele significa."""

    token: str
    phrase: str
    kind: ChallengeSignalKind
    confidence: float
    #: Procedencia do padrao. Sem URL e sem empresa: so o nivel e uma referencia
    evidence_level: EvidenceLevel = EvidenceLevel.INFERRED
    source_reference: str = ""

    def __post_init__(self) -> None:
        if not _MARKER_TOKEN.match(self.token):
            raise ValueError(f"marker token must be a short controlled token, got {self.token!r}")
        if not self.phrase:
            raise ValueError("a response marker needs a phrase")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ChallengeProviderProfile:
    provider: ChallengeProvider

    #: Tipo estrutural tipico, usado quando o DOM nao distingue melhor.
    default_type: ChallengeType = ChallengeType.UNKNOWN

    #: Hosts de iframe do desafio (comparados por host, nao por URL inteira).
    frame_hosts: tuple[str, ...] = ()

    #: Padroes de CAMINHO do frame que distinguem provedores que dividem o mesmo
    #: host. Dado real: o mesmo `www.recaptcha.net` serve
    #: `/recaptcha/enterprise/anchor` (Enterprise) e `/recaptcha/api2/anchor`
    #: (classico). Sem isto, o primeiro perfil da lista vence e Enterprise nunca
    #: e identificado — o que muda o tipo observado e, com ele, a decisao.
    frame_paths: tuple[str, ...] = ()

    #: Caminhos do frame que significam "o desafio esta sendo APRESENTADO", nao
    #: apenas "o selo esta na pagina". No reCAPTCHA, `anchor` e o selo e `bframe`
    #: e o popup interativo com imagens. Sem esta distincao, presenca de selo e
    #: desafio em andamento viram a mesma coisa — e a antiga deteccao do host
    #: aproximava isso procurando a palavra "challenge" na URL.
    challenge_frame_paths: tuple[str, ...] = ()

    #: Hosts que o widget precisa alcancar para funcionar. Sao REQUISITOS
    #: informados ao host, nao concessao de acesso.
    runtime_hosts: tuple[str, ...] = ()

    #: Marcadores estruturais de DOM (classes, atributos). Nunca conteudo.
    dom_markers: tuple[str, ...] = ()

    #: Textos de resposta -> conceito normalizado.
    response_markers: tuple[ResponseMarker, ...] = ()

    #: Hosts que hospedam o proprio widget (selo/badge).
    widget_hosts: tuple[str, ...] = field(default=())

    #: O que o widget precisa alcancar, em termos de DESCRICAO (CG-012).
    network_requirements: tuple = field(default=())

    def marker_for(self, text: str) -> ResponseMarker | None:
        """Primeiro marcador que casa com o texto, ou None."""
        haystack = (text or "").casefold()
        for marker in self.response_markers:
            if marker.phrase in haystack:
                return marker
        return None
