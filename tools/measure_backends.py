"""Mede a MESMA decisao em backends de browser diferentes (CG-035, lado do host).

O `challenge-guard` nao lanca browser (ADR 0007). Quem lanca e o host — e este
script e um host de laboratorio que faz isso de tres formas, com o guard
observando por CDP em duas delas:

```text
a) playwright-direct   sync_playwright().chromium.launch()
b) seleniumbase-cdp    SeleniumBase sb_cdp.Chrome() -> get_endpoint_url()
c) chrome-cdp          Chromium com --remote-debugging-port=<efemera>
```

Cada backend roda em um **subprocesso proprio**. Isso nao e detalhe de
implementacao: SeleniumBase aplica `nest_asyncio` para conviver com Playwright no
mesmo processo, e medir os dois no mesmo interpretador mediria a convivencia, nao
a decisao. Processos separados e o que um host real faz.

O que este script NAO faz, por decisao registrada (ADR 0001/0007):

    nao liga modo UC (`uc_open_with_reconnect`, `--uc`)
    nao desabilita sinal de automacao nem reescreve fingerprint
    nao usa driver modificado para "nao ser detectado"
    nao resolve, clica, digita ou responde desafio nenhum
    nao le sitekey, token, cookie, corpo de resposta ou dado de candidato

O `sb_cdp.Chrome` entra aqui apenas como LANCADOR, exatamente como o roadmap
pediu — e a propria documentacao do SeleniumBase descreve o CDP Mode como stealth,
que e o motivo de ele nao ser dependencia da biblioteca.

Uso:
    python tools/measure_backends.py                 # roda os backends disponiveis
    python tools/measure_backends.py --backend b     # um backend so (uso interno)
    python tools/measure_backends.py --json          # relatorio legivel por maquina
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

CHALLENGE_PATH = "/challenge"
WIDGET_PATH = "/widget"

CHALLENGE_PAGE = f"""<!doctype html><html><body>
<main><form id="app"><input name="email"><button type="submit">Submit</button></form></main>
<div class="h-captcha grid-4x4" data-sitekey="fixture-sitekey"></div>
<iframe src="{WIDGET_PATH}" width="300" height="150"></iframe>
</body></html>""".encode()

PLAIN_PAGE = b"""<!doctype html><html><body><form><input name="email"></form></body></html>"""

BACKENDS = ("a", "b", "c")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = CHALLENGE_PAGE if self.path.startswith(CHALLENGE_PATH) else PLAIN_PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def _serve() -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


# --- um backend por subprocesso -------------------------------------------------


def _measure_in_subprocess(backend: str, url: str) -> dict:
    completed = subprocess.run(
        [sys.executable, __file__, "--backend", backend, "--url", url],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        return {
            "backend": backend,
            "available": False,
            "error": (completed.stderr.strip().splitlines() or ["unknown error"])[-1][:300],
        }
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    payload["available"] = True
    return payload


def _launch_chrome_cdp(tmp_path: Path) -> tuple[subprocess.Popen, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = os.getenv("CHALLENGE_GUARD_CDP_CHROME") or str(playwright.chromium.executable_path)
    profile = tmp_path / f"profile-{int(time.time() * 1000)}"
    profile.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            executable,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    port_file = profile / "DevToolsActivePort"
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError("chrome exited during startup")
        if port_file.exists():
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].strip().isdigit():
                return process, f"http://127.0.0.1:{lines[0].strip()}"
        time.sleep(0.1)
    raise RuntimeError("chrome did not publish a DevTools port")


def _observe(url: str, page, runtime) -> dict:
    page.goto(f"{url}{CHALLENGE_PATH}", wait_until="load")
    decision = runtime.evaluate()
    observation = runtime.monitor.observation
    result = runtime.result()
    adapter = runtime.monitor.adapter
    # A rede CRUA (fato do browser) e a que interessa para comparar backends: o
    # escopo do guard filtra o que o observador le, e isso ja e igual por
    # construcao. O `scoped` reporta quantos registros entraram e quantos ficaram
    # de fora, para a evidencia nao perder o fato.
    inner = getattr(getattr(runtime, "scoped_adapter", None), "inner", None) or adapter
    scope_report = (
        runtime.scoped_adapter.describe_scope() if getattr(runtime, "scoped_adapter", None) is not None else {}
    )
    return {
        "provider": result.provider,
        "challenge_type": result.challenge_type,
        "decision": result.decision,
        "final_status": result.final_status,
        "reason_token": result.reason_token,
        "human_required": result.human_required,
        "capability": result.capability,
        "confidence": round(result.confidence, 4),
        "evidence_sources": sorted(observation.evidence_sources),
        "dom_signals": sorted(observation.dom_signals),
        "frames": sorted(frame.url for frame in adapter.collect_frames()),
        "network_hosts": sorted({record.url for record in inner.collect_network()}),
        "network_in_scope": int(scope_report.get("network_in_scope", 0)),
        "network_dropped": int(scope_report.get("network_dropped", 0)),
        "backend": result.backend,
    }


def _run_backend(backend: str, url: str) -> dict:
    from challenge_guard import ChallengeRuntime, ChallengePhase, PlaywrightCdpSession, RuntimeLimits

    if backend == "a":
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_context().new_page()
            runtime = ChallengeRuntime(page=page, limits=RuntimeLimits(max_rounds=3)).start()
            try:
                return _observe(url, page, runtime)
            finally:
                runtime.close()
        finally:
            browser.close()
            playwright.stop()

    if backend == "b":
        from seleniumbase import sb_cdp

        # Apenas o lancador: nenhuma opcao de modo UC, nenhum disfarce.
        sb = sb_cdp.Chrome(headless=True)
        try:
            endpoint = sb.get_endpoint_url()
            session = PlaywrightCdpSession.from_endpoint(endpoint)
            runtime = ChallengeRuntime(session=session, limits=RuntimeLimits(max_rounds=3)).start()
            try:
                report = _observe(url, session.page, runtime)
                report["cdp_host"] = session.endpoint.host
                report["cdp_port"] = session.endpoint.port
                report["launcher"] = "seleniumbase.sb_cdp"
                return report
            finally:
                runtime.close()
        finally:
            sb.quit()

    if backend == "c":
        import tempfile

        process, endpoint = _launch_chrome_cdp(Path(tempfile.mkdtemp(prefix="cg-cdp-")))
        try:
            session = PlaywrightCdpSession.from_endpoint(endpoint)
            runtime = ChallengeRuntime(session=session, limits=RuntimeLimits(max_rounds=3)).start()
            try:
                report = _observe(url, session.page, runtime)
                report["launcher"] = "chrome --remote-debugging-port"
                return report
            finally:
                runtime.close()
        finally:
            process.terminate()
            process.wait(timeout=10)

    raise SystemExit(f"unknown backend: {backend}")


# --- comparacao -----------------------------------------------------------------


#: Campos que TEM de ser identicos entre backends: sao a decisao e os fatos.
_COMPARABLE = (
    "provider",
    "challenge_type",
    "decision",
    "final_status",
    "reason_token",
    "human_required",
    "capability",
    "evidence_sources",
    "dom_signals",
    "frames",
    "network_hosts",
    "network_in_scope",
    "network_dropped",
)


def compare(reports: list[dict]) -> tuple[bool, list[str]]:
    available = [report for report in reports if report.get("available")]
    if len(available) < 2:
        return False, ["menos de dois backends disponiveis: nada a comparar"]
    reference = available[0]
    divergences: list[str] = []
    for report in available[1:]:
        for field in _COMPARABLE:
            if report.get(field) != reference.get(field):
                divergences.append(
                    f"{field}: {reference['backend']}={reference.get(field)!r} != {report['backend']}={report.get(field)!r}"
                )
        if abs(float(report.get("confidence", 0)) - float(reference.get("confidence", 0))) > 0.2:
            divergences.append(
                f"confidence: {reference['backend']}={reference.get('confidence')} vs {report['backend']}={report.get('confidence')}"
            )
    return not divergences, divergences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara a decisao do guard em backends diferentes.")
    parser.add_argument("--backend", choices=BACKENDS, help="roda um backend e imprime JSON (uso interno)")
    parser.add_argument("--url", help="URL do fixture servido pelo processo pai (uso interno)")
    parser.add_argument("--json", action="store_true", help="imprime o relatorio completo")
    parser.add_argument("--only", choices=BACKENDS, action="append", help="limita os backends do processo pai")
    args = parser.parse_args(argv)

    if args.backend:
        if not args.url:
            parser.error("--backend exige --url")
        print(json.dumps(_run_backend(args.backend, args.url)))
        return 0

    httpd, url = _serve()
    try:
        selected = args.only or list(BACKENDS)
        reports = [_measure_in_subprocess(backend, url) for backend in selected]
    finally:
        httpd.shutdown()

    same, divergences = compare(reports)
    if args.json:
        print(json.dumps({"backend_different_policy_same": same, "reports": reports, "divergences": divergences}, indent=2))
    else:
        print("backend            decisao        provider      tipo          confianca  fontes")
        for report in reports:
            if not report.get("available"):
                print(f"{report['backend']:<18} INDISPONIVEL   {report.get('error', '')[:60]}")
                continue
            print(
                f"{report['backend']:<18} {report.get('decision', ''):<14} {report.get('provider', ''):<13} "
                f"{report.get('challenge_type', ''):<13} {report.get('confidence', ''):<10} {','.join(report.get('evidence_sources', []))}"
            )
        print()
        print("backend diferente != policy diferente:", "OK" if same else "DIVERGENTE")
        for divergence in divergences:
            print("  -", divergence)
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
