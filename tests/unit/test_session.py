"""Ciclo de vida (CG-003) e maquina de estados (CG-004)."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeSessionStatus,
    ChallengeType,
)
from challenge_guard.session import (
    TRANSITIONS,
    ChallengeSessionTracker,
    InvalidChallengeTransition,
    SessionNotFound,
    can_transition,
)


def _observation(**overrides):
    data = {
        "detected": True,
        "phase": ChallengePhase.PRE_SUBMIT,
        "provider": ChallengeProvider.HCAPTCHA,
        "challenge_type": ChallengeType.IMAGE_SELECTION,
        "dom_signals": ("hcaptcha-container", "grid-3x3"),
        "confidence": 0.9,
    }
    data.update(overrides)
    return ChallengeObservation(**data)


def test_starting_a_session_from_an_undetected_observation_is_an_error():
    tracker = ChallengeSessionTracker()
    with pytest.raises(ValueError):
        tracker.start(_observation(detected=False))


def test_a_session_starts_active_with_its_first_round():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation(), observed_at="2026-01-01T00:00:00+00:00")
    assert session.status is ChallengeSessionStatus.ACTIVE
    assert session.rounds_observed == 1
    assert session.rounds[0].round_number == 1
    assert session.rounds[0].content_changed is True
    assert session.first_seen_at == "2026-01-01T00:00:00+00:00"


def test_a_new_grid_opens_a_new_round():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(session, _observation(dom_signals=("hcaptcha-container", "grid-4x4")))
    assert session.rounds_observed == 2
    assert session.status is ChallengeSessionStatus.ROUND_CHANGED
    assert session.rounds[1].content_changed is True
    assert session.rounds[1].round_number == 2
    assert session.dynamic_content is True


def test_the_same_structure_does_not_invent_a_round():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(session, _observation())
    assert session.rounds_observed == 2
    assert session.rounds[1].content_changed is False
    # Uma rodada sem mudanca devolve a sessao para ACTIVE.
    assert session.status is ChallengeSessionStatus.ACTIVE


def test_disappearance_is_not_success():
    """Sumir nao confirma nada: vira DISAPPEARED e o host decide o resto."""
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(session, _observation(detected=False))
    assert session.status is ChallengeSessionStatus.DISAPPEARED
    assert session.visible is False
    assert session.active is False


def test_a_disappeared_challenge_can_come_back():
    """Sumir e uma transicao de ciclo de vida, nao uma rodada do desafio."""
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(session, _observation(detected=False))
    assert session.rounds_observed == 1  # a saida nao conta como rodada
    tracker.observe(session, _observation(dom_signals=("hcaptcha-container", "grid-9x9")))
    assert session.status is ChallengeSessionStatus.ROUND_CHANGED
    assert session.rounds_observed == 2


def test_waiting_for_human_is_explicit_and_idempotent():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.await_human(session)
    assert session.status is ChallengeSessionStatus.WAITING_FOR_HUMAN
    assert session.waits_for_human is True
    tracker.await_human(session)
    assert session.rounds_observed == 1


def test_a_round_after_the_human_intervened_is_recorded():
    """O humano mexeu, a rodada mudou: o guard observa, nao interage."""
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.await_human(session)
    tracker.observe(session, _observation(dom_signals=("hcaptcha-container", "grid-4x4")))
    assert session.status is ChallengeSessionStatus.ROUND_CHANGED
    assert session.rounds_observed == 2


def test_provider_rejection_is_terminal_for_observation():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.provider_rejected(session)
    assert session.status is ChallengeSessionStatus.PROVIDER_REJECTED
    # Uma rodada posterior nao reabre o acompanhamento.
    tracker.observe(session, _observation(dom_signals=("hcaptcha-container", "grid-5x5")))
    assert session.status is ChallengeSessionStatus.PROVIDER_REJECTED
    assert session.rounds_observed == 2


def test_completing_a_rejected_session():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.provider_rejected(session)
    tracker.complete(session)
    assert session.status is ChallengeSessionStatus.COMPLETED
    assert session.active is False


def test_observing_a_completed_session_is_a_caller_error():
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.provider_rejected(session)
    tracker.complete(session)
    with pytest.raises(InvalidChallengeTransition):
        tracker.observe(session, _observation())


def test_invalid_transitions_fail_loudly():
    assert can_transition(ChallengeSessionStatus.COMPLETED, ChallengeSessionStatus.ACTIVE) is False
    assert can_transition(ChallengeSessionStatus.PROVIDER_REJECTED, ChallengeSessionStatus.ACTIVE) is False
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.provider_rejected(session)
    with pytest.raises(InvalidChallengeTransition):
        tracker.transition(session, ChallengeSessionStatus.ACTIVE)


def test_every_status_has_a_transition_entry_and_completed_is_terminal():
    for status in ChallengeSessionStatus:
        assert status in TRANSITIONS
    assert TRANSITIONS[ChallengeSessionStatus.COMPLETED] == frozenset()


def test_unknown_sessions_are_rejected():
    tracker = ChallengeSessionTracker()
    with pytest.raises(SessionNotFound):
        tracker.get("nao-existe")


def test_tracker_lists_active_sessions_only():
    tracker = ChallengeSessionTracker()
    first = tracker.start(_observation())
    tracker.start(_observation(session_id="segunda"))
    tracker.observe(first, _observation(detected=False))
    assert len(tracker.sessions()) == 2
    assert [session.id for session in tracker.active_sessions()] == ["segunda"]


def test_session_ids_are_unique_without_a_factory():
    tracker = ChallengeSessionTracker()
    ids = {tracker.start(_observation()).id for _ in range(5)}
    assert len(ids) == 5


def test_provider_and_type_are_not_downgraded_by_a_blind_observation():
    """Uma rodada que nao identificou o provider nao apaga o que ja sabiamos."""
    tracker = ChallengeSessionTracker()
    session = tracker.start(_observation())
    tracker.observe(
        session,
        _observation(provider=ChallengeProvider.UNKNOWN, challenge_type=ChallengeType.UNKNOWN),
    )
    assert session.provider is ChallengeProvider.HCAPTCHA
    assert session.challenge_type is ChallengeType.IMAGE_SELECTION
