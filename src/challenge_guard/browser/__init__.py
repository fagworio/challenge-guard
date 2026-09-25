"""Adapters e sessoes de browser. O core nao depende de nenhum deles.

`PlaywrightChallengeAdapter` observa uma PAGE e nao importa Playwright no
`import challenge_guard` (e carregado sob demanda). `PlaywrightCdpSession`
conecta a um browser que o HOST lancou, via endpoint CDP, e existe para que o
observer seja um so em qualquer backend (ADR 0007).
"""

from .protocol import BrowserChallengeAdapter, BrowserSession
from .playwright import PlaywrightChallengeAdapter
from .cdp import CdpConnectionError, CdpEndpoint, CdpEndpointError, PlaywrightCdpSession, connect

__all__ = [
    "BrowserChallengeAdapter",
    "BrowserSession",
    "CdpConnectionError",
    "CdpEndpoint",
    "CdpEndpointError",
    "PlaywrightChallengeAdapter",
    "PlaywrightCdpSession",
    "connect",
]
