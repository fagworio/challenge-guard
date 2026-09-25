"""Ponte CDP -> Playwright (CG-022/CG-023).

O guard NAO lanca browser nesta camada: ele **conecta** a um endpoint CDP que ja
existe. Quem decide como o browser nasce e o host — Chrome puro, um Chrome
gerenciado por outra ferramenta, ou qualquer launcher que ele escolha. O que
existe aqui e a unica coisa que precisa existir para reaproveitar o adapter:

    endpoint CDP -> Playwright.connect_over_cdp() -> Page -> PlaywrightChallengeAdapter

Por que a ponte e neutra (ADR 0007): existem launchers que se apresentam como
"stealth" e cujo proposito declarado e nao ser detectado. Isso e o oposto do
contrato desta biblioteca, e importa menos pelo nome do que pelo efeito: a
evidencia que o guard produz tem de descrever um browser comum. Aqui nao ha
opcao de modo UC, de reescrita de fingerprint, de injecao de script nem de
desabilitar sinal de automacao — nao porque estejam desligadas, mas porque **nao
existem** no codigo.

Posse: quem lanca, desliga. `PlaywrightCdpSession.close()` desconecta o
Playwright e NAO mata o browser remoto; `close(close_browser=True)` existe
apenas para quem lancou o browser e quer encerra-lo junto.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

from .protocol import BrowserSession


class CdpEndpointError(ValueError):
    """Um endpoint CDP invalido nunca vira uma conexao."""


class CdpConnectionError(RuntimeError):
    """A conexao falhou. O erro diz o que falhou, nunca o conteudo da pagina."""


_ENDPOINT = re.compile(r"^https?://[A-Za-z0-9.\-]+(?::(\d{1,5}))?/?$")

#: Portas plausiveis de remote debugging. Zero nao existe; acima disso nao e
#: porta. O default do Chrome e 9222, mas um launcher pode pedir porta efemera.
_MIN_PORT = 1
_MAX_PORT = 65535


@dataclass(frozen=True)
class CdpEndpoint:
    """Um endereco de remote debugging, e nada mais.

    Nao guarda token, header, aba escolhida nem estado de conexao: e um valor
    que se pode registrar em log sem vazar nada — e por isso mesmo a
    proveniencia pode carrega-lo.
    """

    url: str

    def __post_init__(self) -> None:
        raw = str(self.url).strip()
        if not raw:
            raise CdpEndpointError("CDP endpoint requires a URL")
        if not _ENDPOINT.match(raw):
            raise CdpEndpointError(f"CDP endpoint must be http(s)://host[:port], got {raw!r}")
        parsed = urlsplit(raw)
        if parsed.username or parsed.password:
            raise CdpEndpointError("CDP endpoint must not carry credentials")
        if parsed.path not in ("", "/"):
            raise CdpEndpointError("CDP endpoint must not carry a path")
        try:
            # `urlsplit().port` LEVANTA para porta fora de 0..65535 e para porta
            # nao numerica; a fronteira traduz isso em erro proprio.
            port = parsed.port
        except ValueError as exc:
            raise CdpEndpointError(f"CDP endpoint has an unusable port: {raw!r}") from exc
        if port is not None and not _MIN_PORT <= port <= _MAX_PORT:
            raise CdpEndpointError(f"CDP endpoint port out of range: {port}")
        object.__setattr__(self, "url", raw.rstrip("/"))

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def port(self) -> int | None:
        return urlsplit(self.url).port

    @property
    def loopback(self) -> bool:
        """Remote debugging fora do loopback e exposicao de browser na rede."""
        return self.host in {"127.0.0.1", "localhost", "::1"}

    def describe(self) -> dict[str, object]:
        """Forma segura para proveniencia: host e porta, nunca a URL crua."""
        return {"cdp_host": self.host, "cdp_port": self.port, "cdp_loopback": self.loopback}

    @classmethod
    def from_url(cls, raw: str) -> "CdpEndpoint":
        return cls(raw)


class _PlaywrightFactory(Protocol):
    def __call__(self) -> Any: ...


def _default_playwright_factory() -> Any:
    """Importa o Playwright SO aqui: `import challenge_guard` nunca o carrega.

    `sync_playwright()` devolve um GERENCIADOR de contexto, nao um cliente. O
    erro de devolver o gerenciador apareceu apenas no teste com Chrome real (com
    cliente falso ele passa, porque o falso ja e o cliente) — e o guard que
    impede a reincidencia e o teste `test_the_default_factory_returns_a_started_client`.
    """
    from playwright.sync_api import sync_playwright

    try:
        return sync_playwright().start()
    except Exception as exc:
        # Medido no CG-035: com o plugin de pytest do SeleniumBase instalado, o
        # Playwright sincrono recusa iniciar ("Sync API inside the asyncio
        # loop"). A biblioteca NAO aplica `nest_asyncio` para contornar isso: isso
        # patchearia o event loop de todo mundo. Ela diz o que houve e devolve a
        # decisao de loop para o host.
        if "asyncio loop" in str(exc):
            raise CdpConnectionError(
                "Playwright sync API cannot start inside a running asyncio loop; the host owns loop "
                "policy (a loaded pytest plugin can create one: run with -p no:seleniumbase, or start "
                "the browser in a separate process)"
            ) from exc
        raise


class PlaywrightCdpSession:
    """Uma `Page` do Playwright sobre um browser que outro processo lancou.

    `start()` e idempotente por desenho: chamar duas vezes devolve a MESMA page e
    nao abre uma segunda conexao. Diferente de um adapter, que fala com a pagina,
    esta sessao fala com o **browser** — e por isso e a unica coisa que precisa
    sobreviver a navegacao.
    """

    name = "playwright-cdp"

    def __init__(
        self,
        endpoint: CdpEndpoint,
        *,
        playwright_factory: _PlaywrightFactory | None = None,
        connect_timeout_ms: float = 30_000,
        prefer_last_page: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._connect_timeout_ms = float(connect_timeout_ms)
        self._prefer_last_page = prefer_last_page
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started = False

    @classmethod
    def from_endpoint(cls, endpoint: CdpEndpoint | str, **kwargs: Any) -> "PlaywrightCdpSession":
        """Construtor a partir de uma URL: `PlaywrightCdpSession.from_endpoint("http://127.0.0.1:9222")`."""
        resolved = endpoint if isinstance(endpoint, CdpEndpoint) else CdpEndpoint.from_url(str(endpoint))
        return cls(resolved, **kwargs)

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> Any:
        """Conecta (uma vez) e devolve a page observavel."""
        if self._page is not None:
            return self._page
        if self._started:
            # Ja conectado, mas sem page (fechada por fora): reencontra uma.
            return self._select_page()
        try:
            self._playwright = self._playwright_factory()
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.endpoint.url,
                timeout=self._connect_timeout_ms,
            )
        except CdpConnectionError:
            # Erro ja traduzido por nos (politica de loop, por exemplo): a
            # mensagem acionavel nao pode ser embrulhada em "AttributeError".
            self._teardown()
            raise
        except Exception as exc:  # a fronteira traduz; nao propaga detalhe do driver
            self._teardown()
            raise CdpConnectionError(f"could not connect to CDP endpoint: {type(exc).__name__}") from exc
        self._started = True
        return self._select_page()

    @property
    def connected(self) -> bool:
        return self._browser is not None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def page(self) -> Any:
        if self._page is None:
            return self._select_page()
        return self._page

    def reset(self) -> None:
        """Descarta a referencia da page. NAO recarrega nem fecha nada.

        Um widget pode abrir aba nova; o host chama `reset()` e a proxima leitura
        pega a aba ativa. `reset` nunca derruba a conexao: reconectar e caro e
        perderia o estado que o host construiu.
        """
        self._page = None

    def close(self, *, close_browser: bool = False) -> None:
        """Desconecta. Idempotente.

        `close_browser=False` (default) e a regra de posse: o browser foi lancado
        pelo host, e o guard nao o mata. Playwright encerra o driver e a conexao
        cai; o Chrome remoto continua vivo.
        """
        if close_browser and self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        self._teardown()

    def _teardown(self) -> None:
        self._browser = None
        self._context = None
        self._page = None
        self._started = False
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    # -- pagina ----------------------------------------------------------------

    def _select_page(self) -> Any:
        if self._browser is None:
            raise CdpConnectionError("session is not started")
        context = self._select_context()
        pages = list(getattr(context, "pages", []) or [])
        if pages:
            page = pages[-1] if self._prefer_last_page else pages[0]
        else:
            page = context.new_page()
        self._page = page
        return page

    def _select_context(self) -> Any:
        if self._context is not None:
            return self._context
        contexts = list(getattr(self._browser, "contexts", []) or [])
        # O browser que o host lancou normalmente ja tem um contexto com a pagina
        # que ele abriu. Preferir o contexto COM paginas evita observar uma aba
        # em branco enquanto a real fica invisivel.
        with_pages = [context for context in contexts if list(getattr(context, "pages", []) or [])]
        if with_pages:
            self._context = with_pages[0]
        elif contexts:
            self._context = contexts[0]
        else:
            self._context = self._browser.new_context()
        return self._context

    def current_url(self) -> str:
        if self._page is None:
            return ""
        return str(getattr(self._page, "url", "") or "")


def connect(endpoint: CdpEndpoint | str, **kwargs: Any) -> PlaywrightCdpSession:
    """Conveniencia: `connect("http://127.0.0.1:9222").start()`."""
    resolved = endpoint if isinstance(endpoint, CdpEndpoint) else CdpEndpoint.from_url(str(endpoint))
    return PlaywrightCdpSession(resolved, **kwargs)


__all__ = [
    "BrowserSession",
    "CdpConnectionError",
    "CdpEndpoint",
    "CdpEndpointError",
    "PlaywrightCdpSession",
    "connect",
]
