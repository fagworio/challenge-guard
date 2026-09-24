"""Observers de DOM, frames, network e resposta (CG-007 .. CG-010)."""

from __future__ import annotations

import pytest

from challenge_guard import (
    ChallengeProvider,
    ChallengeSignalKind,
    ChallengeType,
    DOMObserver,
    FrameInfo,
    FrameObserver,
    NetworkObserver,
    NetworkRecord,
    ResponseObserver,
    ResponseRecord,
    merge,
)


# --- CG-007 DOM ---------------------------------------------------------------


def test_an_empty_dom_is_not_a_challenge():
    result = DOMObserver().observe("")
    assert result.detected is False
    assert result.signals == ()
    assert result.structure == ()


def test_a_plain_form_is_not_a_challenge():
    """Falso positivo mais provavel: um formulario comum cheio de inputs."""
    html = '<form><input name="name"><input name="email"><button>Submit</button></form>'
    assert DOMObserver().observe(html).detected is False


def test_an_hcaptcha_container_is_detected_structurally():
    result = DOMObserver().observe('<div class="h-captcha" data-sitekey="abc"></div>')
    assert result.detected is True
    assert result.provider is ChallengeProvider.HCAPTCHA
    kinds = {signal.kind for signal in result.signals}
    assert kinds == {ChallengeSignalKind.CHALLENGE_VISIBLE}


def test_a_recaptcha_container_is_detected():
    result = DOMObserver().observe('<div class="g-recaptcha" data-sitekey="xyz"></div>')
    assert result.detected is True
    assert result.provider is ChallengeProvider.RECAPTCHA
    assert result.challenge_type is ChallengeType.CHECKBOX


def test_a_turnstile_container_is_detected():
    result = DOMObserver().observe('<div class="cf-turnstile" data-sitekey="k"></div>')
    assert result.detected is True
    assert result.provider is ChallengeProvider.GENERIC


def test_the_observer_never_reads_challenge_text():
    """So estrutura entra: o texto entre tags nao vira sinal nem fingerprint."""
    html = '<div class="g-recaptcha">Select all traffic lights</div>'
    result = DOMObserver().observe(html)
    assert "traffic" not in " ".join(result.structure)
    assert "Select" not in " ".join(result.structure)


def test_a_marker_inside_inline_javascript_is_not_dom():
    """Falso positivo real: o texto do script nao e a pagina renderizada.

    Um widget escrito dentro de `innerHTML` era detectado pelo texto do script e
    nunca desaparecia, porque o codigo continua ali depois de o widget sair.
    """
    html = '<div id="box"></div><script>box.innerHTML = \'<div class="h-captcha"></div>\';</script>'
    assert DOMObserver().observe(html).detected is False


def test_a_marker_inside_a_style_block_is_not_dom():
    html = '<style>.h-captcha { display: none }</style><div class="plain"></div>'
    assert DOMObserver().observe(html).detected is False


def test_the_dom_observer_has_no_ats_specific_selector():
    source = (DOMObserver.observe.__code__.co_consts)
    joined = " ".join(str(item) for item in source if isinstance(item, str)).casefold()
    for vendor in ("greenhouse", "lever", "ashby", "workable"):
        assert vendor not in joined


# --- CG-008 Frames -----------------------------------------------------------


def test_no_frames_is_not_a_challenge():
    assert FrameObserver().observe([]).detected is False


def test_an_unrelated_iframe_is_ignored():
    result = FrameObserver().observe([FrameInfo("https://example.com/embed", width=600, height=400)])
    assert result.detected is False


def test_an_hcaptcha_frame_is_classified_by_host():
    result = FrameObserver().observe(
        [FrameInfo("https://newassets.hcaptcha.com/captcha/v1/abc", width=300, height=400)]
    )
    assert result.detected is True
    assert result.provider is ChallengeProvider.HCAPTCHA


def test_a_present_but_invisible_iframe_is_not_an_active_challenge():
    """iframe presente != challenge ativo: forma entra no fingerprint, nao no sinal."""
    result = FrameObserver().observe(
        [FrameInfo("https://www.google.com/recaptcha/api2/anchor", visible=False, width=300, height=400)]
    )
    assert result.detected is False
    assert result.structure  # a forma continua registrada


def test_a_decorative_micro_iframe_is_not_an_active_challenge():
    result = FrameObserver().observe(
        [FrameInfo("https://www.google.com/recaptcha/api2/anchor", width=1, height=1)]
    )
    assert result.detected is False


def test_frame_signals_carry_host_and_path_but_not_query():
    """A query pode carregar o sitekey: a estrutura registra host e caminho."""
    result = FrameObserver().observe(
        [FrameInfo("https://www.google.com/recaptcha/api2/anchor?k=SEGREDO&co=abc", width=300, height=400)]
    )
    assert result.detected is True
    assert "SEGREDO" not in " ".join(result.structure)
    assert any("google.com" in item for item in result.structure)


# --- CG-009 Network ----------------------------------------------------------


def test_unrelated_traffic_is_ignored():
    result = NetworkObserver().observe([NetworkRecord("https://apply.example.com/api/v1/jobs/1/form")])
    assert result.detected is False


def test_challenge_traffic_is_recorded_as_metadata_only():
    result = NetworkObserver().observe(
        [NetworkRecord("https://hcaptcha.com/getcaptcha/abc?token=SEGREDO", method="POST")]
    )
    assert result.detected is True
    assert result.provider is ChallengeProvider.HCAPTCHA
    assert {signal.kind for signal in result.signals} == {ChallengeSignalKind.CHALLENGE_TRAFFIC}
    assert "SEGREDO" not in " ".join(signal.detail for signal in result.signals)


def test_challenge_traffic_never_becomes_a_rejection():
    """Uma request isolada prova que o widget esta ativo, nao que houve recusa."""
    result = NetworkObserver().observe(
        [NetworkRecord("https://hcaptcha.com/getcaptcha/abc", method="POST", status=200)]
    )
    kinds = {signal.kind for signal in result.signals}
    assert ChallengeSignalKind.VERIFICATION_REJECTED not in kinds
    assert ChallengeSignalKind.CHALLENGE_REQUIRED not in kinds


def test_network_redaction_drops_path_and_query():
    record = NetworkRecord("https://hcaptcha.com/getcaptcha/segredo?token=SEGREDO", method="POST", status=200)
    redacted = NetworkObserver.redact(record)
    assert redacted["origin"] == "https://hcaptcha.com"
    assert redacted["method"] == "POST"
    assert redacted["write"] is True
    assert "segredo" not in str(redacted).casefold()
    assert len(str(redacted["path_hash"])) == 16


# --- CG-010 Response ---------------------------------------------------------


def test_a_status_code_alone_produces_nothing():
    assert ResponseObserver().observe([ResponseRecord(status=428)]).detected is False
    assert ResponseObserver().observe([ResponseRecord(status=400, text="")]).detected is False


def test_the_real_lever_400_message_becomes_a_normalized_signal():
    """Mensagem real da CI&T: o gerundio 'verifying' precisa casar."""
    result = ResponseObserver().observe(
        [ResponseRecord(status=400, text="There was an error verifying your application. Please try again.")]
    )
    (signal,) = result.signals
    assert signal.kind is ChallengeSignalKind.VERIFICATION_REJECTED
    assert signal.detail == "error_verifying_application"
    assert signal.source == "response"


def test_the_real_greenhouse_428_message_becomes_challenge_required():
    result = ResponseObserver().observe(
        [ResponseRecord(status=428, text="Please complete the reCAPTCHA and resubmit your application.")]
    )
    assert {signal.kind for signal in result.signals} == {ChallengeSignalKind.CHALLENGE_REQUIRED}


def test_common_form_errors_stay_out_of_the_captcha_domain():
    for text in ("Resume/CV is required.", "Email is invalid.", "This field is required."):
        assert ResponseObserver().observe([ResponseRecord(status=400, text=text)]).detected is False


def test_the_signal_never_carries_the_provider_text():
    """O texto entra, o sinal sai: o que sobrevive e o token do marcador."""
    marker_text = "There was an error verifying your application."
    result = ResponseObserver().observe([ResponseRecord(status=400, text=marker_text)])
    payload = " ".join(f"{signal.kind.value} {signal.detail}" for signal in result.signals)
    assert "error verifying your application" not in payload.casefold()
    assert result.signals[0].detail == "error_verifying_application"


# --- merge -------------------------------------------------------------------


def test_merging_independent_observers_keeps_the_strongest_provider():
    dom = DOMObserver().observe('<div class="g-recaptcha" data-sitekey="k"></div>')
    frames = FrameObserver().observe(
        [FrameInfo("https://newassets.hcaptcha.com/captcha/v1/x", width=300, height=400)]
    )
    merged = merge([dom, frames])
    assert merged.detected is True
    assert merged.source == "dom+frames"
    assert merged.provider in {ChallengeProvider.RECAPTCHA, ChallengeProvider.HCAPTCHA}
    assert len(merged.signals) == 2


def test_merging_nothing_yields_nothing():
    merged = merge([DOMObserver().observe(""), FrameObserver().observe([])])
    assert merged.detected is False
    assert merged.provider is ChallengeProvider.UNKNOWN


def test_frame_path_shape_normalises_opaque_segments():
    """Achado real: o token `se` do hCaptcha viaja no CAMINHO do frame.

    Registrar o caminho literal vazaria o identificador da conta e faria o
    fingerprint inventar rodada nova quando o provedor troca o id.
    """
    from challenge_guard.observers.frames import path_shape

    assert path_shape("/captcha/v1/0123456789abcdef0123456789abcdef/static/x.html") == (
        "/captcha/v1/:id/static/x.html"
    )
    # Caminhos com palavras continuam intactos: e o que discrimina Enterprise.
    assert path_shape("/recaptcha/enterprise/anchor") == "/recaptcha/enterprise/anchor"
    assert path_shape("/recaptcha/api2/anchor") == "/recaptcha/api2/anchor"


def test_a_token_in_the_frame_path_does_not_reach_the_structure():
    opaque = "0123456789abcdef0123456789abcdef"
    result = FrameObserver().observe(
        [FrameInfo(f"https://newassets.hcaptcha.com/captcha/v1/{opaque}/static/x.html", width=300, height=400)]
    )
    assert opaque not in " ".join(result.structure)


def test_anchor_is_a_badge_and_bframe_is_a_presented_challenge():
    """Distincao que o registry nao capturava.

    No reCAPTCHA, `anchor` e o selo e `bframe` e o popup interativo. Tratar os
    dois igual faria "selo na pagina" virar "desafio em andamento" — que era
    exatamente o que a deteccao antiga do host aproximava procurando a palavra
    "challenge" na URL.
    """
    observer = FrameObserver()
    anchor = observer.observe(
        [FrameInfo("https://www.recaptcha.net/recaptcha/enterprise/anchor", width=256, height=60)]
    )
    assert anchor.challenge_type is ChallengeType.INVISIBLE

    bframe = observer.observe(
        [FrameInfo("https://www.recaptcha.net/recaptcha/enterprise/bframe", width=400, height=580)]
    )
    assert bframe.provider is ChallengeProvider.RECAPTCHA_ENTERPRISE
    assert bframe.challenge_type is ChallengeType.IMAGE_SELECTION
    assert bframe.challenge_type.interactive is True
    # O desafio apresentado pesa mais que o selo.
    assert bframe.confidence > anchor.confidence


def test_a_classic_bframe_is_also_a_presented_challenge():
    result = FrameObserver().observe(
        [FrameInfo("https://www.recaptcha.net/recaptcha/api2/bframe", width=400, height=580)]
    )
    assert result.provider is ChallengeProvider.RECAPTCHA
    assert result.challenge_type is ChallengeType.IMAGE_SELECTION


def test_a_provider_without_challenge_frames_keeps_its_default_type():
    result = FrameObserver().observe(
        [FrameInfo("https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha-enclave.html", width=300, height=400)]
    )
    assert result.provider is ChallengeProvider.HCAPTCHA
    assert result.challenge_type is ChallengeType.CHECKBOX
