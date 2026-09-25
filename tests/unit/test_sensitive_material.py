"""CG-029 — o guard de material sensivel, superficie por superficie.

O ponto nao e "existe uma lista de palavras". E que o material transitorio do
browser nao atravessa a fronteira por um campo novo, por um evento de journal, por
uma mensagem de excecao ou por um `repr` esquecido. E que, ao recusar, ele nao
ecoem o segredo.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from challenge_guard.guards.sensitive_material import (
    SensitiveMaterialLeak,
    assert_key_is_safe,
    assert_no_sensitive_material,
    assert_value_is_safe,
    safe_repr,
)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    "key",
    [
        "captcha_token",
        "cookie",
        "authorization",
        "bearer_token",
        "client_secret",
        "password",
        "credential",
        "sitekey",
        "site_key",
        "captcha_answer",
        "answer_captcha",
        "session_key",
        "api_key",
        "private_key",
    ],
)
def test_sensitive_field_names_are_refused(key: str):
    with pytest.raises(SensitiveMaterialLeak, match="names sensitive material"):
        assert_key_is_safe(key, where="test")


@pytest.mark.parametrize("key", ["reason_token", "response_signals", "session_id", "provider"])
def test_the_domain_vocabulary_is_allowed_deliberately(key: str):
    assert_key_is_safe(key, where="test")


@pytest.mark.parametrize(
    "value",
    [
        JWT,
        "Bearer abcdefghijklmnop",
        "g-recaptcha-response=03AGdBq26",
        "h-captcha-response: P0_eyJ0eXAi",
        "A" * 80,
        "candidate@example.com",
    ],
)
def test_secret_looking_values_are_refused(value: str):
    with pytest.raises(SensitiveMaterialLeak):
        assert_value_is_safe(value, where="test")


@pytest.mark.parametrize("value", ["challenge_detected_pre_submit", "recaptcha_enterprise", "human_required", "0.9"])
def test_ordinary_values_pass(value: str):
    assert_value_is_safe(value, where="test")


def test_the_rejection_never_echoes_the_secret():
    """Um guard que imprime o segredo para reclamar dele e um vazamento com passo extra."""
    with pytest.raises(SensitiveMaterialLeak) as error:
        assert_no_sensitive_material({"captcha_token": JWT}, where="evidence")
    assert JWT not in str(error.value)
    assert "captcha_token" in str(error.value)


@dataclass
class _Nested:
    provider: str = "hcaptcha"
    payload: dict | None = None


def test_nesting_is_walked_all_the_way_down():
    payload = {"rounds": [{"provider": "hcaptcha"}, {"deep": {"sitekey": "abc"}}]}
    with pytest.raises(SensitiveMaterialLeak, match="sitekey"):
        assert_no_sensitive_material(payload, where="journal")
    ok = _Nested(payload={"phase": "pre_submit", "confidence": 0.8})
    assert_no_sensitive_material(ok, where="dataclass")


def test_depth_is_bounded_instead_of_silently_passing():
    deep: dict = {"level": "x"}
    node = deep
    for _ in range(12):
        child: dict = {}
        node["child"] = child
        node = child
    with pytest.raises(SensitiveMaterialLeak, match="nesting too deep"):
        assert_no_sensitive_material(deep, where="deep")


def test_safe_repr_is_usable_for_logs():
    assert safe_repr({"provider": "hcaptcha", "rounds": 2}, where="log")
    with pytest.raises(SensitiveMaterialLeak):
        safe_repr({"cookie": "sessionid=abc"}, where="log")


def test_opaque_objects_are_not_walked():
    """Driver, page e resposta de terceiros: a superficie verificada e a NOSSA."""
    class Driver:
        def __repr__(self) -> str:  # pragma: no cover - nao e chamado
            return "<driver>"

    assert_no_sensitive_material({"driver": Driver()}, where="runtime")
