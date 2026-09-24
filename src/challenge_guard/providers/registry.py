"""Registry declarativo de provedores de challenge (CG-011).

Quatro perfis iniciais: hCaptcha, reCAPTCHA, reCAPTCHA Enterprise e generic.

Zero ATS. Um teste afirma que nenhum nome de vendor de recrutamento aparece
aqui — se um dia aparecer, a inteligencia anti-bot voltou a se acoplar ao board.
"""

from __future__ import annotations

import re

from ..models import ChallengeProvider, ChallengeType
from ..requirements import ChallengeNetworkPurpose, ChallengeNetworkRequirement
from ..signals import ChallengeSignalKind
from .base import ChallengeProviderProfile, EvidenceLevel, ResponseMarker


def _runtime(provider: ChallengeProvider, origins: tuple[str, ...], paths: tuple[str, ...], budget: int) -> ChallengeNetworkRequirement:
    return ChallengeNetworkRequirement(
        provider=provider,
        purpose=ChallengeNetworkPurpose.CHALLENGE_RUNTIME,
        origins=origins,
        # Os caminhos sao os observados em boards reais. Sem eles, um wildcard de
        # origem autorizaria o dominio inteiro — exatamente o defeito ja visto
        # numa policy de upload real (`*.dominio` + `^/.*$`). Aqui isso e
        # impossivel por construcao.
        path_patterns=paths,
        max_requests=budget,
    )

#: Confianca de um texto de resposta que pede o challenge explicitamente.
_REQUIRED_CONFIDENCE = 0.9
#: Confianca de um texto de resposta que afirma falha de verificacao.
_REJECTED_CONFIDENCE = 0.95

HCAPTCHA_PROFILE = ChallengeProviderProfile(
    provider=ChallengeProvider.HCAPTCHA,
    default_type=ChallengeType.CHECKBOX,
    frame_hosts=("hcaptcha.com", "newassets.hcaptcha.com"),
    runtime_hosts=("hcaptcha.com", "*.hcaptcha.com"),
    widget_hosts=("js.hcaptcha.com",),
    network_requirements=(
        _runtime(
            ChallengeProvider.HCAPTCHA,
            ("hcaptcha.com", "*.hcaptcha.com"),
            (r"^/1/", r"^/captcha/", r"^/getcaptcha/", r"^/checkcaptcha/"),
            20,
        ),
    ),
    dom_markers=(
        "h-captcha",
        "hcaptcha",
        "data-hcaptcha-widget-id",
        "hcaptcha-response",
    ),
    response_markers=(
        ResponseMarker(
            token="hcaptcha_verification_failed",
            phrase="verification failed",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=_REJECTED_CONFIDENCE,
            evidence_level=EvidenceLevel.OBSERVED,
            source_reference="board-real-2026-09",
        ),
        ResponseMarker(
            token="challenge_failed",
            phrase="challenge failed",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=_REJECTED_CONFIDENCE,
            evidence_level=EvidenceLevel.INFERRED,
        ),
        ResponseMarker(
            token="complete_the_captcha",
            phrase="complete the captcha",
            kind=ChallengeSignalKind.CHALLENGE_REQUIRED,
            confidence=_REQUIRED_CONFIDENCE,
            evidence_level=EvidenceLevel.INFERRED,
        ),
    ),
)

RECAPTCHA_PROFILE = ChallengeProviderProfile(
    provider=ChallengeProvider.RECAPTCHA,
    network_requirements=(
        _runtime(
            ChallengeProvider.RECAPTCHA,
            ("www.google.com", "www.gstatic.com", "www.recaptcha.net", "recaptcha.net"),
            (r"^/recaptcha/",),
            20,
        ),
    ),
    default_type=ChallengeType.CHECKBOX,
    frame_hosts=("www.google.com", "www.recaptcha.net", "recaptcha.net"),
    # Classico: `api2`. Fica como fallback (sem `frame_paths`) para nao roubar o
    # caminho do Enterprise, que e mais especifico. `bframe` e o popup
    # interativo; `anchor` e apenas o selo.
    challenge_frame_paths=(r"^/recaptcha/api2/bframe",),
    runtime_hosts=(
        "www.google.com",
        "www.gstatic.com",
        "www.recaptcha.net",
        "recaptcha.net",
        "apis.google.com",
        "content.googleapis.com",
    ),
    widget_hosts=("www.gstatic.com",),
    # `data-sitekey` NAO entra: e usado por reCAPTCHA, hCaptcha e Turnstile, entao
    # nao discrimina nada. Ele continua na estrutura como presenca de atributo.
    dom_markers=("g-recaptcha", "grecaptcha", "g-recaptcha-response"),
    response_markers=(
        ResponseMarker(
            token="please_complete_the_recaptcha",
            phrase="please complete the recaptcha",
            kind=ChallengeSignalKind.CHALLENGE_REQUIRED,
            confidence=_REQUIRED_CONFIDENCE,
            evidence_level=EvidenceLevel.OBSERVED,
            source_reference="board-real-2026-09",
        ),
        ResponseMarker(
            token="captcha_verification",
            phrase="captcha verification",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=_REJECTED_CONFIDENCE,
            evidence_level=EvidenceLevel.INFERRED,
        ),
    ),
)

#: Enterprise e um provedor separado de proposito: ele e INVISIVEL por padrao e
#: o servidor responde 428 pedindo o token. Tratar como reCAPTCHA comum faria a
#: policy esperar um widget que nunca aparece.
RECAPTCHA_ENTERPRISE_PROFILE = ChallengeProviderProfile(
    provider=ChallengeProvider.RECAPTCHA_ENTERPRISE,
    network_requirements=(
        _runtime(
            ChallengeProvider.RECAPTCHA_ENTERPRISE,
            ("www.google.com", "www.gstatic.com", "www.recaptcha.net", "recaptcha.net"),
            (r"^/recaptcha/",),
            20,
        ),
    ),
    default_type=ChallengeType.INVISIBLE,
    frame_hosts=("www.google.com", "www.recaptcha.net", "recaptcha.net"),
    # Unico discriminador observado entre Enterprise e classico quando dividem o
    # host. Dado real: `/recaptcha/enterprise/anchor` num board e
    # `/recaptcha/api2/anchor` em outro. A procedencia (qual board) fica na
    # fixture e no ADR — um nome de plataforma aqui e o acoplamento que o
    # desenho evita.
    frame_paths=(r"^/recaptcha/enterprise/",),
    challenge_frame_paths=(r"^/recaptcha/enterprise/bframe",),
    runtime_hosts=(
        "www.google.com",
        "www.gstatic.com",
        "www.recaptcha.net",
        "recaptcha.net",
        "apis.google.com",
        "content.googleapis.com",
    ),
    # Sem marcadores de DOM DE PROPOSITO. O Enterprise e invisivel: normalmente
    # nao renderiza widget. Listar `g-recaptcha` aqui faria todo formulario
    # reCAPTCHA v2 disparar dois sinais — dois "providers" para uma unica
    # observacao — e a evidencia que realmente distingue Enterprise e a
    # resposta (428 pedindo o token), nao a estrutura da pagina.
    dom_markers=(),
    response_markers=(
        ResponseMarker(
            token="please_complete_the_recaptcha",
            phrase="please complete the recaptcha",
            kind=ChallengeSignalKind.CHALLENGE_REQUIRED,
            confidence=_REQUIRED_CONFIDENCE,
        ),
        ResponseMarker(
            token="error_verifying_application",
            # Mensagem real observada num board de producao, HTTP 400. "verify"
            # nao casa com o gerundio "verifying": a forma exata precisa estar
            # aqui. A proveniencia fica no ADR, nao neste arquivo: um nome de ATS
            # no registry e exatamente o acoplamento que o desenho evita.
            phrase="verifying your application",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=_REJECTED_CONFIDENCE,
            evidence_level=EvidenceLevel.OBSERVED,
            source_reference="board-real-2026-09",
        ),
        ResponseMarker(
            token="error_verifying",
            phrase="error verifying",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=_REJECTED_CONFIDENCE,
            evidence_level=EvidenceLevel.INFERRED,
        ),
        ResponseMarker(
            token="unable_to_verify",
            phrase="unable to verify",
            kind=ChallengeSignalKind.VERIFICATION_REJECTED,
            confidence=0.85,
            evidence_level=EvidenceLevel.INFERRED,
        ),
    ),
)

GENERIC_PROFILE = ChallengeProviderProfile(
    provider=ChallengeProvider.GENERIC,
    default_type=ChallengeType.UNKNOWN,
    frame_hosts=("challenges.cloudflare.com",),
    runtime_hosts=("challenges.cloudflare.com",),
    dom_markers=("cf-turnstile", "turnstile"),
    response_markers=(
        ResponseMarker(
            token="challenge_required",
            phrase="captcha required",
            kind=ChallengeSignalKind.CHALLENGE_REQUIRED,
            confidence=0.8,
            evidence_level=EvidenceLevel.INFERRED,
        ),
    ),
)

PROFILES: tuple[ChallengeProviderProfile, ...] = (
    HCAPTCHA_PROFILE,
    RECAPTCHA_PROFILE,
    RECAPTCHA_ENTERPRISE_PROFILE,
    GENERIC_PROFILE,
)

_BY_PROVIDER = {profile.provider: profile for profile in PROFILES}


def profiles() -> tuple[ChallengeProviderProfile, ...]:
    return PROFILES


def profile_for(provider: ChallengeProvider) -> ChallengeProviderProfile | None:
    return _BY_PROVIDER.get(provider)


def profile_for_frame(host: str, path: str = "") -> ChallengeProviderProfile | None:
    """Perfil que cobre host E caminho do frame.

    Caminho especifico vence: e o que separa dois provedores que compartilham o
    mesmo host. Sem caminho (ou sem match especifico), cai no host.
    """
    normalized = (host or "").casefold().strip()
    if not normalized:
        return None
    if path:
        for profile in PROFILES:
            if not profile.frame_paths:
                continue
            if not _host_matches(profile.frame_hosts, normalized):
                continue
            if any(re.match(pattern, path) for pattern in profile.frame_paths):
                return profile
    return profile_for_host(normalized)


def _host_matches(candidates: tuple[str, ...], host: str) -> bool:
    for candidate in candidates:
        if host == candidate or host.endswith("." + candidate.lstrip("*.")):
            return True
    return False


def profile_for_host(host: str) -> ChallengeProviderProfile | None:
    """Perfil cujo frame/runtime cobre o host informado."""
    normalized = (host or "").casefold().strip()
    if not normalized:
        return None
    for profile in PROFILES:
        for candidate in (*profile.frame_hosts, *profile.runtime_hosts, *profile.widget_hosts):
            if normalized == candidate or normalized.endswith("." + candidate.lstrip("*.")):
                return profile
    return None
