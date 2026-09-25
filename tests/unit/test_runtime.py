"""CG-025 — o runtime publico, em modo core e com browser falso.

O runtime e o que o host consome. Estes testes cobrem a composicao: ordem do
lifecycle, orcamento, revalidacao, journal e o resultado de conjunto fechado.
Nada aqui abre browser: o modo core existe justamente para quem ja tem o material
em maos, e o adapter falso prova que a injecao de backend (CG-024) funciona sem
Playwright nenhum.
"""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeRuntime,
    ChallengeType,
    LifecycleViolation,
)
from challenge_guard.guards.sensitive_material import assert_no_sensitive_material
from challenge_guard.observers import FrameInfo, NetworkRecord, ResponseRecord
from challenge_guard.resolution.limits import RuntimeLimits

CHALLENGE_HTML = '<html><body><div class="h-captcha grid-4x4" data-sitekey="fixture"></div></body></html>'
PLAIN_HTML = "<html><body><form><input name='name'></form></body></html>"


class FakeAdapter:
    """Adapter de mentira: existe para provar que o backend e injetavel."""

    name = "fake-adapter"

    def __init__(self, *, url: str = "https://example.test/apply", dom: str = CHALLENGE_HTML) -> None:
        self._url = url
        self._dom = dom
        self.attached = False
        self.attachments = 0
        self.resets = 0

    def attach(self, page: object) -> None:
        if self.attached:
            return
        self.attached = True
        self.attachments += 1

    def detach(self) -> None:
        self.attached = False

    def reset(self) -> None:
        self.resets += 1

    def current_url(self) -> str:
        return self._url

    def collect_dom(self) -> str:
        return self._dom

    def collect_frames(self) -> list[FrameInfo]:
        return []

    def collect_network(self) -> list[NetworkRecord]:
        # Um registro de challenge (dentro do escopo declarado) e um de
        # candidatura (fora dele): o runtime so pode entregar o primeiro.
        return [
            NetworkRecord(url="https://hcaptcha.com/1/api.js", method="GET"),
            NetworkRecord(url="https://boards.example.test/jobs/1/applications", method="POST"),
        ]

    def collect_responses(self) -> list[ResponseRecord]:
        return []


class FakeSession:
    name = "fake-cdp"

    def __init__(self) -> None:
        self.page = object()
        self.started = 0
        self.closed = 0
        self.resets = 0
        self.closed_with: list[dict] = []

    def start(self) -> object:
        self.started += 1
        return self.page

    def reset(self) -> None:
        self.resets += 1

    def close(self, **kwargs: object) -> None:
        self.closed += 1
        self.closed_with.append(dict(kwargs))


# --- modo core -----------------------------------------------------------------


def test_core_mode_needs_no_browser_and_still_decides():
    with ChallengeRuntime(limits=RuntimeLimits(max_rounds=3)) as runtime:
        decision = runtime.evaluate(dom_html=CHALLENGE_HTML)
        result = runtime.result()

    assert decision.human_required is True
    assert result.detected is True
    assert result.final_status == "human_required"
    assert result.capability == "human_required"
    assert result.backend == "core"
    assert result.rounds == 1
    assert result.human_required is True
    assert runtime.journal.kinds() == ("runtime_started", "observation", "decision", "runtime_closed")


def test_a_plain_page_is_not_a_challenge():
    with ChallengeRuntime() as runtime:
        runtime.evaluate(dom_html=PLAIN_HTML)
        result = runtime.result()
    assert result.detected is False
    assert result.final_status == "none"


def test_observe_before_start_is_refused_by_the_runtime():
    runtime = ChallengeRuntime()
    with pytest.raises(LifecycleViolation, match="observe before start"):
        runtime.observe(dom_html=CHALLENGE_HTML)


def test_close_is_idempotent_and_the_runtime_stops_observing():
    runtime = ChallengeRuntime()
    runtime.start()
    runtime.close()
    runtime.close()
    assert runtime.lifecycle.closes == 1
    with pytest.raises(LifecycleViolation, match="observe after close"):
        runtime.observe(dom_html=CHALLENGE_HTML)


def test_result_requires_an_evaluated_observation():
    runtime = ChallengeRuntime()
    runtime.start()
    with pytest.raises(ValueError, match="at least one evaluated observation"):
        runtime.result()


# --- orcamento ------------------------------------------------------------------


def test_the_round_budget_expires_into_a_human_wait_not_a_rejection():
    with ChallengeRuntime(limits=RuntimeLimits(max_rounds=1, timeout_seconds=30.0, max_duration_seconds=60.0)) as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        runtime.evaluate(dom_html=CHALLENGE_HTML)  # orcamento estourado
        result = runtime.result()

    assert result.final_status == "expired"
    assert result.reason_token == "human_observation_timeout"
    assert result.needs_human is True
    assert result.budget["exhausted_by"] == "max_rounds"
    assert "budget_exhausted" in runtime.journal.kinds()


def test_expiry_never_says_the_provider_rejected_anything():
    """Tres campos, tres fatos: DECISAO incerta, motivo do fim, humano ainda necessario.

    `decision="unknown"` vem da policy: nada foi recusado e o desfecho nao se
    sabe. `final_status="expired"` diz POR QUE o ciclo parou. E `human_required`
    continua True — expirar nao resolve nada, e nao rebaixa ninguem.
    """
    with ChallengeRuntime(limits=RuntimeLimits(max_rounds=1, timeout_seconds=30.0, max_duration_seconds=60.0)) as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        result = runtime.result()
    assert result.final_status == "expired"
    assert result.final_status != "provider_rejected"
    assert result.decision == "unknown"
    assert result.human_required is True


# --- revalidacao ----------------------------------------------------------------


def test_revalidation_requires_a_fresh_observation_that_the_challenge_is_gone():
    with ChallengeRuntime() as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        still_there = runtime.revalidate(dom_html=CHALLENGE_HTML, browser_write_sent=True)
        assert still_there.resolved is False
        assert still_there.write_seen is True

    with ChallengeRuntime() as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        gone = runtime.revalidate(dom_html=PLAIN_HTML)
        assert gone.resolved is True
        assert gone.reason_token == "challenge_resolved_externally"
        result = runtime.result()
        assert result.final_status == "resolved_externally"
        assert result.needs_human is False


def test_revalidation_after_the_budget_is_gone_reports_expiry_not_resolution():
    with ChallengeRuntime(limits=RuntimeLimits(max_rounds=1, timeout_seconds=30.0, max_duration_seconds=60.0)) as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        validation = runtime.revalidate(dom_html=PLAIN_HTML)
    assert validation.resolved is False
    assert validation.reason_token == "human_observation_timeout"


# --- browser falso: injecao de backend e posse ----------------------------------


def test_an_injected_adapter_is_used_and_named():
    adapter = FakeAdapter()
    session = FakeSession()
    with ChallengeRuntime(session=session, adapter=adapter) as runtime:
        runtime.evaluate()
        result = runtime.result()
        assert adapter.attachments == 1
        assert runtime.monitor.adapter_name == "fake-adapter"
        assert result.backend == "fake-cdp"
        assert result.provider == "hcaptcha"
    assert session.started == 1 and session.closed == 1
    assert session.closed_with == [{}], "o runtime nao decide sobre um browser que nao lancou"


def test_navigation_resets_transient_data_before_observing_again():
    adapter = FakeAdapter(url="https://example.test/step-1")
    session = FakeSession()
    runtime = ChallengeRuntime(session=session, adapter=adapter)
    runtime.start()
    runtime.evaluate()
    adapter._url = "https://example.test/step-2"
    runtime.observe()
    assert runtime.lifecycle.navigations == 1
    assert runtime.lifecycle.resets >= 1
    assert runtime.lifecycle.reset_pending is False
    assert adapter.resets >= 1
    assert session.resets >= 1
    runtime.close()


def test_the_runtime_never_stores_the_page_url():
    adapter = FakeAdapter(url="https://example.test/apply?token=super-secret-value")
    runtime = ChallengeRuntime(session=FakeSession(), adapter=adapter)
    runtime.start()
    runtime.observe()
    runtime.close()
    serialized = str(runtime.journal.events)
    assert "super-secret-value" not in serialized
    assert "example.test" not in serialized


def test_the_result_is_a_closed_set_without_browser_material():
    with ChallengeRuntime() as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
        payload = runtime.result().to_dict()
    assert set(payload) == {
        "detected",
        "decision",
        "final_status",
        "reason_token",
        "session_id",
        "provider",
        "challenge_type",
        "phase",
        "rounds",
        "confidence",
        "human_required",
        "capability",
        "backend",
        "started_at",
        "finished_at",
        "budget",
    }
    assert_no_sensitive_material(payload, where="result")


def test_provenance_can_be_reconstructed_after_close():
    with ChallengeRuntime() as runtime:
        runtime.evaluate(dom_html=CHALLENGE_HTML)
    provenance = runtime.journal.provenance()
    assert provenance is not None
    assert provenance.provider == "hcaptcha"
    assert provenance.challenge_type == ChallengeType.CHECKBOX.value
    assert provenance.finished is True
    assert provenance.started_at and provenance.finished_at


# --- CG-028: o escopo FILTRA o que o observador le -------------------------------


def test_the_runtime_only_hands_the_observer_records_inside_the_declared_scope():
    adapter = FakeAdapter()
    session = FakeSession()
    with ChallengeRuntime(session=session, adapter=adapter) as runtime:
        runtime.evaluate()
        scoped = runtime.scoped_adapter
        assert scoped is not None
        assert scoped.describe_scope() == {"network_read": 2, "network_in_scope": 1, "network_dropped": 1}
        kept = runtime.monitor.adapter.collect_network()
        assert [record.url for record in kept] == ["https://hcaptcha.com/1/api.js"]
        # O wrapper e transparente: o nome continua sendo o do backend real.
        assert runtime.monitor.adapter_name == "fake-adapter"
    counts = [event for event in runtime.journal.events if event["kind"] == "observation"]
    assert counts and counts[0]["network_read"] == 2 and counts[0]["network_dropped"] == 1
