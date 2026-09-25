"""CG-010 — Dependency Isolation Guard.

`import challenge_guard` precisa continuar funcionando num ambiente sem
`playwright` e sem `seleniumbase`. Isso e uma qualidade do pacote — as
dependencias obrigatorias sao **zero** — e nao um detalhe de empacotamento: quem
so quer classificar uma observacao ja pronta (um evento de log, um texto de
resposta) nao deve instalar um browser para isso.

O guard roda em SUBPROCESSO de proposito. No processo de teste, `playwright` ja
esta em `sys.modules` porque outros testes o carregaram; medir ali mediria o
teste, nao o pacote. Este e o mesmo motivo pelo qual a ADR 0007 exige que a
ponte CDP importe Playwright SO dentro da funcao que conecta.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

#: Dependencias opcionais. Nenhuma delas pode ser carregada pelo import do
#: pacote — nem por tabela (um modulo que importa um deles no topo).
OPTIONAL_MODULES = ("playwright", "seleniumbase", "selenium", "mycdp")

#: Programa que mede o import num interpretador limpo. Ele imprime JSON para que
#: o teste nao dependa de formatacao humana.
PROBE = (
    "import json, sys;"
    "import challenge_guard;"
    "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
    + repr(list(OPTIONAL_MODULES))
    + ")))"
)


class DependencyIsolationViolation(RuntimeError):
    """Uma dependencia opcional foi carregada pelo import do pacote."""


def loaded_optional_modules(modules: list[str] | None = None) -> list[str]:
    """Quais dependencias opcionais estao carregadas AGORA."""
    names = modules if modules is not None else list(sys.modules)
    return sorted({name.split(".")[0] for name in names if name.split(".")[0] in OPTIONAL_MODULES})


def assert_optional_dependencies_absent(modules: list[str] | None = None) -> None:
    loaded = loaded_optional_modules(modules)
    if loaded:
        raise DependencyIsolationViolation(
            "importing challenge_guard must not load optional dependencies: " + ", ".join(loaded)
        )


def probe_clean_import(python_executable: str | None = None, *, timeout: float = 60.0) -> list[str]:
    """Roda o probe num interpretador novo e devolve as opcionais carregadas."""
    # O subprocesso precisa enxergar o MESMO codigo: sem herdar `sys.path` (o
    # pytest injeta `src/` via `pythonpath`, que nao propaga para um filho), ele
    # mediria "modulo nao encontrado" e o teste passaria por engano.
    root_entries = [entry for entry in sys.path if entry]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(root_entries)}
    completed = subprocess.run(
        [python_executable or sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise DependencyIsolationViolation(
            f"import challenge_guard failed in a clean interpreter: {completed.stderr.strip()[:400]}"
        )
    try:
        return list(json.loads(completed.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError) as exc:  # pragma: no cover - ambiente estranho
        raise DependencyIsolationViolation(f"unreadable probe output: {completed.stdout[:200]!r}") from exc


__all__ = [
    "DependencyIsolationViolation",
    "OPTIONAL_MODULES",
    "PROBE",
    "assert_optional_dependencies_absent",
    "loaded_optional_modules",
    "probe_clean_import",
]
