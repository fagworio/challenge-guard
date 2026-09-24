"""Evidencia redigida (CG-013).

Nenhum observer entrega seu objeto interno para persistencia. O caminho e
sempre:

    raw observation
        -> redactor
        -> ChallengeEvidence   (allowlist)

Allowlist, nao denylist: o que nao esta declarado nao entra. Uma denylist
sempre esquece um campo novo; a allowlist falha fechada.

Bloqueado explicitamente: token de resposta, sitekey, cookie, authorization,
body, query string, valor de formulario, e-mail, telefone e qualquer dado de
candidato. Um teste de propriedade serializa a evidencia inteira e procura
payloads sentinela: zero ocorrencia.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .models import ChallengeDecision, ChallengeObservation, ChallengePhase, ChallengeProvider, ChallengeSession
from .signals import ChallengeSignal


class EvidenceLeak(ValueError):
    """Um valor proibido tentou entrar na evidencia."""


#: Palavras que nunca podem aparecer numa chave ou num valor de texto.
_FORBIDDEN = (
    "token",
    "sitekey",
    "cookie",
    "authorization",
    "bearer",
    "password",
    "secret",
    "body",
    "query",
    "payload",
    "@",  # e-mail
    "phone",
    "telefone",
    "candidate",
    "candidato",
    "resume",
    "curriculo",
)

_SAFE_TEXT = re.compile(r"^[a-z0-9_.:+-]{1,64}$")
_PATH_HASH = re.compile(r"^[0-9a-f]{16}$")


def _assert_clean(key: str, value: object) -> None:
    haystack = str(value).casefold()
    for banned in _FORBIDDEN:
        if banned in haystack:
            raise EvidenceLeak(f"evidence field {key!r} carries forbidden content ({banned!r})")


@dataclass(frozen=True)
class ChallengeEvidence:
    """Tudo que pode ser persistido sobre uma sessao de challenge."""

    session_id: str
    provider: str
    phase: str
    decision: str
    reason_token: str
    sources: tuple[str, ...] = ()
    signal_kinds: tuple[str, ...] = ()
    http_status: int | None = None
    path_hashes: tuple[str, ...] = ()
    rounds_observed: int = 0
    confidence: float = 0.0

    def __post_init__(self) -> None:
        for field_name in ("session_id", "provider", "phase", "decision", "reason_token"):
            _assert_clean(field_name, getattr(self, field_name))
        for source in self.sources:
            if not _SAFE_TEXT.match(source):
                raise EvidenceLeak(f"source must be a short token, got {source!r}")
        for kind in self.signal_kinds:
            if not _SAFE_TEXT.match(kind):
                raise EvidenceLeak(f"signal kind must be a short token, got {kind!r}")
        for path_hash in self.path_hashes:
            if not _PATH_HASH.match(path_hash):
                raise EvidenceLeak("path hashes must be opaque, never a literal path")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise EvidenceLeak("http_status must be a plausible status code")
        if not 0.0 <= self.confidence <= 1.0:
            raise EvidenceLeak("confidence must be between 0 and 1")
        if self.rounds_observed < 0:
            raise EvidenceLeak("rounds_observed cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def path_hashes_from(observations: tuple[ChallengeObservation, ...]) -> tuple[str, ...]:
    """Hashes de caminho a partir de sinais de rede, quando houver.

    O observador de rede ja entrega `detail` como token com hash; nada de
    caminho literal chega aqui.
    """
    hashes: list[str] = []
    for observation in observations:
        for signal in observation.signals:
            if signal.kind.value != "challenge_traffic":
                continue
            suffix = signal.detail.rsplit(".", 1)[-1]
            if _PATH_HASH.match(suffix):
                hashes.append(suffix)
    return tuple(dict.fromkeys(hashes))


def redact(
    *,
    session: ChallengeSession | None,
    observation: ChallengeObservation,
    decision: ChallengeDecision,
    signals: tuple[ChallengeSignal, ...] = (),
    path_hashes: tuple[str, ...] = (),
) -> ChallengeEvidence:
    """Constroi a unica forma persistivel de uma observacao."""
    effective_signals = signals or observation.signals
    sources = tuple(
        dict.fromkeys(
            [signal.source for signal in effective_signals]
            + ([session.provider.value] if session is not None else [])
        )
    )
    return ChallengeEvidence(
        session_id=session.id if session is not None else (observation.session_id or "unattached"),
        provider=(session.provider if session is not None else observation.provider).value,
        phase=observation.phase.value,
        decision=decision.status.value,
        reason_token=decision.reason_token,
        sources=tuple(source for source in sources if _SAFE_TEXT.match(source)),
        signal_kinds=tuple(dict.fromkeys(signal.kind.value for signal in effective_signals)),
        http_status=observation.http_status,
        path_hashes=path_hashes,
        rounds_observed=session.rounds_observed if session is not None else 0,
        confidence=decision.confidence,
    )
