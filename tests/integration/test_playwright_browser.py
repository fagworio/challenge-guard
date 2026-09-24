"""CG-014 e CG-015 contra um browser real e fixtures locais.

Nivel 1 e 2 das fixtures: HTML deterministico e respostas locais. Nada aqui
depende de Google, hCaptcha ou de rede externa — um teste que dependesse de
terceiros em tempo real seria instavel e nao provaria nada de forma reprodutivel.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright")

from challenge_guard import (
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengePolicy,
    ChallengeSessionStatus,
    ChallengeSessionTracker,
    DOMObserver,
    FrameObserver,
    NetworkObserver,
    ResponseObserver,
    merge,
    redact,
)
from challenge_guard.browser import PlaywrightChallengeAdapter

#: Pagina cujo widget aparece, muda de estrutura duas vezes e desaparece.
#: E o ciclo que o modelo booleano nao conseguia representar.
CHALLENGE_PAGE = b"""<!doctype html><html><body>
<main><form id="app"><input name="name"><button type="submit">Submit application</button></form></main>
<div id="challenge"></div>
<script>
const box = document.getElementById('challenge');
setTimeout(() => { box.innerHTML = '<div class="h-captcha" data-sitekey="fixture-key"></div>'; }, 300);
setTimeout(() => { const el = box.firstElementChild; if (el) el.className = 'h-captcha grid-4x4'; }, 1500);
setTimeout(() => { const el = box.firstElementChild; if (el) el.className = 'h-captcha grid-5x5'; }, 2800);
setTimeout(() => { box.innerHTML = ''; }, 4200);
</script></body></html>"""

PLAIN_PAGE = b"""<!doctype html><html><body>
<form id="app"><input name="email"><button type="submit">Submit</button></form>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/reject"):
            body = json.dumps({"error": "There was an error verifying your application."}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
        elif self.path.startswith("/challenge"):
            body = CHALLENGE_PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            body = PLAIN_PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join(timeout=2)


@pytest.fixture()
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        yield context.new_page()
        browser.close()


# --- CG-014: ciclo de vida do adapter ----------------------------------------


def test_attach_is_idempotent(page, server):
    """attach duas vezes nao pode duplicar listener."""
    adapter = PlaywrightChallengeAdapter()
    adapter.attach(page)
    adapter.attach(page)
    assert len(adapter._handlers) == 3
    page.goto(server + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(300)
    # Um unico listener por evento: se houvesse dois, a request apareceria duas vezes.
    urls = [record.url for record in adapter.collect_network()]
    assert len(urls) == len(set(urls))


def test_detach_removes_listeners(page, server):
    adapter = PlaywrightChallengeAdapter()
    adapter.attach(page)
    page.goto(server + "/", wait_until="domcontentloaded")
    adapter.detach()
    assert adapter.attached is False
    assert adapter._handlers == []
    assert adapter.collect_network() == []

    before = len(adapter.collect_network())
    page.goto(server + "/?second", wait_until="domcontentloaded")
    page.wait_for_timeout(300)
    assert len(adapter.collect_network()) == before


def test_navigation_clears_transient_observation(page, server):
    """Resposta da pagina anterior nao pode classificar a sessao atual."""
    adapter = PlaywrightChallengeAdapter()
    adapter.attach(page)
    page.goto(server + "/reject", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    assert adapter.collect_responses(), "a resposta deveria ter sido observada"
    page.goto(server + "/", wait_until="domcontentloaded")
    assert adapter.collect_responses() == []


def test_a_new_session_does_not_inherit_old_responses(page, server):
    adapter = PlaywrightChallengeAdapter()
    adapter.attach(page)
    page.goto(server + "/reject", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    adapter.reset()
    assert adapter.collect_responses() == []


def test_the_adapter_exposes_no_policy():
    """Adapter fino: quem decide e o dominio, nao o adapter."""
    from challenge_guard.browser import PlaywrightChallengeAdapter as Adapter

    for forbidden in ("decide", "solve", "bypass", "handle", "policy"):
        assert not hasattr(Adapter, forbidden)


# --- CG-015: prova final -----------------------------------------------------


def _observation_from(adapter, phase):
    dom = DOMObserver().observe(adapter.collect_dom())
    frames = FrameObserver().observe(adapter.collect_frames())
    network = NetworkObserver().observe(adapter.collect_network())
    response = ResponseObserver().observe(adapter.collect_responses())
    merged = merge([dom, frames, network, response])
    return ChallengeObservation(
        detected=merged.detected,
        phase=phase,
        provider=merged.provider,
        challenge_type=merged.challenge_type,
        visible=merged.detected,
        dom_signals=dom.structure,
        frame_signals=frames.structure,
        signals=merged.signals,
        confidence=merged.confidence,
    )


def test_the_full_human_lifecycle_on_a_real_browser(page, server):
    """browser -> challenge -> rodadas -> sumico -> RESOLVED_EXTERNALLY.

    Sem estado de submissao, sem conhecimento de ATS e sem solucao de CAPTCHA:
    se este teste passa, a separacao funcionou.
    """
    adapter = PlaywrightChallengeAdapter()
    tracker = ChallengeSessionTracker()
    policy = ChallengePolicy()
    adapter.attach(page)
    page.goto(server + "/challenge", wait_until="domcontentloaded")

    session = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        observation = _observation_from(adapter, ChallengePhase.PRE_SUBMIT)
        if session is None:
            if not observation.detected:
                page.wait_for_timeout(150)
                continue
            session = tracker.start(observation)
        else:
            tracker.observe(session, observation)
            if session.status is ChallengeSessionStatus.DISAPPEARED:
                break
        page.wait_for_timeout(150)

    assert session is not None, "o challenge deveria ter sido detectado"
    assert tracker.sessions() == [session], "a sessao nao pode reiniciar a cada rodada"
    assert session.rounds_observed >= 3, f"rodadas observadas: {session.rounds_observed}"
    assert session.dynamic_content is True
    assert session.status is ChallengeSessionStatus.DISAPPEARED

    final = _observation_from(adapter, ChallengePhase.PRE_SUBMIT)
    decision = policy.decide(final, session)
    assert decision.status is ChallengeDecisionStatus.RESOLVED_EXTERNALLY
    assert decision.human_required is False

    # A evidencia e persistivel e nao carrega o sitekey da fixture.
    evidence = redact(session=session, observation=final, decision=decision)
    blob = json.dumps(evidence.to_dict())
    assert "fixture-key" not in blob
    assert evidence.rounds_observed >= 3


def test_a_plain_page_produces_no_challenge_session(page, server):
    adapter = PlaywrightChallengeAdapter()
    tracker = ChallengeSessionTracker()
    adapter.attach(page)
    page.goto(server + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    observation = _observation_from(adapter, ChallengePhase.PRE_SUBMIT)
    assert observation.detected is False
    assert tracker.sessions() == []


def test_the_real_rejection_message_flows_from_browser_to_provider_rejected(page, server):
    """Nivel 2: resposta local com a mensagem real, do browser ate a decisao."""
    adapter = PlaywrightChallengeAdapter()
    policy = ChallengePolicy()
    adapter.attach(page)
    page.goto(server + "/", wait_until="domcontentloaded")
    page.evaluate("() => fetch('/reject').catch(() => {})")
    page.wait_for_timeout(700)

    observation = _observation_from(adapter, ChallengePhase.POST_SUBMIT)
    assert observation.detected is True, "a resposta deveria ter virado sinal"
    from dataclasses import replace

    observation = replace(observation, browser_write_sent=True)
    decision = policy.decide(observation)
    assert decision.status is ChallengeDecisionStatus.PROVIDER_REJECTED
