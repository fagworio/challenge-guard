"""Network observer (CG-009).

Guarda METADADOS redigidos: origem, caminho com hash, metodo, tipo de recurso e
status. Nunca body, token, cookie, header de autorizacao ou query completa.

Duas regras:

    trafego de challenge nao vira trafego de submissao
    uma request isolada nao basta para classificar rejeicao

A segunda e por isso que este observador so produz CHALLENGE_TRAFFIC: pedir um
recurso do runtime do provedor prova que o widget esta ativo, nao que a
submissao foi recusada. Rejeicao exige evidencia de resposta (CG-010).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..providers.registry import profile_for_host
from ..signals import ChallengeSignal, ChallengeSignalKind
from .base import ObserverResult

#: Metodos que caracterizam escrita. O observador nao faz nada com isso alem de
#: anotar: quem autoriza escrita e o host, nao ele.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class NetworkRecord:
    """Fato observado na rede, ja sem nada sensivel."""

    url: str
    method: str = "GET"
    resource_type: str = "xhr"
    status: int | None = None

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").casefold()

    @property
    def path_hash(self) -> str:
        """Caminho com hash: preserva correlacao sem guardar o caminho literal."""
        path = urlsplit(self.url).path or "/"
        return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]

    @property
    def is_write(self) -> bool:
        return self.method.upper() in _WRITE_METHODS


class NetworkObserver:
    name = "network"

    def observe(self, records: list[NetworkRecord]) -> ObserverResult:
        signals: list[ChallengeSignal] = []
        structure: list[str] = []
        for record in records:
            profile = profile_for_host(record.host)
            if profile is None:
                continue
            structure.append(f"net.{record.host}")
            signals.append(
                ChallengeSignal(
                    kind=ChallengeSignalKind.CHALLENGE_TRAFFIC,
                    source=self.name,
                    provider=profile.provider,
                    confidence=0.7,
                    detail=f"net.{profile.provider.value}.{record.path_hash[:8]}",
                )
            )
        if not signals:
            return ObserverResult(source=self.name, structure=tuple(structure))
        best = signals[0]
        return ObserverResult(
            source=self.name,
            signals=tuple(signals),
            provider=best.provider,
            structure=tuple(structure),
            confidence=best.confidence,
        )

    @staticmethod
    def redact(record: NetworkRecord) -> dict[str, object]:
        """A forma como uma request pode ser registrada em auditoria."""
        return {
            "origin": f"{urlsplit(record.url).scheme}://{record.host}",
            "path_hash": record.path_hash,
            "method": record.method.upper(),
            "resource_type": record.resource_type,
            "status": record.status,
            "write": record.is_write,
        }
