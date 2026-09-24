"""Fingerprint estrutural para detectar nova rodada (CG-005).

O objetivo e responder "isto mudou?" sem olhar para o que o desafio *diz*.
Comparamos apenas forma: provider, tipo, quantidade e caminho dos frames,
sinais de estrutura do DOM e dimensoes do widget.

O que NUNCA entra no fingerprint:

    resposta escolhida
    tile clicado
    token
    cookie
    header de autorizacao
    texto do desafio

Consequencia deliberada: duas rodadas com o mesmo desenho produzem o mesmo
hash. Preferimos perder uma rodada a registrar conteudo do desafio.
"""

from __future__ import annotations

import hashlib
import json
import re

from .models import ChallengeObservation

#: Sinais que carregam dado sensivel do desafio e por isso nao podem entrar no
#: fingerprint, mesmo que um observador os produza.
#:
#: `tile` e `click` ficaram FORA de proposito: o reCAPTCHA usa classes como
#: `rc-imageselect-tile` e `rc-imageselect-click`, que sao estrutura legitima.
#: Uma lista agressiva demais recusaria paginas reais — falso positivo e tao ruim
#: quanto falso negativo, porque derruba a observacao inteira.
_FORBIDDEN_SIGNAL = re.compile(
    r"(token|cookie|authorization|answer|solution|response_text|payload)",
    re.IGNORECASE,
)


class UnsafeFingerprintInput(ValueError):
    """Um sinal tentou entrar no fingerprint carregando dado do desafio."""


def _safe_signals(signals: tuple[str, ...], *, origin: str) -> list[str]:
    safe: list[str] = []
    for raw in signals:
        text = str(raw).strip()
        if not text:
            continue
        if _FORBIDDEN_SIGNAL.search(text):
            raise UnsafeFingerprintInput(
                f"{origin} signal looks like challenge content, not structure: {text[:40]!r}"
            )
        safe.append(text.casefold())
    # Ordem nao e estrutura: o mesmo conjunto em ordem diferente e a mesma rodada.
    return sorted(set(safe))


def structural_fingerprint(observation: ChallengeObservation) -> str:
    """Hash estavel da ESTRUTURA observada.

    Devolve string vazia quando nao ha desafio: um fingerprint de "nada" nao
    deve ser comparavel com o de uma rodada real.
    """
    if not observation.detected:
        return ""
    payload = {
        "provider": observation.provider.value,
        "type": observation.challenge_type.value,
        "dom": _safe_signals(observation.dom_signals, origin="dom"),
        "frames": _safe_signals(observation.frame_signals, origin="frame"),
        "dimensions": list(observation.challenge_dimensions) if observation.challenge_dimensions else None,
        "structure_version": 1,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]
