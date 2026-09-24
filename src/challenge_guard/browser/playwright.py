"""Adapter Playwright (CG-014).

Fino de proposito: traduz objetos do Playwright para os modelos do
challenge-guard e nada mais. Nao ha policy aqui — decisao e do dominio, e um
adapter que decide seria impossivel de testar sem browser.

Listeners sao gerenciados explicitamente por `attach`/`detach`. Isso evita os
defeitos que aparecem quando um adapter instala logica global sozinho:

    listener duplicado
    memoria acumulada
    sinal de pagina anterior
    resposta velha contaminando sessao nova
    callback sobrevivendo depois do handoff

`attach` e idempotente. Navegacao limpa a observacao transitoria: resposta da
pagina anterior nao pode classificar a sessao atual.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque

from ..observers import FrameInfo, NetworkRecord, ResponseRecord

#: Texto de resposta guardado apenas TRANSITORIAMENTE, para o observer extrair o
#: conceito. Nunca e persistido: o observer converte em sinal e o texto morre
#: com o buffer.
_MAX_RESPONSE_CHARS = 2000

#: Limites dos buffers: memoria nao pode crescer com o tempo de sessao.
_NETWORK_LIMIT = 200
_RESPONSE_LIMIT = 20


class PlaywrightChallengeAdapter:
    name = "playwright"

    def __init__(self, *, network_limit: int = _NETWORK_LIMIT, response_limit: int = _RESPONSE_LIMIT) -> None:
        self._page: Any = None
        self._requests: Deque[NetworkRecord] = deque(maxlen=network_limit)
        self._responses: Deque[ResponseRecord] = deque(maxlen=response_limit)
        self._status_by_url: dict[str, int] = {}
        self._handlers: list[tuple[str, Any]] = []

    # -- ciclo de vida ---------------------------------------------------------

    def attach(self, page: Any) -> None:
        """Instala os listeners. Chamar duas vezes NAO duplica."""
        if self._page is not None:
            return
        self._page = page
        self._bind("request", self._on_request)
        self._bind("response", self._on_response)
        self._bind("framenavigated", self._on_frame_navigated)

    def detach(self) -> None:
        """Remove os listeners e descarta os buffers."""
        if self._page is not None:
            for event, handler in self._handlers:
                try:
                    self._page.remove_listener(event, handler)
                except Exception:
                    # Um listener ja removido nao pode derrubar o detach.
                    pass
        self._handlers.clear()
        self._page = None
        self.reset()

    def reset(self) -> None:
        """Descarta observacao transitoria (nova sessao nao herda a anterior)."""
        self._requests.clear()
        self._responses.clear()
        self._status_by_url.clear()

    @property
    def attached(self) -> bool:
        return self._page is not None

    def _bind(self, event: str, handler: Any) -> None:
        self._page.on(event, handler)
        self._handlers.append((event, handler))

    # -- handlers --------------------------------------------------------------

    def _on_request(self, request: Any) -> None:
        try:
            self._requests.append(
                NetworkRecord(
                    url=str(getattr(request, "url", "")),
                    method=str(getattr(request, "method", "GET")),
                    resource_type=str(getattr(request, "resource_type", "")),
                )
            )
        except Exception:
            return

    def _on_response(self, response: Any) -> None:
        try:
            url = str(getattr(response, "url", ""))
            status = int(getattr(response, "status", 0) or 0)
        except Exception:
            return
        self._status_by_url[url] = status
        try:
            text = response.text()
        except Exception:
            # Corpo indisponivel (redirect, preflight, stream): sem texto nao ha
            # evidencia, e o observer nao inventa uma.
            return
        if not text:
            return
        self._responses.append(ResponseRecord(status=status, text=str(text)[:_MAX_RESPONSE_CHARS], url=url))

    def _on_frame_navigated(self, frame: Any) -> None:
        """Navegacao do frame principal limpa a observacao transitoria."""
        page = self._page
        if page is None:
            return
        try:
            if frame is not page.main_frame:
                return
        except Exception:
            return
        self.reset()

    # -- coleta ----------------------------------------------------------------

    def current_url(self) -> str:
        return str(getattr(self._page, "url", "")) if self._page is not None else ""

    def collect_dom(self) -> str:
        if self._page is None:
            return ""
        try:
            return str(self._page.content())
        except Exception:
            return ""

    def collect_frames(self) -> list[FrameInfo]:
        if self._page is None:
            return []
        frames: list[FrameInfo] = []
        try:
            elements = self._page.query_selector_all("iframe")
        except Exception:
            return []
        for element in elements:
            try:
                box = element.bounding_box()
                frames.append(
                    FrameInfo(
                        url=str(element.get_attribute("src") or ""),
                        visible=bool(element.is_visible()),
                        width=int(box["width"]) if box else 0,
                        height=int(box["height"]) if box else 0,
                    )
                )
            except Exception:
                continue
        return frames

    def collect_network(self) -> list[NetworkRecord]:
        records: list[NetworkRecord] = []
        for record in self._requests:
            status = self._status_by_url.get(record.url)
            records.append(
                NetworkRecord(
                    url=record.url,
                    method=record.method,
                    resource_type=record.resource_type,
                    status=status,
                )
            )
        return records

    def collect_responses(self) -> list[ResponseRecord]:
        return list(self._responses)
