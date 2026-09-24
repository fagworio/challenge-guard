"""Reconhecimento passivo de providers (CG-015A).

Observa a superficie anti-bot de um board publico SEM clicar, preencher ou
submeter nada. O objetivo nao e "testar CAPTCHA": e validar se o registry
reconhece a estrutura real, e corrigir os dados a partir do que for visto.

O que sai daqui (e o que nunca sai):

    DOM estrutural        -> sim
    frames (host/path)    -> sim
    network (origem, caminho com hash, metodo, tipo, status) -> sim

    sitekey, token, cookie, body, query, valor de formulario, header de
    autenticacao, dado de candidato -> NUNCA

Uso:
    python tools/passive_recon.py --out tests/fixtures/real_world
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from challenge_guard import (  # noqa: E402
    ChallengePhase,
    ChallengePolicy,
    DOMObserver,
    FrameObserver,
    NetworkObserver,
    ResponseObserver,
    merge,
)
from challenge_guard.observers import FrameInfo, NetworkRecord, ResponseRecord  # noqa: E402
from challenge_guard.observers.frames import path_shape  # noqa: E402
from challenge_guard.providers import profile_for_host  # noqa: E402

#: Board publico por provider. O nome do board e PROVENIENCIA do arquivo; o
#: conteudo consumido pelo Core fala apenas de provider/challenge.
TARGETS = (
    ("hcaptcha", "lever", "https://jobs.lever.co/spotify/1692fccc-29f4-4525-a683-b004c2ec62b9/apply"),
    ("recaptcha", "greenhouse", "https://job-boards.greenhouse.io/embed/job_app?for=affirm&token=7927799003"),
    ("recaptcha", "ashby", "https://jobs.ashbyhq.com/linear/d3bc1ced-3ce4-4086-a050-555055dbb1ff/application"),
)

#: Atributos cujo VALOR nunca e registrado. A presenca e o fato estrutural.
_REDACT_ATTRS = ("data-sitekey", "data-hcaptcha-widget-id", "value", "src", "href", "action", "data-callback")

_TAG = re.compile(r"<[^>]+>")


def _sanitize_attributes(tag: str) -> str:
    """Mantem so os atributos estruturais; valores sensiveis viram REDACTED."""
    name_match = re.match(r"<\s*([a-zA-Z0-9]+)", tag)
    name = name_match.group(1).casefold() if name_match else "div"
    parts = [name]
    for attribute in ("class", "id", "name", "type", "role", "aria-hidden"):
        match = re.search(rf'{attribute}\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        if match:
            parts.append(f'{attribute}="{match.group(1).strip()}"')
    # `title` fica de fora do valor literal: um title real trazia HTML embutido
    # com o token da conta dentro. Presenca basta como fato estrutural.
    if re.search(r"title\s*=", tag, re.IGNORECASE):
        parts.append('title="REDACTED"')
    for attribute in _REDACT_ATTRS:
        if re.search(rf"{attribute}\s*=", tag, re.IGNORECASE):
            parts.append(f'{attribute}="REDACTED"')
    return "<" + " ".join(parts) + ">"


def _sanitize_fragment(html: str, max_tags: int = 6) -> str:
    """Fragmento estrutural: tags e atributos, sem texto e sem valores sensiveis.

    `max_tags=0` significa SEM LIMITE. Antes o slice `kept[:0]` devolvia vazio, e
    por isso a captura de DOM saiu em branco em todos os boards: um bug da
    ferramenta que parecia "o registry nao detecta DOM".
    """
    body = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    tags = _TAG.findall(body)
    kept = [t for t in tags if not t.casefold().startswith(("</", "<!"))]
    selected = kept if max_tags <= 0 else kept[:max_tags]
    return "".join(_sanitize_attributes(tag) for tag in selected)


def _path_hash(url: str) -> str:
    return hashlib.sha256((urlsplit(url).path or "/").encode("utf-8")).hexdigest()[:16]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" if parts.hostname else ""


def observe(url: str, *, wait_ms: int = 12000) -> dict:
    """Abre a pagina, espera o widget e devolve a captura sanitizada."""
    from playwright.sync_api import sync_playwright

    requests: list[NetworkRecord] = []
    responses: list[ResponseRecord] = []
    frames_raw: list[FrameInfo] = []
    dom_fragments: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_context().new_page()

        def on_request(request):
            requests.append(
                NetworkRecord(
                    url=str(request.url),
                    method=str(request.method),
                    resource_type=str(getattr(request, "resource_type", "")),
                )
            )

        def on_response(response):
            try:
                responses.append(ResponseRecord(status=int(response.status), text="", url=str(response.url)))
            except Exception:
                return

        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            browser.close()
            return {"error": str(exc)[:120], "url": url}
        page.wait_for_timeout(wait_ms)

        for element in page.query_selector_all("iframe"):
            try:
                box = element.bounding_box()
                frames_raw.append(
                    FrameInfo(
                        url=str(element.get_attribute("src") or ""),
                        visible=bool(element.is_visible()),
                        width=int(box["width"]) if box else 0,
                        height=int(box["height"]) if box else 0,
                    )
                )
            except Exception:
                continue

        for selector in (".h-captcha", ".g-recaptcha", ".cf-turnstile", "[data-sitekey]", "iframe"):
            for element in page.query_selector_all(selector):
                try:
                    dom_fragments.append(_sanitize_fragment(element.evaluate("e => e.outerHTML")))
                except Exception:
                    continue
                break  # uma amostra por selector basta

        full = _sanitize_fragment(page.content(), max_tags=0)
        browser.close()

    return {
        "url": url,
        "requests": requests,
        "responses": responses,
        "frames": frames_raw,
        "dom_fragments": dom_fragments,
        "dom_full": full,
    }


def classify(capture: dict) -> dict:
    """Roda os observers sobre a captura e devolve a classificacao."""
    dom = DOMObserver().observe(capture.get("dom_full", ""))
    frames = FrameObserver().observe(capture.get("frames", []))
    network = NetworkObserver().observe(capture.get("requests", []))
    response = ResponseObserver().observe(capture.get("responses", []))
    merged = merge([dom, frames, network, response])
    decision = ChallengePolicy().decide(
        __import__("challenge_guard").ChallengeObservation(
            detected=merged.detected,
            phase=ChallengePhase.PRE_SUBMIT,
            provider=merged.provider,
            challenge_type=merged.challenge_type,
            visible=merged.detected,
            signals=merged.signals,
            confidence=merged.confidence,
        )
    )
    return {
        "dom": dom,
        "frames": frames,
        "network": network,
        "response": response,
        "merged": merged,
        "decision": decision,
    }


def _symbols(result, suffix: str) -> list[str]:
    return sorted({f"{signal.provider.value.upper()}_{suffix}" for signal in result.signals})


def build_fixture(provider: str, board: str, capture: dict, classified: dict) -> dict:
    merged = classified["merged"]
    decision = classified["decision"]
    runtime = [
        {
            "origin": _origin(record.url),
            "path_hash": _path_hash(record.url),
            "method": record.method.upper(),
            "resource_type": record.resource_type,
            "status": record.status,
        }
        for record in capture["requests"]
        # Filtro pelo REGISTRY, nao por substring: `googletagmanager.com` entrou
        # no primeiro passe por conter "google", e nao e runtime de challenge.
        if profile_for_host(urlsplit(record.url).hostname or "")
    ]
    return {
        "provider": merged.provider.value,
        "observation": "passive_public_board",
        "provenance": {"board": board, "recorded_by": "tools/passive_recon.py"},
        "challenge_visible": bool(merged.detected),
        "detected": bool(merged.detected),
        "phase": "pre_submit",
        "decision": decision.status.value,
        "reason_token": decision.reason_token,
        "confidence": round(merged.confidence, 3),
        "signals": {
            "dom": _symbols(classified["dom"], "CONTAINER"),
            "frames": _symbols(classified["frames"], "FRAME"),
            "network": ["CHALLENGE_TRAFFIC"] if classified["network"].signals else [],
        },
        # A fixture guarda a ENTRADA REAL do observer. Antes ela guardava as
        # amostras por selector, que nao eram o que a classificacao consumiu —
        # e o replay offline reproduziria outra coisa.
        "dom_structure": capture.get("dom_full", ""),
        "dom_samples": capture.get("dom_fragments", []),
        "frames": [
            {
                "host": frame.host,
                "path": frame.path_shape,
                "visible": frame.visible,
                "width": frame.width,
                "height": frame.height,
            }
            for frame in capture.get("frames", [])
        ],
        "network": runtime,
        "pii_present": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="tests/fixtures/real_world")
    parser.add_argument("--wait-ms", type=int, default=12000)
    args = parser.parse_args()
    out = pathlib.Path(args.out)

    for provider, board, url in TARGETS:
        print(f"\n=== {provider} / {board} ===", flush=True)
        capture = observe(url, wait_ms=args.wait_ms)
        if "error" in capture:
            print("  ERRO:", capture["error"])
            continue
        classified = classify(capture)
        merged = classified["merged"]
        print(f"  provider identificado : {merged.provider.value}")
        print(f"  primeiro sinal        : {merged.source or '(nenhum)'}")
        print(f"  detectado             : {merged.detected}  confianca={merged.confidence:.2f}")
        print(f"  hosts de frame        : {sorted({f.host for f in capture['frames'] if f.host})}")
        print(f"  decissao              : {classified['decision'].status.value}")
        fixture = build_fixture(provider, board, capture, classified)
        target = out / provider / f"{board}-passive.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  fixture               : {target}")
        print(f"  origens de runtime    : {sorted({item['origin'] for item in fixture['network']})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
