"""CG-027/CG-031/CG-034 — os guards de arquitetura, e o selfcheck que os torna nao-vacuos.

Um contrato que nunca falha nao testa nada. Estes testes fazem duas coisas:

1. aplicam a varredura ao pacote REAL (tem de passar);
2. injetam uma violacao DELIBERADA numa arvore de sonda e exigem que a varredura
   a encontre (tem de falhar).

Se alguem "consertar" um guard afrouxando a checagem, o passo 2 cai.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from challenge_guard.guards.observation import (
    DECISION_NAMES,
    observation_layer_violations,
)
from challenge_guard.guards.submission_isolation import (
    FORBIDDEN_CALL_ATTRIBUTES,
    FORBIDDEN_SUBMISSION_NAMES,
    submission_isolation_violations,
)

SRC = Path(__file__).resolve().parents[2] / "src"


# --- pacote real ---------------------------------------------------------------


def test_the_guard_cannot_submit_anything():
    violations = submission_isolation_violations(SRC)
    assert violations == [], "o guard ganhou capacidade de submissao:\n  " + "\n  ".join(violations)


def test_the_browser_layer_only_reports_facts():
    violations = observation_layer_violations(SRC)
    assert violations == [], "a camada de browser passou a decidir:\n  " + "\n  ".join(violations)


def test_no_module_imports_seleniumbase_playwright_or_stealth_toolkits():
    """ADR 0007: a ponte e neutra, e `seleniumbase` nao entra no pacote."""
    banned = {"seleniumbase", "selenium", "undetected", "playwright_stealth"}
    offenders: list[str] = []
    for path in sorted((SRC / "challenge_guard").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [f"{path.name}:{node.lineno} {alias.name}" for alias in node.names if alias.name.split(".")[0] in banned]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned:
                offenders.append(f"{path.name}:{node.lineno} {node.module}")
    assert offenders == [], "dependencia de browser proibida:\n  " + "\n  ".join(offenders)


def test_playwright_is_imported_only_inside_the_connecting_call():
    """A dependencia opcional nao pode ser carregada no import do pacote."""
    for path in sorted((SRC / "challenge_guard").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # apenas nivel de modulo
            # `node.level > 0` e import RELATIVO: `from .playwright import X`
            # aponta para o nosso `browser/playwright.py`, nao para a dependencia.
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("playwright"):
                pytest.fail(f"{path.name} importa playwright no topo do modulo")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("playwright"):
                        pytest.fail(f"{path.name} importa playwright no topo do modulo")


def test_no_solving_or_evasion_identifier_exists_in_the_package():
    """Mesma regra do job `boundary` do CI, aqui dentro da suite."""
    banned = ("solve", "bypass", "stealth", "answer_captcha", "inject_token", "spoof", "undetected")
    offenders: list[str] = []
    for path in sorted((SRC / "challenge_guard").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name.casefold()
                if any(token in name for token in banned):
                    offenders.append(f"{path.name}:{node.lineno} {node.name}")
    assert offenders == [], "identificador que resolve/contorna:\n  " + "\n  ".join(offenders)


# --- selfcheck: as varreduras nao sao vacuas -----------------------------------


def _probe_tree(tmp_path: Path) -> Path:
    package = tmp_path / "challenge_guard"
    (package / "browser").mkdir(parents=True)
    (package / "browser" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_the_submission_scan_finds_a_deliberate_violation(tmp_path: Path):
    root = _probe_tree(tmp_path)
    probe = root / "challenge_guard" / "probe.py"
    probe.write_text(
        "def helper(page):\n"
        "    page.click('#submit')\n"
        "\n"
        "class _S:\n"
        "    pass\n"
        "\n"
        "def takes(intent: object) -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    violations = submission_isolation_violations(root)
    assert any(".click()" in item for item in violations), violations


def test_the_submission_scan_finds_an_http_client(tmp_path: Path):
    root = _probe_tree(tmp_path)
    (root / "challenge_guard" / "probe.py").write_text("import httpx\n", encoding="utf-8")
    violations = submission_isolation_violations(root)
    assert any("httpx" in item for item in violations), violations


def test_the_observation_scan_finds_a_deciding_adapter(tmp_path: Path):
    root = _probe_tree(tmp_path)
    (root / "challenge_guard" / "browser" / "probe.py").write_text(
        "def looks_like_a_challenge(visible):\n"
        "    return 'needs_human' if visible else 'none'\n",
        encoding="utf-8",
    )
    violations = observation_layer_violations(root)
    assert any("needs_human" in item for item in violations), violations


def test_the_observation_scan_reads_EVERY_file_not_just_the_last(tmp_path: Path):
    """O defeito real: `ast.parse` fora do laco analisava so o ultimo arquivo.

    A violacao fica em `a_violation.py` e um arquivo LIMPO vem depois na ordem
    alfabetica. Um guard que so olha o ultimo arquivo passa neste teste por
    acidente; ele tem de falhar.
    """
    root = _probe_tree(tmp_path)
    browser = root / "challenge_guard" / "browser"
    (browser / "a_violation.py").write_text(
        "DECISION = 'provider_rejected'\n",
        encoding="utf-8",
    )
    (browser / "z_clean.py").write_text("VALUE = 'challenge_detected'\n", encoding="utf-8")
    violations = observation_layer_violations(root)
    assert any(item.startswith("a_violation.py:") for item in violations), violations


def test_the_observation_scan_refuses_to_pass_on_an_empty_tree(tmp_path: Path):
    """Varredura vazia nao pode ser lida como 'fronteira intacta'."""
    from challenge_guard.guards.observation import ObservationBoundaryViolation

    empty = tmp_path / "challenge_guard" / "browser"
    empty.mkdir(parents=True)
    with pytest.raises(ObservationBoundaryViolation, match="scans nothing"):
        observation_layer_violations(tmp_path)


def test_the_observation_scan_allows_documentation_of_the_boundary(tmp_path: Path):
    """Docstring PODE nomear o proibido: documentar a fronteira e o objetivo."""
    root = _probe_tree(tmp_path)
    (root / "challenge_guard" / "browser" / "probe.py").write_text(
        '"""Este adapter nunca decide `needs_human`."""\n\n\ndef read() -> str:\n    return ""\n',
        encoding="utf-8",
    )
    assert observation_layer_violations(root) == []


def test_the_guards_are_not_trivially_empty():
    """Listas de proibicao vazias fariam os dois scans passarem sempre."""
    assert len(FORBIDDEN_SUBMISSION_NAMES) >= 8
    assert len(FORBIDDEN_CALL_ATTRIBUTES) >= 10
    assert len(DECISION_NAMES) >= 8
