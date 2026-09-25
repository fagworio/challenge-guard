"""Contrato do adapter de browser.

O core conhece apenas isto. Nao ha Playwright no nucleo: um adapter Selenium ou
de computer-use caberia aqui sem tocar em dominio, policy ou observers.
"""

from __future__ import annotations

from typing import Protocol

from ..observers import FrameInfo, NetworkRecord, ResponseRecord


class BrowserChallengeAdapter(Protocol):
    """Le a pagina e devolve fatos crus. Nunca decide nada."""

    def attach(self, page: object) -> None: ...

    def detach(self) -> None: ...

    def current_url(self) -> str: ...

    def collect_dom(self) -> str: ...

    def collect_frames(self) -> list[FrameInfo]: ...

    def collect_network(self) -> list[NetworkRecord]: ...

    def collect_responses(self) -> list[ResponseRecord]: ...


class BrowserSession(Protocol):
    """Lifecycle de uma sessao de browser, sem policy de challenge.

    Existe separado do adapter de proposito: um adapter fala com a PAGE (DOM,
    frames, rede); uma sessao fala com o BROWSER (conectar, escolher/renovar a
    page, desconectar). Misturar os dois foi o que tornou o ciclo de vida fragil
    em outros projetos — listener duplicado, page morta ainda referenciada,
    conexao que sobrevive ao handoff.
    """

    def start(self) -> object: ...

    @property
    def page(self) -> object: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...
