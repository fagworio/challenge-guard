"""Boundary de observacao de desafios anti-bot.

O Challenge Guard responde a uma unica pergunta: **a automacao chegou a uma
boundary que exige um humano?** Ele observa o que acontece nessa boundary e
produz evidencia; nunca tenta fazer o mecanismo de seguranca acreditar que o
humano e o agente.

Nao existe aqui — e nao pode passar a existir — qualquer funcao que resolva,
responda, contorne ou falsifique um desafio. Nao ha `solve`, `bypass`,
`stealth`, nem injecao de token. A ausencia dessas operacoes e parte do
contrato: ver docs/adr/0001-challenge-boundary.md.
"""

from .browser.cdp import CdpConnectionError, CdpEndpoint, CdpEndpointError, PlaywrightCdpSession
from .browser.protocol import BrowserChallengeAdapter, BrowserSession
from .evidence import ChallengeEvidence, EvidenceLeak, redact
from .fingerprint import structural_fingerprint
from .guards import (
    BrowserLifecycle,
    ChallengeProvenance,
    LifecycleViolation,
    NetworkScope,
    NetworkScopeViolation,
    ProvenanceJournal,
    ProvenanceViolation,
    SensitiveMaterialLeak,
    assert_no_sensitive_material,
)
from .handoff import HandoffContinuation, HumanHandoff, UnsafeHandoff, build_handoff
from .models import (
    ChallengeDecision,
    ChallengeDecisionStatus,
    ChallengeObservation,
    ChallengePhase,
    ChallengeProvider,
    ChallengeRoundObservation,
    ChallengeSession,
    ChallengeSessionStatus,
    ChallengeType,
    ReasonToken,
)
from .observers import (
    DOMObserver,
    FrameInfo,
    FrameObserver,
    NetworkObserver,
    NetworkRecord,
    ObserverResult,
    ResponseObserver,
    ResponseRecord,
    merge,
)
from .monitor import ChallengeMonitor, challenge_type_of, supported_providers
from .policy import ChallengePolicy
from .providers import (
    ChallengeProviderProfile,
    PROFILES,
    ResponseMarker,
    profile_for,
    profile_for_frame,
    profile_for_host,
    profiles,
)
from .resolution import (
    BudgetViolation,
    ChallengeCapability,
    ResolutionBudget,
    RuntimeLimits,
    ValidationResult,
    capability_for,
    capability_matrix,
    validate_not_premature,
    validate_progress,
)
from .runtime import ChallengeRuntime, ChallengeRuntimeResult
from .requirements import (
    ChallengeNetworkPurpose,
    ChallengeNetworkRequirement,
    requirements_for,
    runtime_read_hosts,
)
from .signals import (
    ChallengeSignal,
    ChallengeSignalKind,
    corroborated_confidence,
    has_kind,
    independent_sources,
    source_votes,
    strongest,
)
from .session import (
    ChallengeSessionTracker,
    InvalidChallengeTransition,
    SessionNotFound,
)

__all__ = [
    "BrowserChallengeAdapter",
    "BrowserLifecycle",
    "BrowserSession",
    "BudgetViolation",
    "CdpConnectionError",
    "CdpEndpoint",
    "CdpEndpointError",
    "ChallengeCapability",
    "ChallengeProvenance",
    "ChallengeRuntime",
    "ChallengeRuntimeResult",
    "LifecycleViolation",
    "NetworkScope",
    "NetworkScopeViolation",
    "PlaywrightCdpSession",
    "ProvenanceJournal",
    "ProvenanceViolation",
    "ResolutionBudget",
    "RuntimeLimits",
    "SensitiveMaterialLeak",
    "ValidationResult",
    "assert_no_sensitive_material",
    "capability_for",
    "capability_matrix",
    "validate_not_premature",
    "validate_progress",
    "ChallengeDecision",
    "ChallengeEvidence",
    "ChallengeNetworkPurpose",
    "ChallengeNetworkRequirement",
    "EvidenceLeak",
    "HandoffContinuation",
    "HumanHandoff",
    "UnsafeHandoff",
    "ChallengeSignal",
    "ChallengeSignalKind",
    "ChallengeProviderProfile",
    "DOMObserver",
    "FrameInfo",
    "FrameObserver",
    "NetworkObserver",
    "NetworkRecord",
    "ObserverResult",
    "PROFILES",
    "ResponseMarker",
    "ResponseObserver",
    "ResponseRecord",
    "corroborated_confidence",
    "has_kind",
    "independent_sources",
    "build_handoff",
    "merge",
    "profile_for",
    "profile_for_frame",
    "profile_for_host",
    "profiles",
    "redact",
    "requirements_for",
    "runtime_read_hosts",
    "source_votes",
    "challenge_type_of",
    "strongest",
    "supported_providers",
    "ChallengeDecisionStatus",
    "ChallengeObservation",
    "ChallengePhase",
    "ChallengeMonitor",
    "ChallengePolicy",
    "ChallengeProvider",
    "ChallengeRoundObservation",
    "ChallengeSession",
    "ChallengeSessionStatus",
    "ChallengeSessionTracker",
    "ChallengeType",
    "InvalidChallengeTransition",
    "ReasonToken",
    "SessionNotFound",
    "structural_fingerprint",
]

__version__ = "0.2.0"
