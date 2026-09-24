"""Adapters de browser. O core nao depende de nenhum deles."""

from .protocol import BrowserChallengeAdapter
from .playwright import PlaywrightChallengeAdapter

__all__ = ["BrowserChallengeAdapter", "PlaywrightChallengeAdapter"]
