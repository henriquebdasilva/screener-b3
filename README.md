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
