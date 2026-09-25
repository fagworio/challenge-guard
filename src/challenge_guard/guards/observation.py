"""CG-027 — Observation Guard: o browser fornece FATOS, nunca DECISAO.

A camada de browser observa. Quem decide e a policy. Parece obvio escrito assim,
e e exatamente por isso que precisa ser verificado por maquina: a forma mais
facil de "resolver" um desafio dentro desta biblioteca nao e escrever um solver,
e deixar o adapter ganhar umaopiniao — `if challenge_visible: return needs_human`.
A partir dai a decisao nao esta mais na policy, e nenhum teste de policy a
alcanca.

O guard e estatico (AST) porque o defeito e estrutural: ele olha a camada de
browser e exige que ela nao NOMEIE decisao. E vale para `browser/` inteiro,
inclusive para o codigo que ainda nao existe.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Nomes que pertencem a decisao. Um adapter que os menciona como codigo esta
#: decidindo — ou esta a um `if` de decidir.
DECISION_NAMES = frozenset(
    {
        "ChallengeDecision",
        "ChallengeDecisionStatus",
        "ReasonToken",
        "human_required",
        "needs_human",
        "provider_rejected",
        "resolved_externally",
        "retry_allowed",
        "decide",
        "timed_out",
        "ChallengePolicy",
    }
)

#: Caminho da camada de observacao, a partir da raiz que CONTEM o pacote
#: (`src/`), igual a `submission_isolation`. O primeiro teste deste guard
#: passava por acidente com um caminho errado: a varredura nao encontrava arquivo
#: nenhum e devolvia lista vazia, que o teste lia como "fronteira intacta". Por
#: isso a varredura vazia agora LEVANTA.
OBSERVATION_PACKAGE = ("challenge_guard", "browser")


class ObservationBoundaryViolation(RuntimeError):
    """A camada de browser mencionou decisao. Fatos e decisao se separaram."""


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Docstring pode NOMEAR o proibido: documentar a fronteira e o objetivo."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


def observation_layer_violations(package_root: Path) -> list[str]:
    """Nomes de decisao usados como codigo na camada de browser."""
    violations: list[str] = []
    scanned = 0
    source = Path(package_root).joinpath(*OBSERVATION_PACKAGE)
    if source.is_dir():
        for path in sorted(source.rglob("*.py")):
            scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            found: list[str] = []
            if isinstance(node, ast.Name):
                found.append(node.id)
            elif isinstance(node, ast.Attribute):
                found.append(node.attr)
            elif isinstance(node, ast.ImportFrom):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                found.append(node.value)
            for candidate in found:
                if candidate in DECISION_NAMES:
                    violations.append(f"{path.name}:{node.lineno} usa {candidate}")
    return violations


def assert_observation_layer_is_factual(package_root: Path) -> None:
    violations = observation_layer_violations(package_root)
    if violations:
        raise ObservationBoundaryViolation("browser layer names a decision:\n  " + "\n  ".join(violations))


__all__ = [
    "DECISION_NAMES",
    "ObservationBoundaryViolation",
    "assert_observation_layer_is_factual",
    "observation_layer_violations",
]
