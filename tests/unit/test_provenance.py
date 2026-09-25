"""CG-033 — proveniencia: o que fica registrado, e o que nunca fica.

A auditoria precisa responder "com base em que, e quando". O journal responde com
um conjunto FECHADO de eventos e de campos; qualquer coisa fora dele levanta, em
vez de entrar por engano.
"""

from __future__ import annotations

import pytest

from challenge_guard.guards.provenance import (
    JOURNAL_KINDS,
    ChallengeProvenance,
    ProvenanceJournal,
    ProvenanceViolation,
)


def test_unknown_event_kind_is_refused():
    journal = ProvenanceJournal()
    with pytest.raises(ProvenanceViolation, match="unsupported journal event"):
        journal.emit("something_new", provider="hcaptcha")
    assert journal.events == []


def test_unknown_field_is_refused():
    journal = ProvenanceJournal()
    with pytest.raises(ProvenanceViolation, match="unsupported fields"):
        journal.emit("observation", html="<html>...</html>")
    assert journal.events == []


def test_journal_refuses_sensitive_material_in_a_known_field():
    journal = ProvenanceJournal()
    with pytest.raises(Exception) as error:
        journal.emit("decision", session_id="sess-1", notes="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop")
    assert "eyJ" not in str(error.value)
    assert journal.events == []


def test_provenance_is_reconstructed_from_the_journal():
    journal = ProvenanceJournal()
    journal.emit("runtime_started", backend="playwright-cdp", started_at="2026-09-25T10:00:00+00:00")
    journal.emit(
        "observation",
        session_id="sess-1",
        provider="hcaptcha",
        challenge_type="checkbox",
        phase="pre_submit",
        detected=True,
        confidence=0.85,
        round=1,
    )
    journal.emit(
        "decision",
        session_id="sess-1",
        provider="hcaptcha",
        challenge_type="checkbox",
        phase="pre_submit",
        decision="needs_human",
        reason_token="challenge_detected_pre_submit",
        confidence=0.85,
        human_required=True,
        detected=True,
        capability="human_required",
        rounds=1,
        round=1,
    )
    journal.emit("runtime_closed", backend="playwright-cdp", finished_at="2026-09-25T10:00:05+00:00")

    provenance = journal.provenance()
    assert provenance is not None
    assert provenance.session_id == "sess-1"
    assert provenance.provider == "hcaptcha"
    assert provenance.decision == "needs_human"
    assert provenance.human_required is True
    assert provenance.backend == "playwright-cdp"
    assert provenance.started_at.startswith("2026-09-25T10:00:00")
    assert provenance.finished_at.startswith("2026-09-25T10:00:05")
    assert provenance.finished is True


def test_an_interrupted_cycle_has_no_finished_at():
    """Processo morto no meio: proveniencia sem fim, e nunca um horario inventado."""
    journal = ProvenanceJournal()
    journal.emit("runtime_started", backend="page", started_at="2026-09-25T10:00:00+00:00")
    journal.emit("decision", decision="observe", reason_token="challenge_detected_pre_submit")
    provenance = journal.provenance()
    assert provenance is not None and provenance.finished is False


def test_empty_journal_has_no_provenance():
    assert ProvenanceJournal().provenance() is None


def test_provenance_rejects_a_negative_round_count():
    with pytest.raises(ProvenanceViolation, match="rounds cannot be negative"):
        ChallengeProvenance(
            session_id="s",
            provider="hcaptcha",
            challenge_type="checkbox",
            phase="pre_submit",
            decision="needs_human",
            reason_token="challenge_detected_pre_submit",
            rounds=-1,
        )


def test_provenance_events_are_closed_and_small():
    assert JOURNAL_KINDS == {
        "runtime_started",
        "observation",
        "decision",
        "revalidation",
        "budget_exhausted",
        "runtime_closed",
        "handoff_built",
    }


def test_sink_failure_does_not_lose_the_local_event():
    class BrokenSink:
        def emit(self, *args, **kwargs):
            raise RuntimeError("sink fora do ar")

    journal = ProvenanceJournal(sink=BrokenSink())
    journal.emit("observation", detected=False)
    assert journal.kinds() == ("observation",)


def test_filtering_by_session():
    journal = ProvenanceJournal()
    journal.emit("observation", session_id="a", detected=True)
    journal.emit("observation", session_id="b", detected=True)
    assert len(journal.for_session("a")) == 1
