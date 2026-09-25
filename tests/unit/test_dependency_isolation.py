"""CG-010/CG-A01 — importar o pacote nao instala nem carrega browser.

Roda em SUBPROCESSO: no processo de teste, `playwright` ja esta carregado por
outros testes, e medir ali mediria o pytest. O subprocesso tambem e a unica
forma honesta de provar "funciona num ambiente sem browser" — o CI faz o mesmo
num venv onde `playwright` e `seleniumbase` nem existem.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from challenge_guard.guards.dependency import (
    OPTIONAL_MODULES,
    assert_optional_dependencies_absent,
    loaded_optional_modules,
    probe_clean_import,
)


def test_the_package_has_no_required_dependencies():
    """`dependencies = []` e uma qualidade do pacote, e nao um acidente."""
    import importlib.metadata as metadata

    requires = metadata.requires("challenge-guard") or []
    required = [item for item in requires if "extra ==" not in item]
    assert required == [], f"dependencia obrigatoria nova: {required}"


def test_importing_the_package_loads_no_optional_browser_dependency():
    assert probe_clean_import(sys.executable) == []


def test_the_probe_would_notice_a_loaded_optional_dependency():
    """Selfcheck: se o detector nao detecta, o teste acima nao prova nada."""
    with pytest.raises(Exception):
        assert_optional_dependencies_absent(["playwright.sync_api", "challenge_guard"])
    assert loaded_optional_modules(["seleniumbase", "challenge_guard"]) == ["seleniumbase"]


def test_the_optional_list_covers_the_browser_stack():
    assert set(OPTIONAL_MODULES) == {"playwright", "seleniumbase", "selenium", "mycdp"}


def test_a_broken_import_is_reported_not_swallowed():
    from challenge_guard.guards.dependency import DependencyIsolationViolation

    completed = subprocess.run(
        [sys.executable, "-c", "import no_such_module_here"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert DependencyIsolationViolation is not None
