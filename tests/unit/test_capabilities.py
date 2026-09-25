"""CG-032 — capacidades: o que o guard PODE fazer, sem nunca sugerir que resolve."""

from __future__ import annotations

import pytest

from challenge_guard import ChallengeType
from challenge_guard.resolution.capabilities import (
    ChallengeCapability,
    capability_for,
    capability_matrix,
)


def test_the_capability_vocabulary_is_closed_and_has_no_solving_value():
    values = {capability.value for capability in ChallengeCapability}
    assert values == {
        "observe_only",
        "wait_external",
        "human_required",
        "provider_supported",
        "unsupported",
    }
    for forbidden in ("solve", "auto", "resolve", "bypass"):
        assert not any(forbidden in value for value in values)


def test_every_challenge_type_has_a_declared_capability():
    matrix = capability_matrix()
    assert set(matrix) == {challenge_type.value for challenge_type in ChallengeType}
    for value in matrix.values():
        assert value in {capability.value for capability in ChallengeCapability}


@pytest.mark.parametrize(
    "challenge_type",
    [ChallengeType.CHECKBOX, ChallengeType.IMAGE_SELECTION, ChallengeType.TEXT, ChallengeType.MATH, ChallengeType.PUZZLE],
)
def test_interactive_types_require_a_human(challenge_type: ChallengeType):
    assert capability_for(challenge_type) is ChallengeCapability.HUMAN_REQUIRED


@pytest.mark.parametrize("challenge_type", [ChallengeType.INVISIBLE, ChallengeType.RISK_ASSESSMENT])
def test_self_assessing_types_are_not_a_promise_that_the_guard_acts(challenge_type: ChallengeType):
    """`PROVIDER_SUPPORTED` diz quem decide; nao diz que NOS resolvemos."""
    assert capability_for(challenge_type) is ChallengeCapability.PROVIDER_SUPPORTED


def test_unknown_type_keeps_observing_instead_of_asking_a_human():
    assert capability_for(ChallengeType.UNKNOWN) is ChallengeCapability.OBSERVE_ONLY


def test_waiting_for_human_describes_waiting_not_acting():
    assert capability_for(ChallengeType.CHECKBOX, waiting_for_human=True) is ChallengeCapability.WAIT_EXTERNAL
    assert capability_for(ChallengeType.INVISIBLE, waiting_for_human=True) is ChallengeCapability.WAIT_EXTERNAL


def test_an_unknown_value_outside_the_enum_is_unsupported_and_not_guessed():
    assert capability_for("something_new") is ChallengeCapability.UNSUPPORTED
    assert capability_for(None) is ChallengeCapability.UNSUPPORTED
