"""CG-035 — a mesma decisao nos dois backends, com Chrome de verdade.

```text
A) Playwright direto                  B) Chrome lancado por fora + CDP
   sync_playwright().chromium.launch()   subprocesso com --remote-debugging-port
   -> Page                               -> CdpEndpoint
   -> PlaywrightChallengeAdapter         -> PlaywrightCdpSession (connect_over_cdp)
                                         -> PlaywrightChallengeAdapter
```

O que se prova: **backend diferente nao muda a decisao**. Um observer, uma policy,
um resultado. E se prova tambem a POSSE: depois do `close()` do runtime, o Chrome
que o teste lancou continua vivo — o guard nao mata um browser que nao e dele.

O Chrome usado e o do proprio Playwright (versao casada com o cliente). Se
`CHALLENGE_GUARD_CDP_CHROME` estiver definida, ela vence: e assim que um host
aponta o binario dele — inclusive um Chrome gerenciado por outro launcher.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="a ponte CDP exige o extra playwright")

from challenge_guard import (
    ChallengePhase,
    ChallengeRuntime,
    LifecycleViolation,
    PlaywrightCdpSession,
    RuntimeLimits,
)
from challenge_guard.guards.network_scope import ScopeVerdict

CHALLENGE_PATH = "/challenge"
PLAIN_PATH = "/plain"
WIDGET_PATH = "/widget"

CHALLENGE_PAGE = f"""<!doctype html><html><body>
<main><form id="app"><input name="email"><button type="submit">Submit</button></form></main>
<div class="h-captcha grid-4x4" data-sitekey="fixture-sitekey"></div>
<iframe src="{WIDGET_PATH}" width="300" height="150"></iframe>
</body></html>""".encode()

PLAIN_PAGE = b"""<!doctype html><html><body>
<form id="app"><input name="email"><button type="submit">Submit</button></form>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith(CHALLENGE_PATH):
            body, status = CHALLENGE_PAGE, 200
        elif self.path.startswith(WIDGET_PATH):
            body, status = b"<html><body><div id='widget'></div></body></html>", 200
        else:
            body, status = PLAIN_PAGE, 200
        self.send_response(status)
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


def _chrome_executable() -> str:
    override = os.getenv("CHALLENGE_GUARD_CDP_CHROME")
    if override:
        return override
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        return str(playwright.chromium.executable_path)


def _launch_chrome_with_cdp(tmp_path: Path) -> tuple[subprocess.Popen, str]:
    """Lanca Chrome com remote debugging e devolve (processo, endpoint)."""
    executable = _chrome_executable()
    if not executable or not Path(executable).exists():
        pytest.skip("nenhum binario de Chrome/Chromium disponivel para o backend CDP")
    profile = tmp_path / f"profile-{int(time.time() * 1000)}"
    profile.mkdir(parents=True, exist_ok=True)
    base = [
        executable,
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "about:blank",
    ]
    for headless in ("--headless=new", "--headless"):
        process = subprocess.Popen(
            [base[0], headless, *base[1:]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port_file = profile / "DevToolsActivePort"
        for _ in range(120):
            if process.poll() is not None:
                break
            if port_file.exists():
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if lines and lines[0].strip().isdigit():
                    return process, f"http://127.0.0.1:{lines[0].strip()}"
            time.sleep(0.1)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    pytest.skip("nao foi possivel abrir um Chrome com remote debugging neste ambiente")


@pytest.fixture()
def cdp_endpoint(tmp_path: Path):
    process, endpoint = _launch_chrome_with_cdp(tmp_path)
    yield endpoint
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - ambiente teimoso
            process.kill()


# --- os dois backends -----------------------------------------------------------


class _DirectBackend:
    """Playwright direto: o backend que ja existia."""

    name = "direct"

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        self._page = self._browser.new_context().new_page()
        self._runtime = ChallengeRuntime(page=self._page, limits=RuntimeLimits(max_rounds=3)).start()
        return self._page, self._runtime

    def __exit__(self, *exc_info: object) -> None:
        try:
            self._runtime.close()
            self._browser.close()
        finally:
            self._playwright.stop()


class _CdpBackend:
    """Chrome lancado por FORA; o guard so conecta."""

    name = "cdp"

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    def __enter__(self):
        session = PlaywrightCdpSession.from_endpoint(self._endpoint)
        runtime = ChallengeRuntime(session=session, limits=RuntimeLimits(max_rounds=3))
        runtime.start()
        return session.page, runtime

    def __exit__(self, *exc_info: object) -> None:
        return None


def _observe_fixture(server: str, page, runtime: ChallengeRuntime):
    """A mesma sequencia nos dois backends: navegar, observar, coletar fatos.

    Quem navega e o HOST (o teste). O guard so observa — e isso vale nos dois
    caminhos, que e o ponto do CG-035.
    """
    page.goto(f"{server}{CHALLENGE_PATH}", wait_until="load")
    decision = runtime.evaluate(phase=ChallengePhase.PRE_SUBMIT)
    observation = runtime.monitor.observation
    adapter = runtime.monitor.adapter
    return decision, observation, adapter.collect_frames(), adapter.collect_network()


def test_both_backends_reach_the_same_decision_on_the_same_fixture(server: str, cdp_endpoint: str):
    with _DirectBackend() as (page, runtime):
        direct_decision, direct_observation, direct_frames, direct_network = _observe_fixture(server, page, runtime)
        direct_result = runtime.result()
        runtime.close()

    with _CdpBackend(cdp_endpoint) as (page, runtime):
        cdp_decision, cdp_observation, cdp_frames, cdp_network = _observe_fixture(server, page, runtime)
        cdp_result = runtime.result()
        runtime.close()

    # decisao: identica, campo a campo que importa
    assert direct_result.provider == cdp_result.provider == "hcaptcha"
    assert direct_result.challenge_type == cdp_result.challenge_type == "checkbox"
    assert direct_result.decision == cdp_result.decision == "needs_human"
    assert direct_result.final_status == cdp_result.final_status == "human_required"
    assert direct_result.human_required is cdp_result.human_required is True
    assert direct_decision.reason_token == cdp_decision.reason_token
    # confianca: compativel, nao necessariamente bit a bit
    assert abs(direct_result.confidence - cdp_result.confidence) <= 0.2

    # fatos observados: as MESMAS fontes, nas duas rotas
    assert direct_observation.evidence_sources == cdp_observation.evidence_sources
    assert "dom" in direct_observation.evidence_sources
    assert direct_observation.dom_signals == cdp_observation.dom_signals

    # DOM: o adapter le a pagina inteira, e ela e a mesma nos dois backends
    assert "h-captcha" in direct_observation.dom_signals
    assert "h-captcha" in cdp_observation.dom_signals

    # frames: o iframe do fixture e visto como fato nas duas rotas
    direct_frame_urls = sorted(frame.url for frame in direct_frames)
    cdp_frame_urls = sorted(frame.url for frame in cdp_frames)
    assert direct_frame_urls == cdp_frame_urls
    assert any(url.endswith(WIDGET_PATH) for url in direct_frame_urls)

    # rede: os dois veem os MESMOS fatos do fixture
    def paths(records):
        return {record.url.split("?")[0] for record in records if record.url}

    direct_paths, cdp_paths = paths(direct_network), paths(cdp_network)
    assert direct_paths == cdp_paths
    assert any(item.endswith(WIDGET_PATH) for item in direct_paths)
    # E a navegacao do frame principal LIMPA os proprios registros: o request que
    # causou a navegacao e dado transitorio (CG-A12). O que sobrevive e o que
    # aconteceu DEPOIS dela — aqui, o iframe do widget.
    assert not any(item.endswith(CHALLENGE_PATH) for item in direct_paths)


def test_the_guard_does_not_kill_a_browser_it_did_not_launch(server: str, cdp_endpoint: str, tmp_path: Path):
    """Posse medida: o endpoint responde DEPOIS do close do runtime."""
    import urllib.request

    process, endpoint = _launch_chrome_with_cdp(tmp_path)
    try:
        session = PlaywrightCdpSession.from_endpoint(endpoint)
        runtime = ChallengeRuntime(session=session)
        runtime.start()
        session.page.goto(f"{server}{CHALLENGE_PATH}", wait_until="load")
        runtime.evaluate()
        runtime.close()

        assert process.poll() is None, "o guard matou o browser do host"
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=10) as response:
            payload = response.read().decode("utf-8")
        assert "webSocketDebuggerUrl" in payload
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


# --- invariantes de lifecycle com browser real ----------------------------------


def test_navigation_invalidates_transient_data_and_the_runtime_resets(server: str, cdp_endpoint: str):
    session = PlaywrightCdpSession.from_endpoint(cdp_endpoint)
    with ChallengeRuntime(session=session) as runtime:
        page = runtime.session.page
        page.goto(f"{server}{CHALLENGE_PATH}", wait_until="load")
        runtime.evaluate()
        page.goto(f"{server}{PLAIN_PATH}", wait_until="load")
        runtime.observe()
        assert runtime.lifecycle.navigations >= 1
        assert runtime.lifecycle.reset_pending is False
    runtime.close()


def test_close_is_idempotent_with_a_real_browser(cdp_endpoint: str):
    session = PlaywrightCdpSession.from_endpoint(cdp_endpoint)
    runtime = ChallengeRuntime(session=session)
    runtime.start()
    runtime.close()
    runtime.close()
    assert runtime.lifecycle.closes == 1


def test_a_second_adapter_on_a_live_page_is_refused(cdp_endpoint: str):
    from challenge_guard.browser import PlaywrightChallengeAdapter

    session = PlaywrightCdpSession.from_endpoint(cdp_endpoint)
    runtime = ChallengeRuntime(session=session, adapter=PlaywrightChallengeAdapter())
    runtime.start()
    try:
        with pytest.raises(LifecycleViolation, match="already has an adapter"):
            runtime.monitor.attach_adapter(PlaywrightChallengeAdapter())
        assert runtime.monitor.adapter_name == "playwright"
    finally:
        runtime.close()


def test_submission_shaped_traffic_is_never_classified_as_challenge(server: str, cdp_endpoint: str):
    """Escopo de rede no browser real: os fatos observados nao viram submissao."""
    session = PlaywrightCdpSession.from_endpoint(cdp_endpoint)
    with ChallengeRuntime(session=session) as runtime:
        page = runtime.session.page
        page.goto(f"{server}{CHALLENGE_PATH}", wait_until="load")
        runtime.evaluate()
        grouped = runtime.scope.classify_all(runtime.monitor.adapter.collect_network())
    assert grouped[ScopeVerdict.SUBMISSION_CANDIDATE] == []


def test_the_default_factory_returns_a_started_client():
    """`sync_playwright()` e um gerenciador de contexto, nao um cliente.

    Devolver o gerenciador so falha com browser real — e foi exatamente o que
    aconteceu na primeira execucao do CG-035. Este teste fecha a porta.
    """
    from challenge_guard.browser.cdp import _default_playwright_factory

    client = _default_playwright_factory()
    try:
        assert hasattr(client, "chromium")
        assert hasattr(client.chromium, "connect_over_cdp")
    finally:
        client.stop()
