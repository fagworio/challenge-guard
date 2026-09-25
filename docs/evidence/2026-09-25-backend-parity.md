# Paridade de backends: a decisao nao muda quando o browser nasce de outro jeito

- **Data:** 2026-09-25
- **Escopo:** CG-021..CG-035 do roadmap 0.2.0 (SeleniumBase/CDP)
- **Comando:** `python tools/measure_backends.py --json`
- **Ambiente:** Chrome/Chromium 141+ do proprio Playwright (`chromium-1243`), headless, fixture local
  (`http://127.0.0.1:<porta>/challenge`) sem rede externa. Python 3.14, `playwright 1.63`,
  `seleniumbase 4.54.11` (SHA `a035346b898546d97abfc12535626f746c44128a` == `master` no momento da medicao).

## Resultado medido

```text
backend              lancador                          decisao      provider   tipo      conf   fontes  frames    rede
a) page              playwright-direct                 needs_human  hcaptcha   checkbox  0.80   dom     /widget   /widget
b) playwright-cdp    seleniumbase.sb_cdp               needs_human  hcaptcha   checkbox  0.80   dom     /widget   /widget
c) playwright-cdp    chrome --remote-debugging-port    needs_human  hcaptcha   checkbox  0.80   dom     /widget   /widget

divergencias: []
```

```text
backend              lancador                          decisao      provider   tipo      conf   escopo(rede)  frames
a) page              playwright-direct                 needs_human  hcaptcha   checkbox  0.80   0 em /1 fora  /widget
b) playwright-cdp    seleniumbase.sb_cdp               needs_human  hcaptcha   checkbox  0.80   0 em /1 fora  /widget
c) playwright-cdp    chrome --remote-debugging-port    needs_human  hcaptcha   checkbox  0.80   0 em /1 fora  /widget

divergencias: []
```

A coluna `escopo(rede)` e o CG-028 aplicado: o host do fixture NAO e host de
provider, entao o unico request observado fica FORA do escopo declarado e nao
chega ao observador — de forma identica nos tres backends. A rede crua continua
auditavel no adapter interno; o que muda e o que o guard LE.

Cada backend rodou em um **subprocesso proprio**. Isso nao e detalhe: o SeleniumBase aplica
`nest_asyncio` para conviver com Playwright no mesmo processo, e medir os dois no mesmo
interpretador mediria a convivencia, e nao a decisao. Um host real escolhe um backend por processo.

O que ficou provado:

```text
CG-A03/A04  SeleniumBase CDP inicia e publica endpoint  -> http://127.0.0.1:<efemera>
CG-A05      Playwright conecta no MESMO browser (connect_over_cdp)
CG-A06..A10 o adapter existente entrega DOM, frames e rede normalmente pelo CDP
CG-A19      Playwright direto e SeleniumBase/CDP dao a MESMA decisao, campo a campo
```

## Correcoes que a revisao do host expos

Tres defeitos que os testes anteriores nao pegavam, todos fechados com teste que
falha se voltarem:

```text
observation_layer_violations()   o `ast.parse` estava FORA do `for`:
                                 contava todos os arquivos de browser/ e
                                 analisava so o ULTIMO. O selfcheck passava
                                 porque a sonda era o ultimo arquivo. Agora
                                 varre todos, e ha teste com a violacao em
                                 `a_violation.py` e arquivo limpo depois.
                                 Varredura sem arquivo LEVANTA (era o unico
                                 guard sem essa protecao).
NetworkScope                     era construido e nunca usado. Agora
                                 `ScopedNetworkAdapter` FILTRA o que o
                                 observador le, e o journal conta
                                 `network_read`/`network_dropped`.
close_browser=True               permitia ao guard fechar um browser que nao
                                 lancou. O parametro NAO EXISTE MAIS: posse e
                                 invariante (ADR 0007), nao opcao.
```

## Posse do browser (medido, nao combinado)

Teste `test_the_guard_does_not_kill_a_browser_it_did_not_launch`: depois de `runtime.close()`, o
`/json/version` do endpoint **continua respondendo** e o processo do Chrome continua vivo. O guard
desconecta o Playwright e nao mata um browser que nao lancou (ADR 0007).

## Dois defeitos que so o browser real revelou

1. **`sync_playwright()` e um gerenciador de contexto, nao um cliente.** Com um cliente falso no
   lugar, a ponte passava; com Chrome de verdade, `connect_over_cdp` estourava `AttributeError`.
   Corrigido em `browser/cdp.py` e guardado pelo teste
   `test_the_default_factory_returns_a_started_client`.
2. **Plugin de pytest + Playwright sincrono = "Sync API inside the asyncio loop".** Com
   `seleniumbase` instalado, o plugin `pytest11: seleniumbase` cria um event loop ativo, e o
   Playwright sincrono recusa iniciar. A biblioteca **nao** aplica `nest_asyncio` para contornar —
   isso patchearia o loop de todo mundo. Ela traduz o erro em `CdpConnectionError` com a causa e a
   acao (`-p no:seleniumbase`, ou lancar o browser em outro processo). Registrado porque um host que
   instale SeleniumBase vai encontrar exatamente isso.

## O que NAO foi usado

```text
modo UC (uc_open_with_reconnect, --uc)   nao usado
uc_driver / driver modificado            nao usado
desabilitar sinal de automacao           nao usado
reescrever fingerprint / plugins         nao usado
clicar, digitar ou responder desafio     nao existe no codigo
ler sitekey, token, cookie, corpo        nao existe no codigo
```

`sb_cdp.Chrome` entra apenas como **lancador**, no host (`tools/measure_backends.py`), nunca como
dependencia da biblioteca — a propria documentacao do SeleniumBase descreve o CDP Mode como *stealth*
e a integracao com Playwright como *Stealthy Playwright Mode*, o que e incompativel com a ADR 0001.
A decisao esta na [ADR 0007](../adr/0007-cdp-neutral-browser-and-host-launcher.md).

## Reproducao

```bash
pip install -e ".[playwright]"        # a ponte e Playwright
pip install seleniumbase              # somente para o backend (b)
python tools/measure_backends.py      # exit 0 = mesma decisao nos backends disponiveis
```

Sem SeleniumBase instalado, o backend (b) aparece como `INDISPONIVEL` e os outros dois continuam
sendo comparados — o script nao depende de nenhum lancador especifico para valer.
