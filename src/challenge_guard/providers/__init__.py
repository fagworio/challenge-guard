"""Perfis declarativos de provedores de challenge (CG-011)."""

from .base import ChallengeProviderProfile, ResponseMarker
from .registry import (
    GENERIC_PROFILE,
    HCAPTCHA_PROFILE,
    PROFILES,
    RECAPTCHA_ENTERPRISE_PROFILE,
    RECAPTCHA_PROFILE,
    profile_for,
    profile_for_host,
    profiles,
)

__all__ = [
    "ChallengeProviderProfile",
    "GENERIC_PROFILE",
    "HCAPTCHA_PROFILE",
    "PROFILES",
    "RECAPTCHA_ENTERPRISE_PROFILE",
    "RECAPTCHA_PROFILE",
    "ResponseMarker",
    "profile_for",
    "profile_for_host",
    "profiles",
]
