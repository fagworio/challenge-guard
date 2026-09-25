"""CG-029 — Sensitive Material Guard.

A redacao de evidencia (`evidence.py`) ja protegia a evidencia. Este guard cobre
as OUTRAS superficies por onde material transitorio do browser escaparia:

```text
dataclasses        campo novo com nome inocente e conteudo sensivel
journal            evento de auditoria com o payload cru
public result      o que o host imprime no terminal
exceptions         mensagem que carrega a resposta do provedor
repr               o que aparece num traceback ou num log de debug
```

Regra de ouro: o guard NUNCA imprime o valor ofensor na mensagem — so o CAMINHO
da chave. Um guard que ecoa o segredo para reclamar dele e um vazamento com passo
extra.

`_ALLOWED_KEYS` e explicito de proposito: `reason_token` e `response_signals`
CONTEM palavras proibidas e sao vocabulario legitimo do dominio. Uma chave nova
com palavra suspeita tem de ser adicionada aqui de forma deliberada — que e o
ponto.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
import re
from typing import Any

#: Palavras que nao podem aparecer em CHAVE nenhuma da superficie publica.
SENSITIVE_KEY_PATTERNS = (
    "token",
    "cookie",
    "authorization",
    "bearer",
    "secret",
    "password",
    "credential",
    "sitekey",
    "site_key",
    "captcha_answer",
    "answer_captcha",
    "session_key",
    "jwt",
    "api_key",
    "apikey",
    "private_key",
)

#: Chaves legitimas que CONTEM uma palavra acima. Deliberado, curto e testado.
_ALLOWED_KEYS = frozenset({"reason_token", "response_signals"})

#: Formatos de VALOR que denunciam material de desafio: um token de resposta, um
#: JWT, um blob longo em base64/hex. Valor de resposta de captcha e o caso mais
#: grave, porque e exatamente o que esta biblioteca promete nunca tocar.
_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)g-recaptcha-response\s*[:=]"),
    re.compile(r"(?i)h-captcha-response\s*[:=]"),
    re.compile(r"^[A-Za-z0-9+/_\-]{64,}={0,2}$"),  # blob opaco longo
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),  # e-mail
)

_MAX_DEPTH = 8


class SensitiveMaterialLeak(RuntimeError):
    """Material sensivel apareceu numa superficie que nao pode carrega-lo."""


def assert_key_is_safe(key: str, *, where: str) -> None:
    folded = str(key).casefold()
    if folded in _ALLOWED_KEYS:
        return
    for pattern in SENSITIVE_KEY_PATTERNS:
        if pattern in folded:
            raise SensitiveMaterialLeak(f"{where}: field name {folded!r} names sensitive material")


def assert_value_is_safe(value: str, *, where: str) -> None:
    """Recusa valores que PARECEM segredo, sem ecoar o valor."""
    text = str(value)
    for pattern in _VALUE_PATTERNS:
        if pattern.search(text):
            raise SensitiveMaterialLeak(f"{where}: value matches a sensitive material pattern")


def assert_no_sensitive_material(payload: object, *, where: str, _path: str = "", _depth: int = 0) -> None:
    """Varre recursivamente. Levanta no primeiro problema, citando so o caminho."""
    if _depth > _MAX_DEPTH:
        raise SensitiveMaterialLeak(f"{where}: nesting too deep to verify (depth>{_MAX_DEPTH})")
    if payload is None or isinstance(payload, (bool, int, float)):
        return
    if isinstance(payload, str):
        assert_value_is_safe(payload, where=f"{where}{_path}")
        return
    if is_dataclass(payload) and not isinstance(payload, type):
        for field in fields(payload):
            assert_key_is_safe(field.name, where=f"{where}{_path}")
            assert_no_sensitive_material(
                getattr(payload, field.name), where=where, _path=f"{_path}.{field.name}", _depth=_depth + 1
            )
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            assert_key_is_safe(str(key), where=f"{where}{_path}")
            assert_no_sensitive_material(value, where=where, _path=f"{_path}.{key}", _depth=_depth + 1)
        return
    if isinstance(payload, Sequence):
        for index, item in enumerate(payload):
            assert_no_sensitive_material(item, where=where, _path=f"{_path}[{index}]", _depth=_depth + 1)
        return
    # Objeto opaco (driver, page, resposta): nao ha o que varrer sem entrar na
    # biblioteca de terceiros. O que se verifica e a superficie NOSSA.
    return


def safe_repr(payload: Any, *, where: str = "repr") -> str:
    """`repr` que nunca carrega material sensivel — para log e excecao."""
    assert_no_sensitive_material(payload, where=where)
    return repr(payload)


__all__ = [
    "SENSITIVE_KEY_PATTERNS",
    "SensitiveMaterialLeak",
    "assert_key_is_safe",
    "assert_no_sensitive_material",
    "assert_value_is_safe",
    "safe_repr",
]
