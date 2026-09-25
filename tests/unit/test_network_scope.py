"""CG-028 — escopo de rede: o guard le, e so o que e challenge.

O caso que este guard existe para impedir: um POST de candidatura observado e
tratado como "trafego do desafio". A partir dai a contagem de escritas do host
fica contaminada, e a fronteira de submissao vira decoracao.
"""

from __future__ import annotations

import pytest

from challenge_guard import NetworkRecord
from challenge_guard.guards.network_scope import (
    NetworkScope,
    NetworkScopeViolation,
    ScopeVerdict,
    WRITE_METHODS,
)
from challenge_guard.requirements import runtime_read_hosts


def test_scope_is_derived_from_declared_requirements():
    scope = NetworkScope.from_providers()
    assert scope.allowed_hosts == frozenset(runtime_read_hosts())
    assert scope.permits("https://www.google.com/recaptcha/api2/anchor")
    assert scope.permits("https://hcaptcha.com/1/api.js")


def test_declared_host_is_challenge_runtime():
    scope = NetworkScope.from_providers(["hcaptcha"])
    record = NetworkRecord(url="https://hcaptcha.com/1/api.js", method="GET")
    assert scope.classify(record) is ScopeVerdict.CHALLENGE_RUNTIME


def test_subdomains_of_declared_hosts_are_in_scope():
    scope = NetworkScope.from_providers(["hcaptcha"])
    assert scope.classify(NetworkRecord(url="https://newassets.hcaptcha.com/x.js", method="GET")) is ScopeVerdict.CHALLENGE_RUNTIME


def test_a_post_to_a_foreign_host_is_out_of_scope():
    scope = NetworkScope.from_providers(["hcaptcha"])
    record = NetworkRecord(url="https://api.example.test/v1/telemetry", method="POST")
    assert scope.classify(record) is ScopeVerdict.OUT_OF_SCOPE


def test_submission_shaped_traffic_is_named_as_such_never_as_challenge():
    scope = NetworkScope.from_providers(["hcaptcha"])
    record = NetworkRecord(url="https://boards.example.test/jobs/1/applications", method="POST")
    assert scope.classify(record) is ScopeVerdict.SUBMISSION_CANDIDATE


def test_a_read_of_an_application_path_is_not_a_submission():
    """So um metodo de ESCRITA vira candidatura: ler a vaga nao e candidatar-se."""
    scope = NetworkScope.from_providers(["hcaptcha"])
    record = NetworkRecord(url="https://boards.example.test/jobs/1/applications", method="GET")
    assert scope.classify(record) is ScopeVerdict.OUT_OF_SCOPE


def test_assert_no_submission_traffic_raises_and_names_only_host_and_path():
    scope = NetworkScope.from_providers(["hcaptcha"])
    records = [
        NetworkRecord(url="https://boards.example.test/apply?token=secret-value", method="POST"),
        NetworkRecord(url="https://hcaptcha.com/1/api.js", method="GET"),
    ]
    with pytest.raises(NetworkScopeViolation) as error:
        scope.assert_no_submission_traffic(records)
    message = str(error.value)
    assert "boards.example.test/apply" in message
    assert "secret-value" not in message, "query com token nunca entra em proveniencia"


def test_grouping_keeps_every_verdict_even_when_empty():
    scope = NetworkScope.empty()
    grouped = scope.classify_all([NetworkRecord(url="https://x.test/a", method="GET")])
    assert set(grouped) == set(ScopeVerdict)
    assert grouped[ScopeVerdict.CHALLENGE_RUNTIME] == []


def test_write_methods_are_declared_not_inferred():
    assert {"POST", "PUT", "PATCH", "DELETE"} == WRITE_METHODS
    assert "GET" not in WRITE_METHODS


def test_hostile_urls_do_not_crash_or_pass():
    scope = NetworkScope.from_providers(["hcaptcha"])
    for url in ("", "not-a-url", "file:///etc/passwd", "https://hcaptcha.com.evil.test/api.js"):
        verdict = scope.classify(NetworkRecord(url=url, method="GET"))
        assert verdict in {ScopeVerdict.OUT_OF_SCOPE, ScopeVerdict.SUBMISSION_CANDIDATE}
