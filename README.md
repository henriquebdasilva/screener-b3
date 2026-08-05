# Screener B3 — Fundamentos + Rompimento (BOVA11 & SMALL11)

App em Python, disparado **todo dia útil via GitHub Actions**, que:

1. varre os constituintes do **BOVA11** (Ibovespa) e do **SMALL11** (SMLL);
2. aplica a **metodologia fundamentalista** (scores Quality / Value / Safety / Dividend →
   **Investment Score**), com tratamento por setor;
3. aplica um **filtro de rompimento gráfico** sobre o preço;
4. gera relatórios em `reports/` (CSV + Markdown) e os commita de volta ao repositório.

> ⚠️ **Material analítico, não recomendação de investimento.** Dados de fontes públicas
> podem ter erros/defasagem. Você é responsável pelas suas decisões.

## Estrutura

```
universe.py     # listas de tickers do BOVA11/Ibovespa e SMALL11/SMLL (edite aqui)
datafeed.py     # fundamentos (fundamentus -> yfinance) e preços OHLCV (yfinance)
scoring.py      # scores Quality/Value/Safety/Dividend/Investment (ranking 0-100)
breakout.py     # >>> filtro de rompimento (TROQUE pela lógica do seu repositório) <<<
screener.py     # orquestra tudo e escreve reports/
.github/workflows/screener.yml  # agendamento diário
requirements.txt
```

## Rodando localmente

```bash
pip install -r requirements.txt
python screener.py --universe both --top-quantile 0.5
# debug rápido (só 15 tickers):
python screener.py --universe smll --limit 15 --no-volume
```

Parâmetros úteis: `--min-invest 60` (corte por nota em vez de quantil),
`--lookback 55` (rompimento de 55 dias), `--vol-mult 2`, `--require-contraction`,
`--no-trend`. Saídas: `reports/screener_AAAA-MM-DD.csv`, `reports/selecionados_AAAA-MM-DD.csv`
e `reports/latest.md`.

**O corte fundamentalista decide quais papéis entram no relatório; o rompimento/pivô NÃO exclui ninguém — vira uma _flag_ por papel (`oportunidade_grafica`: Rompimento | Pivô de alta | Não).** Assim, um papel bom de fundamentos aparece mesmo sem rompimento, marcado como "Não". Para listar **todos** os papéis avaliados, use `--top-quantile 1.0` (ou `--min-invest 0`). A coluna `aprovado` (fundamentos _E_ gráfico) continua disponível no CSV/planilha para quem quiser filtrar por ela.

## GitHub Actions

Já incluso em `.github/workflows/screener.yml`: roda **22:00 UTC (19:00 BRT)** de seg a
sex e também sob demanda (aba **Actions → Run workflow**). Ele commita `reports/` de volta
(precisa de `permissions: contents: write`, já configurado). Em Settings → Actions →
General, deixe *Workflow permissions* em **Read and write**.

## Filtro de rompimento (port do repositório)

`breakout.py` é um **port fiel** do algoritmo de
[`henriquebdasilva/stock_screener`](https://github.com/henriquebdasilva/stock_screener)
(branch **`master`**, `screener.py`). Ele produz **dois sinais**:

- **Rompimento** — a ação está *consolidada* (existe uma janela de 7–14 pregões em que a
  variação entre a máxima e a mínima dos fechamentos é < 15%) **e** o último fechamento
  supera a máxima dos 15 fechamentos anteriores.
- **Pivô de alta** — consolidada (até 20%), em tendência de alta/lateral (MM21), com recuo
  e retomada, confirmado por preço, **engolfo de alta** ou **martelo** (candlestick).

Parâmetros e constantes são os mesmos do original. Os padrões de candle usam **TA-Lib se
estiver instalado** (idêntico ao repo: `CDLENGULFING` / `CDLHAMMER`); se não estiver,
caem para implementações equivalentes em pandas puro — assim o GitHub Actions roda **sem
compilar o TA-Lib**. Para forçar o TA-Lib, adicione-o ao `requirements.txt`.

> O que *não* foi portado (era específico do fluxo do autor): geração de gráficos com
> suportes/resistências (Selenium/matplotlib), relatório HTML com Tailwind e envio por
> e-mail. Aqui o resultado sai como CSV + Markdown. A função tem a mesma assinatura
> (`detect_breakout(df) -> BreakoutResult`), então dá para evoluir sem tocar no resto.

## E-mail (relatório + planilha anexa)

Ao final, o app monta um **relatório HTML** com a tabela dos ativos que passaram nos dois
critérios fundamentalistas, com a **oportunidade gráfica sinalizada por papel** (flag Rompimento/Pivô/Não), e **anexa a planilha `.xlsx`** (aba *Selecionados* + aba *Universo* com o ranking completo) e o CSV dos selecionados. O envio só ocorre se as credenciais estiverem
configuradas — senão, ele é pulado e os relatórios continuam sendo gerados em `reports/`.

Configuração por **variáveis de ambiente / GitHub Secrets** (nunca em código):

| Secret | Exemplo | Obrigatório |
|--------|---------|-------------|
| `SMTP_USER` | `voce@gmail.com` | sim |
| `SMTP_PASS` | senha de app (16 letras) | sim |
| `MAIL_TO`   | `voce@gmail.com, outro@x.com` | sim |
| `SMTP_HOST` | `smtp.gmail.com` (default) | não |
| `SMTP_PORT` | `465` (default, SSL) | não |
| `MAIL_FROM` | default = `SMTP_USER` | não |

No GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
Para Gmail, gere uma **senha de app** (Conta Google → Segurança → Verificação em duas
etapas → Senhas de app) e use-a em `SMTP_PASS`. Localmente:

```bash
export SMTP_USER="voce@gmail.com" SMTP_PASS="xxxx xxxx xxxx xxxx" MAIL_TO="voce@gmail.com"
python screener.py --universe both
# desligar o envio: python screener.py --no-email
```

> ⚠️ Nunca commite senha no código. Se você já expôs uma senha de app num repositório
> público, **revogue-a** e gere outra.



- **Fundamentos:** `fundamentus` (raspa fundamentus.com.br — boa cobertura B3). Se falhar,
  cai para `yfinance` (`.info`), cuja cobertura de fundamentos brasileiros é irregular.
  Campos ausentes viram `NaN` e **saem do ranking daquele indicador** (não zeram a nota).
- **Preços:** `yfinance` (tickers `.SA`). Fonte não-oficial; pode ter falhas pontuais — o
  app trata cada ticker com `try/except` e segue.
- **Composição dos ETFs/índices é _gated_** (página da B3 em JavaScript; arquivo da iShares
  exige download). Por isso as listas ficam em `universe.py`, versionadas e fáceis de
  editar. **Atualize-as a cada rebalanceamento** (a B3 rebalanceia quadrimestralmente).
- **Bancos/seguros/holdings:** EV/EBITDA, Dív.Líq/EBITDA, liquidez corrente e Dív/Patrim
  não se aplicam → o Safety deles usa o que houver; o Investment re-normaliza os pesos.
- **Small caps** têm dados mais ruidosos (lucros voláteis → mais PEG "n/m", menor liquidez).

## Critérios fundamentalistas (checklist) + preços-teto

Além do Investment Score, cada papel passa por um **checklist** (colunas no CSV/planilha,
valores Sim/Não/n/d):

1. **ROE ≥ Selic** (Selic vinda da API do Banco Central — série 432; override por env `SELIC`).
2. **ROE ≥ média do setor**; 3. **ROIC ≥ média do setor**; 5. **CAGR 5a ≥ média do setor**
   (média do setor calculada **dentro do universo varrido** — limitação honesta).
4. **Margem líquida ≥ 15%** (n/a p/ bancos/seguros).
6. **Dív.Líq/EBITDA < 3 e ≤ média do setor** (n/a p/ bancos/seguros).
7. **Market cap ≥ R$ 300 mi** (piso; papéis abaixo saem da seleção, salvo `--no-mktcap-filter`).
8. **Sem venda expressiva de insiders no último ano** — raspagem *best-effort* da página de
   insiders do Fundamentus; frágil, então em dúvida vira `n/d` e não pesa. Desligue com env
   `INSIDER_CHECK=0`.

`criterios_ok / criterios_aplicaveis` conta quantos foram cumpridos. Por padrão o checklist
é **informativo** (não elimina, além do piso de market cap). Para exigir **todos** os
critérios aplicáveis, rode com **`--strict-criteria`**.

**Preços-teto** (no corpo do e-mail e na planilha), por papel: **Bazin** (DY 6%),
**Gordon** (perpetuidade de dividendos), **DCF** (perpetuidade de lucros), **Graham**
(√(22,5·LPA·VPA)) e **Lynch/PEGY** (P/L justo = crescimento% + DY%), mais a **Média** e a
**Mediana** deles. A mediana é mais robusta quando um método dispara; o *upside* do e-mail é
vs. a mediana. A tabela principal do e-mail já mostra o **Teto médio (upside%)** ao lado das
demais colunas. Premissas: `k` = Selic (+ prêmio opcional), `g` conservador. Estimativas
sensíveis às premissas — não são gatilho.

Novas flags: `--strict-criteria`, `--no-mktcap-filter`. Novos envs opcionais: `SELIC`
(ex.: `15`), `INSIDER_CHECK` (`0` desliga).

## Agenda, dividendos e tese por IA (opcional)

Para os papéis do relatório, o app busca (via `yfinance`, best-effort — "n/d" quando não
houver): **data do próximo resultado** e **data ex-dividendo** (marcada como *última* ou
*próxima*), além do **DY** que já vinha dos fundamentos.

Para os **aprovados** (fundamentos + rompimento), gera uma **tese de investimento por IA**
(Gemini Flash, free tier) **ancorada exclusivamente nos números que o app coletou** — o
prompt proíbe usar conhecimento externo, inventar fatos/notícias/preço-alvo e recomendar.
É um resumo automático, pode conter erros e **não é recomendação**.

Ativação (só a tese exige chave): env `GEMINI_API_KEY` (secret). Opcionais: `GEMINI_MODEL`
(default `gemini-2.5-flash`), `AI_MAX_TOKENS` (tamanho da resposta, default 1024) e `AI_MAX_CALLS` (default 40, teto de chamadas/execução p/
respeitar a cota). Sem a chave, as teses ficam vazias e o resto roda igual. Há cache em
`reports/cache_tese.json` (não repete o mesmo papel no mesmo dia). Desligue tudo com
`--no-enrich`. A agenda e as teses aparecem no corpo do e-mail e na planilha.

### Solução de problemas da tese por IA

**Precisa criar alguma secret nova?** Não. A única essencial é `GEMINI_API_KEY`. As demais
são opcionais e têm valores-padrão no código:

- `AI_MAX_TOKENS` — tamanho da resposta. Padrão **1024** (bom para 8–10 frases). Aumente
  para `1536`/`2048` se quiser teses mais longas.
- `AI_DEBUG` — defina `1` **temporariamente** para ver no log a resposta bruta da API e
  avisos de corte por `MAX_TOKENS`. Remova depois.
- `GEMINI_MODEL` — use só o id, ex.: `gemini-2.5-flash` (sem `models/`, sem aspas, sem
  espaços). O código já sanitiza esses casos; se vier inválido/vazio, cai num default.
- `AI_MAX_CALLS` — padrão 40; teto de chamadas por execução (respeita a cota do free tier).

**Erros comuns no log (linhas `[IA] ...`):**

- `chave: VAZIA` → o secret não chegou ao processo. Confira o nome exato `GEMINI_API_KEY` e
  se o workflow injeta `GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}` no `env:` do passo
  (secrets não viram variáveis de ambiente sozinhos).
- `FALHOU -> HTTP 400: ... unexpected model name format` → valor de `GEMINI_MODEL` malformado
  (ex.: com `models/`). Corrija o secret ou confie na limpeza automática.
- `HTTP 404` → modelo inexistente; use um id atual do AI Studio. `HTTP 400` → chave inválida.
  `HTTP 429` → cota do minuto/dia estourada.
- Teses **truncadas** ou com eco de instruções → resolvido desligando o *thinking*
  (`thinkingBudget: 0`) e reforçando o prompt; se persistir, suba `AI_MAX_TOKENS`.

**Cache (importante):** as teses ficam em `reports/cache_tese.json` com a **data** na chave.
Rodar de novo **no mesmo dia** reaproveita as teses já geradas (inclusive versões ruins de
um teste anterior). Para regenerar **hoje**, **apague `reports/cache_tese.json`** do
repositório antes de rodar (ou rode no dia seguinte, quando a chave do cache muda de data).

## Ajustes comuns

- Mudar pesos do Investment Score → `scoring.py` (dict `W`).
- Adicionar indicador (ex.: cobertura de juros) → incluir em `datafeed.Fundamentals`,
  no mapeamento de colunas e no bloco de score correspondente.
- Enviar só quando houver ao menos 1 papel com oportunidade gráfica → guardar em
  `screener.run()` antes de chamar o e-mail (checar `oportunidade_grafica != 'Não'`).
