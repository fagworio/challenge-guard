"""Objeto de handoff humano (CG-018).

Neutro de proposito: descreve o que a PESSOA precisa fazer, sem saber nada sobre
a candidatura. O host enriquece depois com empresa, vaga, curriculo e respostas
aprovadas — este pacote nao conhece nada disso, e nao deve passar a conhecer.

O handoff existe porque `NEEDS_HUMAN` sozinho nao responde a pergunta
operacional: "e agora, o que a pessoa faz?".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit

from .models import ChallengeDecision, ChallengeProvider, ReasonToken


class HandoffContinuation(str, Enum):
    """O que se espera depois que o humano agir."""

    #: A pessoa resolve no navegador e o host retoma o fluxo sozinho.
    MANUAL = "manual"
    #: O provedor recusou o ambiente; a pessoa termina fora do agente.
    MANUAL_FINAL = "manual_final"


#: Nunca pode aparecer num handoff: este objeto circula em log e em mensagem.
_FORBIDDEN = (
    "token",
    "cookie",
    "authorization",
    "bearer",
    "sitekey",
    "password",
    "secret",
    "@",
    "resume",
    "curriculo",
    "candidate",
    "candidato",
)

_SAFE_TEXT = re.compile(r"^[a-z0-9_.:-]{1,64}$")


class UnsafeHandoff(ValueError):
    """Um handoff tentou carregar dado que nao pertence a ele."""


@dataclass(frozen=True)
class HumanHandoff:
    provider: str
    reason_token: str
    challenge_session_id: str = ""
    page_url: str = ""
    continuation: str = HandoffContinuation.MANUAL.value
    instructions: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.reason_token not in {token.value for token in ReasonToken}:
            raise UnsafeHandoff(f"unsupported reason token: {self.reason_token}")
        if self.continuation not in {item.value for item in HandoffContinuation}:
            raise UnsafeHandoff(f"unsupported continuation: {self.continuation}")
        if not _SAFE_TEXT.match(self.provider or ""):
            raise UnsafeHandoff("provider must be a short token")
        if self.challenge_session_id and not _SAFE_TEXT.match(self.challenge_session_id):
            raise UnsafeHandoff("session id must be a short token")
        if self.page_url and not _is_http_url(self.page_url):
            raise UnsafeHandoff("page_url must be an http(s) URL without credentials")
        for text in (self.provider, self.reason_token, self.continuation, *self.instructions):
            haystack = str(text).casefold()
            for banned in _FORBIDDEN:
                if banned in haystack:
                    raise UnsafeHandoff(f"handoff carries forbidden content ({banned!r})")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "reason_token": self.reason_token,
            "challenge_session_id": self.challenge_session_id,
            "page_url": self.page_url,
            "continuation": self.continuation,
            "instructions": list(self.instructions),
        }


def _is_http_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if parts.username or parts.password:
        return False
    # Query string pode carregar identificador do provedor: o handoff aponta a
    # pagina, nao o estado dela.
    return not parts.query and not parts.fragment


#: Instrucoes por decisao. Texto curto, sem dado do candidato.
_INSTRUCTIONS = {
    "needs_human": (
        "Open the page in a visible browser.",
        "Complete the challenge yourself; the guard only observes.",
        "Return to the agent so it can revalidate and continue.",
    ),
    "provider_rejected": (
        "The provider refused this environment after the submission was sent.",
        "Do not resend automatically: finish the application manually.",
    ),
}


def build_handoff(
    decision: ChallengeDecision,
    *,
    session_id: str = "",
    page_url: str = "",
) -> HumanHandoff | None:
    """Handoff para decisoes que exigem uma pessoa, ou None.

    `RESOLVED_EXTERNALLY` NAO gera handoff: o challenge saiu, e quem valida o
    resultado e o host. `OBSERVE` e `NONE` tambem nao: nada a pedir a ninguem.
    """
    if decision.status.value not in _INSTRUCTIONS:
        return None
    continuation = (
        HandoffContinuation.MANUAL_FINAL.value
        if decision.status.value == "provider_rejected"
        else HandoffContinuation.MANUAL.value
    )
    return HumanHandoff(
        provider=decision.provider.value if isinstance(decision.provider, ChallengeProvider) else str(decision.provider),
        reason_token=decision.reason_token,
        challenge_session_id=session_id,
        page_url=page_url,
        continuation=continuation,
        instructions=_INSTRUCTIONS[decision.status.value],
    )
