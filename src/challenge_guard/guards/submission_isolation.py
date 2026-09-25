"""CG-031 — Submission Isolation Guard.

A regra mais importante deste pacote, e a que precisa ser arquitetural em vez de
combinada: **dentro do challenge-guard nao se envia candidatura**.

Nao basta nao ter a funcao hoje. O que se proibe e a forma, e ela entra por
caminhos pequenos:

```text
uma dependencia nova que sabe fazer POST
um helper de conveniencia "so para tirar o captcha da frente"
uma chamada de browser que clica em submit (o clique E a escrita)
uma mensagem de erro que cita a Application para "facilitar o host"
```

O fluxo correto continua sendo do host:

```text
challenge-guard termina
    -> host revalida
        -> SubmissionCoordinator decide e executa o envio
```

Por isso o guard olha duas coisas: os NOMES que o pacote pode usar (submissao,
candidatura, resposta do candidato) e as CHAMADAS de efeito que ele pode fazer
(requisicao HTTP propria, navegacao, clique, digitacao, injecao de script). Se
alguma aparecer, o build quebra — nao ha excecao "temporaria".
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Vocabulario do host que nao pode existir aqui: submissao, candidatura, ATS.
FORBIDDEN_SUBMISSION_NAMES = frozenset(
    {
        "SubmissionIntent",
        "SubmissionAttempt",
        "SubmissionCoordinator",
        "SubmissionService",
        "AuthorizedWrite",
        "NetworkWriteGuard",
        "LiveNetworkPolicy",
        "submit_application",
        "application_submit",
        "upload_resume",
        "ApplicationState",
        "JobBoard",
    }
)

#: Chamadas de EFEITO. Observar e ler; qualquer coisa que clica, digita, navega,
#: injeta script ou faz requisicao propria esta fora do contrato — inclusive
#: porque um clique em submit seria uma escrita disfarcada de interacao.
FORBIDDEN_CALL_ATTRIBUTES = frozenset(
    {
        "goto",
        "click",
        "fill",
        "type",
        "press",
        "check",
        "select_option",
        "set_input_files",
        "evaluate",
        "evaluate_handle",
        "add_init_script",
        "route",
        "fetch",
        "post",
        "request",
    }
)

#: Modulos de cliente HTTP: o guard nao fala com a rede por conta propria.
FORBIDDEN_IMPORTS = frozenset({"httpx", "requests", "urllib.request", "aiohttp"})


class SubmissionIsolationViolation(RuntimeError):
    """O pacote ganhou a capacidade de enviar candidatura."""


def _docstring_nodes(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


#: O proprio guard NOMEIA o proibido como dado (a lista acima). Varrer a si
#: mesmo daria falso positivo em todo build, e a varredura ficaria inutil. O que
#: garante que ela nao e vacua e o selfcheck do anel 5
#: (`tests/unit/test_architecture_guards.py`): ele injeta uma violacao
#: deliberada num arquivo de sonda e exige que a varredura a encontre.
_SKIP_DIRECTORIES = ("guards",)


def submission_isolation_violations(package_root: Path, *, package: str = "challenge_guard") -> list[str]:
    """Varre o pacote inteiro. Documentar o proibido e permitido; usa-lo, nao."""
    violations: list[str] = []
    root = Path(package_root) / package
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts[:-1]):
            continue
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS:
                        violations.append(f"{path.name}:{node.lineno} importa {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in FORBIDDEN_IMPORTS:
                    violations.append(f"{path.name}:{node.lineno} importa {node.module}")
                for alias in node.names:
                    if alias.name in FORBIDDEN_SUBMISSION_NAMES:
                        violations.append(f"{path.name}:{node.lineno} importa {alias.name}")
            elif isinstance(node, ast.Name):
                if node.id in FORBIDDEN_SUBMISSION_NAMES:
                    violations.append(f"{path.name}:{node.lineno} usa {node.id}")
            elif isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_CALL_ATTRIBUTES:
                    violations.append(f"{path.name}:{node.lineno} chama .{node.attr}()")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                for name in FORBIDDEN_SUBMISSION_NAMES:
                    if name == node.value:
                        violations.append(f"{path.name}:{node.lineno} nomeia {name}")
    if scanned == 0:
        raise SubmissionIsolationViolation(
            f"isolation scan found no files under {root}: a scan that scans nothing cannot pass"
        )
    return violations


def assert_submission_isolated(package_root: Path) -> None:
    violations = submission_isolation_violations(package_root)
    if violations:
        raise SubmissionIsolationViolation("the guard can submit:\n  " + "\n  ".join(violations))


__all__ = [
    "FORBIDDEN_CALL_ATTRIBUTES",
    "FORBIDDEN_IMPORTS",
    "FORBIDDEN_SUBMISSION_NAMES",
    "SubmissionIsolationViolation",
    "assert_submission_isolated",
    "submission_isolation_violations",
]
