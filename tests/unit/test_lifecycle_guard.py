"""CG-026 — invariantes do lifecycle, testadas uma a uma.

Cada teste aqui corresponde a um defeito concreto que o guard impede: listener
duplicado, adapter antigo anexado, browser fechado ainda referenciado, resposta da
pagina anterior contaminando a sessao nova.
"""

from __future__ import annotations

import pytest

from challenge_guard import ChallengeMonitor
from challenge_guard.guards.lifecycle import BrowserLifecycle, LifecycleState, LifecycleViolation


def test_start_happens_once():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("playwright-cdp")
    assert lifecycle.started and lifecycle.state is LifecycleState.STARTED
    with pytest.raises(LifecycleViolation, match="start called twice"):
        lifecycle.mark_started("playwright-cdp")
    assert lifecycle.starts == 1


def test_attach_before_start_is_refused():
    lifecycle = BrowserLifecycle()
    with pytest.raises(LifecycleViolation, match="attach before start"):
        lifecycle.mark_attached("playwright")
    assert not lifecycle.attached


def test_start_then_attach_then_detach_is_the_happy_path():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("page")
    lifecycle.mark_attached("playwright")
    assert lifecycle.attached and lifecycle.started
    lifecycle.mark_detached()
    assert lifecycle.started and not lifecycle.attached
    lifecycle.mark_detached()
    assert lifecycle.detaches == 1, "detach idempotente: o finally nunca pode falhar"


def test_replacing_an_attached_adapter_is_refused():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("page")
    lifecycle.mark_attached("playwright")
    with pytest.raises(LifecycleViolation, match="cannot replace"):
        lifecycle.mark_attached("playwright-cdp")


def test_close_is_idempotent_and_final():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("page")
    lifecycle.mark_closed()
    lifecycle.mark_closed()
    assert lifecycle.closed and lifecycle.closes == 1
    with pytest.raises(LifecycleViolation, match="closed"):
        lifecycle.mark_started("page")
    with pytest.raises(LifecycleViolation, match="closed"):
        lifecycle.mark_attached("playwright")


def test_navigation_without_reset_blocks_the_next_observation():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("page")
    lifecycle.mark_attached("playwright")
    lifecycle.mark_navigation("https://example.test/step-2")
    assert lifecycle.reset_pending
    with pytest.raises(LifecycleViolation, match="navigation without reset"):
        lifecycle.assert_ready_for_observation()
    lifecycle.mark_reset()
    assert not lifecycle.reset_pending
    lifecycle.assert_ready_for_observation()


def test_observe_before_start_and_after_close_are_refused():
    lifecycle = BrowserLifecycle()
    with pytest.raises(LifecycleViolation, match="observe before start"):
        lifecycle.assert_ready_for_observation()
    lifecycle.mark_started("page")
    lifecycle.mark_closed()
    with pytest.raises(LifecycleViolation, match="observe after close"):
        lifecycle.assert_ready_for_observation()


def test_describe_is_auditable_and_has_no_url():
    lifecycle = BrowserLifecycle()
    lifecycle.mark_started("playwright-cdp")
    lifecycle.mark_attached("playwright")
    lifecycle.mark_navigation("https://example.test/apply?token=should-not-be-here")
    described = lifecycle.describe()
    assert described["navigations"] == 1 and described["reset_pending"] is True
    assert "should-not-be-here" not in str(described)


def test_monitor_refuses_a_second_adapter_without_detach():
    """O monitor tambem cobra a invariante: dois adapters = dois listeners."""
    monitor = ChallengeMonitor()

    class FakeAdapter:
        name = "first"

        def attach(self, page):  # pragma: no cover - nao chega a ser chamado
            self.attached = True

        def detach(self):  # pragma: no cover
            pass

    first = FakeAdapter()
    monitor.attach_adapter(first)
    assert monitor.adapter_name == "first"
    with pytest.raises(LifecycleViolation, match="already has an adapter"):
        monitor.attach_adapter(FakeAdapter())
    monitor.detach()
