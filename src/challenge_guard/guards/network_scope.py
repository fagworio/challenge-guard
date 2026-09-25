"""CG-028 — Network Scope Guard.

O guard nao navega, nao requisita e nao autoriza trafego. Ele LE o que a pagina
ja fez. Mesmo assim o escopo precisa ser explicito, porque o material observado
pode conter coisas que nao sao challenge: o POST da candidatura, o upload do
curriculo, um beacon de analytics com dado do candidato.

A separacao de PROPOSITO e o ponto (e a razao de `ChallengeNetworkPurpose`
existir): trafego de challenge, upload e submissao de candidatura sao coisas
diferentes, e o guard so tem competencia sobre a primeira.

```text
host declarado pelo provider        -> CHALLENGE_RUNTIME (observavel)
POST para host nao declarado        -> fora de escopo (sinal para o host, nunca aceito)
caminho com cara de candidatura     -> SUBMISSION_CANDIDATE (nunca "resolucao")
```

Recusar nao e censurar a observacao: o registro continua existindo para o host. O
que o guard nao faz e tratar isso como trafego de desafio — que e como um solver
disfarcado entraria pela porta da frente.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from ..observers import NetworkRecord
from ..requirements import runtime_read_hosts


class ScopeVerdict(str, Enum):
    """O que um registro de rede e, para efeito de escopo."""

    CHALLENGE_RUNTIME = "challenge_runtime"
    OUT_OF_SCOPE = "out_of_scope"
    SUBMISSION_CANDIDATE = "submission_candidate"


class NetworkScopeViolation(RuntimeError):
    """Trafego fora do escopo foi tratado como challenge."""


#: Metodos que PRODUZEM efeito. O guard pode OBSERVAR qualquer um deles (o widget
#: do desafio usa POST legitimamente); o que ele nao pode e considerar um write
#: como prova de que um challenge foi resolvido.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Pedacos de caminho que denunciam candidatura, e nao challenge. Lista curta e
#: explicita: caminho desconhecido nao vira suspeita por semelhanca.
_SUBMISSION_HINTS = ("application", "apply", "candidate", "resume", "curriculum", "upload")


@dataclass(frozen=True)
class NetworkScope:
    """Escopo de leitura derivado dos requisitos DECLARADOS dos providers."""

    allowed_hosts: frozenset[str]

    @classmethod
    def from_providers(cls, providers: list[str] | None = None) -> "NetworkScope":
        return cls(frozenset(runtime_read_hosts(providers)))

    @classmethod
    def empty(cls) -> "NetworkScope":
        return cls(frozenset())

    def permits(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            return False
        for allowed in self.allowed_hosts:
            candidate = allowed.lstrip("*.").lower()
            if host == candidate or host.endswith("." + candidate):
                return True
        return False

    def classify(self, record: NetworkRecord) -> ScopeVerdict:
        """Classifica um registro observado. Nunca autoriza nada."""
        url = str(record.url or "")
        path = urlsplit(url).path.casefold()
        if self.permits(url):
            return ScopeVerdict.CHALLENGE_RUNTIME
        method = str(record.method or "GET").upper()
        if method in WRITE_METHODS and any(hint in path for hint in _SUBMISSION_HINTS):
            return ScopeVerdict.SUBMISSION_CANDIDATE
        return ScopeVerdict.OUT_OF_SCOPE

    def classify_all(self, records: list[NetworkRecord]) -> dict[ScopeVerdict, list[str]]:
        """Agrupa por veredito, com o CAMINHO ja reduzido a host+path.

        Sem query: query carrega token de verificacao e dado do candidato, e
        proveniencia nao precisa dela.
        """
        grouped: dict[ScopeVerdict, list[str]] = {verdict: [] for verdict in ScopeVerdict}
        for record in records:
            grouped[self.classify(record)].append(_safe_target(str(record.url or "")))
        return grouped

    def assert_no_submission_traffic(self, records: list[NetworkRecord]) -> None:
        """Recusa chamar de challenge o trafego de candidatura."""
        offenders = [target for target in self.classify_all(records)[ScopeVerdict.SUBMISSION_CANDIDATE]]
        if offenders:
            raise NetworkScopeViolation(
                "submission traffic observed as challenge traffic: " + ", ".join(sorted(set(offenders))[:5])
            )


def _safe_target(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


__all__ = [
    "NetworkScope",
    "NetworkScopeViolation",
    "ScopeVerdict",
    "WRITE_METHODS",
]
