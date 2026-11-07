"""
glossario.py — Glossário pesquisável do Portal Bolsa (/glossario), para todos os membros (nível 1+).

Os termos estão na lista TERMOS abaixo: para acrescentar ou corrigir, basta editar aqui.
Cada termo: id (para links diretos, ex.: /glossario#rsi), termo, categoria, definição, e opcionalmente
    sinonimos  → outras palavras que também o encontram na pesquisa
    exemplo    → um exemplo concreto
    onde       → (texto, link) para a ferramenta do portal onde aparece
Se houver uma lição publicada na Escola cujo título fale do termo, aparece a ligação «Aprender na Escola».
"""

import re
import unicodedata

from flask import render_template_string, session

CATEGORIAS = [
    ("mercado", "📊 Mercado e produtos"),
    ("tecnica", "📈 Análise técnica"),
    ("risco", "🛡️ Risco e gestão"),
    ("fundamental", "🏢 Análise fundamental"),
    ("fiscal", "⚖️ Impostos e poupança (Portugal)"),
    ("macro", "🌍 Macro e dados oficiais"),
    ("portal", "🧭 Ferramentas do portal"),
]

T = "/interativo#tab-"
TERMOS = [
    # ---------------- MERCADO
    {"id": "acao", "termo": "Ação", "categoria": "mercado", "sinonimos": "título, share, stock",
     "definicao": "Uma pequena parte do capital de uma empresa. Quem tem ações é dono de uma fração da empresa: ganha se ela valorizar e pode receber dividendos, mas também perde se o preço cair."},
    {"id": "etf", "termo": "ETF", "categoria": "mercado", "sinonimos": "fundo cotado, exchange traded fund",
     "definicao": "Fundo que compra um cabaz de ativos (por exemplo, as 500 empresas do S&P 500) e que se compra e vende na bolsa como uma ação. Permite diversificar com uma só compra e costuma ter custos baixos.",
     "exemplo": "Um ETF do MSCI World investe em cerca de 1 400 empresas de 23 países desenvolvidos."},
    {"id": "acumulacao", "termo": "ETF de acumulação vs. distribuição", "categoria": "mercado", "sinonimos": "acc, dist, acumulação, distribuição",
     "definicao": "Um ETF de acumulação reinveste os dividendos dentro do fundo; um de distribuição paga-os ao investidor. Em Portugal, o de acumulação só paga imposto quando vendes, o que deixa o dinheiro render mais tempo.",
     "onde": ("Simulador de poupança", T + "oficial")},
    {"id": "indice", "termo": "Índice", "categoria": "mercado", "sinonimos": "S&P 500, PSI, Nasdaq, Stoxx, DAX",
     "definicao": "Um número que resume a evolução de um conjunto de ações. O S&P 500 junta as 500 maiores empresas americanas; o PSI, as maiores da bolsa de Lisboa. Não se compra diretamente: compra-se um ETF que o replica."},
    {"id": "capitalizacao", "termo": "Capitalização bolsista", "categoria": "mercado", "sinonimos": "market cap, valor em bolsa",
     "definicao": "Quanto vale a empresa na bolsa: preço da ação × número de ações. Serve para comparar o tamanho das empresas.",
     "exemplo": "Uma empresa com 1 000 milhões de ações a 50 € vale 50 mil milhões de euros em bolsa."},
    {"id": "volume", "termo": "Volume", "categoria": "mercado",
     "definicao": "Quantas ações mudaram de mãos num período. Um movimento de preço com volume alto é mais «credível» do que o mesmo movimento com pouco volume, porque mostra que muitos participantes concordaram com o preço."},
    {"id": "dividendo", "termo": "Dividendo", "categoria": "mercado", "sinonimos": "dividend yield, rendimento",
     "definicao": "Parte dos lucros que a empresa distribui aos acionistas. O dividend yield é o dividendo anual dividido pelo preço da ação.",
     "onde": ("Cofre fiscal · Dividendos", T + "cofre")},
    {"id": "ex-dividendo", "termo": "Data ex-dividendo", "categoria": "mercado", "sinonimos": "ex-date",
     "definicao": "A partir deste dia, quem compra a ação já não recebe o próximo dividendo. Nesse dia o preço costuma descer mais ou menos o valor do dividendo."},
    {"id": "spread", "termo": "Spread (compra/venda)", "categoria": "mercado", "sinonimos": "bid ask",
     "definicao": "A diferença entre o melhor preço de compra e o melhor preço de venda. Em ações pouco negociadas o spread é maior, e isso é um custo escondido de cada operação."},
    {"id": "ordem-limite", "termo": "Ordem limite vs. ordem ao mercado", "categoria": "mercado", "sinonimos": "limit order, market order",
     "definicao": "Uma ordem ao mercado executa já, ao preço que houver. Uma ordem limite só executa ao preço que escolheste (ou melhor). Em ativos com pouco volume, a ordem limite evita surpresas."},
    {"id": "bull-bear", "termo": "Bull market / Bear market", "categoria": "mercado", "sinonimos": "mercado em alta, mercado em baixa, touro, urso",
     "definicao": "Bull market é uma fase prolongada de subidas; bear market, uma queda de 20% ou mais face ao máximo anterior."},
    {"id": "correcao", "termo": "Correção", "categoria": "mercado",
     "definicao": "Uma queda de 10% a 20% face ao máximo recente. É normal e frequente: no mercado americano acontece, em média, a cada um ou dois anos."},
    {"id": "volatilidade", "termo": "Volatilidade", "categoria": "mercado",
     "definicao": "Quanto o preço oscila. Mede-se normalmente pelo desvio-padrão das variações e apresenta-se em % ao ano. Volatilidade alta = mais incerteza, para cima e para baixo."},
    {"id": "vix", "termo": "VIX", "categoria": "mercado", "sinonimos": "índice do medo",
     "definicao": "Mede a volatilidade que o mercado espera para o S&P 500 nos próximos 30 dias, a partir dos preços das opções. Abaixo de 15 é calma; acima de 25–30 é medo. Sobe quase sempre quando as ações caem.",
     "onde": ("Ações & ETFs · Market Breadth", T + "acoes")},
    {"id": "venda-descoberto", "termo": "Venda a descoberto", "categoria": "mercado", "sinonimos": "short, short selling, shortar",
     "definicao": "Vender ações que se pediram emprestadas, para as recomprar mais baratas depois. Ganha-se se o preço cair. O risco é, em teoria, ilimitado, porque o preço pode subir sem limite.",
     "onde": ("Posições curtas", T + "oficial")},
    {"id": "short-interest", "termo": "Short interest", "categoria": "mercado", "sinonimos": "posições curtas, dias para cobrir",
     "definicao": "Quantas ações estão vendidas a descoberto. «Dias para cobrir» = short interest ÷ volume médio diário: quantos dias de negociação seriam precisos para todos recomprarem.",
     "onde": ("Posições curtas", T + "oficial")},
    {"id": "short-squeeze", "termo": "Short squeeze", "categoria": "mercado",
     "definicao": "Subida rápida forçada pelos vendedores a descoberto que têm de recomprar para limitar perdas, o que empurra o preço ainda mais para cima."},
    {"id": "ftd", "termo": "Fails-to-deliver", "categoria": "mercado", "sinonimos": "FTD, falhas de entrega",
     "definicao": "Ações vendidas que não foram entregues ao comprador no prazo de liquidação. A SEC publica estes números; valores altos e persistentes podem indicar pressão de vendas a descoberto.",
     "onde": ("Dados oficiais · SEC", T + "oficial")},

    # ---------------- TÉCNICA
    {"id": "media-movel", "termo": "Média móvel (MM / SMA)", "categoria": "tecnica", "sinonimos": "SMA, média simples",
     "definicao": "A média dos preços de fecho dos últimos N dias, recalculada todos os dias. Suaviza o ruído e mostra a tendência: preço acima da média = tendência positiva."},
    {"id": "ema", "termo": "EMA (média móvel exponencial)", "categoria": "tecnica", "sinonimos": "EMA 20, EMA 50, exponencial",
     "definicao": "Média móvel que dá mais peso aos dias recentes, por isso reage mais depressa. A EMA 20 segue a tendência de curto prazo e a EMA 50 a de médio prazo.",
     "onde": ("Lista de vigia · Pullback", T + "radar")},
    {"id": "m200", "termo": "Média de 200 dias (M200)", "categoria": "tecnica", "sinonimos": "MM200, 200 dias, SMA 200",
     "definicao": "A média dos últimos 200 fechos (cerca de 10 meses). É a linha mais seguida para separar uma tendência de alta de longo prazo (preço acima) de uma de baixa (preço abaixo)."},
    {"id": "golden-cross", "termo": "Golden cross / Death cross", "categoria": "tecnica", "sinonimos": "cruzamento dourado, cruz da morte",
     "definicao": "Golden cross: a média de 50 dias cruza para cima da de 200 (sinal positivo). Death cross: cruza para baixo (sinal negativo). São sinais lentos: confirmam tendências, não as antecipam."},
    {"id": "rsi", "termo": "RSI (Índice de Força Relativa)", "categoria": "tecnica", "sinonimos": "relative strength index, sobrecompra, sobrevenda",
     "definicao": "Oscilador de 0 a 100 que compara a força das subidas com a das descidas nos últimos 14 períodos. Acima de 70 diz-se «sobrecomprado»; abaixo de 30, «sobrevendido». Em tendências fortes pode ficar muito tempo nesses extremos.",
     "onde": ("Lista de vigia · Capitulação", T + "radar")},
    {"id": "macd", "termo": "MACD", "categoria": "tecnica",
     "definicao": "Diferença entre duas médias exponenciais (12 e 26 períodos), comparada com a sua própria média de 9 (a linha de sinal). Quando o MACD cruza a linha de sinal para cima, o momento está a melhorar."},
    {"id": "bollinger", "termo": "Bandas de Bollinger", "categoria": "tecnica", "sinonimos": "BB, bollinger bands",
     "definicao": "Uma média de 20 dias com duas bandas a 2 desvios-padrão para cima e para baixo. O preço fica dentro das bandas a maior parte do tempo; bandas largas = volatilidade alta, estreitas = calma."},
    {"id": "squeeze", "termo": "Bollinger Squeeze", "categoria": "tecnica", "sinonimos": "compressão de volatilidade",
     "definicao": "Quando as Bandas de Bollinger estreitam muito, o mercado está calmo e a «acumular energia». Estas fases costumam terminar num movimento forte, mas o squeeze não diz em que direção.",
     "onde": ("Lista de vigia", T + "radar")},
    {"id": "adx", "termo": "ADX", "categoria": "tecnica", "sinonimos": "average directional index, força da tendência",
     "definicao": "Mede a força de uma tendência (não a direção), de 0 a 100. Abaixo de 20, o mercado anda de lado; acima de 25, há uma tendência clara."},
    {"id": "suporte-resistencia", "termo": "Suporte e resistência", "categoria": "tecnica",
     "definicao": "Suporte é um nível de preço onde as quedas costumam parar (há compradores); resistência, um nível onde as subidas costumam parar (há vendedores). Quando um é quebrado, muitas vezes troca de papel.",
     "onde": ("Sniper · Extrair Alvos", T + "acoes")},
    {"id": "pullback", "termo": "Pullback", "categoria": "tecnica", "sinonimos": "recuo",
     "definicao": "Um recuo temporário dentro de uma tendência de alta, por exemplo até à EMA 20. Muitos traders usam-no para entrar numa tendência a um preço melhor.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "breakout", "termo": "Breakout", "categoria": "tecnica", "sinonimos": "rompimento, quebra",
     "definicao": "Quando o preço ultrapassa uma resistência (ou cai abaixo de um suporte) que segurava há algum tempo. Com volume alto, o breakout é mais fiável.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "momentum", "termo": "Momentum", "categoria": "tecnica",
     "definicao": "A tendência de os ativos que subiram muito continuarem a subir no curto/médio prazo (e vice-versa). Mede-se, por exemplo, pela variação dos últimos 3, 6 ou 12 meses."},
    {"id": "stop-loss", "termo": "Stop loss", "categoria": "tecnica", "sinonimos": "stop, ordem de stop",
     "definicao": "Ordem para vender automaticamente se o preço cair até um nível definido, para limitar a perda. Deve ser decidido antes de entrar, não depois.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "trailing-stop", "termo": "Trailing stop", "categoria": "tecnica", "sinonimos": "stop móvel, chandelier stop",
     "definicao": "Um stop que sobe à medida que o preço sobe, e nunca desce. Por exemplo: o máximo das últimas 22 sessões menos 3× o ATR. Deixa o ganho correr e protege-o quando a subida acaba.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "atr", "termo": "ATR (oscilação média diária)", "categoria": "tecnica", "sinonimos": "average true range, amplitude média",
     "definicao": "Quanto um ativo oscila, em média, num dia (média de 14 sessões, contando também os saltos de abertura). Serve para pôr o stop fora do «ruído» normal: um stop a menos de 1 ATR é apanhado com facilidade.",
     "exemplo": "Uma ação a 50 € com ATR de 1,5 € oscila cerca de 3% por dia; um stop a 2× ATR ficaria em 47 €.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "fibonacci", "termo": "Fibonacci (recuos e extensões)", "categoria": "tecnica", "sinonimos": "retração, fibo, 61,8%, 38,2%",
     "definicao": "Níveis calculados a partir de um movimento de subida. Os recuos (38,2%, 50%, 61,8% da subida) são zonas onde as correções costumam parar; as extensões (127%, 161,8%) são alvos possíveis acima do máximo. Funcionam sobretudo porque muitos investidores os seguem.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "esticado", "termo": "Ativo esticado", "categoria": "tecnica", "sinonimos": "sobrecomprado, overextended",
     "definicao": "Quando o preço subiu muito em pouco tempo e se afastou das médias: RSI acima de 70 e, por exemplo, muitas sessões seguidas a subir ou o preço a mais de 2× ATR acima da EMA 20. Não é sinal de venda, mas o risco de uma correção brusca é maior.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "risco-retorno", "termo": "Rácio risco/retorno (R:R)", "categoria": "tecnica", "sinonimos": "risk reward, R/R",
     "definicao": "Quanto podes ganhar por cada euro que arriscas. Um R:R de 1:3 quer dizer que o alvo está três vezes mais longe do que o stop. Com R:R alto, podes errar mais vezes e ainda assim ganhar. «2R» é um alvo a duas vezes a distância do stop.",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "backtest", "termo": "Backtest", "categoria": "tecnica", "sinonimos": "teste histórico",
     "definicao": "Testar uma estratégia com dados do passado para ver como se teria comportado. Ajuda a descartar más ideias, mas um bom backtest não garante resultados futuros.",
     "onde": ("Sniper · Backtest 5A", T + "acoes")},

    # ---------------- RISCO
    {"id": "drawdown", "termo": "Drawdown (queda máxima)", "categoria": "risco", "sinonimos": "MDD, max drawdown",
     "definicao": "A maior queda desde um máximo até ao mínimo seguinte. Uma queda de 50% precisa de uma subida de 100% para recuperar: por isso controlar as quedas é tão importante como procurar ganhos.",
     "onde": ("Liga Mensal · Mercado & Risco", T + "liga")},
    {"id": "diversificacao", "termo": "Diversificação", "categoria": "risco",
     "definicao": "Espalhar o dinheiro por vários ativos, setores e países, para que um problema numa empresa não destrua a carteira. Só funciona se os ativos não caírem todos ao mesmo tempo (ver correlação)."},
    {"id": "correlacao", "termo": "Correlação", "categoria": "risco",
     "definicao": "Mede se dois ativos se movem juntos, de −1 (sempre ao contrário) a +1 (sempre iguais). Uma carteira de ações com correlação alta entre si está menos diversificada do que parece.",
     "onde": ("Risco & Stress", T + "risco")},
    {"id": "beta", "termo": "Beta", "categoria": "risco",
     "definicao": "Quanto uma ação tende a mexer quando o mercado mexe. Beta 1,5: se o S&P 500 cair 10%, a ação cai em média 15%. Beta abaixo de 1 = mais defensiva.",
     "onde": ("Risco & Stress", T + "risco")},
    {"id": "position-sizing", "termo": "Position sizing", "categoria": "risco", "sinonimos": "dimensão da posição, alocação",
     "definicao": "Decidir quanto investir em cada operação. Uma regra comum é não arriscar mais de 1–2% do capital em cada trade (a distância até ao stop × número de ações).",
     "onde": ("Stop e alvos", T + "stop")},
    {"id": "win-rate", "termo": "Win rate (taxa de acerto)", "categoria": "risco", "sinonimos": "percentagem de acerto",
     "definicao": "A percentagem de operações que deram lucro. Sozinha não diz nada: 40% de acerto pode ser ótimo se os ganhos forem muito maiores do que as perdas.",
     "onde": ("Diário de bordo", T + "diario")},
    {"id": "profit-factor", "termo": "Profit factor", "categoria": "risco",
     "definicao": "Soma de todos os ganhos ÷ soma de todas as perdas. Acima de 1 a estratégia ganhou dinheiro; acima de 1,5–2 é considerada robusta.",
     "onde": ("Diário de bordo", T + "diario")},
    {"id": "alfa", "termo": "Alfa", "categoria": "risco", "sinonimos": "alpha, pp vs S&P",
     "definicao": "Quanto uma carteira rendeu acima (ou abaixo) do mercado de referência no mesmo período. Na Liga mostra-se em pontos percentuais contra o S&P 500.",
     "onde": ("Liga Mensal", T + "liga")},
    {"id": "sharpe", "termo": "Rácio de Sharpe", "categoria": "risco", "sinonimos": "sharpe ratio",
     "definicao": "Retorno acima da taxa sem risco ÷ volatilidade. Mede quanto se ganhou por cada unidade de risco. Acima de 1 é bom; acima de 2, muito bom."},

    # ---------------- FUNDAMENTAL
    {"id": "eps", "termo": "EPS (lucro por ação)", "categoria": "fundamental", "sinonimos": "earnings per share, resultados",
     "definicao": "O lucro da empresa dividido pelo número de ações. É o número mais seguido nas apresentações de resultados, comparado com o que os analistas esperavam."},
    {"id": "pe", "termo": "P/E (PER)", "categoria": "fundamental", "sinonimos": "price earnings, múltiplo, P/E forward",
     "definicao": "Preço da ação ÷ lucro por ação: quantos anos de lucros atuais estás a pagar. O P/E forward usa os lucros esperados para os próximos 12 meses. Um P/E alto pode significar expectativas de crescimento ou ação cara."},
    {"id": "roe", "termo": "ROE (rendibilidade do capital próprio)", "categoria": "fundamental", "sinonimos": "return on equity",
     "definicao": "Lucro ÷ capital próprio. Mostra quão bem a empresa usa o dinheiro dos acionistas. Acima de 15% é geralmente bom, mas dívida alta também infla o ROE."},
    {"id": "margem", "termo": "Margem líquida", "categoria": "fundamental", "sinonimos": "margem de lucro",
     "definicao": "Lucro líquido ÷ vendas. Quanto fica de cada euro vendido depois de todos os custos e impostos."},
    {"id": "divida-capital", "termo": "Dívida / capital próprio", "categoria": "fundamental", "sinonimos": "debt to equity, D/E, alavancagem",
     "definicao": "Quanto a empresa deve por cada euro de capital próprio. Dívida alta torna a empresa mais vulnerável a juros altos e a crises."},
    {"id": "fcf", "termo": "Free cash flow", "categoria": "fundamental", "sinonimos": "FCF, fluxo de caixa livre",
     "definicao": "O dinheiro que sobra depois das despesas e dos investimentos necessários. É mais difícil de «maquilhar» do que o lucro contabilístico, e é dele que saem dividendos e recompras."},
    {"id": "fair-value", "termo": "Fair value (valor justo)", "categoria": "fundamental", "sinonimos": "valor intrínseco, DCF",
     "definicao": "Estimativa do que uma empresa vale com base nos lucros ou fluxos de caixa futuros. Depende muito das hipóteses: pequenas mudanças no crescimento ou na taxa de desconto mudam muito o resultado.",
     "onde": ("Fair Value Lab", T + "acoes")},
    {"id": "preco-alvo", "termo": "Preço-alvo dos analistas", "categoria": "fundamental", "sinonimos": "target price, consenso",
     "definicao": "O preço que os analistas dos bancos esperam para a ação daqui a cerca de 12 meses. É uma opinião, revista com frequência, e costuma seguir o preço em vez de o antecipar."},
    {"id": "recompra", "termo": "Recompra de ações próprias", "categoria": "fundamental", "sinonimos": "buyback, ações próprias",
     "definicao": "Quando a empresa compra as suas próprias ações em bolsa. Reduz o número de ações e aumenta o lucro por ação. Em Portugal são comunicadas à CMVM.",
     "onde": ("Comunicados CMVM", T + "oficial")},

    # ---------------- FISCAL
    {"id": "mais-valia", "termo": "Mais-valia / menos-valia", "categoria": "fiscal",
     "definicao": "A diferença entre o preço de venda e o de compra (incluindo comissões). Positiva é mais-valia (paga imposto); negativa é menos-valia (pode abater às mais-valias do mesmo ano).",
     "onde": ("Cofre fiscal", T + "cofre")},
    {"id": "taxa-28", "termo": "Taxa liberatória / autónoma de 28%", "categoria": "fiscal", "sinonimos": "28%, taxa especial",
     "definicao": "A taxa de IRS que se aplica, por regra, ao saldo das mais-valias de ações e aos juros e dividendos. Nos juros de depósitos e dividendos portugueses o banco já a retém na fonte.",
     "onde": ("Assistente IRS", T + "irs")},
    {"id": "englobamento", "termo": "Englobamento", "categoria": "fiscal",
     "definicao": "Opção de somar estes rendimentos aos restantes (salário, etc.) e pagar à tua taxa de IRS em vez dos 28%. Compensa quando a tua taxa média fica abaixo de 28%. Optando, também podes levar menos-valias para os 5 anos seguintes. Para quem está no último escalão, as mais-valias de ações detidas menos de 1 ano são obrigatoriamente englobadas.",
     "onde": ("Assistente IRS", T + "irs")},
    {"id": "fifo", "termo": "FIFO", "categoria": "fiscal", "sinonimos": "first in first out, primeiro a entrar primeiro a sair",
     "definicao": "Regra obrigatória em Portugal para saber que ações vendeste: as primeiras compradas são as primeiras vendidas. Determina o preço de compra usado no cálculo da mais-valia.",
     "onde": ("Cofre fiscal", T + "cofre")},
    {"id": "anexo-g", "termo": "Anexo G", "categoria": "fiscal",
     "definicao": "Anexo da declaração de IRS para mais-valias de ativos vendidos através de corretoras portuguesas (ou com intermediário em Portugal).",
     "onde": ("Assistente IRS · Cábula", T + "irs")},
    {"id": "anexo-j", "termo": "Anexo J", "categoria": "fiscal",
     "definicao": "Anexo para rendimentos obtidos no estrangeiro: mais-valias em corretoras estrangeiras (quadro 9), dividendos e juros (quadro 8), com o imposto já pago lá fora para evitar a dupla tributação.",
     "onde": ("Assistente IRS · Cábula", T + "irs")},
    {"id": "dupla-tributacao", "termo": "Dupla tributação internacional", "categoria": "fiscal", "sinonimos": "retenção na fonte, crédito de imposto",
     "definicao": "Um dividendo estrangeiro paga imposto no país de origem (ex.: 15% nos EUA com o formulário W-8BEN) e outra vez em Portugal. O imposto pago lá fora é descontado ao português, até ao limite previsto no acordo entre os dois países.",
     "onde": ("Cofre fiscal · Dividendos", T + "cofre")},
    {"id": "certificados-aforro", "termo": "Certificados de Aforro", "categoria": "fiscal", "sinonimos": "CA, série F, IGCP",
     "definicao": "Produto de poupança do Estado português, com capital garantido. Na Série F, a taxa base acompanha a Euribor a 3 meses (entre 0% e 2,5%) e há prémios de permanência a partir do 2.º ano.",
     "onde": ("Simulador de poupança", T + "oficial")},
    {"id": "juros-compostos", "termo": "Juros compostos", "categoria": "fiscal", "sinonimos": "juros sobre juros",
     "definicao": "Quando os juros ganhos passam a render juros também. No início a diferença é pequena; ao fim de 20–30 anos torna-se enorme. Por isso o tempo é o maior aliado de quem poupa.",
     "onde": ("Simulador de poupança", T + "oficial")},

    # ---------------- MACRO
    {"id": "inflacao", "termo": "Inflação", "categoria": "macro", "sinonimos": "IPC, IHPC, CPI, subida de preços",
     "definicao": "A subida generalizada dos preços. Mede-se pelo índice de preços no consumidor (IHPC na zona euro, CPI nos EUA). O BCE e a Fed procuram mantê-la perto de 2% ao ano.",
     "onde": ("Juros & dados oficiais", T + "oficial")},
    {"id": "taxa-bce", "termo": "Taxa de depósito do BCE", "categoria": "macro", "sinonimos": "DFR, juros do BCE, taxa diretora",
     "definicao": "A taxa que o BCE paga aos bancos pelo dinheiro que estes lá depositam. É a principal taxa de juro da zona euro e influencia a Euribor, os depósitos e o crédito à habitação.",
     "onde": ("Juros & dados oficiais", T + "oficial")},
    {"id": "euribor", "termo": "Euribor", "categoria": "macro",
     "definicao": "Taxa a que os bancos da zona euro emprestam dinheiro entre si (a 3, 6 ou 12 meses). É a base da maioria dos créditos à habitação com taxa variável em Portugal.",
     "onde": ("Juros & dados oficiais", T + "oficial")},
    {"id": "curva-juros", "termo": "Curva de juros", "categoria": "macro", "sinonimos": "yield curve, spread 10a-3m",
     "definicao": "Os juros da dívida do Estado para vários prazos. Normalmente os prazos longos pagam mais. Quando os juros a 3 meses ficam acima dos a 10 anos, a curva está «invertida», o que historicamente antecedeu muitas recessões nos EUA.",
     "onde": ("Curva de juros dos EUA", T + "oficial")},
    {"id": "recessao", "termo": "Recessão", "categoria": "macro",
     "definicao": "Queda da atividade económica durante vários meses. Uma regra prática é dois trimestres seguidos de queda do PIB. A Fed de Nova Iorque publica uma probabilidade de recessão a 12 meses baseada na curva de juros.",
     "onde": ("Curva de juros dos EUA", T + "oficial")},
    {"id": "cli-ocde", "termo": "Indicadores avançados da OCDE (CLI)", "categoria": "macro", "sinonimos": "CLI, ciclo económico",
     "definicao": "Indicador que procura antecipar viragens do ciclo económico 6 a 9 meses antes. Acima de 100 e a subir = expansão; abaixo de 100 e a descer = abrandamento.",
     "onde": ("Juros & dados oficiais", T + "oficial")},
    {"id": "sentimento", "termo": "Indicador de Sentimento Económico (ESI)", "categoria": "macro", "sinonimos": "confiança, consumidores, ESI",
     "definicao": "Inquérito mensal da Comissão Europeia a empresas e consumidores. A média histórica é 100: acima, o sentimento é melhor do que o habitual; perto de 90 ou menos costuma coincidir com abrandamentos.",
     "onde": ("Portugal em números", T + "oficial")},
    {"id": "ciss", "termo": "CISS (stress financeiro)", "categoria": "macro", "sinonimos": "stress sistémico",
     "definicao": "Índice do BCE que mede o stress no sistema financeiro (ações, obrigações, câmbios, bancos). Picos altos coincidiram com 2008, 2011–12 e março de 2020."},
    {"id": "cot", "termo": "Relatório COT (CFTC)", "categoria": "macro", "sinonimos": "commitments of traders, CFTC, especuladores",
     "definicao": "Relatório semanal americano que mostra como especuladores e empresas (comerciais) estão posicionados nos futuros. Posições extremas dos especuladores às vezes antecedem viragens.",
     "onde": ("Posicionamento CFTC", T + "oficial")},
    {"id": "13f", "termo": "13F", "categoria": "macro", "sinonimos": "carteiras institucionais, Berkshire",
     "definicao": "Relatório trimestral obrigatório nos EUA para gestores com mais de 100 milhões de dólares em ações. Mostra o que compraram e venderam, mas com até 45 dias de atraso.",
     "onde": ("Carteiras institucionais", T + "oficial")},
    {"id": "form-4", "termo": "Form 4 (insiders)", "categoria": "macro", "sinonimos": "insider, administradores, insider flow",
     "definicao": "Comunicação obrigatória à SEC quando um administrador ou grande acionista compra ou vende ações da própria empresa. Compras de insiders com dinheiro próprio costumam ser um sinal mais forte do que as vendas.",
     "onde": ("Dados oficiais · SEC", T + "oficial")},
    {"id": "8-k", "termo": "8-K", "categoria": "macro", "sinonimos": "comunicado SEC, evento relevante",
     "definicao": "Comunicado que as empresas americanas enviam à SEC quando acontece algo importante: resultados, aquisições, saída do CEO, etc."},
    {"id": "13d-13g", "termo": "13D / 13G", "categoria": "macro", "sinonimos": "participação de 5%",
     "definicao": "Comunicações à SEC de quem passa a ter mais de 5% de uma empresa americana. O 13D é para quem quer influenciar a gestão (ativistas); o 13G, para investidores passivos."},
    {"id": "participacao-qualificada", "termo": "Participação qualificada", "categoria": "macro", "sinonimos": "CMVM, dirigentes",
     "definicao": "Em Portugal, quem passa certos limiares de participação no capital de uma cotada tem de o comunicar à CMVM, e a informação fica pública. Os dirigentes comunicam também as suas compras e vendas.",
     "onde": ("Comunicados CMVM", T + "oficial")},

    # ---------------- PORTAL
    {"id": "rrg", "termo": "RRG (Rotação Setorial)", "categoria": "portal", "sinonimos": "relative rotation graph, quadrantes",
     "definicao": "Gráfico que mostra a força relativa de cada setor face ao mercado e se essa força está a ganhar ou perder ritmo. Os setores rodam pelos quadrantes Líder → Enfraquecer → Atrasado → Melhorar.",
     "onde": ("Radar Global", T + "radar")},
    {"id": "breadth", "termo": "Market breadth", "categoria": "portal", "sinonimos": "amplitude, saúde estrutural",
     "definicao": "Quantas ações ou setores participam numa subida. Um índice a subir com poucos setores acima das médias é uma subida frágil.",
     "onde": ("Ações & ETFs", T + "acoes")},
    {"id": "regime", "termo": "Regime de mercado", "categoria": "portal", "sinonimos": "tendência, lateral",
     "definicao": "Classificação do momento do mercado (tendência ou lateral, calma ou volátil), que muda a estratégia mais adequada: seguir a tendência ou comprar quedas.",
     "onde": ("Radar Global", T + "radar")},
    {"id": "tier", "termo": "Tier A / Tier B (newsletters)", "categoria": "portal", "sinonimos": "quarentena, blacklist",
     "definicao": "Nas newsletters Radar, as ações são separadas pelo algoritmo: Tier A são as que cumprem os critérios mais exigentes, Tier B as que estão perto, a quarentena as que perderam força e a blacklist as que estão fora."},
    {"id": "nevoeiro", "termo": "Nevoeiro (Liga)", "categoria": "portal",
     "definicao": "Durante a janela de inscrição da Liga Mensal, as carteiras dos outros membros ficam ocultas, para ninguém copiar. O nevoeiro levanta no dia a seguir ao fecho das inscrições.",
     "onde": ("Liga Mensal", T + "liga")},
]


def _normal(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _licoes_por_termo():
    """Liga cada termo à lição publicada da Escola cujo título o menciona (só lições já disponíveis)."""
    try:
        import escola
        dados = escola.carregar()
        hoje = escola.hoje()
        licoes = [l for l in dados["licoes"] if l.get("publicada")
                  and escola.data_licao(dados, l["semana"], l["dia"]) <= hoje]
    except Exception:
        return {}
    out = {}
    for t in TERMOS:
        chaves = [t["termo"].split("(")[0]] + [s for s in t.get("sinonimos", "").split(",") if len(s.strip()) >= 3]
        chaves = [f" {_normal(c).strip()} " for c in chaves if _normal(c).strip()]
        for l in licoes:
            titulo = f" {_normal(l.get('titulo'))} "
            if any(c in titulo for c in chaves):
                out[t["id"]] = {"titulo": l["titulo"], "semana": l["semana"]}
                break
    return out


PAGINA = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Glossário · Portal Bolsa</title>
<style>
  :root { --fundo:#0b0e14; --painel:#11161f; --painel-2:#161c27; --linha:#232b38; --texto:#e6edf3; --suave:#9aa6b8; --mudo:#6e7a8c; --laranja:#f28b24; --azul:#4da6ff; --verde:#3fbf8f; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fundo); color:var(--texto); font-family:Inter, "Segoe UI", Arial, sans-serif; font-size:15px; line-height:1.55; }
  header { position:sticky; top:0; z-index:5; background:rgba(11,14,20,.95); backdrop-filter:blur(6px); border-bottom:1px solid var(--linha); }
  .topo { max-width:980px; margin:0 auto; padding:12px 18px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .topo h1 { font-size:18px; margin:0; flex:1; }
  .topo a { color:var(--suave); text-decoration:none; font-size:13px; border:1px solid var(--linha); border-radius:999px; padding:6px 12px; }
  .topo a:hover { color:var(--texto); border-color:var(--mudo); }
  .busca { max-width:980px; margin:0 auto; padding:0 18px 12px; }
  .busca input { width:100%; padding:12px 14px; border-radius:10px; border:1px solid var(--linha); background:var(--painel); color:var(--texto); font-size:15px; outline:none; }
  .busca input:focus { border-color:var(--azul); }
  .chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
  @media (max-width:700px) { .chips { flex-wrap:nowrap; overflow-x:auto; padding-bottom:4px; scrollbar-width:none; } .chips::-webkit-scrollbar { display:none; } .chip { white-space:nowrap; } }
  .chip { background:transparent; border:1px solid var(--linha); color:var(--suave); border-radius:999px; padding:5px 11px; font-size:12.5px; cursor:pointer; font-family:inherit; }
  .chip.ativo { border-color:var(--laranja); color:var(--laranja); background:rgba(242,139,36,.08); }
  main { max-width:980px; margin:0 auto; padding:18px; }
  .intro { color:var(--suave); font-size:14px; margin:0 0 18px; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.5px; color:var(--mudo); margin:26px 0 10px; border-bottom:1px solid var(--linha); padding-bottom:6px; }
  .termo { background:var(--painel); border:1px solid var(--linha); border-radius:10px; padding:14px 16px; margin-bottom:10px; scroll-margin-top:150px; }
  .termo:target { border-color:var(--laranja); box-shadow:0 0 0 3px rgba(242,139,36,.15); }
  .termo h3 { margin:0 0 4px; font-size:16px; display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
  .termo h3 a.ancora { color:var(--mudo); font-size:12px; text-decoration:none; font-weight:normal; }
  .termo p { margin:4px 0; color:#cdd6e0; }
  .ex { color:var(--suave); font-size:13.5px; border-left:3px solid var(--linha); padding-left:10px; margin-top:6px; }
  .ligacoes { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
  .ligacoes a { font-size:12.5px; text-decoration:none; border-radius:999px; padding:4px 10px; border:1px solid var(--linha); }
  .lig-portal { color:var(--azul); } .lig-escola { color:var(--verde); }
  .vazio { color:var(--mudo); text-align:center; padding:40px 0; }
  .nota { color:var(--mudo); font-size:12px; margin-top:30px; text-align:center; }
  @media (max-width:600px) { body { font-size:14.5px; } .topo h1 { font-size:16px; } }
</style>
</head>
<body>
<header>
  <div class="topo">
    <h1>📖 Glossário</h1>
    <a href="/">Página inicial</a>
    <a href="/escola">🎓 Escola</a>
    {% if nivel >= 2 %}<a href="/interativo">Terminal</a>{% endif %}
  </div>
  <div class="busca">
    <input id="q" type="search" placeholder="Procura um termo: RSI, englobamento, short interest…" autocomplete="off">
    <div class="chips" id="chips"></div>
  </div>
</header>
<main>
  <p class="intro">{{ termos|length }} termos usados no portal, explicados de forma simples. Cada termo tem um link próprio (🔗) para partilhar no Discord.</p>
  <div id="lista"></div>
  <p class="nota">Conteúdo educativo. Não é recomendação de investimento nem aconselhamento fiscal.</p>
</main>
<script>
const TERMOS = {{ termos|tojson }};
const CATS = {{ categorias|tojson }};
const LICOES = {{ licoes|tojson }};
const NIVEL = {{ nivel }};
let cat = "";
const norm = t => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
document.getElementById("chips").innerHTML = `<button class="chip ativo" data-c="">Todos</button>` +
  CATS.map(([k, n]) => `<button class="chip" data-c="${k}">${esc(n)}</button>`).join("");
document.getElementById("chips").addEventListener("click", e => {
  const b = e.target.closest(".chip"); if (!b) return;
  cat = b.dataset.c;
  document.querySelectorAll(".chip").forEach(x => x.classList.toggle("ativo", x === b));
  pintar();
});
function cartao(t) {
  const lic = LICOES[t.id];
  const ligs = [];
  if (t.onde && (NIVEL >= 2 || !t.onde[1].startsWith("/interativo"))) ligs.push(`<a class="lig-portal" href="${esc(t.onde[1])}">🧭 ${esc(t.onde[0])}</a>`);
  if (lic) ligs.push(`<a class="lig-escola" href="/escola">🎓 Aprender na Escola: ${esc(lic.titulo)}</a>`);
  return `<div class="termo" id="${esc(t.id)}">
    <h3>${esc(t.termo)} <a class="ancora" href="#${esc(t.id)}" title="Link direto para este termo">🔗</a></h3>
    <p>${esc(t.definicao)}</p>
    ${t.exemplo ? `<div class="ex">Exemplo: ${esc(t.exemplo)}</div>` : ""}
    ${ligs.length ? `<div class="ligacoes">${ligs.join("")}</div>` : ""}
  </div>`;
}
function pintar() {
  const q = norm(document.getElementById("q").value.trim());
  const lista = TERMOS.filter(t => (!cat || t.categoria === cat) &&
    (!q || norm(t.termo + " " + (t.sinonimos || "") + " " + t.definicao).includes(q)));
  if (!lista.length) { document.getElementById("lista").innerHTML = `<div class="vazio">Nenhum termo encontrado. Sugere-o no Discord!</div>`; return; }
  // termos cujo nome corresponde à pesquisa aparecem primeiro
  if (q) lista.sort((a, b) => (norm(b.termo + " " + (b.sinonimos || "")).includes(q)) - (norm(a.termo + " " + (a.sinonimos || "")).includes(q)));
  let h = "";
  if (q) h = lista.map(cartao).join("");
  else for (const [k, n] of CATS) {
    const g = lista.filter(t => t.categoria === k).sort((a, b) => a.termo.localeCompare(b.termo, "pt"));
    if (g.length) h += `<h2>${esc(n)}</h2>` + g.map(cartao).join("");
  }
  document.getElementById("lista").innerHTML = h;
}
document.getElementById("q").addEventListener("input", pintar);
pintar();
// Ir para um termo (link direto) sem ficar escondido debaixo da barra de pesquisa
function irPara(id) {
  const el = document.getElementById(id); if (!el) return;
  const topo = document.querySelector("header").offsetHeight + 12;
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - topo });
}
window.addEventListener("hashchange", () => irPara(decodeURIComponent(location.hash.slice(1))));
if (location.hash) setTimeout(() => irPara(decodeURIComponent(location.hash.slice(1))), 60);
else if (window.matchMedia("(min-width: 701px)").matches) document.getElementById("q").focus();
</script>
</body>
</html>"""


def registar(app, requer_cargo):
    @app.route("/glossario")
    @requer_cargo(nivel_minimo=1)
    def glossario():
        return render_template_string(PAGINA, termos=TERMOS, categorias=CATEGORIAS, licoes=_licoes_por_termo(),
                                      nivel=int(session.get("nivel_acesso", 0) or 0))
