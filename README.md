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
universe.py     # busca a composição BOVA11/SMAL11 na iShares (fallback: listas estáticas)
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

### Filtros de assertividade (mais rígido que o original)

O algoritmo do repositório é permissivo (consolidação larga, sem volume, sem filtro de
tendência no rompimento). Para reduzir sinais fracos, o **Rompimento** agora exige, além de
consolidação + novo topo:

- **Consolidação estreita:** amplitude ≤ **10%** (era 15%). Flag `--breakout-consol-pct`.
- **Margem mínima:** fechar acima do topo de 15 dias por ≥ **1,5%** (evita romper "de
  raspão"). Flag `--breakout-margin-pct`.
- **Volume:** volume do dia ≥ **1,5×** a média de 20 dias. Flag `--vol-mult`; desliga com
  `--no-volume`.
- **Tendência de alta:** preço > **MM200** e **MM50 > MM200** (elimina rompimentos em
  baixa). Desliga com `--no-trend`.

O **Pivô de alta** segue a lógica original (mais frouxa: consolidação ≤20%, tendência não
"Em Baixa", recuo+retomada) — é a rede mais ampla. Para reproduzir o comportamento original
do rompimento, rode com `--no-volume --no-trend --breakout-consol-pct 15 --breakout-margin-pct 0`.

## E-mail (relatório + planilha anexa)

**Wishlist & Carteira (arquivos `.txt`).** Crie `wishlist.txt` e/ou `carteira.txt` (um ticker
por linha; `#` comenta; na carteira, opcionalmente o **preço médio** após o ticker). Esses
papéis são **sempre varridos e exibidos** no e-mail — com todos os dados, preços-teto e
**análise por IA** —, mesmo que reprovem no corte ou não estejam no BOVA11/SMALL11. A carteira
ainda mostra a **variação vs. preço médio**. Caminhos configuráveis por env `WISHLIST_FILE` /
`CARTEIRA_FILE`. Como a IA roda para todos esses papéis, respeite o teto `AI_MAX_CALLS`.


O topo do e-mail traz um **Resumo de mercado** (Selic, e Ibovespa / Small Caps / IFIX no ano
e no mês via yfinance — IFIX é best-effort) e um **Humor do mercado** (percentual dos papéis
em alta/lateral/baixa pela MM21, por índice BOVA11/SMALL11 e por setor, usando todo o
universo). Duas coisas **não** têm fonte automática confiável na B3 e aparecem como `n/d`:
**fluxo estrangeiro** e **opções mais negociadas** (páginas gated / não expostas por
yfinance).

Em seguida, as listas de **BOVA11** e **SMALL11** aparecem **separadas**, cada uma com os
**30% melhores** por Investment Score dentro do próprio grupo (flags `--group-top`, default
0,30, e `--no-split` para voltar ao corte único por `--top-quantile`). Depois há uma seção
**Defensivas · não-cíclicas** — recorte das selecionadas (BOVA11 + SMALL11 juntas) com
**ciclicidade ≤ `--defensive-max-cyc`** (default 0,4: utilities, saneamento, saúde, consumo
básico, telecom, financeiro). Por fim vêm os preços-teto, a agenda e as teses. O app **anexa a planilha `.xlsx`** (aba *Selecionados* +
aba *Universo*) e o CSV. O envio só ocorre se as credenciais estiverem configuradas — senão,
é pulado e os relatórios continuam em `reports/`.

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
- **Composição dos ETFs vem da iShares (automático).** No início de cada execução o app
  baixa os CSVs oficiais de holdings do **BOVA11** e do **SMAL11** (iShares/BlackRock) e
  extrai os tickers de ação (Asset Class = "Renda Variável", excluindo caixa/futuros). Isso
  mantém a lista sempre atualizada — inclusive mudanças de ticker (ex.: EMBR3→EMBJ3,
  NTCO3→NATU3). Se o download falhar (rede/formato), cai automaticamente nas **listas
  estáticas** de `universe.py` (fallback). Para forçar as listas fixas, defina env
  `UNIVERSE_SOURCE=static`. As listas estáticas seguem lá como rede de segurança — mantê-las
  minimamente atualizadas ajuda quando a iShares está fora.
- **Bancos/seguros/holdings:** EV/EBITDA, Dív.Líq/EBITDA, liquidez corrente e Dív/Patrim
  não se aplicam → o Safety deles usa o que houver; o Investment re-normaliza os pesos.
- **Small caps** têm dados mais ruidosos (lucros voláteis → mais PEG "n/m", menor liquidez).

## Critérios fundamentalistas (checklist) + preços-teto

Além do Investment Score, cada papel passa por um **checklist** (colunas no CSV/planilha,
valores Sim/Não/n/d):

1. **ROE ou ROIC ≥ Selic** — passa se **qualquer um** dos dois atingir a Selic (ativo por
   padrão; desligue com `--no-roe-roic-selic`). A Selic vem da API do BC (série 432; override
   por env `SELIC`).
2. **ROE ≥ média do setor**; 3. **ROIC ≥ média do setor**; 5. **CAGR 5a ≥ média do setor**
   (média do setor calculada **dentro do universo varrido** — limitação honesta).
4. **Margem líquida ≥ 15%** (n/a p/ bancos/seguros).
6. **Dív.Líq/EBITDA < 3 e ≤ média do setor** (n/a p/ bancos/seguros).
7. **Market cap ≥ R$ 500 mi** (piso; abaixo saem da seleção; ajuste com `--min-marketcap` em R$ milhões; `--no-mktcap-filter` desliga).
8. **Sem venda expressiva de insiders no último ano** — raspagem *best-effort* da página de
   insiders do Fundamentus; frágil, então em dúvida vira `n/d` e não pesa. Desligue com env
   `INSIDER_CHECK=0`.

**Seleção em cascata.** Os cortes duros são aplicados **primeiro** e o percentil por grupo
é calculado **apenas entre os sobreviventes** (não sobre o universo inteiro). Cortes duros
(todos exceto financeiras, configuráveis, `0` desliga): market cap ≥ piso (`--min-marketcap`),
**Dív.Líq/EBITDA ≤ 3,0** (`--max-leverage` — alavancagem) e **Dív.Líq/Patrim ≤ 1,5**
(`--max-net-debt-equity`, derivada). Depois, dentro de cada grupo (BOVA11/SMALL11), mantêm-se os melhores por
Investment Score conforme `--top-quantile`.

Além do checklist, há um **filtro absoluto de alavancagem**: não-financeiras com
**Dív.Líq/EBITDA acima de 3,0** saem da seleção (coluna `alavancagem_ok`; flag
`--max-leverage`, 0 desliga; financeiras não são afetadas). Há também um corte por
**Dív.Líq/Patrimônio acima de 1,5** (coluna `div_liq_patrim`/`nde_ok`; flag
`--max-net-debt-equity`, 0 desliga). Como o fundamentus não dá esse índice pronto, ele é
**derivado** dos índices disponíveis — `(Dív.Líq/EBITDA × P/VP) / (EV/EBITDA − Dív.Líq/EBITDA)`
— e vira `n/d` (não corta) quando o EBITDA implícito é ~0/negativo; financeiras são poupadas.

O **setor** de cada papel vem, por ordem de precedência: (1) `SECTOR_OVERRIDE` manual em
`datafeed.py`; (2) o **CSV oficial da iShares/BlackRock** (classificação GICS em português,
já baixado para montar o universo — mais confiável que o yfinance, que erra holdings); (3)
yfinance/fundamentus. Isso corrige sozinho casos como a Itaúsa (ITSA4), que o yfinance
rotula como "Industrials" mas a BlackRock classifica como "Financeiro".

**Safety das seguradoras via solvência (manual).** A SUSEP não tem API aberta, então o
Safety das seguradoras vem de uma **tabela manual** (`solvencia.py`, `SOLVENCIA_MANUAL` ou
env em JSON) com o **índice de solvência PLA/CMR** (piso 1,0 → 0; teto 1,5 → 100), no mesmo
molde da Basileia. Coluna `solvencia`. Alguns papéis mal classificados pelo yfinance têm o
**setor forçado** por `SECTOR_OVERRIDE` em `datafeed.py` (ex.: Itaúsa/ITSA4, uma holding
financeira que às vezes vem como "Industrials", e as seguradoras como "Insurance").

**Penalidade de ciclicidade no Safety.** O Safety mede solidez financeira, mas não a
ciclicidade do negócio — uma siderúrgica/incorporadora tende a ser mais arriscada que uma
geradora/saneamento mesmo com balanço parecido. Então o Safety das **não-financeiras** leva
uma penalidade por setor cíclico: `safety × (1 − k × ciclicidade)`, com ciclicidade 0
(defensivo: utilities, saneamento, consumo básico) a 1 (cíclico: mineração, siderurgia,
consumo discricionário, incorporação) — mapa em `scoring.py`, aproveitando que o setor do
yfinance já separa "Consumer Cyclical/Defensive". `k` é `--cyclical-penalty` (default 0,25;
0 desliga). Financeiras são poupadas (Safety vem da Basileia). Coluna `ciclicidade` na
planilha.

**Safety das financeiras via Basileia (IF.data/BC).** Bancos e seguradoras não têm os
indicadores de balanço usados no Safety (Dív.Líq/EBITDA, liquidez, Dív/Patrim), então ficam
`n/d`. Para preencher, o app busca o **Índice de Basileia** na **API Olinda do IF.data** do
Banco Central (JSON, pública) e o converte em Safety, ancorado no piso regulatório: **11% →
0** e **18% → 100** (linear, saturando). Só cobre os bancos do mapa em `basileia.py`
(ticker→CNPJ/nome — confira os CNPJs); casa por CNPJ ou nome. Coluna `basileia` na planilha.
Em qualquer falha (API fora, banco fora do mapa), o Safety segue `n/d` — nada quebra. Flags:
`--no-basileia` desliga; envs `BASILEIA=0`, `BASILEIA_DEBUG=1` (mostra os campos retornados),
`BASILEIA_RELATORIOS`/`BASILEIA_TIPOS` (ajuste fino da consulta). **v1 — validar no primeiro
run:** a parametrização exata do Olinda pode precisar de ajuste via `BASILEIA_DEBUG=1`.

O **Investment Score** pondera Quality **0,45**, Value 0,25, Safety 0,20 e Dividend 0,10
(mais peso em qualidade, menos em preço/dividendo — reduz o viés a small caps "baratas").
Os pesos ficam no dict `W` de `scoring.py`. O **score de Dividend usa o DY médio de ~5 anos**
(não o DY de 12 meses), e o **PEG usa o crescimento sustentável** (abaixo), com fallback ao
CAGR de receita.

**Crescimento sustentável (para PEG e valuation).** Em vez do CAGR de lucro cru (que quebra
com prejuízo — raiz de número negativo, sinal invertido), o app estima o crescimento por
`g = ROE × (1 − payout)`, com `payout = DY%/100 × P/L`. Usa níveis (sem razão entre lucros),
é limitado por um teto e, quando não é confiável (ROE ≤ 0, payout fora de [0,1]), **cai no
CAGR de receita**. Alimenta Gordon/DCF/Lynch e o PEG.

**Bloco de Consistência (influencia a nota).** Oito critérios de qualidade histórica são
avaliados e a fração atendida (0–100) é **misturada ao Investment Score** (peso
`--consistency-weight`, default 0,15; coluna `consistencia` e `Consist.` no e-mail):
+5 anos de Bolsa, nunca deu prejuízo (anos disponíveis), lucro nos últimos 20 trimestres,
dividendo ≥ 5%/ano nos últimos 5 anos, **dividendos sem corte** (sem queda > 20% ano a ano em 5 anos), ROE > 10%, dívida < patrimônio (n/a p/ financeira),
crescimento de receita 5a e crescimento de lucro 5a. Cada critério vira `n/d` quando falta
dado e **não pesa**. Ressalva honesta: os três ligados a **histórico de lucro** (nunca deu
prejuízo, 20 trimestres, crescimento de lucro) dependem do yfinance, cuja cobertura para a
B3 é irregular — costumam sair `n/d`. Desligue essa coleta com env `PROFIT_HISTORY=0`.

`criterios_ok / criterios_aplicaveis` conta quantos foram cumpridos. Por padrão o checklist
é **informativo** (não elimina, além do piso de market cap). Para exigir **todos** os
critérios aplicáveis, rode com **`--strict-criteria`**.

**Preços-teto** (no corpo do e-mail e na planilha), por papel: **Bazin** (DY 6%),
**Gordon** (perpetuidade de dividendos), **DCF** (perpetuidade de lucros), **Graham**
(√(22,5·LPA·VPA)) e **Lynch/PEGY** (P/L justo = crescimento% + DY%), mais a **Média** e a
**Mediana** deles. A mediana é mais robusta quando um método dispara; o *upside* do e-mail é
vs. a mediana. A tabela principal do e-mail já mostra o **Teto médio (upside%)** ao lado das
demais colunas. Premissas: `k` = Selic (+ prêmio opcional), `g` conservador.

**DY do valuation = média de ~5 anos.** Bazin e Gordon dependem do dividendo; usar o **DY de
12 meses** cru infla o teto quando há distribuição extraordinária (ex.: VULC3 com DY 29% →
Bazin irreal). Por isso, para esses dois métodos o app usa o **DY médio dos últimos N anos**
(proventos do ano ÷ preço médio do ano, via histórico do yfinance) — a coluna `dy_teto` na
planilha mostra o valor usado, e a coluna `dy` mantém o DY corrente. Flags: `--dy-years`
(default 5) e `--no-avg-dy` (volta ao DY de 12 meses).

**Bazin amarrado à Selic + margem de segurança.** O Bazin clássico usa 6% fixo, o que
descola do custo de capital atual (Selic ~14%). Aqui o yield-alvo do Bazin é a **Selic**
(flag `--bazin-yield` fixa um % se quiser). E o teto consolidado ganha um **desconto de
segurança** (coluna `teto_ajustado` = mediana × (1 − desconto); default **10%**, flag
`--teto-desconto`). O e-mail mostra o **Teto (aj.)** e o *upside* é calculado sobre ele.
Além disso, um método muito fora dos demais (além de **~2,5×** a mediana — ex.: Lynch
disparado em papel de crescimento) é **descartado do consolidado** (coluna `teto_n_metodos`
mostra quantos entraram; flag `--teto-outlier-mult`, 0 desliga). Em **bancos, seguradoras e
holdings**, Graham (subestima) e Lynch (infla) ficam **fora do consolidado** — sobram
Bazin, Gordon e DCF (os métodos individuais seguem visíveis na tabela). Estimativas
sensíveis às premissas — não são gatilho.

**Neutralização de dado suspeito no score.** Valores de fonte claramente errados poluem o
Value/Dividend. Por isso, **P/L de não-financeira abaixo de `--suspect-pl-min`** (default 2,0)
sai do bloco Value (e do PEG) daquele papel, e **DY médio de 5 anos ≥ `--suspect-dy-max`**
(default 20%) sai do bloco Dividend. O dado bruto continua visível e ainda alimenta o teto
(que tem seu próprio guarda). Financeiras são poupadas do corte de P/L (bancos têm P/L
estruturalmente baixo). Coluna `dado_suspeito` registra o motivo.

**Confiabilidade do teto.** Se os métodos discordam demais entre si (dispersão máx/mín >
`--teto-disp-max`, default 8×) ou o upside fica implausível (> `--teto-max-upside`, default
200%) — típico de dado ruim na fonte (P/L irreal) ou histórico curto de dividendos —, o teto
consolidado é marcado **não confiável** e vira `n/d` ("—"), em vez de exibir um número
distorcido. Colunas `teto_confiavel`/`teto_dispersao`.

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
- `AI_SLEEP` — segundos entre chamadas (padrão 30, ~2/min). Aumente se tomar muito 429.

**Cota / HTTP 429 (importante).** A tese roda **só para os aprovados** (fundamentos +
rompimento) — não para todos os selecionados. O free tier do Gemini limita ~10 req/min e
tem teto diário; em dias com muitos aprovados (ou depois de vários testes no mesmo dia) as
chamadas podem tomar **HTTP 429** e alguns papéis ficam sem tese. O app já faz **retry com
espera** (respeita `Retry-After`) e usa `AI_SLEEP` entre chamadas. Se ainda faltar: aumente
`AI_SLEEP`, use um modelo **Flash-Lite** (mais req/min), reduza o universo, ou rode no dia
seguinte — o **cache preserva** as teses que já saíram, então só as faltantes são geradas.

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

**Cache:** as teses ficam em `reports/cache_tese.json`, com chave `ticker:data:versão`.
Rodar de novo no mesmo dia reaproveita o que já foi gerado (economiza cota). Duas formas de
regenerar sem esperar o dia seguinte:

- **Automático ao mudar o prompt:** a constante `PROMPT_VERSION` em `enrich.py` entra na
  chave do cache. Sempre que a lógica/prompt da tese muda, essa versão sobe e o cache antigo
  é **ignorado sozinho** — você não precisa apagar nada.
- **Sob demanda:** rode com **`--force-ia`** para ignorar o cache e regenerar todas as teses
  (ou apague `reports/cache_tese.json`).

## Ajustes comuns

- Mudar pesos do Investment Score → `scoring.py` (dict `W`).
- Adicionar indicador (ex.: cobertura de juros) → incluir em `datafeed.Fundamentals`,
  no mapeamento de colunas e no bloco de score correspondente.
- Enviar só quando houver ao menos 1 papel com oportunidade gráfica → guardar em
  `screener.run()` antes de chamar o e-mail (checar `oportunidade_grafica != 'Não'`).

**Tabela de indicadores (por seção).** Abaixo de cada lista, uma tabela **Indicadores fundamentalistas** por papel: P/L, P/VP, PEG, EV/EBITDA, Dív.Líq/EBITDA, Dív.Líq/PL, ROE e ROIC. Cada valor é **colorido vs. a mediana do setor** no universo do dia (verde = melhor; vermelho = pior). Setores com poucos papéis têm mediana menos robusta; financeiras não têm alguns indicadores (—).

**Teto projetivo (à la Hannah).** 6º método: LPA×(1+crescimento)×**payout médio** ÷ DY-alvo. O payout médio é a média de (dividendo anual ÷ LPA anual) dos últimos anos (yfinance, best-effort; fallback: payout do yfinance ou implícito). DY-alvo fixo em `--teto-proj-yield` (default 6%). LPA real do yfinance ou preço/PL. Coluna própria (Projet.) e entra no consolidado (média/mediana).

**Graham ajustado à Selic.** LPA × (8,5 + 2g) × 4,4 ÷ Selic — a fórmula de Graham com crescimento, sensível ao nível de juros (com Selic alta, o teto cai). g limitado a 15%. Coluna Grah.Selic. Não-financeiras.

**Múltiplo-alvo EV/EBITDA.** Preço a que a ação negociaria no EV/EBITDA-alvo (mediana do setor, limitada a 3–15×): preço × (alvo − DL/EBITDA) ÷ (EV/EBITDA − DL/EBITDA). Âncora de valuation relativo. Coluna Múlt.EV. Não-financeiras (dependem de EV/EBITDA e dívida líquida do yfinance).

**Padrões gráficos adicionais (candidatos).** Além de rompimento e pivô, o app detecta, de forma conservadora e só fora de tendência de baixa: **fundo duplo** (W, dois fundos parecidos + rompimento do pescoço), **fundo triplo** (três fundos + rompimento da resistência) e **bandeira de alta** (mastro forte + consolidação curta + rompimento). Só disparam quando o padrão **se confirma** (rompe o nível), e vêm rotulados como 'candidato' — detecção automática de padrão tem erro; trate como ponto de partida, não sinal definitivo. Desligue com `detect_patterns=False`.
