# ADR 0007: browser neutro a CDP, e o launcher fica com o host

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

O roadmap 0.2.0 quer reaproveitar infraestrutura de browser pronta em vez de reescrever CDP. A
proposta original colocava `seleniumbase` como dependencia **do pacote** e `browser/seleniumbase.py`
como launcher padrao, usando:

```text
sb_cdp.Chrome -> get_endpoint_url() -> playwright.connect_over_cdp() -> PlaywrightChallengeAdapter
```

Antes de desenhar, foi medido — no SHA `a035346b898546d97abfc12535626f746c44128a`, que e exatamente o
`master` no momento da medicao:

```text
help_docs/uc_mode.md            "For the successor to plain UC Mode, see CDP Mode"
examples/cdp_mode/ReadMe.md     "CDP Mode is a stealth mode"
                                "From CDP Mode, you can make Playwright stealthy
                                 (Stealthy Playwright Mode)"
seleniumbase/core/sb_cdp.py     from seleniumbase.undetected.cdp_driver import cdp_util
                                get_rd_url(): "allowing the Playwright integration
                                 to launch stealthy"
```

E o probe funcional, no mesmo ambiente deste repositorio:

```text
sb_cdp.Chrome(headless=True) -> endpoint http://127.0.0.1:36361 -> get_title() == "Example Domain"
```

Ou seja: a integracao funciona, e o modo que ela usa e descrito pelo proprio fornecedor como
**stealth**, construido sobre a linhagem `undetected`.

Isso colide com a ADR 0001, que e a identidade desta biblioteca: ela **nunca** esconde sinal de
automacao. E colide de um jeito traicoeiro: o job `boundary` do CI procura a palavra `stealth` em
nomes de funcao/Classe. Um `import seleniumbase` nao cria nenhum nome desses — o check passaria
verde enquanto a fronteira substancial (o browser observado deixa de ser um browser comum) teria
mudado. Um contrato que nao falha no caso que importa e o que o anel 5 deste projeto existe para
recusar.

## Decision

**O `challenge-guard` nao lanca browser e nao depende de `seleniumbase`.** Ele conecta a um endpoint
CDP ja existente, e quem decide como o browser nasce e o host.

```text
host (jobsearch-agent)
  └── launcher: SeleniumBase, Chrome puro, o que o host decidir
         └── CDP endpoint (http://127.0.0.1:<port>)
                └── challenge_guard.browser.cdp.PlaywrightCdpSession
                       └── connect_over_cdp() -> Page
                              └── PlaywrightChallengeAdapter (o mesmo de sempre)
```

Tres consequencias, todas verificaveis por maquina:

1. **`seleniumbase` nao entra no pacote nem nos extras dele.** Quem quiser esse launcher instala no
   host. O extra `playwright` (ja existente) e o unico necessario para a ponte, porque a ponte **e**
   Playwright.
2. **A ponte e neutra.** `CdpEndpoint` e validado e nao guarda nada alem de host/porta. A sessao nao
   liga modo UC, nao reescreve fingerprint, nao injeta script e nao desabilita sinal de automacao —
   nao ha, no codigo, nenhuma opcao para isso.
3. **A posse do browser e invariante, nao opcao.** `PlaywrightCdpSession.close()` **desconecta** e
   nao mata o browser: quem lancou (o host) desliga. A versao inicial tinha
   `close(close_browser=True)`, que na pratica permitia ao guard matar um browser que ele nao
   lancou — convencao disfarcada de parametro. Ele foi removido: uma sessao que so sabe CONECTAR
   nao pode ter a opcao de fechar o que nao e dela.

O ganho do roadmap continua inteiro: **um unico observer** (`PlaywrightChallengeAdapter`), o mesmo
para qualquer backend, e a decisao provada identica nos dois caminhos (CG-035).

## What this ADR does not forbid

Nada aqui proibe o host de usar SeleniumBase, nem de escolher um browser que ele considere menos
detectavel. A fronteira e sobre a **biblioteca**: o material que o guard produz (evidencia,
proveniencia, decisao) tem de descrever um browser comum, e a biblioteca nao pode ser o instrumento
do disfarce. Se um host escolhe outro launcher, o guard observa o mesmo conjunto de fatos e chega a
mesma decisao — e isso e exatamente o que CG-035 mede.

## Consequences

- `BrowserChallengeAdapter` (o contrato que o core ja conhece) nao muda. `PlaywrightCdpSession`
  produz a `Page`; o adapter continua lendo DOM, frames, rede e respostas.
- CG-024 (`ChallengeMonitor.attach_adapter`) passa a ser o caminho explicito: o backend e injetado,
  nunca escolhido por import implicito.
- `ChallengeRuntime` recebe **ou** uma `Page` **ou** um `CdpEndpoint`; os dois produzem o mesmo
  `ChallengeRuntimeResult`.
- O escopo de rede e **aplicado**, nao consultivo: o adapter entregue ao observador passa por
  `ScopedNetworkAdapter`, e o que fica fora do escopo declarado nao chega a observacao (com contagem
  no journal). Um guard que "sabe" o escopo e entrega tudo assim mesmo nao protege nada.
- O CI ganha dois jobs novos: um que verifica dependencia opcional (importar o pacote sem
  `playwright`/`seleniumbase` instalados) e outro que verifica que o pacote nao importa
  `seleniumbase` em nenhum modulo.
