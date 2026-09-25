"""Guards: as fronteiras que o pacote nao pode cruzar.

Cada guard responde a uma pergunta que nao pode depender de disciplina de quem
escreve o proximo commit. Alguns sao verificados em tempo de execucao (lifecycle,
material sensivel, escopo de rede); outros sao verificados por AST no CI
(observacao factual, isolamento de submissao, isolamento de dependencia), porque
o defeito que eles previnem e estrutural.
"""

from .dependency import (
    DependencyIsolationViolation,
    OPTIONAL_MODULES,
    assert_optional_dependencies_absent,
    loaded_optional_modules,
    probe_clean_import,
)
from .lifecycle import BrowserLifecycle, LifecycleState, LifecycleViolation
from .network_scope import NetworkScope, NetworkScopeViolation, ScopeVerdict, ScopedNetworkAdapter
from .observation import (
    ObservationBoundaryViolation,
    assert_observation_layer_is_factual,
    observation_layer_violations,
)
from .provenance import (
    ChallengeProvenance,
    ProvenanceJournal,
    ProvenanceViolation,
)
from .sensitive_material import (
    SensitiveMaterialLeak,
    assert_no_sensitive_material,
    safe_repr,
)
from .submission_isolation import (
    SubmissionIsolationViolation,
    assert_submission_isolated,
    submission_isolation_violations,
)

__all__ = [
    "BrowserLifecycle",
    "ChallengeProvenance",
    "DependencyIsolationViolation",
    "LifecycleState",
    "LifecycleViolation",
    "NetworkScope",
    "NetworkScopeViolation",
    "OPTIONAL_MODULES",
    "ObservationBoundaryViolation",
    "ProvenanceJournal",
    "ProvenanceViolation",
    "ScopeVerdict",
    "ScopedNetworkAdapter",
    "SensitiveMaterialLeak",
    "SubmissionIsolationViolation",
    "assert_no_sensitive_material",
    "assert_observation_layer_is_factual",
    "assert_optional_dependencies_absent",
    "assert_submission_isolated",
    "loaded_optional_modules",
    "observation_layer_violations",
    "probe_clean_import",
    "safe_repr",
    "submission_isolation_violations",
]
