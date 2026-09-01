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

**Padrões gráficos adicionais (candidatos).** Além de rompimento e pivô: **fundo duplo** e **fundo triplo** — tratados como **reversão**: exigem tendência de BAIXA antes do padrão (MM21) + queda ≥20% de um topo prévio até os fundos, fundos alinhados (≤2% entre si), pescoço ≥8% acima e rompimento confirmado. E **bandeira de alta** (mastro forte + consolidação inclinada p/ baixo + rompimento da linha de resistência). Vêm rotulados como 'candidato'; detecção automática de padrão tem erro — trate como ponto de partida. Desligue com `detect_patterns=False`.

**Tabela Preço & risco (por seção).** Abaixo dos indicadores: mínima e máxima de 1 ano (R$), distância da mínima de 52 semanas, posição vs média de 100 dias (+ acima / − abaixo), beta e correlação com o Ibovespa (retornos diários ~1 ano, vs ^BVSP). O P/L futuro (forward P/E do yfinance) entra na tabela de indicadores, colorido vs mediana do setor.

**Guarda de tamanho do e-mail (anti-clipping do Gmail).** O Gmail corta e-mails acima de ~102 KB. O relatório se ajusta: se passar de ~100 KB, corta na ordem agenda → trunca teses → preço & risco → **preços-teto** → indicadores. A **tabela de fundamentos é a ÚLTIMA a cair** (o teto é sacrificado antes, pois está na planilha anexa). A seção Defensivas mostra só a tabela principal. Uma nota indica o que foi omitido; tudo permanece na planilha.

**Novas métricas de balanço (tabela de fundamentos).** Liquidez corrente (Liq.corr), liquidez geral (Liq.ger, best-effort), grau de endividamento (Endiv = Passivo/Ativo), independência financeira (Indep = PL/Ativo) e retorno sobre ativos (ROA). Dependem do balanço do yfinance (uma chamada a mais por papel; desligue com env BALANCE=0) — cobertura irregular na B3, então podem vir (—).

**Tendências de 5 anos na avaliação.** A consistência agora inclui flags de EBITDA, margem líquida e ROE **crescentes** nos últimos anos (best-effort, do histórico do yfinance). ROIC crescente é incluído só quando há dados (raro). Um papel com esses indicadores melhorando ano a ano ganha pontos de consistência.

**Panorama macro + Índice de Regime Brasil (topo do e-mail).** Um painel compacto no início do relatório resume juros (Selic + Focus), inflação (IPCA 12m + Focus), câmbio (USD/BRL + Focus), setor externo (balança comercial e transações correntes 12m) e fiscal (DBGG) — cada linha com data-base e fonte (BCB SGS, Boletim Focus e yfinance). O **Índice de Regime Brasil (0-100)** agrega esses componentes com pesos renormalizados (exclui fluxo estrangeiro e valuation do Ibov, sem fonte automática confiável). É heurístico, não previsão. Um **relatório macro** mais completo (macro_AAAA-MM-DD.html) é gerado e anexado. Desligue tudo com env MACRO=0. As APIs oficiais rodam no ambiente do usuário; em falha, cada item vira n/d (nada é estimado).

**Fluxo estrangeiro (B3, best-effort scraping).** `fluxo.py` tenta baixar o arquivo de participação de investidores da B3 e extrair o saldo do estrangeiro (dia/mês/ano), em qualquer formato (CSV/XLSX/JSON), procurando a linha 'Estrangeiro/Não Residente'. A B3 não tem API estável para isso e o formato muda — então é frágil: configure a URL correta em `FLUXO_URL`, depure com `FLUXO_DEBUG=1`, desligue com `FLUXO=0`. Aparece no painel macro (verde/vermelho por sinal) quando disponível; senão, n/d. Ainda NÃO entra no Índice de Regime (fica como informação até validarmos a fonte).

**Relatório em PDF anexo (resolve o limite do Gmail).** Por padrão, o relatório COMPLETO (todas as tabelas, todos os papéis, preços-teto e teses — sem cortes) é gerado como PDF landscape (`relatorio_AAAA-MM-DD.pdf`, via xhtml2pdf) e anexado. O **corpo do e-mail vira um resumo curto** (painel macro + regime + destaques + aviso de anexos), que nunca é cortado. Desligue o PDF com env `EMAIL_PDF=0` (aí volta ao relatório no corpo, com o guarda de tamanho). Requer `xhtml2pdf` no requirements (pip; não precisa de libs de sistema).

**Cortes duros de margem líquida e ROE.** Por padrão, o screener agora reprova (corte duro, antes do percentil): não-financeiras com **margem líquida < 8%** (`--min-margin`, 0 desliga; não se aplica a bancos/seguros) e qualquer papel com **ROE médio de 5 anos < 10%** (`--min-roe`, 0 desliga; vale para todos os setores). O corte usa o **ROE médio dos últimos anos** (>=2 anos de histórico) para não reprovar uma boa empresa por um único ano fraco — ex.: elétricas reguladas; onde não há histórico, cai no ROE atual. Dado ausente não reprova sozinho. Coluna `roe_medio` na planilha. Colunas `margem_ok`/`roe_ok` na planilha.

**Corte de dívida sensível ao setor (defensivos/regulados).** Setores defensivos com baixa ciclicidade (≤ `--defensive-lev-cyc`, default 0.2 — utilities, elétricas, saneamento) ganham um limite de dívida MAIOR nos cortes de alavancagem (Dív.Líq/EBITDA) e Dív.Líq/Patrimônio: limite × `--defensive-lev-mult` (default 1.8). Racional: dívida dessas empresas é lastreada em fluxo de caixa estável/regulado. Assim, elétricas como EGIE3/ISAE4 podem passar na seleção (e entrar nas Defensivas) sem afrouxar o corte para setores cíclicos. `--defensive-lev-mult 1.0` desliga a folga.

**Safety cruza ROIC com dívida líquida.** O componente de alavancagem do Safety agora usa a **alavancagem ajustada pelo retorno**: DL/EBITDA ÷ (ROIC/Selic), limitada entre 0,4× e 2,5×. Quando o ROIC supera o custo de capital (Selic), a dívida pesa menos na nota; quando fica abaixo, pesa mais — refletindo que dívida só é boa se o capital rende acima do custo. Substitui o DL/EBITDA cru (sem dupla contagem) e cai no cru quando falta ROIC. Coluna `lev_roic_adj` na planilha. NÃO altera os cortes duros (só o score).

**Ajuste setorial para regulados (resultado regulatório/VNR).** Elétricas, saneamento e utilities (ciclicidade ≤ 0.2) têm o lucro CONTÁBIL distorcido pelo resultado regulatório (IFRIC 12/VNR). Para esses setores, o scoring: (a) usa o **ROE médio de 5 anos** no lugar do ROE atual dentro do bloco Quality; (b) reponticera Quality e Value (~60/40) a favor de métricas de **EBITDA/caixa** (ROIC, EV/EBITDA) e contra as de **lucro contábil** (ROE, P/L, PEG). Ajuste moderado. NÃO altera os cortes duros nem os preços-teto. Coluna `regulado` (True/False) na planilha. Setores cíclicos seguem com média simples.

**Options ratio (Put/Call) via COTAHIST + barras gráficas do humor.** Novo módulo `opcoes.py` baixa o COTAHIST diário oficial da B3 (arquivo público, com fallback de pregões) e calcula a razão **Put/Call por volume** em três níveis: por ativo, por setor e do mercado (TPMERC 070=call, 080=put). P/C > 1 = mais puts (viés defensivo/baixista); < 1 = mais calls (altista). No relatório: um **termômetro de opções** do mercado, a coluna **P/C por setor** no Humor do mercado, e **P/C por papel** na tabela Preço & risco. O Humor do mercado agora mostra o %alta/lateral/baixa como **barra empilhada colorida** (verde/cinza/vermelho). Best-effort: a busca do COTAHIST valida no runtime (não no sandbox); desligue com env `OPCOES=0`.

**Open interest de opções (posições em aberto, fonte oficial B3).** Novo módulo `posicoes.py` calcula a razão Put/Call por VOLUME (giro do dia, via COTAHIST) E por POSIÇÕES EM ABERTO (open interest, mais estrutural). O arquivo oficial é 'Posições em Aberto em Derivativos (Listado)' (B3, Boletim Diário, público, ~10 dias). A URL diária é dinâmica: configure em env `OI_URL` (desligue com `OI=0`). O parser é flexível (acha as colunas pelo nome) e classifica call/put pela letra de série do código (A–L call, M–X put), casando a opção ao ativo-base pela raiz e EXCLUINDO ações à vista. No relatório: colunas 'P/C vol.' e 'P/C posições' no Humor do mercado + termômetro do mercado com as duas medidas. Nota: aluguel de ações (BTC) — mesmo canal da B3 — fica para a próxima rodada.

**Open interest REAL via BDI de derivativos (PDF oficial B3).** O `posicoes.py` agora baixa o PDF 'Derivativos de bolsa' (BDI_03-4) do BDI novo (`arquivos.b3.com.br/bdi/download/bdi/AAAA-MM-DD/BDI_03-4_AAAAMMDD.pdf`, com fallback de pregões) e extrai, da tabela 'Quadro Analítico das Posições em Aberto', o open interest das OPÇÕES SOBRE AÇÕES: usa a coluna 'Ativo' (ativo-base), 'Segmento' (EQUITY CALL/PUT) e 'Total de posições'. Parser por coordenadas (PyMuPDF), testado no PDF real (~43 mil séries). Envs: OI=0 desliga; OI_CAPITULO troca o capítulo; OI_URL força uma URL. O aluguel de ativos (BDI_04-2) é o próximo. Requer pymupdf (já no requirements).

**Aluguel de ações (pressão vendedora) via BDI oficial B3.** O `posicoes.py` agora também baixa o PDF 'Empréstimos de ativos' (BDI_04-2) e extrai, da tabela 'Posições em aberto', o 'Saldo em quantidade do ativo' (ações em aberto no empréstimo = proxy de posição vendida) e o saldo em R$, por ativo (linha 'Total'). No relatório, a tabela Preço & risco ganha a coluna 'Aluguel' = % das ações em circulação (market cap ÷ preço) em posição de aluguel: ≥5% pressão alta (vermelho), 2–5% moderada (âmbar). Parser por coordenadas, testado no PDF real (~1.043 ativos). Envs: ALUGUEL=0 desliga; ALUGUEL_CAPITULO/ALUGUEL_URL configuram a fonte. Com isso, a pressão vendedora tem duas óticas: open interest de puts + ações efetivamente alugadas.

**Destaques de opção por papel (strike + tipo).** Na tabela Preço & risco, cada papel selecionado mostra duas opções-destaque: 'Maior OI' (a opção com maior posição em aberto — tipo, strike e OI; via BDI de derivativos) e 'Mais neg.' (a mais negociada em volume — tipo, strike, volume R$ e nº de negócios; via COTAHIST). O strike vem LIMPO do COTAHIST (campo explícito) cruzado pelo código; quando a série não está no COTAHIST, estima-se do código (menos preciso). CALL em verde, PUT em vermelho.

**Filtro de atualidade nos padrões de fundo (duplo/triplo).** Antes, um fundo duplo/triplo continuava sendo sinalizado enquanto o preço estivesse acima do pescoço — mesmo que o rompimento tivesse ocorrido há meses e o papel já estivesse esticado e lateral perto da máxima (ex.: CMIN3). Agora o padrão só é marcado se o rompimento do pescoço for RECENTE (≤ `max_bars_since`, default 20 pregões) E o preço não estiver ESTICADO (≤ `max_ext` acima do pescoço, default 10%). Assim o sinal reflete um setup atual e acionável, não um movimento que já aconteceu.

**Frescor + extensão padronizados em todos os sinais gráficos.** Além do fundo duplo/triplo, agora o ROMPIMENTO, o PIVÔ e a BANDEIRA de alta também só disparam quando o sinal é atual e não-esticado: rompimento ganhou teto de extensão explícito (`--breakout-max-ext`, default 8%%); pivô idem (`--pivot-max-ext`, default 6%%); bandeira exige rompimento recente da linha superior (fechamento anterior ainda na linha) e não esticado (`--pattern-max-ext`, default 10%% acima da linha/mastro). Rompimento e pivô já eram frescos por construção (sinal do dia); a novidade é o controle de extensão. Evita 'perseguir' movimentos que já aconteceram.

**Bandeira com janela flexível (mínimo de pregões).** A consolidação da bandeira agora é flexível: testa de `--flag-min-dias` (default 7) a 15 pregões e aceita a bandeira válida mais curta/recente (antes era fixa em 15). A nota do sinal passa a informar a duração da bandeira (ex.: 'bandeira 7d'). Frescor e extensão continuam valendo.

**Bandeira: mastro mínimo 12%% e recuo mínimo 8%%.** O mastro mínimo caiu de 18%% para **12%%** (`--flag-pole-min`, default 0.12) e a bandeira passou a exigir um recuo MÍNIMO de **5%%** do mastro (`--flag-min-retrace`, default 0.05) — além do teto de 45%% já existente. Assim entram bandeiras com mastro mais modesto, mas exige-se um recuo real (nem raso demais, nem fundo demais). Faixa de recuo válida agora: 5%%–45%% do mastro.

**Fração superior por segmento (ajustável).** A seleção fundamentalista agora usa uma fração superior por segmento, em vez de uma única: blue chips/BOVA11 `--q-bluechip` (default 0.60), small caps/SMALL11 `--q-smallcap` (default 0.50) e um pool DEFENSIVO (baixa ciclicidade ≤ defensive_max_cyc) `--q-defensive` (default 0.70, mais permissivo). Cada papel é aprovado se passa no corte do seu grupo OU (se defensivo) no corte defensivo mais brando. `--group-top` continua forçando a mesma fração em tudo (retrocompatível).

**Pivô mais exigente: recuo ao suporte em tendência de alta.** O pivô de alta agora só é sinalizado quando (a) a tendência é de ALTA ESTRUTURAL (preço > MM200 e MM50 > MM200) e (b) o fechamento está na PARTE INFERIOR da consolidação (≤ `--pivot-lower-frac` da faixa a partir do fundo; default 0.5 = metade inferior). Ou seja: um recuo ao suporte, dentro de uma alta de fundo, que vira para cima — não mais um pivô no meio/topo do range. Mantém o teto de extensão (`--pivot-max-ext`). Use `--pivot-lower-frac 0.33` para exigir o terço inferior.

**Tendência com MM21 + MM30.** A classificação de tendência (Em Alta/Lateral/Em Baixa) agora usa DUAS médias móveis: a curta (MM21) e a longa (MM30, ajustável por `--trend-ma-long`). Em Alta exige as DUAS médias subindo E o preço acima da MM longa; Em Baixa, as duas caindo E preço abaixo; Lateral nos demais casos. Exigir a concordância dos dois horizontes reduz falsos sinais de tendência (antes só a MM21 decidia).

**Defensivas: apenas blue chips (BOVA11).** O pool defensivo de 70% e a seção 'Defensivas' passam a considerar SÓ papéis do BOVA11. Small caps de setores defensivos seguem sendo avaliadas normalmente pelo corte do SMALL11 (50%), mas não ganham a folga de 70% nem aparecem na seção Defensivas — que agora é um recorte de blue chips não-cíclicas.

**Fundo duplo/triplo: separação máxima entre fundos.** Além da separação mínima, os fundos agora têm uma separação MÁXIMA (`--pattern-max-sep`, default 45 pregões). Isso evita o falso positivo em que o detector casava dois vales distantes (ex.: 59 pregões, ~3 meses) numa tendência de alta — que não formam um 'W' de verdade. Foi a causa do FLRY3 aparecer como fundo duplo. Diagnóstico via env PATTERN_DEBUG=<TICKER> imprime, no log, os fundos, o pescoço, a separação, o frescor, a extensão e o contexto de reversão de cada candidato.

**Sinais mais 'colados' no nível rompido (4%).** Os limites de extensão dos sinais de entrada foram apertados para no máximo 4% acima do respectivo nível rompido: rompimento `--breakout-max-ext` 0.04, pivô `--pivot-max-ext` 0.04, e bandeira ganhou limite próprio `--flag-max-ext` 0.04. Assim só entram sinais em que o preço ainda está perto do nível rompido (topo/linha/consolidação), evitando perseguir movimentos já esticados. Fundos duplo/triplo (reversão) seguem em 10% (`--pattern-max-ext`).

**Pivô: janela adaptativa + metade inferior (0.5).** O `--pivot-lower-frac` é **0.5** (metade inferior) — o pivô é aceito enquanto o fechamento estiver até 75%% da consolidação, medindo do fundo. Isso captura papéis que consolidam na parte de cima da faixa dentro de uma alta (ex.: FLRY3), sem voltar a aceitar pivô colado no topo. Continua exigindo tendência de alta estrutural e o teto de extensão de 4%%.

**Pivô com janela adaptativa.** A posição do preço na consolidação passou a ser medida numa janela ADAPTATIVA: o código procura a maior janela recente que seja uma pausa de verdade (amplitude ≤ `--pivot-range-pct`, default 5%%) em vez de usar uma janela fixa que misturava o rally com a pausa (isso fazia o preço aparecer sempre no topo da 'faixa'). Com a janela correta, o `--pivot-lower-frac` voltou a **0.5** (metade inferior), exigindo virada perto do suporte.

**Rompimento exige BASE ESTRUTURADA.** Amplitude pequena, sozinha, não distingue uma base real de uma subida lenta em linha reta ('drift') — as duas cabem no mesmo percentual. Agora o rompimento exige que a janela tenha sido TESTADA NAS DUAS BORDAS: o preço precisa alternar entre a região baixa (≤ `--base-edge-frac`, default 30%% da faixa) e a alta, com pelo menos `--base-min-toques` (default 2) transições. Um drift direcional é rejeitado mesmo com a amplitude dentro do limite. Desligue com `--no-base-structure`. Recomenda-se também baixar `--breakout-consol-pct` de 12 para ~8 (bases mais estreitas).

**Fundo duplo tem que SER a virada.** Um W é o momento em que a tendência vira; se o papel já estava em alta, a reversão é antiga e o padrão é histórico (caso SANB11). Agora, além do contexto de baixa antes do padrão, exige-se que **no 2º fundo** a tendência ainda não fosse 'Em Alta' (desligue com `--no-pattern-virada`). O frescor também apertou: rompimento do pescoço em até **10 pregões** (era 20) e extensão máx. **5%** (era 10%), alinhado com os demais sinais.

**Layout do PDF/e-mail redesenhado.** Compatível com o xhtml2pdf (sem flexbox/grid/SVG, tudo via tabelas + cores de fundo): (1) **faixas coloridas** de título em cada seção (BOVA11/SMALL11/Defensivas/Wishlist/Carteira/Humor do mercado), substituindo o texto simples anterior; (2) **cartões de KPI** (papéis, score médio, com sinal gráfico, upside mediano) no topo do relatório e no início de cada grupo; (3) **scores como badges coloridos** (verde escuro=ótimo → vermelho=fraco) em vez de números soltos, na tabela principal. Objetivo: escanear o relatório mais rápido, com as informações-chave saltando aos olhos.

**IFIX, fluxo estrangeiro e opções mais negociadas via BDI.** Novo módulo `bdi_indices.py`: IFIX (fechamento + variações dia/mês/ano) via o capítulo 02 do BDI (fonte oficial). Fluxo estrangeiro: o BDI só publica o ACUMULADO DO MÊS — o valor do DIA é calculado pela diferença com o cache do dia anterior (`reports/.fluxo_cache.json`); sem cache (1º dia do mês/1ª execução) mostra só o acumulado. `fluxo.py` foi reescrito para usar essa fonte real (antes era placeholder). Opções mais negociadas: ranking geral do dia via COTAHIST (já baixado para o P/C ratio), exposto no Resumo de mercado.

**P/C vol. e P/C posições agora também por ÍNDICE.** `put_call_ratios`/`oi_ratios` agregam por grupo (BOVA11/SMALL11), não só por setor — aparece nas linhas de índice do Humor do mercado, com destaque visual (fundo azul claro).

**Humor do mercado redesenhado:** badges coloridos para os P/C ratios (fundo verde/vermelho/cinza, igual aos scores), barras de tendência maiores e mais legíveis, termômetro em cartões de KPI.

**Coluna Tendência colorida:** ▲ Em Alta (verde), ▼ Em Baixa (vermelho), ▬ Lateral (cinza) em toda tabela principal.

**Bug do painel macro corrigido:** tabela Focus/Data-base sobrepunha texto (limitação do xhtml2pdf com colunas estreitas); layout consolidado em 2 colunas resolve.

**IFIX/fluxo estrangeiro: parser por coordenadas (corrige 'layout não reconhecido').** O BDI_02 tem layout de 3 colunas lado a lado (ex.: IBOVESPA | IBRX50 | IBRX100), e o texto corrido (`get_text()` simples) pode intercalar essas colunas — quebrando a regex original. Agora IFIX e fluxo estrangeiro são extraídos por COORDENADAS de palavra (mesma técnica de posicoes.py/opcoes.py), com o texto corrido como fallback. Ative `BDI_DEBUG=1` para logar um trecho do texto ao redor da palavra-chave se ainda falhar.

**Nota sobre os '***' nos logs:** não é redação nossa — é o GitHub Actions mascarando automaticamente qualquer trecho de log que bata com o valor de um Secret. Se algum Secret (ex. INSIDER_CHECK/BASILEIA_DEBUG) estiver com o valor literal `on`, o GitHub substitui TODA ocorrência de "on" em QUALQUER lugar do log por ***, corrompendo palavras como 'zona'→'z***a', 'reconhecido'→'rec***hecido'. Troque esse Secret para `true`/`1` para limpar os logs.

**Fundo duplo/triplo recalibrado (caso CYRE3).** Diagnóstico com dados reais mostrou um padrão legítimo ficando de fora por margens pequenas em TRÊS filtros ao mesmo tempo: separação (48 pregões vs. limite 45), zona de fundo (3,4% vs. limite 3%) e um terceiro que não estava exposto — o alinhamento entre os fundos (`tol`, 3,4% vs. limite 2%, reprovava silenciosamente antes mesmo da checagem de zona). Ajustes: `max_sep` 45→60 pregões (~3 meses, cobre bases formadas ao longo de mais tempo), `pattern_low_zone` 3%→4,5%, `tol` (alinhamento) 2%→4% — todos ainda disciplinados, mas cobrindo fundos 'largos' comuns em ações reais. Importante: se o preço romper o pescoço e depois RECUAR de volta para baixo dele, o padrão não confirma até fechar acima de novo — isso é intencional (rompimento devolvido é sinal fraco).

**Candidato pré-confirmação + virada de tendência.** Dois sinais informativos novos, visíveis mesmo quando não há rompimento/pivô/padrão confirmado:
- **Candidato pré-confirmação**: quando um fundo duplo/triplo é estruturalmente válido (fundos alinhados, na zona, separação ok, contexto de reversão) mas o preço ainda não fechou acima do pescoço (ou rompeu e devolveu), aparece como 'Fundo duplo (quase)' com a distância exata até o pescoço. NÃO conta como sinal confirmado (`oportunidade_grafica` continua 'Não'), é só informativo — colunas `candidato_padrao`/`candidato_nota` no CSV.
- **Virada de tendência**: quando a tendência (MM21+MM30) vira de 'Em Baixa' para 'Em Alta' EXATAMENTE no último pregão, aparece o badge 'Virada p/ Alta'. Nota: como exige as duas médias concordando, a virada costuma passar por 'Lateral' no meio — um salto direto Baixa→Alta é raro por desenho (reflete uma reversão robusta, não um dia isolado). Coluna `virada_alta` no CSV.

**Badge de candidato mais distinto visualmente.** 'Fundo duplo (quase)' e 'Virada p/ Alta' agora usam um estilo próprio (itálico, cinza, borda tracejada) em vez das cores sólidas de sinal confirmado — evita confundir 'Não + candidato' com um sinal real numa leitura rápida da tabela.

**Bandeira agora tem debug + vira candidato pré-confirmação.** Antes, `detect_bull_flag` não recebia `PATTERN_DEBUG` nem rastreava candidato — por isso, quando havia mastro+consolidação perto do topo (padrão de bandeira), o sistema só mostrava 'Fundo duplo (quase)' se esse também fosse estruturalmente válido, mesmo que a bandeira fosse o padrão mais relevante no momento (caso SANB11). Agora: (1) a bandeira loga diagnóstico completo por tentativa de janela; (2) quando há mais de um candidato possível (fundo duplo/triplo/bandeira), o sistema escolhe o MAIS PRÓXIMO de confirmar (menor distância ao gatilho), não uma prioridade fixa entre os tipos.

**Mastro da bandeira agora é adaptativo (resolve o caso CMIN3).** O `pole_win` era fixo em 20 pregões, e — como ele desliza junto com o `flag_len` — para ralis longos (ex.: CMIN3, +48%% ao longo de 35+ pregões) a janela capturava só pedaços inconsistentes: ora 'mastro fraco demais', ora 'recuo grande demais', nunca o rali inteiro. Agora, para cada bandeira candidata, testamos o mastro em várias extensões (20 a 50 pregões, `pole_win_max`) e usamos a MAIOR janela que validar — capturando o rali completo antes da consolidação. Resultado: CMIN3 passa de 'Fundo duplo (quase)' para 'Bandeira de alta (quase)', a poucos décimos % do pescoço.

**Correção de escala na inclinação da bandeira (2ª parte do CMIN3).** O check de 'consolidação achatada' comparava a inclinação POR DIA direto com a amplitude TOTAL da janela — um erro de escala que ficava mais rígido em janelas curtas e mais permissivo em longas, de forma inconsistente, e rejeitava toda consolidação com leve viés de alta (comum em 'high tight flags' dentro de ralis fortes). Agora comparamos o DRIFT TOTAL da janela (inclinação × nº de dias) contra a amplitude, tolerando até 40%% — a consolidação pode subir um pouco, desde que não consuma a maior parte do range. Debug agora mostra o valor do drift (%%) em cada rejeição.

**Estatísticas anuais por papel (nova tabela).** Cada papel selecionado ganha uma tabela 'Estatísticas do ano': (1) **Retorno no ano** (YTD) e **vs Ibov (ano)** — desempenho relativo ao índice, em pontos percentuais; (2) **Drawdown máximo** — maior queda pico→vale nos últimos ~12 meses; (3) **Volatilidade anualizada** — desvio-padrão dos retornos diários × √252; (4) **Mediana do preço (1a)** — referência menos sensível a picos/mínimas que a média; (5) **Correlação com o dólar** (USD/BRL) — positiva sugere exportadora/commodity, negativa sugere consumo doméstico/importadora. Fontes: yfinance (preço da ação, Ibovespa ^BVSP, USD/BRL 'BRL=X'). Tudo com fallback gracioso (n/d) em falha de dados.

**Ajustes na tabela de estatísticas + IFIX corrigido.** (1) Preço atual agora também aparece na tabela 'Estatísticas do ano'; (2) Volatilidade mostra o símbolo %%; (3) Corr. Ibov saiu de 'Preço & risco' e foi para 'Estatísticas do ano', ao lado de Corr. USD (evita duplicar e agrupa as duas correlações juntas). (4) **Bug do IFIX corrigido**: o yfinance usa o ticker `IFIX.SA` (como um papel comum), não `^IFIX` (como índice) — por isso o IFIX vinha sempre 'n/d' na seção Resumo de mercado (market.py). O Panorama macro (via BDI) já usava fonte própria e não era afetado.

**Preço médio + mín/máx do ano na tabela de estatísticas.** 'Média (1a)' agora aparece ao lado de 'Mediana (1a)'. Novas colunas 'Mín (ano)' e 'Máx (ano)' — mínima e máxima do PRÓPRIO ano corrente (1º de janeiro até hoje), diferente do Mín/Máx 52 semanas (janela móvel de 12 meses) que já existia em 'Preço & risco'. Esclarecimento sobre o drawdown: ele é medido sobre o PREÇO em si (maior queda do preço em relação ao pico mais recente até aquele ponto) — não usa média nem mediana como referência.

**IFIX no BDI: bug real corrigido (não achava se não fosse o 1º painel da linha).** O BDI mostra até 3 painéis de índice LADO A LADO na mesma linha (ex.: IBOVESPA | IFIX | IBRX50). O parser por coordenadas descartava a posição X de cada palavra e exigia que o nome do índice fosse a PRIMEIRA palavra da linha reconstruída — então só funcionava se o índice buscado por acaso fosse o painel mais à esquerda da sua fileira. Como o IFIX raramente é o primeiro (a ordem no BDI é IBOVESPA, IGCX, IBRX50... primeiro), a busca falhava sempre ('layout não reconhecido'). Agora a coordenada X é preservada, o nome do índice é buscado em QUALQUER posição da linha, e essa posição define a faixa de coluna usada para filtrar as linhas seguintes (Fechamento, %, etc.) — isolando corretamente os dados do IFIX mesmo dividindo linha com outros índices. Testado com um cenário sintético reproduzindo o layout real (IFIX como 2º painel).

**IFIX: causa real encontrada (formato numérico BR, não posição de coluna).** Baixei um BDI_02 real e atual (abril/2026) via busca e confirmei: os números usam formato BRASILEIRO — ponto como separador de MILHAR nos pontos do índice ('Fechamento 3.885' = 3885 pts) e VÍRGULA como decimal nos percentuais ('Do dia 0,22%'). O parser assumia o formato americano (invertido) e a regex do modo texto nem sequer aceitava vírgula na classe de caracteres — então a extração falhava sempre, independente da correção de coluna feita antes. Corrigido usando `_num_br` (conversão BR) em todo o parser do IFIX, com validação direta contra o texto REAL baixado (fechamento 3885 pts, dia +0,22%%, mês +0,39%%, ano +2,92%% — todos batendo).

**IFIX/fluxo: validado end-to-end contra PDF real do usuário (BDI_02_20260828.pdf).** Testei os parsers direto contra o arquivo real: IFIX fechamento 3740 pts (+0,59% dia, -2,04% mês, -0,92% ano) e fluxo estrangeiro (compras R$311,2mi, vendas R$329,9mi, saldo -R$18,7mi, base 26/08/2026) — todos batendo. Achei e corrigi mais um problema: a largura de coluna do modo por coordenadas (`largura_col`) estava em 200pt, mas a coluna real vai do rótulo até o valor alinhado à direita, ~265pt — cortava o próprio 'Fechamento' fora da faixa. Aumentado para 265. Agora os dois modos (coordenadas e texto corrido) funcionam de forma independente contra dados reais.

**Fluxo estrangeiro: bug de escala corrigido (R$ mil ≠ R$ milhões).** O relatório mostrava '-18.697.049 R$ mi' — um erro de 1000x. O cabeçalho REAL da tabela do BDI é 'Compras (R$) mil' (confirmado no PDF do usuário): o valor bruto já vem em MILHARES de reais, não em reais. O código pegava esse valor bruto e rotulava como 'R$ mi' (milhões) sem dividir por 1000. Corrigido: agora convertemos R$ mil → R$ milhões (÷1000) direto no parsing. Valor real do saldo do mês (28/08/2026): R$ -18.697 milhões = R$ -18,7 bilhões de saída líquida de estrangeiros — número plausível e agora exibido corretamente.

**IFIX duplicado no Resumo de mercado — corrigido.** O `market.py` (via yfinance, ticker IFIX.SA) e o `mailer.py` (via BDI, mais confiável) mostravam o IFIX cada um na sua própria linha — resultando em DUAS linhas de IFIX no Resumo de mercado, uma delas sempre 'n/d' (a do yfinance). Removido o IFIX do `INDEX_SYMS` do market.py; a linha única que sobra é a do BDI, que já estava funcionando corretamente.

**Gráfico de evolução: fluxo estrangeiro e OI Put/Call, últimos 7 BDIs.** Novo bloco 'Evolução — últimos N BDIs' no relatório: barras horizontais (a única técnica de barra confiável no xhtml2pdf — descoberto durante a implementação: uma tabela quebra internamente quando só ALGUMAS células têm width%% definida, ou quando uma barra chega a 100%% deixando a célula vizinha com width:0%%; corrigido isolando cada linha numa mini-tabela autônoma com larguras explícitas e limitando a barra a 96%%) mostrando o fluxo estrangeiro do dia (R$ mi) e o Put/Call de posições em aberto do mercado. Histórico mantido num cache rolante (`atualizar_historico_bdi`, `bdi_indices.py`) que preenche aos poucos a cada execução — 1 dia no 1º run, até 7 depois de uma semana. Idempotente: rodar de novo no mesmo dia sobrescreve, não duplica.

**Fallback de dia anterior no BDI:** já existia (bdi_indices.py, opcoes.py, posicoes.py tentam ~6 dias para trás automaticamente) — nenhuma mudança necessária.

**Bandeira: achatamento por R² (não mais drift/amplitude) — resolve faixas estreitas como CMIN3.** A métrica antiga (drift total ÷ amplitude > 40%%) é instável para faixas ESTREITAS: numa consolidação de só ~2%% de amplitude (caso real do CMIN3, R$5,88-R$6,01), qualquer ruído natural do preço já consome uma fração enorme dela — punindo exatamente as bandeiras mais 'limpas' e apertadas, que costumam ser as mais fortes. Trocado para R² do ajuste linear (quanto da variação é tendência vs. oscilação), que não depende da escala absoluta. Testado: alta reta sem consolidação continua rejeitada; faixa estreita/oscilante com leve alta (como o CMIN3 real) agora é aceita como candidata.

**Diagnóstico de persistência do cache (fluxo estrangeiro + histórico).** Se o 'dia disponível amanhã' aparecer TODOS os dias (não só uma vez) e/ou o gráfico de evolução nunca crescer, é sinal de que o cache não persiste entre execuções do GitHub Actions. Adicionado log explícito: 'cache LIDO de <caminho>' vs. 'cache NÃO EXISTE' (com dica para checar .gitignore/git add) e 'cache GRAVADO' com caminho absoluto e tamanho — para diagnosticar com certeza em vez de adivinhar. Gráfico de evolução agora mostra a partir de 1 dia (antes exigia 2), como feedback mais rápido de que está funcionando.

**BDI_02 (IFIX/fluxo): valida COMPLETUDE do arquivo, não só se baixou.** Os arquivos do BDI são publicados de forma progressiva — o do dia corrente pode existir e baixar normalmente (200 OK, tamanho razoável) mas ainda estar incompleto (só a parte administrativa inicial, sem a seção 'Evolução dos índices', publicada depois). Isso explicava o caso real observado: 1,15 MB baixados, mas só 6.257 caracteres de texto (o documento completo tem ~280 mil). Agora `_fetch_bdi02` verifica se o texto extraído tem um tamanho mínimo E contém o marco 'Evolução dos índices'; se não tiver, trata como indisponível e cai para o dia anterior — igual já fazia quando o download falhava de vez. Testado: arquivo de hoje incompleto é corretamente rejeitado, caindo pro dia anterior válido.

**Busca retroativa do histórico (fluxo estrangeiro + OI), janela configurável.** Nova função `preencher_historico_retroativo()` em bdi_indices.py: em vez de esperar `janela` execuções diárias para o gráfico de evolução encher naturalmente, busca direto nos BDIs dos últimos pregões (BDI_02 p/ fluxo, BDI_03-4 p/ OI). Só roda de verdade se o cache salvo tiver MENOS dias que a janela pedida — 'caso não tenha os dados salvos no git', como pedido; se já tiver o suficiente, não baixa nada. Janela configurável via `--historico-janela` (default 7). O fluxo estrangeiro do BDI é um ACUMULADO DO MÊS — buscamos janela+1 dias e calculamos os deltas nós mesmos; na VIRADA DO MÊS o delta daquele dia fica indisponível por definição (o acumulado reinicia, não há 'ontem' comparável no mesmo mês) — isso é uma limitação real dos dados da B3, não um bug. Testado: cálculo de deltas dentro do mês, comportamento na virada do mês, e robustez a falha de rede (não apaga o cache existente).

**Barras verticais + janela de 15 dias + rankings de opções (matplotlib).** Três melhorias no gráfico de evolução e nas opções:
- **Janela padrão 15 dias** (era 7) — `--historico-janela 15`, também usado pela busca retroativa.
- **Barras VERTICAIS de verdade**: trocamos o CSS/tabela (limitado no xhtml2pdf para barras em pé) por imagens geradas via `matplotlib` (novo módulo `charts.py`), embutidas como base64 — funciona igual no PDF e no e-mail. Corrigido no processo: `width:100%%` em `<img>` não funciona no xhtml2pdf (loga 'Not a float', corta a imagem) — usamos largura fixa em pixels; e `display:block` para os dois gráficos empilharem em vez de tentar ficar lado a lado.
- **Dois rankings novos de opções** ('Opções — rankings do dia'): Top 10 por volume financeiro (COTAHIST) e Top 10 por posições em aberto/open interest (BDI), em barras horizontais coloridas por CALL/PUT. Nova função `top_oi()` em posicoes.py (análoga ao `top_negociadas` de opcoes.py) + `resolver_strikes_lista()` para resolver o strike via COTAHIST. Requer `matplotlib` (adicionado ao requirements.txt).
