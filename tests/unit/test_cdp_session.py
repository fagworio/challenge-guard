"""CG-022/CG-023 — a ponte CDP, com um Playwright falso.

A ponte tem duas responsabilidades e nenhuma delas precisa de browser real para
ser verificada: escolher a PAGE certa e respeitar a POSSE do browser. O
Playwright entra por injecao (`playwright_factory`) exatamente para isso — o
teste de integracao, com Chrome de verdade, prova o resto.
"""

from __future__ import annotations

import pytest

from challenge_guard.browser.cdp import (
    CdpConnectionError,
    CdpEndpoint,
    CdpEndpointError,
    PlaywrightCdpSession,
    connect,
)


class FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.closed = False


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        self.pages = pages or []
        self.created = 0

    def new_page(self) -> FakePage:
        self.created += 1
        page = FakePage("about:blank#new")
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext] | None = None) -> None:
        self.contexts = contexts or []
        self.closed = 0
        self.new_contexts = 0

    def new_context(self) -> FakeContext:
        self.new_contexts += 1
        context = FakeContext()
        self.contexts.append(context)
        return context

    def close(self) -> None:
        self.closed += 1


class FakeChromium:
    def __init__(self, browser: FakeBrowser | None = None, error: Exception | None = None) -> None:
        self.browser = browser
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def connect_over_cdp(self, url: str, timeout: float = 0) -> FakeBrowser:
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        assert self.browser is not None
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1


def _session(browser: FakeBrowser | None = None, *, error: Exception | None = None, url: str = "http://127.0.0.1:9222"):
    chromium = FakeChromium(browser or FakeBrowser(), error)
    playwright = FakePlaywright(chromium)
    session = PlaywrightCdpSession(CdpEndpoint.from_url(url), playwright_factory=lambda: playwright)
    return session, playwright, chromium


# --- endpoint -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:9222", "https://browser.internal:443", "http://localhost:1", "http://127.0.0.1:9222/"],
)
def test_valid_endpoints(url: str):
    endpoint = CdpEndpoint.from_url(url)
    assert endpoint.url.startswith("http")
    assert endpoint.host


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "ws://127.0.0.1:9222",
        "http://user:pass@127.0.0.1:9222",
        "http://127.0.0.1:9222/json/version",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
    ],
)
def test_invalid_endpoints_are_refused(url: str):
    with pytest.raises(CdpEndpointError):
        CdpEndpoint.from_url(url)


def test_describe_never_exposes_the_raw_url():
    described = CdpEndpoint.from_url("http://127.0.0.1:9222").describe()
    assert described == {"cdp_host": "127.0.0.1", "cdp_port": 9222, "cdp_loopback": True}
    assert "http://" not in str(described)


def test_loopback_is_reported_because_remote_debugging_is_a_local_privilege():
    assert CdpEndpoint.from_url("http://127.0.0.1:9222").loopback is True
    assert CdpEndpoint.from_url("http://10.0.0.5:9222").loopback is False


# --- sessao ---------------------------------------------------------------------


def test_start_connects_once_and_reuses_the_page():
    page = FakePage("https://example.test/apply")
    browser = FakeBrowser([FakeContext([page])])
    session, playwright, chromium = _session(browser)

    first = session.start()
    second = session.start()

    assert first is page and second is page
    assert len(chromium.calls) == 1
    assert chromium.calls[0][0] == "http://127.0.0.1:9222"
    assert session.started and session.connected
    assert session.current_url() == "https://example.test/apply"
    session.close()
    assert playwright.stopped == 1


def test_the_context_with_pages_wins_over_an_empty_one():
    wanted = FakePage("https://example.test/real")
    browser = FakeBrowser([FakeContext([]), FakeContext([wanted])])
    session, _playwright, _chromium = _session(browser)
    assert session.start() is wanted


def test_the_last_page_is_preferred_because_a_widget_may_open_a_tab():
    first, last = FakePage("https://example.test/one"), FakePage("https://example.test/two")
    browser = FakeBrowser([FakeContext([first, last])])
    session, _playwright, _chromium = _session(browser)
    assert session.start() is last


def test_prefer_first_page_is_available_for_hosts_that_need_it():
    first, last = FakePage("https://example.test/one"), FakePage("https://example.test/two")
    browser = FakeBrowser([FakeContext([first, last])])
    chromium = FakeChromium(browser)
    session = PlaywrightCdpSession(
        CdpEndpoint.from_url("http://127.0.0.1:9222"),
        playwright_factory=lambda: FakePlaywright(chromium),
        prefer_last_page=False,
    )
    assert session.start() is first


def test_a_context_without_pages_gets_one():
    context = FakeContext([])
    browser = FakeBrowser([context])
    session, _playwright, _chromium = _session(browser)
    page = session.start()
    assert context.created == 1 and page in context.pages


def test_a_browser_without_context_gets_one():
    browser = FakeBrowser([])
    session, _playwright, _chromium = _session(browser)
    session.start()
    assert browser.new_contexts == 1


def test_reset_drops_the_page_reference_and_reselects():
    first = FakePage("https://example.test/one")
    context = FakeContext([first])
    session, _playwright, _chromium = _session(FakeBrowser([context]))
    assert session.start() is first
    new_page = FakePage("https://example.test/two")
    context.pages.append(new_page)
    session.reset()
    assert session.page is new_page


def test_close_does_not_kill_a_browser_the_session_did_not_launch():
    browser = FakeBrowser([FakeContext([FakePage()])])
    session, playwright, _chromium = _session(browser)
    session.start()
    session.close()
    assert browser.closed == 0, "posse: quem lancou desliga"
    assert playwright.stopped == 1
    assert session.connected is False


def test_close_browser_is_opt_in_for_hosts_that_own_the_browser():
    browser = FakeBrowser([FakeContext([FakePage()])])
    session, playwright, _chromium = _session(browser)
    session.start()
    session.close(close_browser=True)
    assert browser.closed == 1 and playwright.stopped == 1


def test_close_is_idempotent():
    session, playwright, _chromium = _session(FakeBrowser([FakeContext([FakePage()])]))
    session.start()
    session.close()
    session.close()
    assert playwright.stopped == 1


def test_a_failed_connection_raises_a_typed_error_and_cleans_up():
    session, playwright, _chromium = _session(error=RuntimeError("boom"))
    with pytest.raises(CdpConnectionError, match="could not connect"):
        session.start()
    assert session.connected is False
    assert playwright.stopped == 1, "uma conexao que falhou nao pode deixar driver vivo"


def test_the_error_message_never_carries_the_driver_detail():
    session, _playwright, _chromium = _session(error=RuntimeError("secret-ish detail from the driver"))
    with pytest.raises(CdpConnectionError) as error:
        session.start()
    assert "secret-ish" not in str(error.value)


def test_page_after_close_is_an_error_not_a_silent_none():
    session, _playwright, _chromium = _session(FakeBrowser([FakeContext([FakePage()])]))
    session.start()
    session.close()
    with pytest.raises(CdpConnectionError, match="not started"):
        _ = session.page


def test_connect_helper_accepts_a_url_string():
    session = connect("http://127.0.0.1:9222")
    assert session.endpoint.port == 9222
    assert session.name == "playwright-cdp"
