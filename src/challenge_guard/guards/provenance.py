"""CG-033 — Provenance Guard: journal seguro e auditavel.

A pergunta que a auditoria faz e sempre a mesma: *com base em que evidencia o
guard disse que precisava de um humano, e em que momento?* Sem proveniencia a
resposta e "confie". Com proveniencia demais (payload cru) a resposta e um
vazamento.

O meio termo e um conjunto FECHADO de campos, todos curtos ou numericos, e um
journal que recusa qualquer coisa fora dele. Os kinds sao fechados pelo mesmo
motivo: um evento novo exige decisao explicita, e nao pode chegar de carona num
`emit("qualquer_coisa", ...)`.

`finished_at` vazio significa "ainda nao terminou" — nunca "terminou agora". A
diferenca importa quando um processo morre no meio: proveniencia sem fim e a
assinatura de um ciclo interrompido, e inventar o horario esconderia isso.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

from .sensitive_material import assert_no_sensitive_material

#: Eventos permitidos no journal. Conjunto fechado.
JOURNAL_KINDS = frozenset(
    {
        "runtime_started",
        "observation",
        "decision",
        "revalidation",
        "budget_exhausted",
        "runtime_closed",
        "handoff_built",
    }
)

#: Campos permitidos em QUALQUER evento. Tudo aqui e curto, numerico ou booleano.
ALLOWED_FIELDS = frozenset(
    {
        "session_id",
        "provider",
        "challenge_type",
        "phase",
        "round",
        "decision",
        "reason_token",
        "confidence",
        "detected",
        "human_required",
        "capability",
        "rounds",
        "max_rounds",
        "timed_out",
        "backend",
        "cdp_host",
        "cdp_port",
        "started_at",
        "finished_at",
        "page_reloaded",
        "notes",
    }
)


class ProvenanceViolation(RuntimeError):
    """Um evento de journal saiu do conjunto fechado."""


@dataclass(frozen=True)
class ChallengeProvenance:
    """O que fica registrado sobre um ciclo de observacao. Nada alem disso."""

    session_id: str
    provider: str
    challenge_type: str
    phase: str
    decision: str
    reason_token: str
    rounds: int = 0
    confidence: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    backend: str = ""
    capability: str = ""
    human_required: bool = False
    detected: bool = False

    def __post_init__(self) -> None:
        if self.rounds < 0:
            raise ProvenanceViolation("rounds cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ProvenanceViolation("confidence must be between 0 and 1")
        # O guard de material sensivel roda na PROPRIA proveniencia: um campo
        # novo com nome inocente e conteudo sensivel nao passa por aqui.
        assert_no_sensitive_material(self, where="provenance")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def finished(self) -> bool:
        return bool(self.finished_at)


@dataclass
class ProvenanceJournal:
    """Journal em memoria, com sink opcional. Nunca guarda payload cru."""

    sink: object | None = None
    events: list[dict[str, object]] = field(default_factory=list)

    def emit(self, kind: str, /, **fields: object) -> dict[str, object]:
        if kind not in JOURNAL_KINDS:
            raise ProvenanceViolation(f"unsupported journal event: {kind}")
        unknown = set(fields) - ALLOWED_FIELDS
        if unknown:
            raise ProvenanceViolation(f"journal event {kind} carries unsupported fields: {sorted(unknown)}")
        record: dict[str, object] = {"kind": kind}
        record.update(fields)
        assert_no_sensitive_material(record, where=f"journal[{kind}]")
        self.events.append(record)
        self._forward(record)
        return record

    def _forward(self, record: dict[str, object]) -> None:
        if self.sink is None:
            return
        handler = getattr(self.sink, "emit", None)
        if callable(handler):
            try:
                handler(record.get("kind"), **{key: value for key, value in record.items() if key != "kind"})
            except Exception:
                # Auditoria nao derruba a observacao; o evento ja esta em memoria.
                pass

    def kinds(self) -> tuple[str, ...]:
        return tuple(str(event.get("kind", "")) for event in self.events)

    def for_session(self, session_id: str) -> list[dict[str, object]]:
        return [event for event in self.events if event.get("session_id") == session_id]

    def provenance(self) -> ChallengeProvenance | None:
        """Reconstroi a proveniencia do ciclo a partir dos eventos gravados."""
        if not self.events:
            return None
        started = next((event for event in self.events if event.get("kind") == "runtime_started"), {})
        decisions = [event for event in self.events if event.get("kind") in {"decision", "revalidation"}]
        closed = next((event for event in self.events if event.get("kind") == "runtime_closed"), {})
        last = decisions[-1] if decisions else {}
        return ChallengeProvenance(
            session_id=str(last.get("session_id", started.get("session_id", ""))),
            provider=str(last.get("provider", started.get("provider", ""))),
            challenge_type=str(last.get("challenge_type", started.get("challenge_type", ""))),
            phase=str(last.get("phase", started.get("phase", ""))),
            decision=str(last.get("decision", "")),
            reason_token=str(last.get("reason_token", "")),
            rounds=int(last.get("rounds", 0) or 0),
            confidence=float(last.get("confidence", 0.0) or 0.0),
            started_at=str(started.get("started_at", "")),
            finished_at=str(closed.get("finished_at", "")),
            backend=str(started.get("backend", "")),
            capability=str(last.get("capability", "")),
            human_required=bool(last.get("human_required", False)),
            detected=bool(last.get("detected", False)),
        )

    def extend(self, events: Iterable[dict[str, object]]) -> None:
        for event in events:
            self.emit(str(event.get("kind", "")), **{k: v for k, v in event.items() if k != "kind"})


__all__ = [
    "ALLOWED_FIELDS",
    "JOURNAL_KINDS",
    "ChallengeProvenance",
    "ProvenanceJournal",
    "ProvenanceViolation",
]
