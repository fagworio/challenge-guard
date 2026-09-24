"""Requisitos de rede do challenge (CG-012).

A biblioteca DESCREVE o que o widget precisa; ela nao autoriza nada. Quem
transforma isto num permit de rede e o host, com o orcamento proprio dele.

Tres regras que existem para nao repetir um defeito ja visto em producao:

1. Requisito de challenge nunca compartilha orcamento com upload ou submissao.
   Aqui nao ha credito: ha descricao. O host mantem contadores separados.
2. Origem com wildcard precisa vir acompanhada de path quando o path e
   conhecido. O caso ruim e `*.dominio` + `^/.*$`, que autoriza qualquer
   caminho de qualquer subdominio.
3. Ausencia de requisito significa "nao sei", nunca `^/.*$`. `path_patterns`
   vazio e uma afirmacao explicita (`paths_known=False`), e o host que decida —
   nao um default permissivo escondido aqui.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .models import ChallengeProvider


class ChallengeNetworkPurpose(str, Enum):
    """Para que serve o trafego. Um valor novo exige decisao explicita."""

    CHALLENGE_RUNTIME = "challenge_runtime"


_ORIGIN = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


@dataclass(frozen=True)
class ChallengeNetworkRequirement:
    provider: ChallengeProvider
    purpose: ChallengeNetworkPurpose
    origins: tuple[str, ...]
    methods: tuple[str, ...] = ("GET", "POST")
    #: Padroes de caminho conhecidos. Vazio significa "nao sei o caminho".
    path_patterns: tuple[str, ...] = ()
    #: Quantas requisicoes o widget costuma precisar. O host decide o que fazer
    #: com isso; nao e uma concessao.
    max_requests: int = 0

    def __post_init__(self) -> None:
        if not self.origins:
            raise ValueError("a network requirement must name at least one origin")
        for origin in self.origins:
            if not _ORIGIN.match(origin):
                raise ValueError(f"origin must be a bare lowercase host, got {origin!r}")
        if not self.methods:
            raise ValueError("a network requirement must name at least one method")
        for method in self.methods:
            if method != method.upper():
                raise ValueError(f"methods must be uppercase, got {method!r}")
        if self.max_requests < 1:
            raise ValueError("max_requests must be at least 1 (the host still decides)")
        for pattern in self.path_patterns:
            if pattern in {r"^/.*$", "^/.*$", ".*", "^.*$"}:
                raise ValueError(
                    "a catch-all path pattern defeats the purpose of scoping: "
                    "declare no path instead, and let the host read it as unknown"
                )
            if not pattern.startswith("^"):
                raise ValueError(f"path pattern must be anchored, got {pattern!r}")
        for origin in self.origins:
            if origin.startswith("*.") and not self.path_patterns:
                raise ValueError(
                    f"wildcard origin {origin!r} requires a known path: "
                    "a wildcard with an open path authorises a whole domain"
                )

    @property
    def paths_known(self) -> bool:
        return bool(self.path_patterns)

    @property
    def is_scoped(self) -> bool:
        return bool(self.path_patterns)

    @property
    def has_wildcard_origin(self) -> bool:
        return any(origin.startswith("*.") for origin in self.origins)

    def permits_origin(self, origin: str) -> bool:
        """Se um requisito cobre o host — apenas DESCRICAO, nao autorizacao."""
        host = (origin or "").casefold()
        for candidate in self.origins:
            if candidate.startswith("*."):
                suffix = candidate[2:]
                if host == suffix or host.endswith("." + suffix):
                    return True
            elif host == candidate:
                return True
        return False


def requirements_for(provider: ChallengeProvider) -> tuple[ChallengeNetworkRequirement, ...]:
    """Requisitos declarados pelo provider. Vazio significa "nao sei"."""
    from .providers.registry import profile_for

    profile = profile_for(provider)
    return profile.network_requirements if profile else ()
