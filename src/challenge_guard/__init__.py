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

from .browser.protocol import BrowserChallengeAdapter
from .evidence import ChallengeEvidence, EvidenceLeak, redact
from .fingerprint import structural_fingerprint
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
from .policy import ChallengePolicy
from .providers import (
    ChallengeProviderProfile,
    PROFILES,
    ResponseMarker,
    profile_for,
    profile_for_host,
    profiles,
)
from .requirements import ChallengeNetworkPurpose, ChallengeNetworkRequirement, requirements_for
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
    "ChallengeDecision",
    "ChallengeEvidence",
    "ChallengeNetworkPurpose",
    "ChallengeNetworkRequirement",
    "EvidenceLeak",
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
    "merge",
    "profile_for",
    "profile_for_host",
    "profiles",
    "redact",
    "requirements_for",
    "source_votes",
    "strongest",
    "ChallengeDecisionStatus",
    "ChallengeObservation",
    "ChallengePhase",
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

__version__ = "0.1.0"
