"""Observadores: DOM, frames, network e resposta.

Nenhum deles decide: todos produzem sinais normalizados. A decisao e da policy.
"""

from .base import ChallengeObserver, ObserverResult, merge
from .dom import DOMObserver
from .frames import FrameInfo, FrameObserver
from .network import NetworkObserver, NetworkRecord
from .response import ResponseObserver, ResponseRecord

__all__ = [
    "ChallengeObserver",
    "DOMObserver",
    "FrameInfo",
    "FrameObserver",
    "NetworkObserver",
    "NetworkRecord",
    "ObserverResult",
    "ResponseObserver",
    "ResponseRecord",
    "merge",
]
