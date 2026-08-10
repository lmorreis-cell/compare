import yfinance as yf
import pandas as pd
import numpy as np  # NOVO (Essencial para a trigonometria do Radar Chart)
import os
import io
import base64
from datetime import datetime
from jinja2 import Template
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys
import hashlib
import plotly.graph_objects as go
import pytz

# ==========================================
# MÓDULO 1: O TERMÓMETRO DE RISCO
# ==========================================
def avaliar_risco_mercado():
    tickers = ["^VIX", "SPY", "RSP", "^TNX", "^IRX"]
    # A injeção do .ffill() garante que herda o fecho de 6ª feira se o mercado US estiver fechado
    dados = yf.download(tickers, period="1y", progress=False, threads=False)['Close'].ffill().dropna(how='all')
    
    vix_atual = dados['^VIX'].iloc[-1]
    vix_m20 = dados['^VIX'].rolling(window=20).mean().iloc[-1]
    alerta_vix = vix_atual > vix_m20

    spy_atual = dados['SPY'].iloc[-1]
    spy_m50 = dados['SPY'].rolling(window=50).mean().iloc[-1]
    mercado_em_alta = spy_atual > spy_m50

    spy_perf_20d = (spy_atual / dados['SPY'].iloc[-20]) - 1
    rsp_perf_20d = (dados['RSP'].iloc[-1] / dados['RSP'].iloc[-20]) - 1
    amplitude_fraca = (spy_perf_20d - rsp_perf_20d) > 0.015

    # --- NOVA MÉTRICA MACRO: INVERSÃO DA CURVA DE JUROS ---
    yield_10y = dados['^TNX'].iloc[-1]
    yield_3m = dados['^IRX'].iloc[-1]
    spread_curva = yield_10y - yield_3m
    curva_invertida = spread_curva < 0  # Se menor que zero, a curva está invertida (Sinal de Alerta)

    # Penalização de risco recalculada (agora sobre 4 pontos de stress)
    pontos_risco = sum([alerta_vix, not mercado_em_alta, amplitude_fraca, curva_invertida])
    
    if pontos_risco == 0: regime, cor, aviso = "CONSTRUTIVO", "#3fbf8f", "Mercado saudável. Condições macro de forte expansão."
    elif pontos_risco == 1: regime, cor, aviso = "NEUTRO", "#f0b90b", "Atrito detetado na estrutura técnica ou macro."
    elif pontos_risco == 2: regime, cor, aviso = "CAUTELA", "#f28b24", "Risco elevado. Curva de juros sob stress ou volatilidade latente."
    else: regime, cor, aviso = "DEFENSIVO", "#e06a5a", "PERIGO MACRO. Curva invertida e capitulação técnica iminente."

    nlg_risco = "A avaliação quantitativa do Regime define o tamanho das tuas posições. O VIX dita o pânico/complacência institucional. A posição face à M50 do SPY dita a força gravitacional da tendência primária. A Amplitude mede o 'oxigénio': mercados saudáveis sobem com participação alargada; mercados divergentes sobem carregados por meia dúzia de mega-caps, aumentando severamente o risco de colapso invisível."
    
    return {
        "regime": regime, "cor": cor, "aviso": aviso,
        "vix": f"{vix_atual:.1f}", "spy": "Acima M50" if mercado_em_alta else "Abaixo M50",
        "amplitude": "Divergente" if amplitude_fraca else "Saudável",
        "curva": f"{spread_curva:+.2f}%",
        "curva_status": "INVERTIDA (Perigo)" if curva_invertida else "Normal (Saudável)",
        "curva_cor": "var(--vermelho)" if curva_invertida else "var(--verde)",
        "nlg": nlg_risco
    }

def avaliar_breadth_macro():
    """Analisa os 11 Setores SPDR do S&P 500 para aferir a verdadeira saúde interna do mercado"""
    try:
        # Os 11 ETFs Setoriais SPDR que compõem o mercado americano
        etfs = {"Tecnologia": "XLK", "Saúde": "XLV", "Financeiro": "XLF", 
                "Consumo Discric": "XLY", "Comunicações": "XLC", 
                "Indústria": "XLI", "Bens de Consumo": "XLP", 
                "Energia": "XLE", "Utilities": "XLU", 
                "Imobiliário": "XLRE", "Materiais": "XLB"}
        
        tickers = list(etfs.values())
        # Ffill garante que falhas de feriados num setor sejam colmatadas
        dados = yf.download(tickers, period="1y", progress=False, threads=True)['Close'].ffill()
        
        setores_alta = 0
        total_setores = len(tickers)
        
        for ticker in tickers:
            preco = dados[ticker].iloc[-1]
            m200 = dados[ticker].rolling(window=200).mean().iloc[-1]
            if preco > m200:
                setores_alta += 1
                
        breadth_pct = (setores_alta / total_setores) * 100
        
        if breadth_pct >= 70:
            status = "Forte (Risk-On)"
            cor = "var(--verde)"
        elif breadth_pct >= 40:
            status = "Misto (Transição)"
            cor = "var(--amarelo)"
        else:
            status = "Fraco (Risk-Off)"
            cor = "var(--vermelho)"
            
        return {"pct": f"{breadth_pct:.0f}%", "status": status, "cor": cor, "largura": f"{breadth_pct}%", "num": setores_alta, "total": total_setores}
    except Exception as e:
        return {"pct": "N/A", "status": "Erro Algorítmico", "cor": "var(--mudo)", "largura": "0%", "num": 0, "total": 11}


def obter_variacao_hibrida(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Puxamos 5 dias na mesma como rede de segurança contra feriados/fins de semana
        hist = ticker.history(period="5d")
        
        if len(hist) < 2:
            return {'variacao': 0.0, 'estado': 'Sem Dados'}
        
        ultimo_fecho = hist['Close'].iloc[-1]
        fecho_anterior = hist['Close'].iloc[-2]
        variacao_pct = ((ultimo_fecho - fecho_anterior) / fecho_anterior) * 100
        
        # ---------------------------------------------------------
        # O DETETOR DE ESTADO DO MERCADO
        # ---------------------------------------------------------
        ny_tz = pytz.timezone('America/New_York')
        hoje_ny = datetime.now(ny_tz).date()
        data_ultimo_registo = hist.index[-1].date()
        
        # Se a data do último preço coincidir com o dia de hoje em NY, estamos na sessão atual.
        # Caso contrário, o mercado está fechado e os dados são do último fecho válido.
        if data_ultimo_registo == hoje_ny:
            estado_mercado = "Sessão Atual"
        else:
            estado_mercado = "Fecho Anterior"
            
        return {
            'variacao': round(variacao_pct, 2),
            'estado': estado_mercado
        }
        
    except Exception:
        # Fallback de emergência caso a API estoure
        return {'variacao': 0.0, 'estado': 'Erro API'}

def avaliar_smart_money():
    """Lê a curva de volatilidade e o sentimento Cripto/Ações como proxy de fluxo institucional"""
    import urllib.request
    import json
    
    dados_sm = {}
    
    # 1. Estrutura a Termo do VIX (Contango vs Backwardation)
    try:
        vix_curve = yf.download(["^VIX", "^VIX3M"], period="5d", progress=False, threads=False)['Close'].ffill()
        vix_curto = vix_curve['^VIX'].iloc[-1]
        vix_longo = vix_curve['^VIX3M'].iloc[-1]
        
        racio = vix_curto / vix_longo
        
        # Matemática para o cursor visual (0.75 = Esq. Extrema, 1.25 = Dir. Extrema)
        pct_vix = max(0, min(100, ((racio - 0.75) / (1.25 - 0.75)) * 100))
        dados_sm['vix_pct'] = f"{pct_vix:.1f}%"
        
        if racio > 1.0:
            dados_sm['vix_status'], dados_sm['vix_cor'] = "BACKWARDATION", "var(--vermelho)"
        elif racio > 0.85:
            dados_sm['vix_status'], dados_sm['vix_cor'] = "CONTANGO FRACO", "var(--amarelo)"
        else:
            dados_sm['vix_status'], dados_sm['vix_cor'] = "CONTANGO", "var(--verde)"
        dados_sm['vix_val'] = f"{racio:.2f}"
    except:
        dados_sm.update({'vix_status': "N/A", 'vix_cor': "var(--mudo)", 'vix_val': "-", 'vix_pct': "0%"})

    # 2. Crypto Fear & Greed
    try:
        url = "https://api.alternative.me/fng/"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            fng_valor = int(json.loads(response.read())['data'][0]['value'])
            dados_sm['cripto_pct'] = f"{fng_valor}%"
            
            if fng_valor > 75: dados_sm['cripto_status'], dados_sm['cripto_cor'] = "EXTREME GREED", "var(--vermelho)"
            elif fng_valor > 55: dados_sm['cripto_status'], dados_sm['cripto_cor'] = "GREED", "var(--verde)"
            elif fng_valor > 45: dados_sm['cripto_status'], dados_sm['cripto_cor'] = "NEUTRAL", "var(--amarelo)"
            elif fng_valor > 25: dados_sm['cripto_status'], dados_sm['cripto_cor'] = "FEAR", "var(--azul)"
            else: dados_sm['cripto_status'], dados_sm['cripto_cor'] = "EXTREME FEAR", "#b388ff"
            dados_sm['cripto_val'] = str(fng_valor)
    except:
        dados_sm.update({'cripto_status': "N/A", 'cripto_cor': "var(--mudo)", 'cripto_val': "-", 'cripto_pct': "50%"})

    # 3. Stock Fear & Greed (CNN) - Extração Camuflada
    try:
        url_cnn = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        req_cnn = urllib.request.Request(url_cnn, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json', 'Referer': 'https://edition.cnn.com/'
        })
        with urllib.request.urlopen(req_cnn, timeout=3) as response:
            cnn_val = int(json.loads(response.read())['fear_and_greed']['score'])
            dados_sm['cnn_pct'] = f"{cnn_val}%"
            
            if cnn_val > 75: dados_sm['cnn_status'], dados_sm['cnn_cor'] = "EXTREME GREED", "var(--vermelho)"
            elif cnn_val > 55: dados_sm['cnn_status'], dados_sm['cnn_cor'] = "GREED", "var(--verde)"
            elif cnn_val > 45: dados_sm['cnn_status'], dados_sm['cnn_cor'] = "NEUTRAL", "var(--amarelo)"
            elif cnn_val > 25: dados_sm['cnn_status'], dados_sm['cnn_cor'] = "FEAR", "var(--azul)"
            else: dados_sm['cnn_status'], dados_sm['cnn_cor'] = "EXTREME FEAR", "#b388ff"
            dados_sm['cnn_val'] = str(cnn_val)
    except:
        dados_sm.update({'cnn_status': "CNN Bloqueou Bot", 'cnn_cor': "var(--mudo)", 'cnn_val': "-", 'cnn_pct': "50%"})

    return dados_sm

# =========================================
def avaliar_curva_juros():
    """Lê o spread entre a yield do Tesouro a 10 Anos e a 3 Meses"""
    try:
        dados = yf.download(["^TNX", "^IRX"], period="5d", progress=False, threads=False)['Close'].ffill()
        t10 = dados['^TNX'].iloc[-1]
        t3m = dados['^IRX'].iloc[-1]
        spread = t10 - t3m
        
        if spread < -0.5:
            return {"status": "INVERTIDA (Recessão)", "cor": "var(--vermelho)", "valor": f"{spread:.2f}"}
        elif spread < 0:
            return {"status": "INVERSÃO (Aviso)", "cor": "var(--amarelo)", "valor": f"{spread:.2f}"}
        else:
            return {"status": "NORMAL (Expansão)", "cor": "var(--verde)", "valor": f"{spread:.2f}"}
    except:
        return {"status": "N/A", "cor": "var(--mudo)", "valor": "0.00"}

def gerar_relatorio_excecao(fechos, volumes, tickers):
    """
    Motor de Triagem Diária rigoroso.
    Monitoriza Quebras de Preço, Cruzamentos de Médias (Golden/Death Cross reais), 
    Fugas de Volume e Choques de Volatilidade.
    """
    excecoes = []
    
    for ticker in tickers:
        try:
            if ticker not in fechos.columns or ticker == 'SPY' or ticker == '^VIX':
                continue
                
            hist = fechos[ticker].dropna()
            vol = volumes[ticker].dropna()
            if len(hist) < 200: continue
            
            preco_hoje = hist.iloc[-1]
            preco_ontem = hist.iloc[-2]
            
            m50_hoje = hist.rolling(window=50).mean().iloc[-1]
            m50_ontem = hist.rolling(window=50).mean().iloc[-2]
            
            m200_hoje = hist.rolling(window=200).mean().iloc[-1]
            m200_ontem = hist.rolling(window=200).mean().iloc[-2]
            
            vol_hoje = vol.iloc[-1]
            vol_m20 = vol.tail(20).mean()

            # --- CÁLCULOS TÉCNICOS ADICIONAIS ---
            
            # Cálculo RSI (Wilder's EMA Approximation)
            delta = hist.diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_hoje = rsi.iloc[-1]
            
            # Cálculo Bandas de Bollinger (20, 2)
            m20_hoje = hist.rolling(window=20).mean().iloc[-1]
            std20_hoje = hist.rolling(window=20).std().iloc[-1]
            bb_upper = m20_hoje + (std20_hoje * 2)
            bb_lower = m20_hoje - (std20_hoje * 2)
            
            # Cálculo de Sequência (Últimas 6 sessões)
            ultimos_6 = hist.tail(6)
            diff_6 = ultimos_6.diff().dropna()
            seq_alta = all(x > 0 for x in diff_6)
            seq_baixa = all(x < 0 for x in diff_6)
            
            var_diaria = ((preco_hoje / preco_ontem) - 1) * 100
            impacto = abs(var_diaria) # Usado para ordenar a severidade do evento
            
            # 1. Choque de Volume (> 250% da média)
            if vol_hoje > (vol_m20 * 2.5) and vol_m20 > 0:
                direcao = "Acumulação" if var_diaria > 0 else "Distribuição"
                cor = "var(--verde)" if var_diaria > 0 else "var(--vermelho)"
                excecoes.append({
                    "ticker": ticker, 
                    "tipo": "Fuga de Volume", 
                    "cor": cor,
                    "desc": f"Volume {vol_hoje/vol_m20:.1f}x superior à média mensal. Forte {direcao} institucional ({var_diaria:+.1f}%).",
                    "impacto": impacto + 5 # Bónus de impacto para priorizar anomalias de volume
                })
            
            # 2. VERDADEIRO Golden / Death Cross (M50 cruza M200)
            if m50_ontem < m200_ontem and m50_hoje >= m200_hoje:
                excecoes.append({
                    "ticker": ticker, 
                    "tipo": "Golden Cross", 
                    "cor": "var(--verde)",
                    "desc": "Ignição Macro: M50 cruzou hoje acima da M200. Confirmação técnica de bull market no ativo.",
                    "impacto": 100 # Prioridade máxima absoluta
                })
            elif m50_ontem > m200_ontem and m50_hoje <= m200_hoje:
                excecoes.append({
                    "ticker": ticker, 
                    "tipo": "Death Cross", 
                    "cor": "var(--vermelho)",
                    "desc": "Falência Estrutural: M50 cruzou hoje abaixo da M200. Confirmação técnica de bear market no ativo.",
                    "impacto": 100 # Prioridade máxima absoluta
                })
                
            # 3. Quebra de Suporte / Recuperação de Resistência (Preço cruza M200)
            elif preco_ontem < m200_ontem and preco_hoje >= m200_hoje:
                excecoes.append({
                    "ticker": ticker, 
                    "tipo": "Recuperação (M200)", 
                    "cor": "var(--verde)",
                    "desc": "Preço recuperou e cota acima da M200 nas últimas 24h. Alívio tático.",
                    "impacto": impacto + 2
                })
            elif preco_ontem > m200_ontem and preco_hoje <= m200_hoje:
                excecoes.append({
                    "ticker": ticker, 
                    "tipo": "Perda de Suporte (M200)", 
                    "cor": "var(--vermelho)",
                    "desc": "Preço cedeu e cota abaixo da M200 nas últimas 24h. Risco de liquidação imediata.",
                    "impacto": impacto + 2
                })
                
            # 4. Anomalia de Volatilidade Extrema
            elif abs(var_diaria) > 7.0:
                cor = "var(--verde)" if var_diaria > 0 else "var(--vermelho)"
                excecoes.append({
                    "ticker": ticker,
                    "tipo": "Choque de Volatilidade",
                    "cor": cor,
                    "desc": f"Movimento parabólico extremo na sessão ({var_diaria:+.1f}%). Exige revisão de catalisadores.",
                    "impacto": impacto
                })

            # 5. Extremos Absolutos de RSI (Momentum)
            if rsi_hoje > 80:
                excecoes.append({
                    "ticker": ticker,
                    "tipo": "Sobrecompra Extrema (RSI)",
                    "cor": "var(--amarelo)", # Amarelo: Sinaliza risco iminente de correção, não uma venda a descoberto
                    "desc": f"RSI parabólico ({rsi_hoje:.1f}). O ativo está num esticão não sustentável a curto prazo. Risco de pullback.",
                    "impacto": impacto + 3
                })
            elif rsi_hoje < 20:
                 excecoes.append({
                    "ticker": ticker,
                    "tipo": "Sobrevenda Extrema (RSI)",
                    "cor": "var(--verde)", # Verde: Oportunidade tática
                    "desc": f"RSI colapsou para {rsi_hoje:.1f}. Liquidação irracional cria potencial para ressalto técnico tático.",
                    "impacto": impacto + 3
                })
                
            # 6. Desvio Padrão Extremo (Bandas de Bollinger)
            elif preco_hoje > bb_upper:
                 excecoes.append({
                    "ticker": ticker,
                    "tipo": "Ruptura Estatística (Alta)",
                    "cor": "var(--amarelo)",
                    "desc": "Preço cota acima de 2 Desvios Padrão (Bollinger). O movimento atual excede a normalidade estatística.",
                    "impacto": impacto + 2
                })
            elif preco_hoje < bb_lower:
                 excecoes.append({
                    "ticker": ticker,
                    "tipo": "Ruptura Estatística (Baixa)",
                    "cor": "var(--vermelho)",
                    "desc": "Preço cota abaixo de 2 Desvios Padrão. Pressão vendedora anómala a exigir atenção.",
                    "impacto": impacto + 2
                })
                
            # 7. Capitulação ou Exaustão (Ação de Preço em Sequência)
            elif seq_alta:
                 excecoes.append({
                    "ticker": ticker,
                    "tipo": "Exaustão Compradora",
                    "cor": "var(--amarelo)",
                    "desc": "Ativo regista 6 sessões consecutivas de subida sem retração. Compras de curto prazo são perigosas neste nível.",
                    "impacto": impacto + 1
                })
            elif seq_baixa:
                 excecoes.append({
                    "ticker": ticker,
                    "tipo": "Exaustão Vendedora",
                    "cor": "var(--verde)",
                    "desc": "Ativo sofre 6 sessões consecutivas de queda ininterrupta. Possível ponto de capitulação e entrada contrária.",
                    "impacto": impacto + 1
                })

        except Exception as e:
            continue
            
    # Ordenar por impacto puro (para cima ou para baixo) e remover duplicados do mesmo ticker se houver múltiplos alertas
    excecoes = sorted(excecoes, key=lambda x: x['impacto'], reverse=True)
    
    # Filtrar para ter apenas o alerta mais crítico por Ticker (evita que o DHR apareça duas vezes como na tua imagem)
    excecoes_unicas = []
    tickers_vistos = set()
    for ex in excecoes:
        if ex['ticker'] not in tickers_vistos:
            excecoes_unicas.append(ex)
            tickers_vistos.add(ex['ticker'])

    # NOVA LÓGICA: Extrair o nome da empresa APENAS para o Top 12 final (Performance impecável)
    excecoes_finais = excecoes_unicas[:12]
    for ex in excecoes_finais:
        try:
            info = yf.Ticker(ex['ticker']).info
            ex['nome'] = info.get('shortName', ex['ticker'])
        except Exception:
            ex['nome'] = ex['ticker'] # Fallback de segurança

    #nº de Market Breadth        
    #return excecoes_unicas[:12]
    return excecoes_finais

# =========================================

# ==========================================
# MÓDULO 2: VISUALIZAÇÃO E BACKTEST
# ==========================================
def formatar_grafico(ax):
    ax.set_facecolor('#151a23')
    ax.tick_params(colors='#8a94a8', labelsize=8)
    ax.spines['bottom'].set_color('#232d3f')
    ax.spines['left'].set_color('#232d3f')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, color='#232d3f', linestyle=':', alpha=0.5)

def gerar_grafico_linha(historico_preco, historico_vol, ticker):
    try:
        # Matemática do RSI (Relative Strength Index - 14 períodos clássico)
        delta = historico_preco.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        rsi = 100 - (100 / (1 + rs))

        # Isolar a janela de 6 meses (125 dias de trading)
        hist_recente = historico_preco.tail(125)
        vol_recente = historico_vol.tail(125)
        m200_recente = historico_preco.rolling(window=200).mean().tail(125)
        rsi_recente = rsi.tail(125)
        
        # Layout: 3 Subplots -> Preço (Top 3x), Volume (Meio 1x), RSI (Fundo 1x)
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(5.5, 4.2), facecolor='#151a23', gridspec_kw={'height_ratios': [3, 1, 1]})
        fig.subplots_adjust(hspace=0.1) # Cola os gráficos uns aos outros
        
        # Extrair os valores exatos de fecho para a legenda
        preco_atual = hist_recente.iloc[-1]
        m200_atual = m200_recente.iloc[-1]
        
        # 1. Painel de Preço (ax1)
        ax1.set_facecolor('#151a23')
        ax1.plot(hist_recente.index, hist_recente.values, color='#3fbf8f', label=f'Preço ({preco_atual:.2f})', linewidth=1.5)
        ax1.plot(m200_recente.index, m200_recente.values, color='#8a94a8', label=f'M200 ({m200_atual:.2f})', linestyle='--', linewidth=1)
        ax1.legend(loc='upper left', fontsize=7, facecolor='#151a23', edgecolor='#232d3f', labelcolor='white')
        ax1.set_title(f"{ticker} (6M + Vol + RSI)", color='#fff', fontsize=9, pad=5)
        ax1.tick_params(colors='#8a94a8', labelsize=7, bottom=False, labelbottom=False)
        ax1.spines['bottom'].set_color('#232d3f')
        ax1.spines['left'].set_color('#232d3f')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.grid(True, color='#232d3f', linestyle=':', alpha=0.5)
        
        # 2. Painel de Volume (ax2)
        ax2.set_facecolor('#151a23')
        cores_vol = ['#3fbf8f' if hist_recente.iloc[i] >= hist_recente.iloc[i-1] else '#e06a5a' for i in range(len(hist_recente))]
        if cores_vol: cores_vol[0] = '#3fbf8f'
        ax2.bar(vol_recente.index, vol_recente.values, color=cores_vol, alpha=0.6)
        ax2.tick_params(colors='#8a94a8', labelsize=7, bottom=False, labelbottom=False) # Oculta as datas
        ax2.spines['bottom'].set_color('#232d3f')
        ax2.spines['left'].set_color('#232d3f')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.set_yticks([]) # Oculta os números do volume para não poluir
        
        # 3. Painel de Momentum/RSI (ax3)
        ax3.set_facecolor('#151a23')
        
        # Extrair o valor atual do RSI (o último ponto da série)
        rsi_atual = rsi_recente.iloc[-1]
        
        # Adicionamos o label dinâmico com o valor atualizado
        ax3.plot(rsi_recente.index, rsi_recente.values, color='#4da6ff', linewidth=1, label=f'RSI ({rsi_atual:.1f})')
        
        ax3.axhline(70, color='#e06a5a', linestyle=':', linewidth=1, alpha=0.8) # Alarme Sobrecompra
        ax3.axhline(30, color='#3fbf8f', linestyle=':', linewidth=1, alpha=0.8) # Alarme Sobrevenda
        
        # Ativar a legenda específica para o RSI no canto superior esquerdo do mini-painel
        ax3.legend(loc='upper left', fontsize=7, facecolor='#151a23', edgecolor='#232d3f', labelcolor='#4da6ff')
        
        # Colorir dinamicamente os extremos para leitura instantânea pelo olho humano
        ax3.fill_between(rsi_recente.index, rsi_recente.values, 70, where=(rsi_recente.values >= 70), facecolor='#e06a5a', alpha=0.3)
        ax3.fill_between(rsi_recente.index, rsi_recente.values, 30, where=(rsi_recente.values <= 30), facecolor='#3fbf8f', alpha=0.3)
        
        ax3.set_ylim(0, 100)
        ax3.tick_params(colors='#8a94a8', labelsize=7)
        ax3.spines['bottom'].set_color('#232d3f')
        ax3.spines['left'].set_color('#232d3f')
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.set_yticks([30, 70])
        ax3.set_yticklabels(['30', '70'], color='#8a94a8', fontsize=6)
        ax3.grid(True, color='#232d3f', linestyle=':', alpha=0.5)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=120, facecolor='#151a23')
        plt.close()
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except Exception as e: 
        return ""


def gerar_radar_chart(a):
    """Gera o Floco de Neve Quantitativo (Matemática Normalizada 0-10)"""
    try:
        # Algoritmos de Normalização
        forca = min(10, max(0, a['perf'] / 6))
        efi = min(10, max(0, (a['roe']*100) / 3))
        pe = float(a['pe_fwd'])
        valor = 0 if pe <= 0 else min(10, max(0, 10 - ((pe - 10) / 4)))
        est = min(10, max(0, 10 - ((a['vol'] - 20) / 4)))

        categorias = ['Força', 'Eficiência', 'Valor', 'Estab.']
        valores = [forca, efi, valor, est]
        
        valores += [valores[0]]
        angulos = [n / float(len(categorias)) * 2 * np.pi for n in range(len(categorias))]
        angulos += [angulos[0]]

        plt.figure(figsize=(3, 3), facecolor='#151a23')
        ax = plt.subplot(111, polar=True)
        ax.set_facecolor('#151a23')

        ax.plot(angulos, valores, color='#f28b24', linewidth=1.5, linestyle='solid')
        ax.fill(angulos, valores, color='#f28b24', alpha=0.3)

        ax.set_xticks(angulos[:-1])
        ax.set_xticklabels(categorias, color='#8a94a8', size=8, weight='bold')
        ax.set_yticks([]) 
        ax.spines['polar'].set_color('#232d3f')

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=120, facecolor='#151a23')
        plt.close()
        buf.seek(0)
        return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    except: return ""

def avaliar_correlacao_carteira(tier_a, fechos):
    """Mede o Risco de Contágio (Matriz de Pearson) do Tier A"""
    if len(tier_a) < 2:
        return {"valor": "0.00", "nlg": "Ativos insuficientes para isolar uma matriz de correlação.", "cor": "var(--verde)", "status": "DIVERSIFICADO"}
    try:
        tickers = [a['ticker'] for a in tier_a]
        # Extrai a janela estatística de 6 meses (125 dias) com alinhamento forçado
        df = fechos[tickers].ffill().tail(125)
        
        # Calcula matriz de Pearson e isola a média acima da diagonal principal
        matriz = df.corr()
        valores_corr = matriz.values[np.triu_indices_from(matriz.values, 1)]
        media_corr = np.mean(valores_corr)

        if media_corr > 0.70:
            nlg = f"⚠️ ALERTA DE CONTÁGIO: A correlação média é massiva ({media_corr:.2f}). Estás a comprar exatamente o mesmo risco com *tickers* diferentes. Qualquer quebra macroeconómica irá arrastar todo o Tier A."
            cor = "var(--vermelho)"
            status = "SOBRECARGA"
        elif media_corr < 0.30:
            nlg = f"🛡️ DIVERSIFICAÇÃO REAL: A correlação média é baixa ({media_corr:.2f}). O teu capital está blindado com diversificação matemática cruzada."
            cor = "var(--verde)"
            status = "DIVERSIFICADO"
        else:
            nlg = f"⚖️ CORRELAÇÃO NEUTRA: Nível médio de {media_corr:.2f}. A geometria do portefólio é aceitável, mas exige vigilância."
            cor = "var(--amarelo)"
            status = "MODERADO"

        return {"valor": f"{media_corr:.2f}", "nlg": nlg, "cor": cor, "status": status}
    except Exception as e:
        return {"valor": "Erro", "nlg": "Falha quantitativa ao calcular a matriz de Pearson.", "cor": "var(--mudo)", "status": "N/A"}


def gerar_grafico_setores(tier_a):
    """Gera um gráfico Donut com a exposição setorial das oportunidades de topo"""
    if not tier_a: 
        return {"img": "", "nlg": "Sem ativos no Tier A para calcular exposição."}
    try:
        from collections import Counter
        setores = [a.get('setor', 'Unknown') for a in tier_a]
        contagem = Counter(setores)
        
        # Filtrar os nomes para ficarem mais curtos no gráfico
        # Filtrar os nomes mantendo o padrão em inglês e encurtando para o layout
        labels = [s.replace('Financial Services', 'Financials')
                   .replace('Consumer Cyclical', 'Cons. Cyclical')
                   .replace('Consumer Defensive', 'Cons. Defensive')
                   .replace('Healthcare', 'Healthcare') 
                   .replace('Basic Materials', 'Materials')
                   .replace('Real Estate', 'Real Estate')
                   .replace('Communication Services', 'Telecom') for s in contagem.keys()]
        sizes = list(contagem.values())
        
        # Paleta de cores institucional
        cores = ['#3fbf8f', '#4da6ff', '#f28b24', '#b388ff', '#e06a5a', '#f0b90b', '#8a94a8']
        
        fig, ax = plt.subplots(figsize=(4, 3), facecolor='#151a23')
        
        # O argumento "wedgeprops" com "width" é o que transforma uma tarte num Donut
        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, autopct='%1.0f%%', pctdistance=0.75,
            startangle=90, colors=cores, 
            textprops=dict(color="#8a94a8", fontsize=8, weight="bold"),
            wedgeprops=dict(width=0.4, edgecolor='#151a23', linewidth=2)
        )
        
        # Formatar as percentagens no interior do donut
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(8)
            autotext.set_weight('bold')
            
        plt.title("Concentração Setorial (Tier A)", color='#fff', pad=15, fontsize=10)
        ax.axis('equal')  # Garante que é um círculo perfeito
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor='#151a23')
        plt.close()
        buf.seek(0)
        
        nlg_setor = "Diversificação é a primeira linha de defesa. Uma concentração superior a 30% num único setor exige hedging ou redução drástica do position sizing na linha de base."
        return {"img": f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}", "nlg": nlg_setor}
    except Exception as e: 
        return {"img": "", "nlg": "Erro ao gerar gráfico setorial."}

def gerar_grafico_dispersao(dados_plot):
    # Dicionário interno para garantir que a tooltip traduz a cor bruta para uma leitura limpa
    mapa_tiers = {
        "#3fbf8f": "Tier A (Qualidade & Momentum)",
        "#f0b90b": "Tier B (Fundamentais Sólidos)",
        "#8a94a8": "Quarentena (Especulativo / Indefinição)",
        "#e06a5a": "Blacklist (Risco de Ruína)"
    }

    fig = go.Figure()

    # Iterar sobre a lista para plotar individualmente e forçar a tooltip correta
    # Novo dicionário com as "lições" de cada quadrante/classificação
    mapa_notas = {
        "#3fbf8f": "Nota: O algoritmo valida este ativo. Combina forte dinâmica de preço (momentum) com excelência comprovada nos fundamentais.",
        "#f0b90b": "Nota: Balanço sólido e eficiente, mas a ação de preço carece de ignição. Custo de oportunidade requer atenção.",
        "#8a94a8": "Nota: O gráfico atrai, mas os fundamentais assustam. Forte risco especulativo; o movimento de preço não é suportado pelo balanço.",
        "#e06a5a": "Nota: Falência estrutural. Preço em queda e métricas operacionais destrutivas. Típica armadilha de valor (Value Trap)."
    }

    # Iterar sobre a lista para plotar individualmente
    for item in dados_plot:
        tier_desc = mapa_tiers.get(item['cor'], "Desconhecido")
        # Extrai a nota correta com base na cor do ativo
        nota_edu = mapa_notas.get(item['cor'], "")
        
        fig.add_trace(go.Scatter(
            x=[item['volatilidade']],
            y=[item['perf']],
            mode='markers+text', 
            marker=dict(
                color=item['cor'], 
                size=11, 
                line=dict(width=1, color='rgba(255, 255, 255, 0.2)')
            ),
            text=[item['ticker']],
            textposition="top center",
            textfont=dict(size=9, color='rgba(255, 255, 255, 0.4)'),
            # Injetamos o ROE (1), Margem (2) e agora a Nota Dinâmica (3)
            customdata=[[tier_desc, item.get('roe', 'N/A'), item.get('margem', 'N/A'), nota_edu]],
            hovertemplate=(
                "<b style='font-size:14px'>%{text}</b><br><br>"
                "<b>Classificação:</b> %{customdata[0]}<br>"
                "<b>Retorno 6M:</b> %{y:.2f}%<br>"
                "<b>Volatilidade:</b> %{x:.2f}%<br>"
                "<b>ROE:</b> %{customdata[1]}<br>"
                "<b>Margem Op:</b> %{customdata[2]}<br><br>"
                # A nota pedagógica é chamada via variável, adaptando-se a 100% à realidade da cotada
                "<i style='font-size:11px; color:#8a94a8; display:block; max-width:250px; white-space:normal;'>%{customdata[3]}</i>"
                "<extra></extra>"
            )
        ))

    fig.update_layout(
        # 1. Correção do Título: Posição matemática no eixo horizontal (x=0.5) e ancoragem ao centro
        title=dict(
            text="Risco vs Retorno 6M", 
            font=dict(color='white', size=16),
            x=0.5,
            xanchor='center'
        ),
        xaxis=dict(
            title="Volatilidade (Risco)", 
            color='#8a94a8', 
            gridcolor='#2d333b',
            zeroline=False
        ),
        yaxis=dict(
            title="Retorno % (Lucro)", 
            color='#8a94a8', 
            gridcolor='#2d333b',
            zerolinecolor='#8a94a8',
            zerolinewidth=1
        ),
        plot_bgcolor='#0d1117', 
        paper_bgcolor='#0d1117',
        showlegend=False,
        # 2. Correção de Espaço: Forçar o autosize e esmagar a margem direita (r) para 10px
        autosize=True,
        margin=dict(l=50, r=10, t=60, b=50),
        hoverlabel=dict(bgcolor="#161b22", font_size=12, font_family="monospace")
    )

    # Adicionar a linha de água (Zero Retorno)
    fig.add_hline(y=0, line_dash="dot", line_color="#8a94a8", line_width=1.5)

    # Retorna a string HTML com a biblioteca Javascript injetada via CDN
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

def gerar_grafico_backtest(fechos):
    """Walk-Forward Backtest Real com Rotação Dinâmica Mensal"""
    nlg_base = "Simulação Out-of-Sample (Walk-Forward Dinâmico). "
    try:
        import pandas as pd
        # Para simular 6 meses com lookback de 6 meses, precisamos de 1 ano completo de dados (aprox. 250 dias)
        if len(fechos) < 250 or 'SPY' not in fechos.columns:
            return {"img": "", "nlg": "Dados insuficientes (mín. 250 dias úteis) no dataset para executar simulação dinâmica."}
        
        fechos_limpos = fechos.ffill()
        tickers_validos = [c for c in fechos_limpos.columns if c not in ['SPY', '^VIX', '^TNX', '^IRX']]
        
        # Parâmetros da Rotação
        dias_simulacao = 125          # Tempo total do teste (6 meses)
        janela_rebalanceamento = 21   # Roda a carteira a cada 21 dias úteis (1 mês)
        janela_momentum = 125         # Mede a força dos últimos 6 meses para escolher
        
        # Pré-calcula os retornos diários de todo o dataset para extração rápida
        retornos_totais = fechos_limpos[tickers_validos].pct_change().fillna(0)
        serie_retornos_estrategia = []
        
        # O motor avança no tempo aos blocos de 21 dias
        for start_idx in range(-dias_simulacao, 0, janela_rebalanceamento):
            end_idx = start_idx + janela_rebalanceamento
            if end_idx >= 0: 
                end_idx = None # Última iteração vai exatamente até hoje
                
            loc_atual = len(fechos_limpos) + start_idx
            loc_passado = loc_atual - janela_momentum
            
            # Fotografia do passado: medir quem eram os líderes naquele dia exato
            preco_passado = fechos_limpos[tickers_validos].iloc[loc_passado]
            preco_atual = fechos_limpos[tickers_validos].iloc[loc_atual]
            
            # Calcula o Momentum cruzado
            momentum = (preco_atual / preco_passado) - 1
            top_10 = momentum.nlargest(10).index.tolist()
            
            if not top_10:
                continue
                
            # Simular o comportamento estrito do Top 10 durante os 21 dias seguintes
            if end_idx is None:
                retornos_periodo = retornos_totais[top_10].iloc[start_idx:]
            else:
                retornos_periodo = retornos_totais[top_10].iloc[start_idx : end_idx]
                
            # A carteira é equiponderada (média matemática dos 10 retornos diários)
            retorno_medio_diario = retornos_periodo.mean(axis=1)
            serie_retornos_estrategia.append(retorno_medio_diario)
            
        # Unifica todas as janelas mensais numa curva contínua
        serie_final = pd.concat(serie_retornos_estrategia)
        eq_estr = (1 + serie_final).cumprod() * 100
        
        # Isola o SPY exato no mesmo calendário para a comparação ser justa
        retornos_spy = fechos_limpos['SPY'].pct_change().fillna(0).loc[serie_final.index]
        eq_spy = (1 + retornos_spy).cumprod() * 100
        
        # Cálculo das métricas finais (mantendo as 2 casas decimais)
        alfa = (eq_estr.iloc[-1] - 100) - (eq_spy.iloc[-1] - 100)
        retorno_estr = eq_estr.iloc[-1] - 100
        retorno_spy = eq_spy.iloc[-1] - 100
        
        nlg_calc = nlg_base + f"O motor avalia os ativos a cada 21 dias, corta os que perdem força e compra os novos líderes (Rebalanceamento Mensal). Alfa gerado: <strong style='color: {'var(--verde)' if alfa > 0 else 'var(--vermelho)'}'>{alfa:+.2f}%</strong> face ao S&P 500."
        
        # Geração Visual
        import matplotlib.pyplot as plt
        import io
        import base64
        
        plt.figure(figsize=(5, 3), facecolor='#151a23')
        ax = plt.axes()
        
        plt.plot(eq_estr.index, eq_estr.values, color='#3fbf8f' if alfa > 0 else '#f0b90b', 
                 label=f'Estratégia Momentum ({retorno_estr:+.2f}%)', linewidth=1.5)
        
        plt.plot(eq_spy.index, eq_spy.values, color='#8a94a8', 
                 label=f'S&P 500 (SPY) ({retorno_spy:+.2f}%)', linewidth=1.2, linestyle='-')
                 
        plt.legend(loc='upper left', fontsize=7, facecolor='#151a23', edgecolor='#232d3f', labelcolor='white')
        plt.title("Teste de Stress (Rotação Dinâmica Mensal)", color='#fff', pad=10, fontsize=10)
        plt.ylabel("Evolução (Base 100)", color='#8a94a8', fontsize=8)
        
        formatar_grafico(ax) # Mantemos a tua função de formatação de eixos
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor='#151a23')
        plt.close()
        buf.seek(0)
        
        return {"img": f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}", "nlg": nlg_calc}
        
    except Exception as e: 
        return {"img": "", "nlg": f"Falha no Backtest de Rotação Walk-Forward."}

def gerar_rrg_setorial():
    """Gera um Gráfico de Rotação Setorial (RS-Ratio vs RS-Momentum)"""
    try:
        etfs = {"Tecnologia": "XLK", "Saúde": "XLV", "Finanças": "XLF", 
                "Consumo Disc": "XLY", "Comunicações": "XLC", "Indústria": "XLI", 
                "Bens Básicos": "XLP", "Energia": "XLE", "Utilities": "XLU", 
                "Imóveis": "XLRE", "Materiais": "XLB", "SP500": "SPY"}
        
        tickers = list(etfs.values())
        dados = yf.download(tickers, period="6mo", progress=False, threads=True)['Close'].ffill()
        
        plt.figure(figsize=(6, 4.5), facecolor='#151a23')
        ax = plt.axes()
        formatar_grafico(ax)
        
        # Desenhar Eixos Centrais (100)
        ax.axhline(100, color='#8a94a8', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.axvline(100, color='#8a94a8', linestyle='--', linewidth=0.8, alpha=0.5)
        
        # Pintar Quadrantes
        ax.axhspan(100, 110, xmin=0.5, xmax=1, facecolor='#3fbf8f', alpha=0.05) # Líderes (Top-Right)
        ax.axhspan(90, 100, xmin=0, xmax=0.5, facecolor='#e06a5a', alpha=0.05)  # Atrasados (Bottom-Left)
        
        for nome, ticker in etfs.items():
            if ticker == "SPY": continue
            # RS-Ratio (Força Relativa contra o S&P 500)
            rs = dados[ticker] / dados["SPY"]
            # Normalizado à média móvel de 50 dias da Força Relativa
            rs_mm = rs.rolling(window=50).mean()
            rs_ratio = (rs.iloc[-1] / rs_mm.iloc[-1]) * 100
            
            # RS-Momentum (Variação do RS-Ratio nos últimos 10 dias)
            rs_ratio_ontem = (rs.iloc[-10] / rs_mm.iloc[-10]) * 100
            rs_mom = 100 + (rs_ratio - rs_ratio_ontem)
            
            # Decidir Cor do Ponto
            if rs_ratio >= 100 and rs_mom >= 100: cor_ponto = '#3fbf8f' # Liderança
            elif rs_ratio < 100 and rs_mom >= 100: cor_ponto = '#4da6ff' # A Melhorar
            elif rs_ratio >= 100 and rs_mom < 100: cor_ponto = '#f0b90b' # A Enfraquecer
            else: cor_ponto = '#e06a5a' # Atrasado
            
            ax.scatter(rs_ratio, rs_mom, color=cor_ponto, s=50, edgecolors='#151a23', zorder=5)
            ax.annotate(nome, (rs_ratio, rs_mom), xytext=(8, 4), textcoords='offset points', 
                        color='white', fontsize=9, weight='bold')

        ax.set_title("Rotação Setorial Institucional (RRG)", color='#fff', pad=12, fontsize=12)
        ax.set_xlabel("Força Relativa (RS-Ratio)", color='#8a94a8', fontsize=10)
        ax.set_ylabel("Momentum (RS-Mom)", color='#8a94a8', fontsize=10)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor='#151a23')
        plt.close()
        buf.seek(0)
        
        nlg = "Gráfico de Rotação (RRG). O capital viaja no sentido dos ponteiros do relógio. Procura setores no quadrante <strong style='color:var(--azul);'>Azul (A Melhorar)</strong> que estejam a cruzar para o quadrante <strong style='color:var(--verde);'>Verde (Líderes)</strong>. É aí que os fundos institucionais estão a injetar liquidez."
        return {"img": f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}", "nlg": nlg}
    except: return {"img": "", "nlg": "Falha matemática ao gerar Rotação Setorial."}

# ==========================================
# SUB-MÓDULO: MOTOR DE BADGES QUANTITATIVOS
# ==========================================
def calcular_badges_ativo(a):
    """Analisa anomalias de preço, volume e balanço para atribuir etiquetas estilo Bloomberg"""
    badges = []
    
    # 1. 🔥 Breakout
    vol_recente = a['vol_hist'].tail(5).mean() if 'vol_hist' in a and not a['vol_hist'].empty else 1
    vol_medio = a['vol_hist'].tail(20).mean() if 'vol_hist' in a and not a['vol_hist'].empty else 1
    if a.get('perf', 0) > 45 and vol_recente > vol_medio:
        badges.append({"txt": "🔥 Breakout", "bg": "#2d1f10", "cor": "#f28b24", 
                       "desc": "Forte momento direcional: Subiu >45% em 6M suportado por volume de acumulação recente acima da média."})
        
    # 2. 💎 Valor Deep
    pe = float(a.get('pe_fwd', 0))
    if 0 < pe < 12 and a.get('roe', 0) > 0.18:
        badges.append({"txt": "💎 Valor Deep", "bg": "#102533", "cor": "#4da6ff", 
                       "desc": "Anomalia de valor: Múltiplos de avaliação com forte desconto (P/E < 12) perante uma alta eficiência de capital (ROE > 18%)."})
        
    # 3. 🩸 Capitulação
    # Forçar a conversão para float e absorver lixo da API
    try:
        mdd_raw = float(a.get('mdd', 0))
        perf_raw = float(a.get('perf', 0))
    except (ValueError, TypeError):
        mdd_raw = 0.0
        perf_raw = 0.0
        
    if mdd_raw < -40 and perf_raw < -20:
        badges.append({"txt": "🩸 Capitulação", "bg": "#2d1a1a", "cor": "#e06a5a",
                       "desc": "Pânico técnico detetado: Ativo sofreu uma contração severa (>40% do topo). Possível oportunidade de reversão."})
                       
    # 4. ⭐ Elite Op
    try:
        roe_raw = float(a.get('roe', 0))
        margem_raw = float(a.get('margem', 0))
    except (ValueError, TypeError):
        roe_raw = 0.0
        margem_raw = 0.0
        
    if roe_raw > 0.25 and margem_raw > 0.22:
        badges.append({"txt": "⭐ Elite Op", "bg": "#1a2b24", "cor": "#3fbf8f",
                       "desc": "Qualidade institucional: Retornos sobre o capital (>25%) e margens operacionais (>22%) no percentil de topo."})


    # 5. 🧲 Risco Squeeze (Short Squeeze)
    try: short_float = float(a.get('short_pct', 0))
    except: short_float = 0
    if short_float > 0.15 and a.get('perf', 0) > 5:
        badges.append({"txt": "🧲 Alerta Squeeze", "bg": "#2d1a29", "cor": "#b388ff",
                       "desc": f"Pressão explosiva: {short_float*100:.1f}% das ações estão vendidas a descoberto (Short). Como a ação está a subir, estes fundos começarão a entrar em pânico e serão forçados a comprar a mercado para cobrir perdas, gerando uma subida vertical irracional."})

    # 6. 👔 Dinheiro Insider (Pele no Jogo)
    try: insider_float = float(a.get('insider_pct', 0))
    except: insider_float = 0
    if insider_float > 0.10:
        badges.append({"txt": "👔 Pele no Jogo", "bg": "#102533", "cor": "#4da6ff",
                       "desc": f"Alinhamento de Topo: {insider_float*100:.1f}% da empresa é detida pela própria administração. Quando os fundadores não vendem, significa que a convicção no pipeline futuro de resultados é absoluta."})

    return badges

def calcular_sazonalidade(ticker):
    """Calcula a estatística de sucesso do ativo no mês atual (últimos 10 anos)"""
    try:
        # Puxa 10 anos de histórico da ação isolada
        dados = yf.download(ticker, period="10y", progress=False, threads=False)['Close'].dropna()
        if dados.empty: return ""
        if isinstance(dados, pd.DataFrame): dados = dados.iloc[:, 0]
        
        # Agrupa os fechos por fim de mês para obter o retorno mensal puro
        mensal = dados.resample('ME').last()
        retornos = mensal.pct_change().dropna() * 100
        
        mes_atual = datetime.now().month
        meses_pt = {1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril", 5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"}
        nome_mes = meses_pt.get(mes_atual, "")
        
        # Isolar os retornos históricos apenas do mês atual
        retornos_mes = retornos[retornos.index.month == mes_atual]
        if len(retornos_mes) < 4: return "" # Ignora se tiver menos de 4 anos de histórico
        
        # Matemática de probabilidades
        win_rate = (len(retornos_mes[retornos_mes > 0]) / len(retornos_mes)) * 100
        media = float(retornos_mes.mean())
        
        sinal = "+" if media > 0 else ""
        cor = "var(--verde)" if media > 0 else "var(--vermelho)"
        
        return f"⏳ <strong style='color:var(--mudo)'></strong> Historicamente em {nome_mes}, este ativo sobe <strong>{win_rate:.0f}%</strong> das vezes (Retorno Médio: <span style='color:{cor}; font-weight:bold;'>{sinal}{media:.1f}%</span>)."
    except: 
        return ""

# ==========================================
# MÓDULO 3: SCREENER + MOTOR NLG
# ==========================================
def calcular_position_sizing(a_comp):
    """
    Calcula o peso ideal na carteira usando Volatility Targeting.
    Substitui a heurística falhada do MDD por risco dinâmico atual.
    """
    # 1. Extração de Variáveis Críticas
    conviccao = a_comp.get('conv', 50)
    # A volatilidade vem como string no teu df ou número bruto. Garantir conversão segura:
    try:
        vol_str = str(a_comp.get('vol', 20)).replace('%', '')
        volatilidade = float(vol_str)
    except:
        volatilidade = 20.0

    # 2. Parâmetros Base da Gestão de Risco
    max_peso_carteira = 10.0  # Nenhuma ação pode ultrapassar 10% do capital (controlo de concentração)
    volatilidade_alvo = 15.0  # Volatilidade de referência de um mercado saudável (ex: S&P 500)

    # 3. O Motor Matemático (Volatility Parity)
    # Se a ação tem 30% de volatilidade (dobro do alvo), o peso sugerido é cortado para metade.
    # Se tem 10% de volatilidade, o peso pode expandir.
    fator_risco = volatilidade_alvo / max(volatilidade, 1.0)
    
    # 4. Modulador de Convicção Qualitativa (Radar Score)
    # Transforma o teu score de 0-100 num multiplicador de 0.0 a 1.0
    fator_conviccao = conviccao / 100.0

    # 5. Cálculo Final
    peso_sugerido = max_peso_carteira * fator_risco * fator_conviccao

    # Garantir que anomalias matemáticas de baixíssima volatilidade não estoiram o limite de 10%
    peso_final = min(peso_sugerido, max_peso_carteira)

    return f"{peso_final:.1f}%"

def auditar_fundamentais(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        # 1. Tentar via .info (método rápido)
        next_date = info.get('nextEarningsDate')

        # 2. Fallback robusto (O yfinance moderno usa get_earnings_dates)
        if next_date is None:
            try:
                import datetime as dt
                calendario = ticker_obj.get_earnings_dates()
                if calendario is not None and not calendario.empty:
                    # O yfinance devolve um DataFrame com o índice em datas futuras e passadas
                    hoje = dt.datetime.now(dt.timezone.utc)
                    datas_futuras = calendario[calendario.index > hoje]
                    
                    if not datas_futuras.empty:
                        # Extrai a data mais próxima e converte para Timestamp UNIX
                        next_date = datas_futuras.index[-1].timestamp()
            except Exception:
                pass # Mantém o next_date a None se o motor estoirar de vez

        # Caça ao Target Price
        alvo = info.get('targetMeanPrice') or info.get('targetMedianPrice') or info.get('currentPrice')
        if alvo is None or alvo == info.get('currentPrice'):
            alvo = 0
            
        roe = info.get('returnOnEquity', 0)
        margem = info.get('operatingMargins', 0)
        pe = info.get('forwardPE', 0)
        
        debt_to_equity = info.get('debtToEquity', 0)
        margin_net = info.get('profitMargins', 0)
        
        recom = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
        
        earnings_trend = info.get('earningsQuarterlyGrowth', None)
        if earnings_trend is None:
            earnings_trend = info.get('heldPercentInstitutions', 0) * 10

        # --- SCRAPER DIRETO AO FINVIZ (BYPASS AO YAHOO) ---
        short_pct = 0.0
        insider_pct = 0.0
        
        # O Finviz apenas tem dados fiáveis para o mercado americano.
        # Evitamos fazer pedidos inúteis se o ticker for europeu (ex: contiver ".LS" ou ".DE")
        if "." not in ticker:
            try:
                import urllib.request
                url_finviz = f"https://finviz.com/quote.ashx?t={ticker}"
                req_finviz = urllib.request.Request(url_finviz, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })
                
                with urllib.request.urlopen(req_finviz, timeout=3) as response:
                    html_finviz = response.read().decode('utf-8')
                    
                # Extração cirúrgica via manipulação de texto (rápido e não exige BeautifulSoup)
                if "Short Float" in html_finviz:
                    bloco_short = html_finviz.split('Short Float')[1].split('</b>')[0]
                    valor_short = bloco_short.split('<b>')[-1].replace('%', '').strip()
                    if valor_short != '-':
                        short_pct = float(valor_short) / 100.0
                        
                if "Insider Own" in html_finviz:
                    bloco_insider = html_finviz.split('Insider Own')[1].split('</b>')[0]
                    valor_insider = bloco_insider.split('<b>')[-1].replace('%', '').strip()
                    if valor_insider != '-':
                        insider_pct = float(valor_insider) / 100.0
            except:
                pass # Se o Finviz bloquear ou o ticker não existir, mantém-se a 0
            
        vol_medio_10d = info.get('averageDailyVolume10Day') or info.get('averageVolume') or 1
        preco_nominal = info.get('currentPrice') or info.get('previousClose') or 1
        adv_calculado = (vol_medio_10d * preco_nominal) / 1_000_000
        
        return {
            "nome": info.get('shortName', ticker),
            "industria": info.get('industry', 'N/A'),
            "setor": info.get('sector', 'Unknown'),
            "roe": roe if roe is not None else 0,
            "margem": margem if margem is not None else 0,
            "pe_fwd": pe if pe is not None else 0,
            "target_mean": float(alvo) if alvo else 0,
            "debt_eq": (debt_to_equity / 100) if debt_to_equity else 0,
            "margem_liq": margin_net if margin_net is not None else 0,
            "eps": info.get('trailingEps', 0),
            "moeda": info.get('currency', 'USD'),
            "recom": recom,
            "earnings_trend": earnings_trend if earnings_trend is not None else 0,
            "adv": adv_calculado,
            "next_earnings": next_date,  # <-- A VARIAVEL CORRETA INJETADA NO DICIONÁRIO
            # --- NOVAS MÉTRICAS INSTITUCIONAIS ---
            short_pct : info.get('shortPercentOfFloat', 0),
            insider_pct : info.get('heldPercentInsiders', 0),
            "preco_live": info.get('currentPrice') or info.get('regularMarketPrice')
        }
    except Exception as e:
        return {"nome": ticker, "industria": "N/A", "setor": "Unknown", "roe": 0, "margem": 0, "pe_fwd": 0, "target_mean": 0, "debt_eq": 0, "margem_liq": 0, "eps": 0, "recom": "N/A", "next_earnings": None}

def gerar_analise_profunda_nlg(a_comp):
    bullets_fundo = []
    bullets_tatica = []

    # ==========================================
    # EXTRAÇÃO E CÁLCULO SEGURO DE VARIÁVEIS
    # ==========================================
    roe = a_comp.get('roe', 0)
    margem_op = a_comp.get('margem', 0)
    margem_liq = a_comp.get('margem_liq', 0)
    pe_fwd = a_comp.get('pe_fwd', 0)
    debt_eq = a_comp.get('debt_eq', 0)
    eps_trend = a_comp.get('earnings_trend', 0)
    adv = a_comp.get('adv', 0)  # Average Daily Volume em milhões
    
    # Tentativa de cálculo dinâmico da Tática usando o Histórico Real
    hist = a_comp.get('hist')
    if hist is not None and not hist.empty and len(hist) >= 50:
        preco_atual = hist.iloc[-1]
        m200 = hist.rolling(window=200).mean().iloc[-1]
        m50 = hist.rolling(window=50).mean().iloc[-1]
        dist_m200 = ((preco_atual / m200) - 1) * 100
        dist_m50 = ((preco_atual / m50) - 1) * 100
        
        # RSI 14 local para garantir precisão
        delta = hist.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100 / (1 + (ema_up / ema_down))).iloc[-1]
    else:
        dist_m200, dist_m50, rsi, preco_atual = 0, 0, 50, 0

    try: vol_val = float(str(a_comp.get('vol', 20)).replace('%', ''))
    except: vol_val = 20.0

    # ==========================================
    # 1. MOTOR FUNDAMENTAL (Cruzamento Complexo)
    # ==========================================
    
    # 1.1 Rentabilidade vs Alavancagem (Teste de Ácido do ROE)
    if roe >= 0.15:
        if debt_eq > 1.5:
            bullets_fundo.append(f"<b>Miragem de Alavancagem (ROE {roe*100:.1f}% | Dívida/CP {debt_eq:.2f}x):</b> O ROE parece de elite, mas é artificialmente inflado por níveis tóxicos de dívida. Com uma estrutura de capital tão exposta, o ativo é extremamente sensível a contrações no mercado de crédito ou subidas de juros.")
        elif margem_op >= 0.15:
            bullets_fundo.append(f"<b>Balanço Fortress (ROE {roe*100:.1f}% | Margem Op. {margem_op*100:.1f}%):</b> O negócio possui uma vantagem competitiva inegável. Consegue retornos sobre o capital de nível institucional com forte <i>pricing power</i>, refletido numa capacidade rara de converter vendas em caixa líquido (Margem Líquida {margem_liq*100:.1f}%).")
        else:
            bullets_fundo.append(f"<b>Eficiência Escala-Dependente (ROE {roe*100:.1f}% | Margem Op. {margem_op*100:.1f}%):</b> A gestão gera bons retornos sobre o capital acionista, mas opera com margens industriais esmagadas. A sobrevivência deste lucro depende estritamente da manutenção de alto volume de faturação.")
    else:
        if debt_eq < 0.5 and margem_op > 0.10:
            bullets_fundo.append(f"<b>Balanço Adormecido (ROE {roe*100:.1f}% | Dívida/CP {debt_eq:.2f}x):</b> A operação é saudável e desalavancada, mas a gestão falha em alocar capital para crescer. Existe dinheiro parado a destruir valor para o acionista. Potencial alvo de ativismo institucional.")
        elif margem_op < 0.05:
            bullets_fundo.append(f"<b>Falência Estrutural (ROE {roe*100:.1f}% | Margem Op. {margem_op*100:.1f}%):</b> Destruição clara de valor. O modelo de negócio atual consome recursos sem gerar caixa defensável. Risco elevado de diluição acionista (emissão de novas ações) para manter a operação viva.")

    # 1.2 Valuation vs Growth (Teste PEG / Trajetória de Lucros)
    if pe_fwd > 0:
        if pe_fwd > 30 and eps_trend < 5:
            bullets_fundo.append(f"<b>Risco de Compressão Múltipla (P/E Fwd {pe_fwd:.1f}x):</b> O mercado exige perfeição, pagando um prémio massivo por um ativo cujo ritmo de revisão de lucros estagnou ({eps_trend:+.1f}%). Qualquer falha (miss) nos próximos resultados trimestrais desencadeará uma correção violenta da cotação.")
        elif pe_fwd < 15 and eps_trend > 10:
            bullets_fundo.append(f"<b>Assimetria de Crescimento/Valor (P/E Fwd {pe_fwd:.1f}x | Lucros {eps_trend:+.1f}%):</b> Discrepância assinalável. O mercado atribui um múltiplo deprimente a uma empresa com revisões de lucro robustas. A probabilidade de reavaliação altista (<i>re-rating</i>) é estatisticamente a favor do investidor.")
    else:
        bullets_fundo.append("<b>Ineficiência Terminal (P/E Inexistente):</b> Ausência de lucros projetados. Trata-se de um ativo puramente especulativo a queimar caixa, sem suporte para modelos de avaliação tradicionais.")

    if not bullets_fundo:
         bullets_fundo.append("Fricções de balanço não detetadas ou falha nos dados estruturais.")

    # ==========================================
    # 2. CONTEXTO TÁTICO E COMPORTAMENTAL
    # ==========================================
    
    # 2.1 Análise Gravitacional (Preço vs Médias Móveis + RSI)
    if rsi >= 70:
        if dist_m200 > 20:
            bullets_tatica.append(f"<b>Exaustão Parabólica e Estiramento (RSI {rsi:.1f}):</b> O elástico técnico está no limite. O ativo negoceia com uma gravidade insustentável de +{dist_m200:.1f}% face à sua M200. Comprar o *breakout* nestes níveis oferece uma assimetria destrutiva; a reversão à média (pullback) é matematicamente iminente.")
        else:
            bullets_tatica.append(f"<b>Absorção Institucional (RSI {rsi:.1f}):</b> Forte pressão compradora mantém o ativo em sobrecompra sem que este se afaste de forma irracional das suas médias de suporte. O mercado está a aceitar os novos preços. Gerir ativamente quebras da M50 (-{abs(dist_m50):.1f}%).")
            
    elif rsi <= 30:
        if dist_m200 < -15:
            bullets_tatica.append(f"<b>Faca em Queda / Capitulação (RSI {rsi:.1f} | M200: {dist_m200:.1f}%):</b> Liquidação irracional de mãos fracas. O ativo colapsou abaixo de todos os suportes institucionais. O RSI grita sobrevenda, mas intervir agora é apostar contra momentum puro. Aguardar lateralização clara antes de tentar apanhar o fundo.")
        else:
            bullets_tatica.append(f"<b>Sobrevenda em Tendência (RSI {rsi:.1f}):</b> O ativo encontra-se sobre-vendido, contudo permanece próximo ou acima da M200. Identifica-se uma zona de provável defesa por parte de fundos institucionais (suporte de valor).")
            
    else:
        if dist_m50 > 0 and dist_m200 > 0:
             bullets_tatica.append(f"<b>Equilíbrio Construtivo (RSI {rsi:.1f}):</b> Ação de preço estruturada e limpa. O ativo consolida ganhos descansando sobre a M50 de forma controlada, criando uma base sólida para a próxima expansão direcional.")
        elif dist_m200 < 0:
             bullets_tatica.append(f"<b>Letargia Descendente (RSI {rsi:.1f}):</b> O RSI neutro mascara uma tendência morta. O ativo transaciona {dist_m200:.1f}% abaixo da M200. Sem ignição de volume, continuará a sangrar lentamente e a destruir o custo de oportunidade do capital parado.")

    # 2.2 Choque de Risco e Iliquidez (Slippage)
    if vol_val > 45:
        bullets_tatica.append(f"<b>Regime de Turbulência (Volatilidade {vol_val:.1f}%):</b> Movimentos diários erráticos. O risco de gap (abrir a perder 10% de um dia para o outro) impõe o estrangulamento imediato do <i>position sizing</i> para não contaminar a variância global da carteira.")
        
    if adv > 0 and adv < 15:
        bullets_tatica.append(f"<b>Alerta de Iliquidez Institucional (ADV {adv:.1f}M USD/dia):</b> Volume de transação diário muito baixo. Ativos abaixo dos 15M$ sofrem forte manipulação de <i>spread</i> e <i>slippage</i> (derrapagem de preço na execução de ordens). Não recomendado para tamanhos de carteira elevados.")

    if not bullets_tatica:
        bullets_tatica.append("Ruído técnico. Sem anomalias direcionais detetáveis.")

    # ==========================================
    # 3. EMPACOTAMENTO HTML
    # ==========================================
    html_fundo = "<ul style='margin: 0; padding-left: 18px;'>" + "".join([f"<li style='margin-bottom: 10px;'>{b}</li>" for b in bullets_fundo]) + "</ul>"
    html_tatica = "<ul style='margin: 0; padding-left: 18px;'>" + "".join([f"<li style='margin-bottom: 10px;'>{b}</li>" for b in bullets_tatica]) + "</ul>"

    return html_fundo, html_tatica


def gerar_texto_nlg(a, tier):
    """
    Descodificador NLG Avançado.
    Cruza o comportamento do Preço/Volume com a assimetria da Matriz Radar.
    """
    # 1. Extração e cálculo de dinâmicas de Preço e M200
    preco_atual = a['hist'].iloc[-1]
    m200_atual = a['hist'].rolling(window=200).mean().iloc[-1]
    distancia_m200 = ((preco_atual - m200_atual) / m200_atual) * 100
    
    # 2. Análise do Volume (Últimos 5 dias vs Média de 20 dias)
    vol_recente = a['vol_hist'].tail(5).mean()
    vol_medio = a['vol_hist'].tail(20).mean()
    volume_aumentou = vol_recente > vol_medio

    # 3. Reconstrução dos Pilares do Radar (Escala 0-10)
    forca = min(10, max(0, a['perf'] / 6))
    efi = min(10, max(0, (a['roe']*100) / 3))
    pe = float(a['pe_fwd'])
    valor = 0 if pe <= 0 else min(10, max(0, 10 - ((pe - 10) / 4)))
    est = min(10, max(0, 10 - ((a['vol'] - 20) / 4)))

    # --- LÓGICA DE DESCODIFICAÇÃO DO GRÁFICO (Preço + Volume) ---
    if preco_atual > m200_atual:
        if volume_aumentou:
            leitura_grafico = f"O gráfico valida uma tendência de alta saudável: o preço opera {distancia_m200:.1f}% acima da M200, suportado por um influxo de volume institucional acima da média histórica (+Vol). Há acumulação real ativa."
        else:
            leitura_grafico = f"O preço mantém-se em estrutura de alta ({distancia_m200:.1f}% acima da M200), mas o volume recente está a secar. Isto indica exaustão de compradores ou subida por inércia (falta de liquidez vendedora). Cuidado com reversões abruptas."
    else:
        if volume_aumentou:
            leitura_grafico = f"Alerta de capitulação no gráfico: o ativo negoceia {abs(distancia_m200):.1f}% abaixo da sua M200 com volume pesado em picos de venda. Mãos fortes estão a liquidar posições."
        else:
            leitura_grafico = f"O ativo encontra-se em tendência descendente secular ({abs(distancia_m200):.1f}% abaixo da M200), contudo o volume baixo sugere um desinteresse generalizado do mercado, característico de uma fase de consolidação ou agonia técnica."

    # --- LÓGICA DE DESCODIFICAÇÃO DO RADAR (Geometria Quântica) ---
    # Identificar a maior força e a maior vulnerabilidade do floco de neve
    pilares = {"Força (Momentum)": forca, "Eficiência (Fundamentais)": efi, "Valor (Preço Múltiplo)": valor, "Estabilidade (Baixo Risco)": est}
    forte = max(pilares, key=pilares.get)
    fraco = min(pilares, key=pilares.get)
    
    leitura_radar = f"A geometria do radar revela que o principal motor deste ativo é a sua [{forte}], enquanto a sua maior vulnerabilidade estrutural reside no pilar de [{fraco}]."

    # 4. Geração do Score de Convicção Sintético
    conviccao = int((forca * 0.35 + efi * 0.30 + valor * 0.15 + est * 0.20) * 10)

    # --- SÍNTESE FINAL DA LEITURA E RESERVAS ---
    if tier in ["A", "Tier A"]:
        leitura = f"{leitura_grafico} {leitura_radar} Isto justifica a sua classificação no Tier A: um perfil focado em forte momento e eficiência operacional superior."
        reservas = "Risco de estiramento tático. Se o pilar de Valor estiver severamente contraído no radar, qualquer falha no crescimento trimestral desencadeará uma forte contração de múltiplos."
    elif tier in ["B", "Tier B"]:
        leitura = f"{leitura_grafico} {leitura_radar} Integrado no Tier B porque exibe excelentes fundamentais, mas a ação do preço ainda carece de ignição ou volume de rutura para confirmar o 'momentum'."
        reservas = "Custo de oportunidade elevado. O ativo pode permanecer lateralizado se a pontuação de Força no radar continuar deprimida, independentemente da qualidade do balanço."
    elif tier == "Quarentena":
        leitura = f"{leitura_grafico} {leitura_radar} Colocado de quarentena. Existe uma divergência severa: o balanço apresenta solidez, mas o mercado está a rejeitar o ativo tecnicamente."
        reservas = "Risco elevado de <span class='dica-edu dica-desce' style='border-bottom: 1px dotted var(--vermelho); color: var(--vermelho);'>Value Trap<span class='dica-texto' style='width: 300px;'><strong style='color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;'>Armadilha de Valor (Value Trap)</strong>Uma ação que parece 'barata' pelos seus múltiplos (P/E baixo) e lucros passados, mas que continua a cair em bolsa de forma consistente. O mercado desconta um colapso futuro nos lucros que os analistas e o balanço atual ainda não refletem.</span></span>. Não tentar adivinhar fundos."
    elif tier == "Especulativo":
        leitura = f"{leitura_grafico} {leitura_radar} Ativo de carácter puramente especulativo: forte ignição técnica mas carente de suporte estrutural nos fundamentais institucionais."
        reservas = "Alocação deve ser residual. Qualquer inversão de volume resultará numa queda agressiva sem rede de segurança."
    else:
        leitura = f"{leitura_grafico} {leitura_radar} Classificado como {tier} devido à falência dos seus indicadores de risco e tendência."
        reservas = "A destruição de capital aqui é puramente matemática e validada pelo volume de fuga. Ignorar ruído mediático."


    
    return leitura, reservas, conviccao

    
# ==========================================
# MÓDULO EXTRA: ANÁLISE DE SENTIMENTO (NLP)
# ==========================================
def analisar_sentimento_noticias(ticker):
    """Lê as últimas notícias via RSS nativo do Yahoo (Anti-Bloqueio) e classifica o sentimento."""
    import urllib.request
    import xml.etree.ElementTree as ET
    
    try:
        # Ligação direta à fonte de dados contornando os bloqueios de API
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        
        with urllib.request.urlopen(req, timeout=3) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        titulos = [item.text.lower() for item in root.findall('.//item/title')]
        
        if not titulos:
            return "Sem Dados", "#8a94a8" # Cinza
            
        # Dicionário de NLP otimizado para o calão financeiro americano
        palavras_bull = ['buy', 'up', 'beat', 'growth', 'record', 'higher', 'jump', 'rally', 'surge', 'gain', 'bull', 'outperform', 'strong', 'soar']
        palavras_bear = ['sell', 'down', 'miss', 'drop', 'cut', 'lower', 'fall', 'plunge', 'decline', 'loss', 'bear', 'underperform', 'weak', 'crash']
        
        score_bull = 0
        score_bear = 0
        
        for titulo in titulos[:5]: # Auditar apenas as 5 manchetes mais recentes
            if any(p in titulo for p in palavras_bull): score_bull += 1
            if any(p in titulo for p in palavras_bear): score_bear += 1
            
        if score_bull > score_bear:
            return "Otimista", "#3fbf8f" # Verde
        elif score_bear > score_bull:
            return "Pessimista", "#e06a5a" # Vermelho
        else:
            return "Neutro", "#f0b90b" # Amarelo
    except Exception as e:
        return "Sem Dados", "#8a94a8"

def executar_screener():
    with open("tickers_escolhidos_states.txt", "r") as f:
        tickers = [linha.strip().upper() for linha in f if linha.strip()]
        
    # Garante que o SPY está no pacote global de dados para o Backtest cruzar
    tickers_globais = list(set(tickers + ['SPY']))
        
    print(f"A descarregar Preço e Volume para {len(tickers_globais)} ações europeias...")
    
    # 1. Alterado de 1y para 2y para alimentar a M200 com histórico profundo
    dados_raw = yf.download(tickers_globais, period="2y", progress=False, threads=False)
    
    # 2. REMOVIDO o ffill() global que corrompia os calendários com feriados cruzados
    fechos = dados_raw['Close'].dropna(how='all')
    volumes = dados_raw['Volume'].dropna(how='all')
    
    # --- NOVA INJEÇÃO GLOBAL EM TEMPO REAL ---
    print("A sincronizar cotações em tempo real na matriz global...")
    cache_fundamentais = {}
    novos_precos = {}
    novos_volumes = {}
    
    for ticker in tickers:
        try:
            # Puxa os dados e guarda na cache para não repetir pedidos à API
            f = auditar_fundamentais(ticker)
            cache_fundamentais[ticker] = f
            preco_live = f.get('preco_live')
            hist = fechos[ticker].dropna()
            
            # Se o preço live existe e é diferente do último fecho atrasado do Yahoo
            if not hist.empty and preco_live and preco_live > 0 and round(preco_live, 2) != round(hist.iloc[-1], 2):
                novos_precos[ticker] = preco_live
                novos_volumes[ticker] = volumes[ticker].dropna().iloc[-1]
        except: pass

    # Atualiza a base de dados central com a vela de hoje ANTES dos relatórios!
    if novos_precos:
        hoje_str = datetime.now().strftime('%Y-%m-%d')
        ultima_data_str = fechos.index[-1].strftime('%Y-%m-%d')
        
        if ultima_data_str == hoje_str:
            # Já existe uma vela com a data de hoje. Vamos SOBRESCREVER para não duplicar.
            for t, p in novos_precos.items():
                fechos.iloc[-1, fechos.columns.get_loc(t)] = p
            for t, v in novos_volumes.items():
                volumes.iloc[-1, volumes.columns.get_loc(t)] = v
        else:
            # A última vela é de ontem. Adicionamos uma nova linha.
            nova_data = fechos.index[-1] + pd.Timedelta(days=1)
            fechos = pd.concat([fechos, pd.DataFrame([novos_precos], index=[nova_data])])
            volumes = pd.concat([volumes, pd.DataFrame([novos_volumes], index=[nova_data])])
    # -----------------------------------------

    # Calcular a força base contra a média europeia
    try:
        stoxx_limpo = fechos['^STOXX'].dropna()
        perf_stoxx_6m = ((stoxx_limpo.iloc[-1] / stoxx_limpo.iloc[-125]) - 1) * 100
    except:
        perf_stoxx_6m = 0
    
    try:
        # Calcular a variação diária de forma isolada e imune a matrizes desalinhadas
        dict_perf = {}
        for col in fechos.columns:
            if col != '^STOXX':
                hist_limpo = fechos[col].dropna()
                if len(hist_limpo) >= 2:
                    dict_perf[col] = ((hist_limpo.iloc[-1] / hist_limpo.iloc[-2]) - 1) * 100
                    
        perf_diaria = pd.Series(dict_perf).sort_values(ascending=False)
        market_movers = {
            "gainers": [{"ticker": t, "perf": round(p, 1)} for t, p in perf_diaria.head(5).items() if p > 0],
            "losers": [{"ticker": t, "perf": round(p, 1)} for t, p in perf_diaria.tail(5).sort_values(ascending=True).items() if p < 0]
        }
    except: market_movers = {"gainers": [], "losers": []}

    # Como a matriz 'fechos' foi atualizada globalmente, o Exception Report e o Breadth já vão ler a vela de hoje!
    alertas_excecao = gerar_relatorio_excecao(fechos, volumes, tickers)
    dados_breadth = calcular_market_breadth(fechos, tickers)
    breadth_macro = avaliar_breadth_macro()

    cand_alta, cand_baixa = [], []
    for ticker in tickers:
        try:
            historico = fechos[ticker].dropna()
            vol_hist = volumes[ticker].dropna()
            if len(historico) < 200: continue
            
            # Puxamos os dados da cache (acelera brutalmente a velocidade do código)
            f = cache_fundamentais.get(ticker, auditar_fundamentais(ticker))
            
            # A matemática corre de forma limpa e em tempo real
            preco = historico.iloc[-1]
            m200 = historico.rolling(window=200).mean().iloc[-1]
            m50 = historico.rolling(window=50).mean().iloc[-1]
            perf_6m = ((preco / historico.iloc[-125]) - 1) * 100
            
            alpha_6m = perf_6m - perf_stoxx_6m
                
            base_data = {"ticker": ticker, "perf": perf_6m, "alpha": alpha_6m, "vol": historico.pct_change().std() * (252 ** 0.5) * 100, 
                         "mdd": ((historico - historico.cummax()) / historico.cummax()).min() * 100, 
                         "hist": historico, "vol_hist": vol_hist, **f}
            
            if preco >= m200:
                cand_alta.append(base_data)
            else:
                base_data["tendencia_morta"] = m50 < m200
                cand_baixa.append(base_data)
        except: pass

    
    df_alta = pd.DataFrame(cand_alta).sort_values(by="perf", ascending=False) if cand_alta else pd.DataFrame()
    df_baixa = pd.DataFrame(cand_baixa).sort_values(by="perf", ascending=True) if cand_baixa else pd.DataFrame()

   

    tier_a, tier_b, blacklist, quarentena, dados_plot = [], [], [], [], [] # <-- Nova lista adicionada

       
    if not df_alta.empty:
        for _, row in df_alta.iterrows():
            a_comp = row.to_dict()
            f = a_comp  # Aproveitamos a cache que já está na memória! 
            
            preco_atual = row['hist'].iloc[-1]
            target_mean = f.get('target_mean', 0)
            a_comp['upside'] = ((target_mean / preco_atual) - 1) * 100 if target_mean and preco_atual else 0
            
            # 3º - AGORA SIM, com o a_comp criado, podemos injetar os cálculos
            a_comp['position_size'] = calcular_position_sizing(a_comp)
            
            # 4º - O Motor Narrativo que discutimos
            txt_fundo, txt_tatica = gerar_analise_profunda_nlg(a_comp)
            a_comp['analise_fundo_txt'] = txt_fundo
            a_comp['analise_tatica_txt'] = txt_tatica

            
            if f['roe'] > 0.15 and f['margem'] > 0.15:
                a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, "A")
                a_comp['position_size'] = calcular_position_sizing(a_comp)
                a_comp['badges'] = calcular_badges_ativo(a_comp)
                a_comp['sazonalidade'] = calcular_sazonalidade(a_comp['ticker'])
                a_comp['grafico'] = gerar_grafico_linha(row['hist'], row['vol_hist'], row['ticker'])
                a_comp['radar'] = gerar_radar_chart(a_comp)
                sent_txt, sent_cor = analisar_sentimento_noticias(row['ticker'])
                a_comp['sentimento_txt'] = sent_txt
                a_comp['sentimento_cor'] = sent_cor
                tier_a.append(a_comp)
                dados_plot.append({
                    "ticker": row['ticker'], 
                    "perf": row['perf'], 
                    "volatilidade": row['vol'], 
                    "cor": "#3fbf8f",  # <- Mantém o código de cor original que lá tens (verde, amarelo, vermelho ou cinza)
                    "roe": f"{a_comp.get('roe', 0)*100:.1f}%",
                    "margem": f"{a_comp.get('margem', 0)*100:.1f}%"
                })
            else:
                # O CAPTADOR DA ZONA CINZENTA (ALTA TENDÊNCIA, MAUS FUNDAMENTAIS)
                a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, "Quarentena")
                a_comp['position_size'] = calcular_position_sizing(a_comp)
                a_comp['badges'] = calcular_badges_ativo(a_comp)
                a_comp['sazonalidade'] = calcular_sazonalidade(a_comp['ticker'])
                a_comp['grafico'] = gerar_grafico_linha(row['hist'], row['vol_hist'], row['ticker'])
                a_comp['radar'] = gerar_radar_chart(a_comp)
                sent_txt, sent_cor = analisar_sentimento_noticias(row['ticker'])
                a_comp['sentimento_txt'] = sent_txt
                a_comp['sentimento_cor'] = sent_cor
                quarentena.append(a_comp)
                dados_plot.append({
                    "ticker": row['ticker'], 
                    "perf": row['perf'], 
                    "volatilidade": row['vol'], 
                    "cor": "#8a94a8",  # <- Mantém o código de cor original que lá tens (verde, amarelo, vermelho ou cinza)
                    "roe": f"{a_comp.get('roe', 0)*100:.1f}%",
                    "margem": f"{a_comp.get('margem', 0)*100:.1f}%"
                })

    if not df_baixa.empty:
        for _, row in df_baixa.iterrows():
            a_comp = row.to_dict()
            f = a_comp  # Aproveitamos a cache que já está na memória!
            
            preco_atual = row['hist'].iloc[-1]
            target_mean = f.get('target_mean', 0)
            a_comp['upside'] = ((target_mean / preco_atual) - 1) * 100 if target_mean and preco_atual else 0
            
            # ADICIONAR O MOTOR AQUI:
            txt_fundo, txt_tatica = gerar_analise_profunda_nlg(a_comp)
            a_comp['analise_fundo_txt'] = txt_fundo
            a_comp['analise_tatica_txt'] = txt_tatica

            if f['roe'] > 0.20 and f['margem'] > 0.20:
                a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, "B")
                a_comp['position_size'] = calcular_position_sizing(a_comp)
                a_comp['badges'] = calcular_badges_ativo(a_comp)
                a_comp['sazonalidade'] = calcular_sazonalidade(a_comp['ticker'])
                a_comp['grafico'] = gerar_grafico_linha(row['hist'], row['vol_hist'], row['ticker'])
                a_comp['radar'] = gerar_radar_chart(a_comp)
                sent_txt, sent_cor = analisar_sentimento_noticias(row['ticker'])
                a_comp['sentimento_txt'] = sent_txt
                a_comp['sentimento_cor'] = sent_cor
                tier_b.append(a_comp)
                dados_plot.append({
                    "ticker": row['ticker'], 
                    "perf": row['perf'], 
                    "volatilidade": row['vol'], 
                    "cor": "#f0b90b",  # <- Mantém o código de cor original que lá tens (verde, amarelo, vermelho ou cinza)
                    "roe": f"{a_comp.get('roe', 0)*100:.1f}%",
                    "margem": f"{a_comp.get('margem', 0)*100:.1f}%"
                })
            elif (f['roe'] < 0 or f['margem'] < 0) and row.get('tendencia_morta', False):
                a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, "Blacklist")
                a_comp['position_size'] = calcular_position_sizing(a_comp)
                a_comp['badges'] = calcular_badges_ativo(a_comp)
                a_comp['grafico'] = gerar_grafico_linha(row['hist'], row['vol_hist'], row['ticker'])
                a_comp['radar'] = gerar_radar_chart(a_comp)
                sent_txt, sent_cor = analisar_sentimento_noticias(row['ticker'])
                a_comp['sentimento_txt'] = sent_txt
                a_comp['sentimento_cor'] = sent_cor
                blacklist.append(a_comp)
                dados_plot.append({
                    "ticker": row['ticker'], 
                    "perf": row['perf'], 
                    "volatilidade": row['vol'], 
                    "cor": "#e06a5a",  # <- Mantém o código de cor original que lá tens (verde, amarelo, vermelho ou cinza)
                    "roe": f"{a_comp.get('roe', 0)*100:.1f}%",
                    "margem": f"{a_comp.get('margem', 0)*100:.1f}%"
                })
            else:
                # O CAPTADOR DA ZONA CINZENTA (BAIXA TENDÊNCIA, FUNDAMENTAIS MEDÍOCRES)
                a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, "Quarentena")
                a_comp['position_size'] = calcular_position_sizing(a_comp)
                a_comp['badges'] = calcular_badges_ativo(a_comp)
                a_comp['sazonalidade'] = calcular_sazonalidade(a_comp['ticker'])
                a_comp['grafico'] = gerar_grafico_linha(row['hist'], row['vol_hist'], row['ticker'])
                a_comp['radar'] = gerar_radar_chart(a_comp)
                sent_txt, sent_cor = analisar_sentimento_noticias(row['ticker'])
                a_comp['sentimento_txt'] = sent_txt
                a_comp['sentimento_cor'] = sent_cor
                quarentena.append(a_comp)
                dados_plot.append({
                    "ticker": row['ticker'], 
                    "perf": row['perf'], 
                    "volatilidade": row['vol'], 
                    "cor": "#8a94a8",  # <- Mantém o código de cor original que lá tens (verde, amarelo, vermelho ou cinza)
                    "roe": f"{a_comp.get('roe', 0)*100:.1f}%",
                    "margem": f"{a_comp.get('margem', 0)*100:.1f}%"
                })

    graf_disp = gerar_grafico_dispersao(dados_plot)
    graf_backtest = gerar_grafico_backtest(fechos)
    corr_tier_a = avaliar_correlacao_carteira(tier_a, fechos)
    
    # === MAPEAMENTO SETORIAL DO UNIVERSO (PADRÃO GICS) ===
    universo_setorial = {
        "Technology": {"nome": "Tecnologia", "tickers": []},
        "Healthcare": {"nome": "Saúde", "tickers": []},
        "Financial Services": {"nome": "Serviços Financeiros", "tickers": []},
        "Consumer Cyclical": {"nome": "Consumo Discricionário", "tickers": []},
        "Consumer Defensive": {"nome": "Bens Básicos", "tickers": []},
        "Industrials": {"nome": "Indústria", "tickers": []},
        "Energy": {"nome": "Energia", "tickers": []},
        "Utilities": {"nome": "Utilities", "tickers": []},
        "Real Estate": {"nome": "Imobiliário", "tickers": []},
        "Basic Materials": {"nome": "Materiais Básicos", "tickers": []},
        "Communication Services": {"nome": "Comunicações", "tickers": []},
        "Unknown": {"nome": "Sem Classificação (ETFs/Outros)", "tickers": []}
    }
    
    # Varre a lista mestre original que puxaste do ficheiro TXT
    for ticker in tickers:
        f = cache_fundamentais.get(ticker, {})
        setor_raw = f.get('setor', 'Unknown')
        
        if setor_raw in universo_setorial:
            universo_setorial[setor_raw]["tickers"].append(ticker)
        else:
            universo_setorial["Unknown"]["tickers"].append(ticker)
            
    # Ordena alfabeticamente para leitura rápida e limpa setores residuais vazios
    for s in universo_setorial:
        universo_setorial[s]["tickers"].sort()
    
    if not universo_setorial["Unknown"]["tickers"]:
        del universo_setorial["Unknown"]

    # Retorna também a quarentena
    return tier_a, tier_b, quarentena, blacklist, graf_disp, graf_backtest, market_movers, corr_tier_a, alertas_excecao, dados_breadth, breadth_macro, universo_setorial
     

# ==========================================
# MÓDULO HISTÓRICO: FORWARD TESTING
# ==========================================
def gravar_historico_auditoria(tier_a, tier_b):
    """Grava as sinalizações num CSV para Forward Testing implacável"""
    ficheiro_csv = "historico_sinalizacoes.csv"
    novos_registos = []
    data_atual = datetime.now().strftime("%Y-%m-%d")
    
    for a in tier_a:
        novos_registos.append([data_atual, a['ticker'], "Tier A", a['perf'], a['conv'], a['position_size']])
    for a in tier_b:
        novos_registos.append([data_atual, a['ticker'], "Tier B", a['perf'], a['conv'], a['position_size']])
        
    if novos_registos:
        df_novos = pd.DataFrame(novos_registos, columns=["Data", "Ticker", "Tier", "Perf_6M_Reg", "Conviccao", "Peso_Sugerido"])
        if os.path.exists(ficheiro_csv):
            df_novos.to_csv(ficheiro_csv, mode='a', header=False, index=False)
        else:
            df_novos.to_csv(ficheiro_csv, index=False)
        print(f"-> Base da Verdade Atualizada: {len(novos_registos)} ativos registados para auditoria futura.")

def calcular_market_breadth(fechos, tickers):
    """
    Calcula a amplitude interna do mercado (Advancing/Declining, New Highs/Lows, SMAs).
    """
    adv = 0
    dec = 0
    nh = 0
    nl = 0
    ab_50 = 0
    bl_50 = 0
    ab_200 = 0
    bl_200 = 0
    total_validos = 0

    for ticker in tickers:
        try:
            # Ignora índices para não viciar a contagem de ações individuais
            if ticker not in fechos.columns or ticker in ['SPY', '^VIX', 'QQQ']:
                continue
            
            hist = fechos[ticker].dropna()
            # Precisamos de pelo menos 252 sessões (1 ano de trading) para New Highs/Lows
            if len(hist) < 200:
                continue
            
            total_validos += 1
            hoje = hist.iloc[-1]
            ontem = hist.iloc[-2]
            
            # 1. Advancing / Declining (Sessão Atual)
            if hoje > ontem:
                adv += 1
            elif hoje < ontem:
                dec += 1
                
            # 2. New Highs / New Lows (52 semanas / 252 dias)
            max_52w = hist.tail(252).max()
            min_52w = hist.tail(252).min()
            
            # Usamos uma margem de proximidade de 1% para capturar falsos rompimentos ou toques
            if hoje >= max_52w * 0.99:
                nh += 1
            if hoje <= min_52w * 1.01:
                nl += 1
                
            # 3. Tendência Estrutural (SMA 50 e 200)
            m50 = hist.tail(50).mean()
            m200 = hist.tail(200).mean()
            
            if hoje > m50: ab_50 += 1
            else: bl_50 += 1
            
            if hoje > m200: ab_200 += 1
            else: bl_200 += 1
            
        except Exception:
            continue

    # Função auxiliar de proteção contra divisão por zero
    def calc_pct(val):
        return round((val / total_validos) * 100, 1) if total_validos > 0 else 0

    return {
        "total": total_validos,
        "adv": {"val": adv, "pct": calc_pct(adv)},
        "dec": {"val": dec, "pct": calc_pct(dec)},
        "nh": {"val": nh, "pct": calc_pct(nh)},
        "nl": {"val": nl, "pct": calc_pct(nl)},
        "ab50": {"val": ab_50, "pct": calc_pct(ab_50)},
        "bl50": {"val": bl_50, "pct": calc_pct(bl_50)},
        "ab200": {"val": ab_200, "pct": calc_pct(ab_200)},
        "bl200": {"val": bl_200, "pct": calc_pct(bl_200)}
    }


# ==========================================
# MÓDULO 4: COMPILADOR HTML
# ==========================================
def analisar_destaques_pedido(tickers_str):
    """Processa os tickers pedidos no terminal (ex: JMT.LS,BRK-B,TSLA)"""
    tickers = tickers_str.upper().split(',')
    destaques = []
    
    print(f"\n=== A processar Destaques a Pedido: {tickers} ===")
    
    # Injeção forçada do SPY para garantir o cálculo do Alpha nos destaques
    tickers_globais = list(set(tickers + ['SPY']))
    # Alterado para 2y
    dados_raw = yf.download(tickers_globais, period="2y", progress=False, threads=False)
    
    if len(tickers_globais) == 1:
        fechos = pd.DataFrame({tickers_globais[0]: dados_raw['Close']}).dropna(how='all')
        volumes = pd.DataFrame({tickers_globais[0]: dados_raw['Volume']}).dropna(how='all')
    else:
        # Remoção do ffill global
        fechos = dados_raw['Close'].dropna(how='all')
        volumes = dados_raw['Volume'].dropna(how='all')

    # Calcula performance base do mercado para a Força Relativa de forma limpa
    try:
        spy_limpo = fechos['SPY'].dropna()
        perf_spy_6m = ((spy_limpo.iloc[-1] / spy_limpo.iloc[-125]) - 1) * 100 if len(spy_limpo) >= 125 else 0
    except:
        perf_spy_6m = 0

    

    for ticker in tickers:
        try:
            if ticker not in fechos.columns or fechos[ticker].dropna().empty:
                print(f"Aviso: Sem dados para {ticker}")
                continue
                
            hist = fechos[ticker].dropna()
            vol = volumes[ticker].dropna()
            if len(hist) < 200:
                print(f"Aviso: Histórico insuficiente (<200 dias) para {ticker}")
                continue
            
            # Audita os dados primeiro
            f = auditar_fundamentais(ticker)
            preco_live = f.get('preco_live')
            
            # Injeta a cotação live com proteção contra duplicação de datas
            if preco_live and preco_live > 0 and round(preco_live, 2) != round(hist.iloc[-1], 2):
                hoje_str = datetime.now().strftime('%Y-%m-%d')
                ultima_data_str = hist.index[-1].strftime('%Y-%m-%d')
                
                if ultima_data_str == hoje_str:
                    hist.iloc[-1] = preco_live
                else:
                    nova_data = hist.index[-1] + pd.Timedelta(days=1)
                    hist.loc[nova_data] = preco_live
                    vol.loc[nova_data] = vol.iloc[-1]

            perf_6m = ((hist.iloc[-1] - hist.iloc[-125]) / hist.iloc[-125]) * 100
            volatilidade = hist.pct_change().std() * np.sqrt(252) * 100
            mdd = ((hist - hist.cummax()) / hist.cummax()).min() * 100
            alpha_6m = perf_6m - perf_spy_6m
            
            a_comp = {"ticker": ticker, "perf": perf_6m, "alpha": alpha_6m, "vol": volatilidade, "mdd": mdd, "hist": hist, "vol_hist": vol, **f}
            a_comp['earnings_trend'] = f.get('earnings_trend', 0)
            
            preco_atual = hist.iloc[-1]
            target_mean = f.get('target_mean', 0)
            a_comp['upside'] = ((target_mean / preco_atual) - 1) * 100 if target_mean and preco_atual else 0
            
            # tier_simulado = "A" if f.get('roe', 0) > 0.15 else "B"

            # Extrai as métricas fundamentais e técnicas
            # (Ajusta as chaves 'roe' e 'vs_m200' para os nomes exatos que já usas nos teus dicionários)
            # A versão corrigida com os nomes reais (assumindo que 'f' guarda tudo)
            roe = f.get('roe', 0)
            # O histórico de preços cru é usado para calcular a distância autêntica
            preco_atual = hist.iloc[-1]
            m200_atual = hist.rolling(window=200).mean().iloc[-1]
            distancia_m200 = ((preco_atual / m200_atual) - 1) * 100
            roe = f.get('roe', 0) 

            # Nova Árvore de Decisão: O Filtro Rígido
            if roe > 0.15 and distancia_m200 > 0:
                tier_simulado = "Tier A"
                justificacao_nlg = "um perfil focado em forte momento e eficiência operacional superior."
            elif roe > 0.15 and distancia_m200 <= 0:
                tier_simulado = "Quarentena"
                justificacao_nlg = "uma divergência severa: o balanço apresenta solidez, mas o mercado está a rejeitar o ativo tecnicamente (faca em queda)."
            elif roe <= 0.15 and distancia_m200 > 0:
                tier_simulado = "Especulativo"
                justificacao_nlg = "um rali impulsionado puramente por momento técnico, carecendo de forte suporte estrutural nos fundamentais."
            else:
                tier_simulado = "Lixo/Evitar"
                justificacao_nlg = "uma degradação dupla: ineficiência operacional combinada com uma tendência descendente secular. Ausência de catalisadores."


            # Constrói o parágrafo de leitura dinamicamente
            texto_leitura = (
                f"O ativo encontra-se a {distancia_m200}% da M200. "
                f"A geometria do radar e a avaliação cruzada justificam a sua classificação no grupo [{tier_simulado}]: "
                f"{justificacao_nlg}"
            )

            # ADICIONAR O MOTOR AQUI:
            txt_fundo, txt_tatica = gerar_analise_profunda_nlg(a_comp)
            a_comp['analise_fundo_txt'] = txt_fundo
            a_comp['analise_tatica_txt'] = txt_tatica

            a_comp['leitura'], a_comp['reservas'], a_comp['conv'] = gerar_texto_nlg(a_comp, tier_simulado)
            a_comp['position_size'] = calcular_position_sizing(a_comp)
            a_comp['badges'] = calcular_badges_ativo(a_comp)
            a_comp['sazonalidade'] = calcular_sazonalidade(ticker)
            
            a_comp['grafico'] = gerar_grafico_linha(hist, vol, ticker)
            a_comp['radar'] = gerar_radar_chart(a_comp)
            sent_txt, sent_cor = analisar_sentimento_noticias(ticker)
            a_comp['sentimento_txt'] = sent_txt; a_comp['sentimento_cor'] = sent_cor
            
            destaques.append(a_comp)
        except Exception as e:
            print(f"Erro ao processar {ticker}: {e}")

    # CORREÇÃO APLICADA AQUI:
            
    return destaques

def formatar_numero(valor, formato="{:.1f}", multiplicador=1.0, sufixo="", fallback="N/D"):
    """
    Tenta converter qualquer lixo que a API envie num número e formata-o.
    Se falhar, devolve o valor de fallback (ex: "N/D").
    """
    try:
        # Rejeita nulos ou strings vazias imediatamente
        if valor is None or valor == "":
            return fallback
            
        # Converte para decimal e aplica multiplicadores (ex: * 100 para %)
        numero_real = float(valor) * multiplicador
        
        # Aplica a máscara de formatação pedida e junta o sufixo
        return formato.format(numero_real) + sufixo
        
    except (ValueError, TypeError):
        return fallback

def formatar_tabela(acoes):
    formatadas = []
    for a in acoes:
        # 1. ESTADO NEUTRO (Garante que as variáveis existem sempre)
        preco_real = None
        var_pct = None
        d_m50 = None
        d_m200 = None
        d_max52 = None
        rsi_atual = None
        stop_price = None
        stop_dist_pct = None
        earnings_warning = False  # <- AQUI. Fica imune ao IF.
    # --- EXTRAÇÃO DA COTAÇÃO, VARIAÇÃO DIÁRIA E RAIO-X TÉCNICO ---
        if 'hist' in a and len(a['hist']) >= 200:
            preco_real = a['hist'].iloc[-1]
            preco_ant = a['hist'].iloc[-2]
            var_pct = ((preco_real / preco_ant) - 1) * 100
            
            # Cálculo de Médias e Distâncias
            m50 = a['hist'].rolling(window=50).mean().iloc[-1]
            m200 = a['hist'].rolling(window=200).mean().iloc[-1]
            max52 = a['hist'].tail(252).max()
            
            d_m50 = ((preco_real / m50) - 1) * 100
            d_m200 = ((preco_real / m200) - 1) * 100
            d_max52 = ((preco_real / max52) - 1) * 100
            
            # Cálculo instantâneo do RSI (14d)
            delta = a['hist'].diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down
            rsi_serie = 100 - (100 / (1 + rs))
            rsi_atual = rsi_serie.iloc[-1]
        # Matemática da Fuga (Proxy de ATR - 2.5 Desvios Padrão)
            retornos_20d = a['hist'].tail(20).pct_change().dropna()
            stop_dist_pct = retornos_20d.std() * 2.5
            stop_price = preco_real * (1 - stop_dist_pct)
        # ... dentro do loop das acoes ...
        #    next_earn = a.get('next_earnings')
        #    earnings_warning = False
        #    if next_earn:
        #        # Converte timestamp UNIX para data e compara com hoje
        #        dt_earn = datetime.fromtimestamp(next_earn)
        #        dias_para_earnings = (dt_earn - datetime.now()).days
        #        if 0 <= dias_para_earnings <= 20:
        #            earnings_warning = True
        else:
            preco_real = a['hist'].iloc[-1] if 'hist' in a else 0
            var_pct, d_m50, d_m200, d_max52, rsi_atual = 0.0, 0.0, 0.0, 0.0, 50.0
            stop_dist_pct, stop_price = 0.05, preco_real * 0.95

        # 3. EXTRAÇÃO DE EARNINGS (Independente dos 200 dias de histórico)
        next_earn = a.get('next_earnings')
        if next_earn:
            try:
                dt_earn = datetime.fromtimestamp(next_earn)
                dias_para_earnings = (dt_earn - datetime.now()).days
                if 0 <= dias_para_earnings <= 20:
                    earnings_warning = True
            except (ValueError, TypeError):
                pass

        # Cores Dinâmicas
        if var_pct > 0: var_cor = "var(--verde)"
        elif var_pct < 0: var_cor = "var(--vermelho)"
        else: var_cor = "var(--mudo)"
        
        # 1. Verificar se o histórico de preços existe para esta ação
        if 'hist' not in a or a['hist'] is None or a['hist'].empty:
            # Se não há histórico, não vale a pena tentar formatar preços, RSI, médias móveis, etc.
            # Podes registar a ação como falhada ou atribuir valores "N/D" a tudo.
            preco_atual_seguro = "N/D"
            # O ideal seria usares um `continue` para saltar esta ação no loop se for um erro crítico.
        else:
            # Se existe histórico, extrai o preço com segurança
            try:
                preco_atual_bruto = a['hist'].iloc[-1]
                preco_atual_seguro = f"{float(preco_atual_bruto):.2f}"
            except (IndexError, ValueError, TypeError):
                preco_atual_seguro = "N/D"

        cor_rsi = "var(--vermelho)" if rsi_atual > 70 else "var(--verde)" if rsi_atual < 30 else "var(--texto)"

        #vol_width = min(100, max(0, a.get('vol', 0)))
        
        # 1. Recupera o valor, garante que é texto e remove sinais de percentagem
        # vol_bruto = str(a.get('vol', 0)).replace('%', '').strip()
        
        # --- 1. SANITIZAÇÃO DA VOLATILIDADE ---
        vol_bruto = str(a.get('vol', 0)).replace('%', '').strip()
        try:
            vol_num = float(vol_bruto)
        except ValueError:
            vol_num = 0
        # A variável volta a ter o nome que usas na linha 1666
        vol_width = min(100, max(0, vol_num))

        # --- 2. SANITIZAÇÃO DO MAXIMUM DRAWDOWN ---
        mdd_bruto = str(a.get('mdd', 0)).replace('%', '').strip()
        try:
            mdd_num = float(mdd_bruto)
        except ValueError:
            mdd_num = 0
        # A variável volta a ter o nome que usas na linha 1666
        mdd_width = min(100, max(0, abs(mdd_num)))

        # --- 3. SANITIZAÇÃO DO ROE ---
        roe_bruto = str(a.get('roe', 0)).replace('%', '').strip()
        try:
            roe_num = float(roe_bruto)
        except ValueError:
            roe_num = 0
        # A variável volta a ter o nome que usas na linha 1666
        roe_width = min(100, max(0, roe_num))
        
        # Percentil P/E
        eps = a.get('eps', 0)
        if eps > 0 and 'hist' in a:
            pe_serie = a['hist'] / eps
            pe_min, pe_max, pe_med = pe_serie.min(), pe_serie.max(), pe_serie.median()
            pe_pctl = ((pe_serie.iloc[-1] - pe_min) / (pe_max - pe_min)) * 100 if pe_max > pe_min else 50
        else:
            pe_pctl, pe_min, pe_max, pe_med = -1, 0, 0, 0

        # Limpeza da Sazonalidade (Corte seguro no fecho da tag)
        saz_raw = a.get('sazonalidade', '')
        if "</strong>" in saz_raw:
            saz_limpa = saz_raw.split("</strong>", 1)[1].replace("</b>", "").strip()
        else:
            saz_limpa = saz_raw
            
        # Força da tendência de Lucros (Earnings Revision Speed)
        etrend = a.get('earnings_trend', 0)
        #cor_trend = "var(--verde)" if etrend > 0 else "var(--vermelho)" if etrend < 0 else "var(--texto)"
        # 1. Recuperar e sanitizar a chave exata instanciada pelo yfinance
        etrend_bruto = str(a.get('earnings_trend', 0)).replace('%', '').replace('+', '').strip()
        try:
            etrend_num = float(etrend_bruto)
        except ValueError:
            etrend_num = 0

        # 2. Aplicar a lógica da cor com o número limpo (etrend_num)
        cor_trend = "var(--verde)" if etrend_num > 0 else "var(--vermelho)" if etrend_num < 0 else "var(--texto)"

        # --- 4. SANITIZAÇÃO DA PERFORMANCE ---
        perf_bruto = str(a.get('perf', 0)).replace('%', '').replace('+', '').strip()
        try:
            perf_num = float(perf_bruto)
        except ValueError:
            perf_num = 0.0

        # --- 5. SANITIZAÇÃO DO ALPHA ---
        alpha_bruto = str(a.get('alpha', 0)).replace('%', '').replace('+', '').strip()
        try:
            alpha_num = float(alpha_bruto)
        except ValueError:
            alpha_num = 0.0

        try:
            debt_bruto = float(a.get('debt_eq', 0))
        except (ValueError, TypeError):
            # Se vier texto ou falhar, assumes 0 (ou outro valor de segurança) para o Jinja não estoirar
            debt_bruto = 0.0


    # --- CÁLCULO DINÂMICO DOS EARNINGS ---
        next_earn = a.get('next_earnings')
        data_curta = "N/A"  # <-- 1. Variável segura criada por defeito
        
        if next_earn:
            try:
                dt_earn = datetime.fromtimestamp(next_earn)
                data_curta = dt_earn.strftime("%d/%m")  # <-- 2. A data só é formatada se não houver erro
                
                dias_para_earnings = (dt_earn - datetime.now()).days
                data_str = dt_earn.strftime("%d/%m/%Y")
                
                if dias_para_earnings < 0:
                    earn_txt = f"Já apresentados (Data: {data_str})."
                    earn_cor = "var(--mudo)"
                elif dias_para_earnings <= 7:
                    earn_txt = f"{data_str} 🔴 ALERTA: Faltam {dias_para_earnings} dias (Risco de Gap)."
                    earn_cor = "var(--vermelho)"
                elif dias_para_earnings <= 30:
                    earn_txt = f"{data_str} 🟡 Aproximação: Faltam {dias_para_earnings} dias."
                    earn_cor = "var(--amarelo)"
                else:
                    earn_txt = f"{data_str} 🟢 Seguro: Faltam {dias_para_earnings} dias."
                    earn_cor = "var(--verde)"
            except:
                earn_txt = "Erro na leitura da API."
                earn_cor = "var(--mudo)"
        else:
            earn_txt = "Indisponível (Sem dados oficiais no Yahoo Finance)."
            earn_cor = "var(--mudo)"


        # Forçar a conversão de forma segura antes de colocar no dicionário
        try:
            margem_limpa = f"{float(a.get('margem', 0)) * 100:.1f}%"
        except (ValueError, TypeError):
            margem_limpa = "N/D"

        try:
            pe_limpo = f"{float(a.get('pe_fwd', 0)):.1f}x"
        except (ValueError, TypeError):
            pe_limpo = "N/D"

        try:
            # Tenta converter o que a API enviou para um decimal real
            upside_bruto = float(a.get('upside', 0))
            if upside_bruto != 0:
                upside_limpo = f"{upside_bruto:+.1f}%"
            else:
                upside_limpo = "N/A"
        except (ValueError, TypeError):
            # Se a API enviar "N/A", "-" ou qualquer outro texto anómalo
            upside_limpo = "N/A"

        try:
            debt_eq_bruto = float(a.get('debt_eq', 0))
            debt_eq_limpo = f"{debt_eq_bruto:.2f}x"
        except (ValueError, TypeError):
            debt_eq_limpo = "N/D"

        try:
            margem_liq_limpa = f"{float(a.get('margem_liq', 0)) * 100:.1f}%"
        except (ValueError, TypeError):
            margem_liq_limpa = "N/D"

        # Proteger o cálculo do stop_price contra a ausência de histórico
        try:
            # Tenta ir buscar o preço de fecho
            preco_fecho = float(a['hist'].iloc[-1])
            # Calcula o stop e formata
            stop_price_seguro = f"{(preco_fecho * (1 - stop_dist_pct)):.2f}"
        except (KeyError, IndexError, ValueError, TypeError):
            # Se não houver 'hist' ou se os dados forem inválidos
            stop_price_seguro = "N/D"

        # --- SANITIZAÇÃO DE FLUXOS OCULTOS ---
        spct = a.get('short_pct')
        ipct = a.get('insider_pct')
        
        try:
            spct_val = float(spct) if pd.notna(spct) else 0.0
        except:
            spct_val = 0.0
            
        try:
            ipct_val = float(ipct) if pd.notna(ipct) else 0.0
        except:
            ipct_val = 0.0
        
        if spct_val > 0:
            short_str = f"{spct_val * 100:.1f}%"
            short_cor = "#b388ff" if spct_val > 0.15 else "var(--texto)"
        else:
            short_str = "N/D"
            short_cor = "var(--mudo)"
            
        if ipct_val > 0:
            insider_str = f"{ipct_val * 100:.1f}%"
            insider_cor = "var(--azul)"
        else:
            insider_str = "N/D"
            insider_cor = "var(--mudo)"

        formatadas.append({
            "ticker": a['ticker'], "setor": a['setor'], "perf": f"{perf_num:.1f}%",
            "alpha": f"{alpha_num:+.1f}%", # <-- NOVO (Alpha Puro)
            "cor_alpha": "var(--verde)" if alpha_num > 0 else "var(--vermelho)",
            #"vol": f"{float(a['vol']):.1f}%", "mdd": f"{float(a['mdd']):.1f}%", "roe": f"{float(a['roe']) * 100:.1f}%",
            "vol": f"{float(str(a['vol']).replace('%', '').strip()):.1f}%",
            "mdd": f"{float(str(a['mdd']).replace('%', '').strip()):.1f}%",
            "roe": f"{roe_num * 100:.1f}%",  # <- INJEÇÃO DO ROE CORRIGIDO AQUI
            "margem": margem_limpa, "pe_fwd": pe_limpo, 
            "leitura": a.get('leitura', ''), "reservas": a.get('reservas', ''), "conv": a.get('conv', 0), 
            "grafico": a.get('grafico', ''), "radar": a.get('radar', ''),
            "position_size": a.get('position_size', 0),
            "sent_txt": a.get('sentimento_txt', ''), "sent_cor": a.get('sentimento_cor', ''),
            "badges": a.get('badges', []), "nome": a.get('nome', a['ticker']), "industria": a.get('industria', ''),      
            "vol_w": vol_width, "mdd_w": mdd_width, "roe_w": roe_width, 
            #"upside": f"{a.get('upside', 0):+.1f}%" if a.get('upside', 0) != 0 else "N/A",
            "upside": upside_limpo, 
            "upside_raw": a.get('upside', 0),
            #"debt_eq": f"{a.get('debt_eq', 0):.2f}x", "debt_raw": a.get('debt_eq', 0),
            "debt_eq": debt_eq_limpo, "debt_raw": debt_bruto,                                              
            #"margem_liq": f"{a.get('margem_liq', 0) * 100:.1f}%",
            "margem_liq": margem_liq_limpa,
            
            # Em vez da formatação direta que estala com texto, usas o filtro:
            "adv": formatar_numero(a.get('adv'), formato="{:.1f}", sufixo="M"),
            "earnings_trend": formatar_numero(etrend, formato="{:+.1f}", sufixo="%"),
            "pe_min_fmt": formatar_numero(pe_min, formato="{:.1f}"),
            "pe_med_fmt": formatar_numero(pe_med, formato="{:.1f}"),
            "pe_max_fmt": formatar_numero(pe_max, formato="{:.1f}"),
            "var_dia": formatar_numero(var_pct, formato="{:+.2f}", sufixo="%"),
            "d_m50": formatar_numero(d_m50, formato="{:+.1f}", sufixo="%"),
            "d_m200": formatar_numero(d_m200, formato="{:+.1f}", sufixo="%"),
            "d_max52": formatar_numero(d_max52, formato="{:+.1f}", sufixo="%"),
            # ... e por aí fora para todas as variáveis numéricas.
            
            "short_pct": short_str,
            "short_cor": short_cor,
            "insider_pct": insider_str,
            "insider_cor": insider_cor,
                                    
            "pe_pctl": pe_pctl, "pe_pctl_fmt": f"{pe_pctl:.0f}%" if pe_pctl != -1 else "N/A",                     
            "preco_atual": preco_atual_seguro,
            "moeda": a.get('moeda', 'USD'),
            "var_cor": var_cor,
            "cor_m50": "var(--verde)" if d_m50 > 0 else "var(--vermelho)", "cor_m200": "var(--verde)" if d_m200 > 0 else "var(--vermelho)",   
            "rsi": f"{rsi_atual:.1f}", "cor_rsi": cor_rsi,
            "sazonalidade_texto": saz_limpa,
            "recom": a.get('recom', 'N/A'),
            "stop_pct": f"{(stop_dist_pct * 100):.1f}%",
            #"stop_price": f"{(a['hist'].iloc[-1] * (1 - stop_dist_pct)):.2f}",
            "stop_price": stop_price_seguro,
            "cor_trend": cor_trend,
            "analise_fundo_txt": a.get('analise_fundo_txt', 'Sem dados de fundo.'),
            "analise_tatica_txt": a.get('analise_tatica_txt', 'Sem dados táticos.'),
            "earnings_warning": earnings_warning,
            "next_earn_date": data_curta,
            "earn_txt": earn_txt,           # <-- NOVO
            "earn_cor": earn_cor            # <-- NOVO
        })
    return formatadas





html_template = """
<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<title>Radar Quantitativo States - Seleção do Discord  - {{ data }}</title>

<!-- METADADOS OPEN GRAPH PARA DISCORD/REDES SOCIAIS a imagem fica neste bloco-->
<meta property="og:title" content="Radar States -" {{ data }}/>
<meta property="og:description" content="Relatório de mercado algorítmico. Avaliação de risco, matrizes de contágio e momentum institucional." />
<meta property="og:image" content="https://lmorreis-cell.github.io/newsletter/21mar26.jpg" />
<meta property="og:type" content="website" />
<meta name="theme-color" content="#3fbf8f"> <!-- Opcional: Pinta a barra lateral da embed no Discord com a tua cor verde -->

<style>
    :root{--fundo:#0b0e14;--painel:#151a23;--linha:#232d3f;--texto:#d7dce6;--mudo:#8a94a8;
          --verde:#3fbf8f; --amarelo:#f0b90b; --vermelho:#e06a5a; --azul:#4da6ff; --painel-dark:#0e121a;}
    body{background:var(--fundo);color:var(--texto);font-family: -apple-system, sans-serif; padding:40px; line-height: 1.6;}
    main{max-width:1100px;margin:0 auto}
    h1{font-size: 26px; margin-bottom: 5px; color: #fff;}
    .data{color: var(--mudo); font-size: 14px; margin-bottom: 30px;}
    .painel-destaque { margin-bottom: 25px; }
    .card-risco { background: var(--painel); border-left: 5px solid {{ risco.cor }}; padding: 25px; border-radius: 6px; }
    .card-risco h2 { margin: 0 0 10px 0; font-size: 20px; }
    .metricas { display: flex; gap: 20px; font-size: 14px; color: var(--mudo); margin-top: 15px; border-top: 1px solid var(--linha); padding-top: 15px; }
    .metricas span strong { color: var(--texto); }
    .legenda-edu { font-size: 12px; color: var(--mudo); margin-top: 15px; border-top: 1px dashed var(--linha); padding-top: 12px; text-align: justify; line-height: 1.5; }
    .legenda-edu strong { color: var(--texto); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;}
    
    .grid-graficos { display: flex; gap: 20px; margin-bottom: 40px; }
    .card-dashboard { background: var(--painel); padding: 15px; border-radius: 6px; text-align: center; flex: 1; display: flex; align-items: center; justify-content: center; min-height: 250px;}
    .card-dashboard img { max-width: 100%; height: auto; border-radius: 4px; }
    
    .seccao{margin-bottom: 40px;}
    .seccao-titulo{font-size: 18px; padding-bottom: 5px; border-bottom: 1px solid var(--linha); margin-bottom: 5px;}
    .seccao-subtitulo{font-size: 13px; color: var(--mudo); margin-bottom: 15px;}
    .t-verde{color: var(--verde);} .t-amarelo{color: var(--amarelo);} .t-vermelho{color: var(--vermelho);} .t-azul{color: var(--azul);}
    
    table{width:100%;border-collapse:collapse;font-size:13px; background: var(--painel); border-radius: 6px; overflow: hidden;}
    th{text-align:left;color:var(--mudo);font-size:11px;text-transform:uppercase;padding:12px 15px;border-bottom:1px solid var(--linha);}
    td{padding:12px 15px;border-bottom:1px solid var(--linha);}
    .linha-dados{cursor: pointer; transition: background 0.2s;}
    .linha-dados:hover{background:#1a212c;}
    .ticker{font-weight: bold; color: #fff;}
    .vazio{padding: 20px; background: var(--painel); text-align: center; color: var(--mudo); border-radius: 6px;}
    
    .nlg-row{display: none; background: var(--painel-dark);}
    .conteudo-flex{display: flex; gap: 30px; padding: 25px; border-left: 3px solid var(--mudo);}
    .texto-analise{flex: 1;}
    .texto-analise p{margin: 8px 0; font-size: 13.5px;}
    .container-grafico{flex: 0 0 450px; text-align: right;}
    .container-grafico img{max-width: 100%; border-radius: 4px; border: 1px solid var(--linha);}
    .seta{color: var(--mudo); font-size: 10px; margin-right: 8px;}
    .conviccao{float: right; font-weight: bold; font-size: 13px;}

/* CONTAINER DE MÉTRICAS GLOBAIS */
.tabela-metricas {
    width: 100%;
    border-collapse: separate;
    border-spacing: 12px 0;
    margin: 20px 0;
    overflow: visible !important; /* Força a libertação dos balões para fora da tabela */
}
.card-metrica {
    display: table-cell;
    width: 33.33%;
    background: var(--painel);
    border: 1px solid var(--linha);
    border-radius: 6px;
    padding: 15px;
    vertical-align: top;
}
.metrica-label {
    font-size: 10pt;
    color: var(--mudo);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}
.metrica-valor {
    font-size: 18pt;
    font-weight: bold;
    line-height: 1.2;
    margin-bottom: 5px;
}
.metrica-status {
    font-size: 9pt;
    font-weight: 500;
}

/* BARRAS DE DADOS INLINE */
.bar-bg { 
    background: #1a212c; 
    border-radius: 2px; 
    height: 6px; 
    width: 50px; 
    display: inline-block; 
    vertical-align: middle; 
    margin-left: 10px; 
    overflow: hidden; 
}
.bar-fill { height: 100%; border-radius: 2px; transition: width 0.5s ease; }
.fill-amarelo { background: var(--amarelo); }
.fill-vermelho { background: var(--vermelho); }
.fill-verde { background: var(--verde); }
.td-flex { display: flex; align-items: center; justify-content: space-between; }


/* TOOLTIP EDUCACIONAL (HOVER) */
.dica-edu {
    position: relative;
    display: inline-block;
    cursor: help;
    border-bottom: 1px dotted var(--mudo); /* Linha tracejada subtil a indicar que é clicável/hover */
}
.dica-edu .dica-texto {
    visibility: hidden;
    width: 320px;
    background-color: var(--painel-dark);
    color: var(--texto);
    text-align: left;
    border: 1px solid var(--linha);
    border-radius: 6px;
    padding: 15px;
    position: absolute;
    z-index: 100;
    bottom: 130%; /* Posiciona o balão por cima do texto */
    left: 50%;
    transform: translateX(-50%);
    opacity: 0;
    transition: opacity 0.3s, bottom 0.3s;
    font-size: 11.5px;
    font-weight: normal;
    line-height: 1.5;
    box-shadow: 0px 8px 16px rgba(0,0,0,0.6);
    pointer-events: none; /* Evita falhas no rato */
}
/* A pequena seta a apontar para baixo */
.dica-edu .dica-texto::after {
    content: "";
    position: absolute;
    top: 100%;
    left: 50%;
    margin-left: -6px;
    border-width: 6px;
    border-style: solid;
    border-color: var(--linha) transparent transparent transparent;
}
.dica-edu:hover .dica-texto {
    visibility: visible;
    opacity: 1;
    bottom: 140%; /* Efeito de levitação suave */
}
/* Variante para tooltips no topo do ecrã (Abrem para baixo) */
.dica-edu.dica-desce .dica-texto {
    bottom: auto;
    top: 130%;
}
.dica-edu.dica-desce:hover .dica-texto {
    bottom: auto;
    top: 145%; /* Efeito de levitação para baixo */
}
/* Inverte a seta para apontar para cima */
.dica-edu.dica-desce .dica-texto::after {
    top: auto;
    bottom: 100%;
    border-color: transparent transparent var(--linha) transparent;
}

/* Variante para tooltips colados à margem esquerda (Crescem para a direita) */
.dica-edu.dica-ancora-esq .dica-texto {
    left: 0;
    transform: none; /* Remove a centralização forçada */
}
/* Reposiciona a seta para apontar para a esquerda da caixa */
.dica-edu.dica-ancora-esq .dica-texto::after {
    left: 30px; 
    margin-left: 0;
}

/* Variante para tooltips colados à margem direita (Crescem para a esquerda) */
.dica-edu.dica-ancora-dir .dica-texto {
    left: auto;
    right: 0;
    transform: none;
}
.dica-edu.dica-ancora-dir .dica-texto::after {
    left: auto;
    right: 15px; 
    margin-left: 0;
}

/* MARCA DE ÁGUA INSTITUCIONAL */
.marca-agua {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: -1;
    pointer-events: none;
    user-select: none;
    /* O SVG abaixo desenha o texto e repete-o em blocos de 300x300 pixels */
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Ctext x='50%25' y='50%25' transform='rotate(-35 150 150)' dominant-baseline='middle' text-anchor='middle' font-family='Arial, sans-serif' font-size='20' font-weight='900' fill='rgba(255, 255, 255, 0.08)'%3EPartilha de Ideias - Luís Reis%3C/text%3E%3C/svg%3E");
    
    background-repeat: repeat;
}

.badge-alerta-vermelho {
    background-color: var(--vermelho, #d9534f); /* Usa a tua variável de vermelho ou o fallback */
    color: #ffffff;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    margin-left: 10px;
    vertical-align: middle;
    display: inline-block;
    box-shadow: 0 0 8px rgba(217, 83, 79, 0.4);
    letter-spacing: 0.5px;
}

</style>
    <script>
        function toggleRow(id, setaId) {
            var el = document.getElementById(id);
            var seta = document.getElementById(setaId);
            if(el.style.display === 'table-row') { el.style.display = 'none'; seta.innerHTML = '▶'; } 
            else { el.style.display = 'table-row'; seta.innerHTML = '▼'; }
        }
    </script>
    </head>
    <body>
    
    <!-- INJEÇÃO DA MARCA DE ÁGUA -->
    <div class="marca-agua"></div>
    
    
    <main>
      <header style="padding-bottom: 15px; border-bottom: 1px solid var(--linha); margin-bottom: 30px;">
    
    <!-- PRIMEIRA LINHA: Título à esquerda, Autor à direita -->
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 15px;">
        <div>
            <h1 style="margin: 0; font-size: 26px; color: #fff; letter-spacing: -0.5px; text-transform: uppercase;">Radar Quantitativo States - Seleção do Discord</h1>
            <div style="color: var(--mudo); font-size: 13px; margin-top: 5px; font-weight: 500;">Relatório de Mercado gerado a {{ data }}</div>
        </div>
        
        <div style="text-align: right; background: var(--painel); padding: 8px 15px; border-radius: 4px; border: 1px solid var(--linha);">
            <div style="font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--mudo); margin-bottom: 2px;">Engenharia Quantitativa</div>
            <div style="font-size: 14px; font-weight: bold; color: var(--azul);">Luís Reis</div>
        </div>
    </div>
    
    <!-- SEGUNDA LINHA: Disclaimer por baixo, a ocupar a largura toda -->
    <div style="font-size: 11px; color: var(--mudo); text-align: justify; line-height: 1.4; border-top: 1px dashed var(--linha); padding-top: 10px;">
        <p style="margin: 0;"><strong>Isenção de Responsabilidade (Disclaimer):</strong> O conteúdo deste relatório gerado automaticamente por via algorítmica destina-se exclusivamente a fins informativos e educacionais. Nenhuma das informações, métricas ou sugestões de dimensionamento de posição aqui expostas constitui uma recomendação de compra, venda ou investimento em ativos financeiros. O mercado de capitais envolve riscos elevados e perdas potenciais de capital. Cabe ao utilizador validar os dados e tomar decisões de forma independente.</p>
    </div>
    
</header>

      <div class="painel-destaque">
          <div class="card-risco">
              <h2 style="color: #fff; margin: 0 0 10px 0; font-size: 20px;">Regime Atual: 
                  <span class="dica-edu dica-desce" style="color: {{ risco.cor }}; border-bottom: 2px dotted {{ risco.cor }}; padding-bottom: 2px;">
                      {{ risco.regime }}
                      <span class="dica-texto" style="width: 450px; font-weight: normal; text-transform: none; font-size: 12px;">
                          <strong style="color: #fff; font-size: 13px; display: block; margin-bottom: 8px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Matriz de Risco (Termómetro)</strong>
                          O algoritmo cruza 4 pilares de stress: Volatilidade (VIX), Tendência (M50), Amplitude Interna e a Curva de Juros.<br><br>
                          <span style="color: var(--verde);">■ CONSTRUTIVO (0 Alertas):</span> Máxima alocação. Mercado saudável.<br>
                          <span style="color: var(--amarelo);">■ NEUTRO (1 Alerta):</span> Atrito inicial. Elevar exigência de qualidade.<br>
                          <span style="color: #f28b24;">■ CAUTELA (2 Alertas):</span> Risco elevado. Focar apenas em valor profundo.<br>
                          <span style="color: var(--vermelho);">■ DEFENSIVO (3-4 Alertas):</span> Risco de colapso. Fechar posições fracas e acumular liquidez.
                      </span>
                  </span>
              </h2>
              <p style="font-size: 15px;">{{ risco.aviso }}</p>
              <div class="metricas">
                  <span>VIX: <strong>{{ risco.vix }}</strong></span>
                  <span>S&P 500: <strong>{{ risco.spy }}</strong></span>
                  <span>Amplitude: <strong>{{ risco.amplitude }}</strong></span>
                  
                  <span class="dica-edu dica-desce" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                      Curva de Juros (10Y-3M): <strong style="color: {{ risco.curva_cor }};">{{ risco.curva }} ({{ risco.curva_status }})</strong>
                      <span class="dica-texto" style="width: 400px;">
                          <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Spread da Curva de Juros (10Y vs 3M)</strong>
                          Mede a diferença de rendimento entre obrigações do Tesouro EUA a 10 anos e 3 meses. É a métrica mãe da saúde macroeconómica.<br><br>
                          <span style="color: var(--verde);">■ Spread Positivo (&gt; 0%):</span> Curva normal. Os investidores exigem mais juros por emprestar a longo prazo. Cenário saudável de crescimento económico.<br><br>
                          <span style="color: var(--vermelho);">■ Spread Negativo (&lt; 0%):</span> CURVA INVERTIDA. O mercado aceita receber menos juros a longo prazo porque antecipa um colapso económico ou cortes drásticos de taxas pela Fed. Antecedeu todas as grandes recessões modernas.
                      </span>
                  </span>
              </div>
              <div class="legenda-edu"><strong>Mecânica:</strong> {{ risco.nlg }}</div>
          </div>
      </div>

    <!-- MARKET MOVERS DA CARTEIRA & ÍNDICES -->
      {% if movers and (movers.gainers or movers.losers) %}
      <div style="display: flex; gap: 20px; margin-bottom: 25px;">
      
          <div style="flex: 1; background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 15px;">
              <h3 style="margin: 0 0 10px 0; color: var(--verde); font-size: 13px; text-transform: uppercase; border-bottom: 1px solid var(--linha); padding-bottom: 8px;">🚀 Top Vencedores (24h)</h3>
              <table style="width: 100%; font-size: 13px; background: transparent;">
                  {% for g in movers.gainers %}
                  <tr><td style="padding: 6px 0; border-bottom: 1px dashed var(--linha); color: #fff; font-weight: bold;">{{ g.ticker }}</td><td style="text-align: right; border-bottom: 1px dashed var(--linha); color: var(--verde);">+{{ g.perf }}%</td></tr>
                  {% endfor %}
              </table>
          </div>
          <div style="flex: 1; background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 15px;">
              <h3 style="margin: 0 0 10px 0; color: var(--vermelho); font-size: 13px; text-transform: uppercase; border-bottom: 1px solid var(--linha); padding-bottom: 8px;">🩸 Top Perdedores (24h)</h3>
              <table style="width: 100%; font-size: 13px; background: transparent;">
                  {% for l in movers.losers %}
                  <tr><td style="padding: 6px 0; border-bottom: 1px dashed var(--linha); color: #fff; font-weight: bold;">{{ l.ticker }}</td><td style="text-align: right; border-bottom: 1px dashed var(--linha); color: var(--vermelho);">{{ l.perf }}%</td></tr>
                  {% endfor %}
              </table>
          </div>




        




          <div style="flex: 1; background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 15px;">
              <h3 style="margin: 0 0 10px 0; color: var(--azul); font-size: 13px; text-transform: uppercase; border-bottom: 1px solid var(--linha); padding-bottom: 8px;">🌐 Índices Globais (24h)</h3>
              <table style="width: 100%; font-size: 13px; background: transparent;">
                  {% for idx in indices %}
                  <tr>
                      <td style="padding: 6px 0; border-bottom: 1px dashed var(--linha); color: #fff; font-weight: bold;">{{ idx.nome }}</td>
                      <td style="text-align: right; border-bottom: 1px dashed var(--linha); font-weight: bold; color: {% if idx.perf > 0 %}var(--verde){% elif idx.perf < 0 %}var(--vermelho){% else %}var(--mudo){% endif %};">
                          {% if idx.perf > 0 %}+{% endif %}{{ idx.perf }}%
                      </td>
                  </tr>
                  {% endfor %}
              </table>
          </div>

      <div style="flex: 1.2; background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 15px; display: flex; flex-direction: column; justify-content: space-between;">
              <h3 style="margin: 0 0 10px 0; color: #b388ff; font-size: 13px; text-transform: uppercase; border-bottom: 1px solid var(--linha); padding-bottom: 8px;">🧠 Fluxo Institucional</h3>
              
              <div style="margin-bottom: 12px;">
                  <div style="display: flex; justify-content: space-between; align-items: baseline;">
                      <span class="dica-edu dica-desce dica-ancora-dir" style="font-size: 11px; color: var(--mudo); border-bottom: 1px dotted var(--mudo); cursor: help;">
                          CURVA DO VIX (Institucionais)
                          <span class="dica-texto" style="width: 320px; font-weight: normal; text-transform: none;">
                              <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Contango vs Backwardation</strong>
                              Divide o VIX a 30 dias pelo VIX a 3 meses.<br><br>
                              Se &gt; 1.0 (Backwardation): Institucionais estão em pânico a pagar um prémio absurdo por proteção imediata. O mercado vai sangrar.<br>
                              Se &lt; 1.0 (Contango): Estado normal de complacência. Seguro de curto prazo é barato.
                          </span>
                      </span>
                      <span style="font-size: 13px; font-weight: bold; color: {{ fluxo.vix_cor }};">{{ fluxo.vix_val }}x <span style="font-size: 10px;">{{ fluxo.vix_status }}</span></span>
                  </div>
                  <div style="margin-top: 8px; position: relative; height: 6px; background: linear-gradient(90deg, var(--verde), var(--amarelo), var(--vermelho)); border-radius: 3px;">
                      <div style="position: absolute; top: -3px; left: {{ fluxo.vix_pct }}; width: 4px; height: 12px; background: #fff; border-radius: 2px; box-shadow: 0 0 4px #000; transform: translateX(-50%);"></div>
                  </div>
              </div>

              <div style="margin-bottom: 12px;">
                  <div style="display: flex; justify-content: space-between; align-items: baseline;">
                      <span class="dica-edu dica-desce dica-ancora-dir" style="font-size: 11px; color: var(--mudo); border-bottom: 1px dotted var(--mudo); cursor: help;">
                          FEAR & GREED (Ações)
                          <span class="dica-texto" style="width: 320px; font-weight: normal; text-transform: none;">
                              <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Índice Tradicional (CNN)</strong>
                              Mede a emoção do retalho e fundos tradicionais no mercado de ações (0-100).<br><br>
                              Valores extremos (Vermelho) indicam ganância cega (risco de topo). Valores baixos (Roxo/Azul) indicam pânico generalizado (oportunidade de compra contrária).
                          </span>
                      </span>
                      <span style="font-size: 13px; font-weight: bold; color: {{ fluxo.cnn_cor }};">{{ fluxo.cnn_val }}/100 <span style="font-size: 10px;">{{ fluxo.cnn_status }}</span></span>
                  </div>
                  <div style="margin-top: 8px; position: relative; height: 6px; background: linear-gradient(90deg, #b388ff, var(--azul), var(--amarelo), var(--verde), var(--vermelho)); border-radius: 3px;">
                      <div style="position: absolute; top: -3px; left: {{ fluxo.cnn_pct }}; width: 4px; height: 12px; background: #fff; border-radius: 2px; box-shadow: 0 0 4px #000; transform: translateX(-50%);"></div>
                  </div>
              </div>

              <div>
                  <div style="display: flex; justify-content: space-between; align-items: baseline;">
                      <span class="dica-edu dica-desce dica-ancora-dir" style="font-size: 11px; color: var(--mudo); border-bottom: 1px dotted var(--mudo); cursor: help;">
                          FEAR & GREED (Cripto)
                          <span class="dica-texto" style="width: 320px; font-weight: normal; text-transform: none;">
                              <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Índice Especulativo Extreme</strong>
                              O canário na mina de carvão. O mercado de criptoativos não fecha e reage instantaneamente aos choques de liquidez globais.<br><br>
                              Mede a pura especulação de risco. Se os especuladores estão em "Extreme Greed" (Vermelho), a liquidez está no limite.
                          </span>
                      </span>
                      <span style="font-size: 13px; font-weight: bold; color: {{ fluxo.cripto_cor }};">{{ fluxo.cripto_val }}/100 <span style="font-size: 10px;">{{ fluxo.cripto_status }}</span></span>
                  </div>
                  <div style="margin-top: 8px; position: relative; height: 6px; background: linear-gradient(90deg, #b388ff, var(--azul), var(--amarelo), var(--verde), var(--vermelho)); border-radius: 3px;">
                      <div style="position: absolute; top: -3px; left: {{ fluxo.cripto_pct }}; width: 4px; height: 12px; background: #fff; border-radius: 2px; box-shadow: 0 0 4px #000; transform: translateX(-50%);"></div>
                  </div>
              </div>
          </div>

              
      
      </div>
      {% endif %}
    
    <!-- CALENDÁRIO MACROECONÓMICO -->
      <div class="seccao" style="margin-top: 25px; margin-bottom: 25px;">
          <div style="background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 20px;">
              <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--linha); padding-bottom: 10px; margin-bottom: 15px;">
                  <div>
                      <h3 style="margin: 0; color: #fff; font-size: 16px; text-transform: uppercase; letter-spacing: 0.5px;">🌍 Escudo Macro (Vigilância de Catalisadores)</h3>
                      <div style="font-size: 12px; color: var(--mudo); margin-top: 4px;">Vigiar injeções exógenas de volatilidade que anulam a Análise Técnica (Europa & EUA).</div>
                  </div>
                  <span class="dica-edu dica-ancora-dir" style="background: var(--painel-dark); border: 1px solid var(--linha); padding: 6px 12px; border-radius: 4px; font-size: 11px; font-weight: bold; color: var(--amarelo); cursor: help;">
                      ⚠️ REGRA DE OURO MACRO
                      <span class="dica-texto" style="width: 320px; font-weight: normal; text-transform: none;">
                          <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">A Supremacia do Risco Macro</strong>
                          A Análise Técnica pressupõe um mercado fechado. Eventos Macro são <i>Choques Exógenos</i>.<br><br>
                          <b>Regra Algorítmica:</b> Nunca iniciar posições em ativos europeus ou americanos a menos de 24 horas da publicação destes dados. O risco de gap destrói qualquer cálculo de Stop Loss.
                      </span>
                  </span>
              </div>
              
              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px;">
                  
                  <div style="background: #1a212c; padding: 12px; border-radius: 6px; border-left: 3px solid var(--vermelho);">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                          <div style="font-size: 13px; font-weight: bold; color: #fff;">1. Inflação (CPI EUA & HICP Euro)</div>
                          <div style="background: #2d1a1a; color: var(--vermelho); border: 1px solid var(--vermelho); font-size: 9px; padding: 2px 6px; border-radius: 3px; font-weight: bold; letter-spacing: 0.5px;">PRÓX: {{ macro.inflacao }}</div>
                      </div>
                      <div style="font-size: 11.5px; color: var(--mudo); margin-top: 5px; line-height: 1.4;">Se a inflação subir, os juros mantêm-se altos, asfixiando empresas altamente alavancadas no Tier B europeu e na Quarentena. O <b>HICP</b> europeu dita o ritmo de Frankfurt; o <b>CPI</b> dita o resto do mundo.</div>
                  </div>

                  <div style="background: #1a212c; padding: 12px; border-radius: 6px; border-left: 3px solid #b388ff;">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                          <div style="font-size: 13px; font-weight: bold; color: #fff;">2. Juros (BCE & FOMC)</div>
                          <div style="background: #1a1525; color: #b388ff; border: 1px solid #b388ff; font-size: 9px; padding: 2px 6px; border-radius: 3px; font-weight: bold; letter-spacing: 0.5px;">PRÓX: {{ macro.juros }}</div>
                      </div>
                      <div style="font-size: 11.5px; color: var(--mudo); margin-top: 5px; line-height: 1.4;">Decisões institucionais do custo do capital. O discurso de Lagarde (BCE) afeta instantaneamente a liquidez e o volume de transação do STOXX 600. Evitar exposição cega técnica em dias de decisão.</div>
                  </div>

                  <div style="background: #1a212c; padding: 12px; border-radius: 6px; border-left: 3px solid var(--azul);">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                          <div style="font-size: 13px; font-weight: bold; color: #fff;">3. Atividade (PMI & NFP)</div>
                          <div style="background: #102533; color: var(--azul); border: 1px solid var(--azul); font-size: 9px; padding: 2px 6px; border-radius: 3px; font-weight: bold; letter-spacing: 0.5px;">PRÓX: {{ macro.emprego }}</div>
                      </div>
                      <div style="font-size: 11.5px; color: var(--mudo); margin-top: 5px; line-height: 1.4;">O <b>PMI da Alemanha</b> é o batimento cardíaco da indústria europeia e reverte gráficos do DAX num segundo. O <b>NFP</b> (Emprego EUA) mede a fadiga global. Se ambos colapsarem, é sinal de risco recessivo brutal.</div>
                  </div>
              </div>
          </div>
      </div>


    <!-- MARKET BREADTH (Profundidade de Mercado) -->


{% if breadth_interno %}

<div class="seccao" style="margin-top: 15px; margin-bottom: 25px;">
    
    <!-- NOVO: Indicador de Estado -->
    <div style="margin-bottom: 10px; font-size: 12px; color: var(--mudo); text-align: right;">
        <span style="padding: 2px 6px; background: var(--painel); border-radius: 4px; border: 1px solid var(--linha);">
            {{ breadth_interno.estado | default('Dados Históricos') }}
        </span>
    </div>

    



    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px;">
        
        <!-- 1. Advancing vs Declining -->
        <div style="background: var(--painel); padding: 15px; border-radius: 6px; border: 1px solid var(--linha);">
            <div class="dica-edu dica-ancora-esq" style="display: block; width: 100%; border-bottom: none; cursor: help;">
                <div class="dica-texto">
                    <strong>Advancing / Declining:</strong><br><br>Mede a participação geral do mercado (Market Breadth). Um mercado em alta saudável exige que a maioria das ações participe na subida. Se os índices principais sobem, mas o número de ações em declínio aumenta (Divergência Negativa), o movimento é frágil, sustentado por poucas empresas de grande capitalização, e propenso a reversões abruptas.
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
                    <span style="color: var(--verde);">Advancing<br><span style="font-size: 13px;">{{ breadth_interno.adv.pct }}% <span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.adv.val }})</span></span></span>
                    <span style="color: var(--vermelho); text-align: right;">Declining<br><span style="font-size: 13px;"><span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.dec.val }})</span> {{ breadth_interno.dec.pct }}%</span></span>
                </div>
            </div>
            <div style="width: 100%; height: 6px; background: var(--vermelho); border-radius: 3px; overflow: hidden; display: flex;">
                <div style="width: {{ breadth_interno.adv.pct }}%; height: 100%; background: var(--verde);"></div>
            </div>
        </div>

        <!-- 2. New Highs vs New Lows (52w) -->
        <div style="background: var(--painel); padding: 15px; border-radius: 6px; border: 1px solid var(--linha);">
            <div class="dica-edu" style="display: block; width: 100%; border-bottom: none; cursor: help;">
                <div class="dica-texto">
                    <strong>New High / New Low:</strong><br><br>Mede extremos de força e fraqueza estrutural. A expansão de Novos Máximos confirma que o apetite por risco está intacto e lidera o mercado. Um pico repentino em Novos Mínimos, mesmo com o índice estável, revela que o capital institucional está a liquidar posições debaixo da superfície. Valores acima de 10% em Novos Mínimos exigem postura defensiva.
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
                    <span style="color: var(--verde);">New High<br><span style="font-size: 13px;">{{ breadth_interno.nh.pct }}% <span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.nh.val }})</span></span></span>
                    <span style="color: var(--vermelho); text-align: right;">New Low<br><span style="font-size: 13px;"><span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.nl.val }})</span> {{ breadth_interno.nl.pct }}%</span></span>
                </div>
            </div>
            <div style="width: 100%; height: 6px; background: var(--vermelho); border-radius: 3px; overflow: hidden; display: flex;">
                <div style="width: {{ breadth_interno.nh.pct }}%; height: 100%; background: var(--verde);"></div>
            </div>
        </div>

        <!-- 3. Acima vs Abaixo SMA50 -->
        <div style="background: var(--painel); padding: 15px; border-radius: 6px; border: 1px solid var(--linha);">
            <div class="dica-edu" style="display: block; width: 100%; border-bottom: none; cursor: help;">
                <div class="dica-texto">
                    <strong>Above / Below SMA 50:</strong><br><br>Mede o momentum tático. Se >50% do mercado negoceia acima da sua média de 50 dias, o viés de médio prazo é de alta. Valores extremos (>85%) indicam sobrecompra generalizada, elevando o risco de correções iminentes. Valores extremamente baixos (<15%) assinalam pânico e potenciais zonas de capitulação e ressalto.
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
                    <span style="color: var(--verde);">Above SMA50<br><span style="font-size: 13px;">{{ breadth_interno.ab50.pct }}% <span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.ab50.val }})</span></span></span>
                    <span style="color: var(--vermelho); text-align: right;">Below SMA50<br><span style="font-size: 13px;"><span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.bl50.val }})</span> {{ breadth_interno.bl50.pct }}%</span></span>
                </div>
            </div>
            <div style="width: 100%; height: 6px; background: var(--vermelho); border-radius: 3px; overflow: hidden; display: flex;">
                <div style="width: {{ breadth_interno.ab50.pct }}%; height: 100%; background: var(--verde);"></div>
            </div>
        </div>

        <!-- 4. Acima vs Abaixo SMA200 -->
        <div style="background: var(--painel); padding: 15px; border-radius: 6px; border: 1px solid var(--linha);">
            <div class="dica-edu dica-ancora-dir" style="display: block; width: 100%; border-bottom: none; cursor: help;">
                <div class="dica-texto">
                    <strong>Above / Below SMA 200:</strong><br><br>O derradeiro barómetro de regime de mercado. Um Bull Market secular exige que a esmagadora maioria (>60%) dos ativos se mantenha acima da sua média de 200 dias. Uma queda sustentada desta métrica para níveis inferiores a 40% confirma um regime de Bear Market ou distribuição institucional pesada, invalidando estratégias clássicas.
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
                    <span style="color: var(--verde);">Above SMA200<br><span style="font-size: 13px;">{{ breadth_interno.ab200.pct }}% <span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.ab200.val }})</span></span></span>
                    <span style="color: var(--vermelho); text-align: right;">Below SMA200<br><span style="font-size: 13px;"><span style="font-weight: normal; font-size: 11px; color: var(--mudo);">({{ breadth_interno.bl200.val }})</span> {{ breadth_interno.bl200.pct }}%</span></span>
                </div>
            </div>
            <div style="width: 100%; height: 6px; background: var(--vermelho); border-radius: 3px; overflow: hidden; display: flex;">
                <div style="width: {{ breadth_interno.ab200.pct }}%; height: 100%; background: var(--verde);"></div>
            </div>
        </div>

    </div>
</div>
{% endif %}


    <!-- RELATÓRIO DE EXCEÇÃO DIÁRIO (FLOW LAYOUT AUTO-EQUILIBRADO) -->
      {% if excecoes %}
      <div class="seccao" style="margin-top: 10px; margin-bottom: 35px;">
          <div style="background: var(--painel); border: 1px solid var(--linha); border-radius: 6px; padding: 20px;">
              <div style="border-bottom: 1px solid var(--linha); padding-bottom: 10px; margin-bottom: 20px;">
                  <h3 style="margin: 0; color: #fff; font-size: 16px; text-transform: uppercase; letter-spacing: 0.5px;">⚡ Exception Report (24h)</h3>
                  <div style="font-size: 12px; color: var(--mudo); margin-top: 4px;">Anomalias algorítmicas, quebras de suporte e choques de volume detetados na sessão.</div>
              </div>
              
              <!-- Pré-verificação de existência de dados para gerir o layout sem falhas -->
              {% set ns_verde = namespace(encontrou=false) %}
              {% set ns_risco = namespace(encontrou=false) %}
              {% for alerta in excecoes %}
                  {% if alerta.cor == 'var(--verde)' %}{% set ns_verde.encontrou = true %}{% endif %}
                  {% if alerta.cor != 'var(--verde)' %}{% set ns_risco.encontrou = true %}{% endif %}
              {% endfor %}

              <!-- SECÇÃO 1: GATILHOS BULLISH (Linha contínua) -->
              {% if ns_verde.encontrou %}
              <div style="margin-bottom: {% if ns_risco.encontrou %}25px{% else %}0{% endif %};">
                  <h4 style="color: var(--verde); font-size: 13px; margin-top: 0; margin-bottom: 12px; border-bottom: 1px solid #23863640; padding-bottom: 5px;">▲ GATILHOS BULLISH</h4>
                  
                  <!-- CSS Grid que adapta o número de colunas à largura disponível do ecrã -->
                  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">
                      {% for alerta in excecoes %}
                          {% if alerta.cor == 'var(--verde)' %}
                          <div style="background: #0d1117; padding: 12px; border-radius: 6px; border: 1px solid var(--linha); border-left: 3px solid var(--verde);">
                              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                  <!-- <span style="font-weight: 800; color: #fff; font-size: 14px;">{{ alerta.ticker }}</span> -->
                                  <span class="dica-edu dica-desce" style="font-weight: 800; color: #fff; font-size: 14px; border-bottom: 1px dotted var(--mudo); cursor: help;">
    {{ alerta.ticker }}
    <span class="dica-texto" style="width: auto; min-width: 150px; white-space: nowrap; font-weight: bold; font-size: 12px; color: #fff; text-transform: none; text-align: center; padding: 8px 12px;">
        {{ alerta.nome }}
    </span>
</span>
                                  <span style="background: {{ alerta.cor }}1a; color: {{ alerta.cor }}; border: 1px solid {{ alerta.cor }}4d; padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{{ alerta.tipo }}</span>
                              </div>
                              <div style="font-size: 12px; color: #8b949e; line-height: 1.4;">{{ alerta.desc }}</div>
                          </div>
                          {% endif %}
                      {% endfor %}
                  </div>
              </div>
              {% endif %}

              <!-- SECÇÃO 2: RISCO & FRAQUEZA (Linha contínua) -->
              {% if ns_risco.encontrou %}
              <div>
                  <h4 style="color: var(--vermelho); font-size: 13px; margin-top: 0; margin-bottom: 12px; border-bottom: 1px solid #da363340; padding-bottom: 5px;">▼ RISCO & FRAQUEZA</h4>
                  
                  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px;">
                      {% for alerta in excecoes %}
                          {% if alerta.cor != 'var(--verde)' %}
                          <div style="background: #0d1117; padding: 12px; border-radius: 6px; border: 1px solid var(--linha); border-left: 3px solid {{ alerta.cor }};">
                              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                  <!-- <span style="font-weight: 800; color: #fff; font-size: 14px;">{{ alerta.ticker }}</span> -->

                                  <span class="dica-edu dica-desce" style="font-weight: 800; color: #fff; font-size: 14px; border-bottom: 1px dotted var(--mudo); cursor: help;">
    {{ alerta.ticker }}
    <span class="dica-texto" style="width: auto; min-width: 150px; white-space: nowrap; font-weight: bold; font-size: 12px; color: #fff; text-transform: none; text-align: center; padding: 8px 12px;">
        {{ alerta.nome }}
    </span>
</span>

                                  <span style="background: {{ alerta.cor }}1a; color: {{ alerta.cor }}; border: 1px solid {{ alerta.cor }}4d; padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{{ alerta.tipo }}</span>
                              </div>
                              <div style="font-size: 12px; color: #8b949e; line-height: 1.4;">{{ alerta.desc }}</div>
                          </div>
                          {% endif %}
                      {% endfor %}
                  </div>
              </div>
              {% endif %}
              
          </div>
      </div>
      {% endif %}

    <div style="display: flex; margin-bottom: 20px; width: 100%;">
          <div class="seccao">
    <div class="seccao-titulo">Mapa de Risco e Retorno</div>
    <div class="seccao-subtitulo">Passe o cursor sobre os pontos para isolar a performance exata e a classificação algorítmica de cada ativo. Arraste para fazer zoom nas zonas de maior densidade.</div>
    
    <!-- O filtro 'safe' é estritamente obrigatório para o Python não quebrar as tags HTML geradas pelo Plotly -->
    <div class="grafico-container" style="border: 1px solid var(--borda); border-radius: 8px; overflow: hidden; background: #0d1117; margin-bottom: 15px;">
        {{ g_disp | safe }}
    </div>
    
    <div class="nota-tecnica" style="font-size: 12px; color: var(--mudo); border-top: 1px dashed var(--borda); padding-top: 10px;">
        <strong>A MATEMÁTICA:</strong> O Eixo Y avalia o lucro, o Eixo X mede o "preço" pago sob a forma de oscilações bruscas (Volatilidade). O quadrante ideal é o Superior Esquerdo. Ações no extremo direito sofrem de 'Risco de Ruína'.
    </div>
</div>
      </div>
      
      <div class="grid-graficos" style="margin-bottom: 40px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
          <!-- 1. Concentração Setorial (Donut Original) -->
          <div class="card-dashboard" style="flex-direction: column; align-items: stretch; justify-content: space-between;">
              <div style="text-align: center; width: 100%;">
                  {% if graf_setores.img %}<img src="{{ graf_setores.img }}" alt="Exposição Setorial">{% endif %}
              </div>
              <div class="legenda-edu">
                  <strong>Alojamento Macro:</strong> {{ graf_setores.nlg }}<br><br>
                  <span class="dica-edu">
                      <strong style="color: {{ correlacao.cor }};">AUDITORIA CONTÁGIO:</strong>
                      <span class="dica-texto">Valores &gt; 0.70 indicam Risco Sistémico. A carteira move-se em bloco.</span>
                  </span> {{ correlacao.valor }}
              </div>
          </div>

          <!-- 2. Rotação Setorial RRG (O Novo Motor) -->
          <div class="card-dashboard" style="flex-direction: column; align-items: stretch; justify-content: flex-start;">
              <div style="text-align: center; width: 100%; margin-bottom: 10px;">
                  {% if grafico_rrg.img %}<img src="{{ grafico_rrg.img }}" alt="Rotação RRG">{% endif %}
              </div>
              <div class="legenda-edu" style="text-align: left; margin-top: 0;">
                  <span class="dica-edu dica-desce">
                      <strong>FLUXO INTELIGENTE (RRG):</strong>
                      <span class="dica-texto" style="width: 350px;">
                          <strong style="color: #fff; font-size: 12px; display: block; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">A Viagem do Capital</strong>
                          O Eixo X (Força Relativa) e o Eixo Y (Momentum) revelam para onde as "baleias" estão a mover o dinheiro. Quadrantes à direita significam liderança; quadrantes acima significam aceleração de compras.
                      </span>
                  </span><br><br>
                  <p style="margin-top: 0; margin-bottom: 15px; text-align: justify;">{{ grafico_rrg.nlg | safe }}</p>

                  <details style="border-top: 1px dashed #2d333b; padding-top: 12px;">
                      <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
                          <span style="color: var(--azul); font-size: 14px;">▸</span> ANATOMIA DA ROTAÇÃO
                      </summary>
                      
                      <div style="margin-top: 12px; font-size: 11.5px; line-height: 1.6; color: #c9d1d9; background: rgba(13, 17, 23, 0.5); padding: 15px; border-radius: 6px; border-left: 3px solid var(--azul);">
                          <strong style="color: #fff; display: block; margin-bottom: 8px;">O Ciclo Institucional:</strong>
                          O capital nunca dorme, apenas muda de setor. Num ciclo completo, o dinheiro viaja sempre no sentido dos ponteiros do relógio através de 4 fases matemáticas:<br><br>
                          
                          <span style="color: var(--verde); font-weight: bold;">1. LÍDERES (Top-Right):</span> Forte Momentum e Forte Preço. O setor está a esmagar o mercado base. Aqui mora a euforia.<br><br>
                          
                          <span style="color: var(--amarelo); font-weight: bold;">2. A ENFRAQUECER (Bottom-Right):</span> O preço ainda está alto (Força > 100), mas o Momentum quebrou. Os institucionais pararam de comprar e começaram a distribuir lucros (vender) secretamente ao retalho.<br><br>
                          
                          <span style="color: var(--vermelho); font-weight: bold;">3. ATRASADOS (Bottom-Left):</span> Capitulação total. Preço esmagado e sem ignição. Ninguém quer exposição a este setor.<br><br>
                          
                          <span style="color: var(--azul); font-weight: bold;">4. A MELHORAR (Top-Left):</span> <b>A Zona de Ouro.</b> O preço ainda está a transacionar abaixo da média (Barato), mas o Momentum disparou de forma anómala (>100). O <i>Smart Money</i> começou a acumular estas ações a desconto para preparar o próximo ciclo de Liderança.
                      </div>
                  </details>
              </div>
          </div>

          <!-- 3. Walk-Forward Backtest (Original) -->
          <div class="card-dashboard" style="flex-direction: column; align-items: stretch; justify-content: space-between;">
              <div style="text-align: center; width: 100%;">
                  {% if graf_backtest.img %}<img src="{{ graf_backtest.img }}" alt="Backtest">{% endif %}
              </div>
              <div class="legenda-edu">
                  <span class="dica-edu dica-desce dica-ancora-dir">
                      <strong>TESTE DE STRESS:</strong>
                      <span class="dica-texto" style="width: 350px;">Simulação cega. Ignora o futuro e testa as métricas do algoritmo há 6 meses atrás. Prova matemática de Alfa autêntico.</span>
                  </span><br><br>
                  {{ graf_backtest.nlg | safe }}
              </div>
          </div>
      </div>
      

    <table class="tabela-metricas">
      <tr>
        <td class="card-metrica" style="border-left: 4px solid var(--amarelo);">
          <div class="metrica-status" style="color: var(--mudo);">Regime Atual: <span style="color: var(--texto); font-weight: bold;">{{ risco.regime }}</span></div>
          <div class="metrica-status" style="color: var(--mudo); margin-top: 6px; border-top: 1px dashed var(--linha); padding-top: 4px;">
              <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">Curva Juros (10Y-3M)
                  <span class="dica-texto" style="width: 250px;"><strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Motor de Liquidez Institucional</strong>O ditador do risco de recessão. Subtrai a yield do Tesouro a 3 Meses à yield a 10 Anos. Uma curva abaixo de 0 (Invertida) sinaliza asfixia de liquidez.</span>
              </span>: 
              <span style="color: {{ curva.cor }}; font-weight: bold;">{{ curva.valor }} ({{ curva.status }})</span>
          </div>
          
        </td>

        <td class="card-metrica" style="border-left: 4px solid var(--azul);">
          <div class="metrica-label">
              <span class="dica-edu dica-desce" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                  ALOCAÇÃO DA CARTEIRA
                  <span class="dica-texto" style="width: 280px; text-transform: none; letter-spacing: normal;">
                      <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Exposição Tática</strong>
                      A soma do "Position Sizing" recomendado para os ativos. O algoritmo calcula o peso ótimo de cada ação através da matemática de Kelly, penalizada ativamente pelo seu "Risco de Ruína" histórico (Max Drawdown). O remanescente é liquidez de proteção.
                  </span>
              </span>
          </div>
          <div class="metrica-status" style="color: var(--mudo);">Liquidez em Reserva: <span style="color: var(--verde); font-weight: bold;">{{ carteira.liquidez }}%</span></div>
          <div class="metrica-status" style="color: var(--mudo); margin-top: 6px; border-top: 1px dashed var(--linha); padding-top: 4px;">
              <span class="dica-edu dica-desce" style="border-bottom: 1px dotted var(--mudo); cursor: help;">Matriz Correlação (Tier A)
                  <span class="dica-texto" style="width: 260px;"><strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Auditoria de Risco Direcional</strong>Cruza a matriz matemática entre todas as ações do Tier A. Valores &gt; 0.65 indica que a tua carteira sofre de sobrecarga fatorial (vai colapsar toda ao mesmo tempo numa rotação de mercado).</span>
              </span>: 
              <span style="color: {{ correlacao.cor }}; font-weight: bold;">{{ correlacao.valor }} ({{ correlacao.status }})</span>
          </div>
        </td>

        <td class="card-metrica" style="border-left: 4px solid var(--verde);">
          <!-- Exemplo da estrutura do teu KPI Card -->
    <div class="kpi-box">
        <div class="kpi-box">
        <div class="kpi-titulo">
            <span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">
                SCREENER ATIVOS
                <span class="dica-texto">Volume total de cotadas auditadas na sessão. Um mercado saudável apresenta um rácio equilibrado; um mercado em correção empurra a massa de ativos para a Quarentena ou Blacklist.</span>
            </span>
        </div>
        
        <div class="kpi-valor" style="color: var(--verde);">{{ total_ativos }}</div>
        
        <div class="kpi-sub" style="font-size: 11px; margin-top: 5px;">
            <span style="color: var(--verde);">↑ {{ q_a }} Tier A</span> | 
            <span style="color: var(--amarelo);">↓ {{ q_b }} Tier B</span> <br>
            <span style="color: var(--mudo); margin-top: 3px; display: inline-block;">⚪ {{ q_q }} Quarentena</span> | 
            <span style="color: var(--vermelho);">🔴 {{ q_bl }} Blacklist</span>
        </div>
    </div>
          <!--<div class="metrica-valor t-verde">{{ screener.total_ativos }}</div>
          div class="metrica-status" style="color: var(--mudo);"><span class="t-verde">↑ {{ screener.tier_a }} Tier A</span> | <span class="t-amarelo">↓ {{ screener.tier_b }} Tier B</span></div> -->
        </td>
      </tr>
    </table>
    <div style="margin-bottom: 30px; background: var(--painel); padding: 15px; border-radius: 6px; border: 1px solid var(--linha);">
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
              <span class="dica-edu dica-desce" style="font-weight: bold; font-size: 12px; color: var(--mudo); border-bottom: 1px dotted var(--mudo); cursor: help;">
                  LARGURA DE MERCADO (BREADTH SETORIAL)
                  <span class="dica-texto" style="width: 350px; font-weight: normal; text-transform: none;">
                      <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Participação Interna da Economia</strong>
                      O algoritmo audita a força dos 11 ETFs Setoriais do S&P 500 (Tecnologia, Saúde, Energia, etc).<br><br>
                      Se o mercado subir mas a barra de Breadth estiver vermelha/amarela, é um "falso rally" carregado por poucas empresas gigantes. Se a barra for verde (maioria dos setores acima da sua M200), a expansão de capital é estrutural e segura.
                  </span>
              </span>
              <span style="font-weight: bold; color: {{ breadth.cor }}; font-size: 13px;">{{ breadth.status }} ({{ breadth.num }}/{{ breadth.total }} Setores &gt; M200)</span>
          </div>
          <div style="background: #1a212c; height: 6px; border-radius: 3px; overflow: hidden; width: 100%;">
               <div style="height: 100%; width: {{ breadth.largura }}; background: {{ breadth.cor }}; transition: width 1s ease-in-out;"></div> 
              <!-- <div style="height: 100%; width: {{ barras_sp500.largura }}; background: {{ breadth.cor }}; transition: width 1s ease-in-out;"></div> -->
          </div>
          
      </div>
    {% if destaques %}
      <div class="seccao">
          <div class="seccao-titulo t-azul">🔎 Destaques Analisados a Pedido</div>
          <div class="seccao-subtitulo">Ativos específicos solicitados via terminal.</div>
          <table>
            <thead><tr>
              <th>Ticker</th><th>Setor</th><th>Notícias</th>
              <th>
                  <span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">6M Perf (Alpha)<span class="dica-texto" style="width:280px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Alpha Relativo vs S&P 500</strong><br>Mede o desempenho real do ativo descontando a subida do mercado. Se o Alpha for positivo (Verde), a ação está a gerar Alpha real; se for negativo (Vermelho), é um ativo fraco que está a render menos que o índice passivo.</span></span>
              </th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Vol<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Volatilidade Anualizada</strong><br>Mede o "batimento cardíaco" da ação. Valores altos exigem <em>stops</em> mais largos e tamanhos de posição menores.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Max Drawdown<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Perda Máxima (1 Ano)</strong><br>A maior queda do topo ao fundo. Mede o "Risco de Ruína" histórico. Drawdowns altos destroem a composição do capital.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">ROE<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Return on Equity</strong><br>A medida pura da eficiência: quanto lucro o negócio gera por cada euro de capital. Acima de 15% indica vantagem competitiva real.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Margem Op<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Margem Operacional</strong><br>O fosso do negócio. De cada 100€ de vendas, quanto sobra após os custos. Margens altas protegem a empresa contra a inflação.</span></span></th>
              <th><span class="dica-edu dica-desce dica-ancora-dir" style="border-bottom:1px dotted var(--mudo); cursor:help;">P/E Fwd<span class="dica-texto" style="width:260px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Múltiplo Projetado</strong><br>O custo do bilhete de entrada: quanto pagas hoje pelos lucros do próximo ano. Valores muito altos não perdoam desilusões.</span></span></th>
            </tr></thead>
            <tbody>
              {% for a in destaques %}
              <tr class="linha-dados" onclick="toggleRow('nlg-dest-{{ a.ticker }}', 'seta-dest-{{ a.ticker }}')">
                <td class="ticker">
                    <div style="display: flex; align-items: center;">
                        <span class="seta" id="seta-dest-{{ a.ticker }}">▶</span>
                        <span style="font-size: 14px;">{{ a.ticker }}</span>
                    </div>
                    {% if a.badges %}
                    <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; margin-left: 16px;">
                        {% for b in a.badges %}
                        <span class="dica-edu dica-ancora-esq" style="border-bottom: none; cursor: help; margin-right: 4px;">
                            <span style="background: {{ b.bg }}; color: {{ b.cor }}; font-size: 8.5px; padding: 2px 5px; border-radius: 3px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid {{ b.cor }}33; white-space: nowrap;">{{ b.txt }}</span>
                            <span class="dica-texto" style="width: 250px; text-transform: none; letter-spacing: normal; font-weight: normal; margin-bottom: 5px;">
                                <strong style="color: {{ b.cor }}; font-size: 11px; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{{ b.txt }}</strong>
                                {{ b.desc }}
                            </span>
                        </span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </td>
                <td style="color:var(--mudo)">{{ a.setor }}</td><td style="font-weight: bold; color: {{ a.sent_cor }};">{{ a.sent_txt }}</td>
                <td style="font-weight: bold; white-space: nowrap;">
                    {{ a.perf }} <span style="font-size: 11px; color: {{ a.cor_alpha }}; font-family: monospace;">({{ a.alpha }})</span>
                </td>
                <td><div class="td-flex"><span>{{ a.vol }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.vol_w }}" height="14" fill="var(--amarelo)"/></svg></div></td>
                <td><div class="td-flex"><span style="color:#e06a5a">{{ a.mdd }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.mdd_w }}" height="14" fill="var(--vermelho)"/></svg></div></td>
                <td><div class="td-flex"><span>{{ a.roe }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.roe_w }}" height="14" fill="var(--verde)"/></svg></div></td>
                <td>{{ a.margem }}</td><td>{{ a.pe_fwd }}</td>
              </tr>
              <tr id="nlg-dest-{{ a.ticker }}" class="nlg-row">
                <td colspan="9">
                    <div class="conteudo-flex" style="display: flex; gap: 20px; padding: 20px; align-items: stretch; border-left: 3px solid var(--mudo);"> 
                        
                        <div class="texto-analise" style="flex: 1.3; display: flex; flex-direction: column; gap: 12px;">
                            
                            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                <span style="background: #1a2133; color: var(--azul); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Convicção: {{ a.conv }}/100</span>
                                <span style="background: #232d3f; color: var(--verde); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Alocação: {{ a.position_size }}</span>
                                <span style="background: {% if a.upside == 'N/A' %}#151a23{% elif a.upside_raw > 0 %}#1a2b24{% else %}#2d1a1a{% endif %}; color: {% if a.upside == 'N/A' %}var(--mudo){% elif a.upside_raw > 0 %}var(--verde){% else %}var(--vermelho){% endif %}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Target: {{ a.upside }}</span>
                            </div>
                            
                            <p style="margin: 0;"><strong style="color:var(--mudo)">LEITURA:</strong> {{ a.leitura }}</p>
                            <p style="margin: 0;"><strong style="color:var(--vermelho)">RESERVAS:</strong> {{ a.reservas }}</p>

                            <!-- CÓDIGO A INSERIR ABAIXO DA DIV "RESERVAS" DO ATIVO -->

<details style="margin-top: 15px; border-top: 1px dashed #2d333b; padding-top: 15px;">
    <!-- O BOTÃO DE ABRIR/FECHAR -->
    <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
        <span style="color: #f0b90b; font-size: 14px;">▸</span> EXPANDIR DIAGNÓSTICO
    </summary>
    
    <!-- O CONTEÚDO QUE FICA ESCONDIDO ATÉ AO CLIQUE -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; cursor: default;">
        
        <!-- BLOCO 1: DIAGNÓSTICO FUNDAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Motor Fundamental
                    <span class="dica-texto" style="left: 0; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O objetivo é detetar fraudes narrativas. Usa esta secção para cruzar a qualidade real do negócio com o seu preço. Procura <i>"Assimetrias de Valor"</i> e foge de <i>"Dissonâncias"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_fundo_txt | safe }}
            </div>
        </div>

        <!-- BLOCO 2: CONTEXTO TÁTICO E COMPORTAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #3fbf8f;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Contexto Tático
                    <span class="dica-texto" style="right: 0; left: auto; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O <i>timing</i> dita a sobrevivência. Usa esta secção para decidir a ação imediata: entrar num <i>"Equilíbrio"</i>, cortar a posição devido a alta volatilidade, ou ficar de fora numa <i>"Exaustão Parabólica"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_tatica_txt | safe }}
            </div>
        </div>

    </div>
</details>
                            
                            <div style="margin-top: 5px; padding-top: 10px; border-top: 1px dashed var(--linha); display: flex; flex-direction: column; gap: 10px;">
            
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛡️ <strong style="color:var(--mudo)">RISCO CORPORATIVO & LIQUIDEZ:</strong>
                    <span class="dica-texto" style="width: 350px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Insolvência e Filtro de Liquidez ADV</strong>
                        Cruza a alavancagem com a liquidez de proteção institucional.<br><br>
                        <span style="color: var(--vermelho);">■ Dívida/CP &gt; 1.5x:</span> Alavancagem perigosa.<br>
                        <span style="color: var(--azul);">■ ADV (Average Daily Volume):</span> Volume diário médio transacionado em dólares. O robô rejeita automaticamente qualquer ativo abaixo de 10M$ para evitar perdas com spreads (slippage).
                    </span>
                </span>
                Dívida/CP: <span style="font-weight:bold; color:{% if a.debt_raw > 1.5 %}var(--vermelho){% else %}var(--texto){% endif %};">{{ a.debt_eq }}</span> 
                | M.Liq: <span style="font-weight:bold; color:var(--azul);">{{ a.margem_liq }}</span>
                | ADV: <span style="font-weight:bold; color:var(--texto);">{{ a.adv }} USD/dia</span>
            </p>

            <p style="margin: 3px 0 0 0; font-size: 12.5px; border-top: 1px dashed var(--linha); padding-top: 6px; margin-top: 6px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🕵️ <strong style="color:var(--mudo)">FLUXOS OCULTOS:</strong>
                    <span class="dica-texto" style="width: 380px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Short Interest & Posicionamento Insider</strong>
                        Mede quem está a apostar contra ou a favor da empresa com o próprio dinheiro.<br><br>
                        <span style="color: var(--vermelho);">■ Short Interest (&gt;15%):</span> Risco de volatilidade extrema. Elevada probabilidade de <i style="color:#b388ff;">Short Squeeze</i> se existirem catalisadores positivos.<br>
                        <span style="color: var(--azul);">■ Insiders (&gt;10%):</span> Positivo. A gestão detém grande parte do capital, alinhando os seus interesses com a valorização do preço da ação para o retalho.
                    </span>
                </span>
                Short Interest: <span style="font-weight:bold; color:{{ a.short_cor }};">{{ a.short_pct }}</span> 
                | Detenção Insider: <span style="font-weight:bold; color:{{ a.insider_cor }};">{{ a.insider_pct }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⚖️ <strong style="color:var(--mudo)">VALUATION & REVISIONS TREND:</strong>
                    <span class="dica-texto" style="width: 360px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Percentil de Múltiplos e Revisão de Lucros</strong>
                        Mede o prémio do preço face ao histórico e o sentido das estimativas.<br><br>
                        <span style="color: var(--verde);">■ Percentil &lt; 20%:</span> Pechincha histórica relativa.<br>
                        <span style="color: var(--verde);">■ Momentum de EPS (Growth):</span> Se o crescimento operacional estiver a acelerar (Verde), valida o prémio pago e evita armadilhas de valor (Value Traps).
                    </span>
                </span>
                Percentil P/E: <strong style="color:{% if a.pe_pctl == -1 %}var(--mudo){% elif a.pe_pctl > 80 %}var(--vermelho){% elif a.pe_pctl < 20 %}var(--verde){% else %}var(--amarelo){% endif %};">{{ a.pe_pctl_fmt }}</strong>
                | Módulo EPS Trend: <span style="font-weight:bold; color:{{ a.cor_trend }}">{{ a.earnings_trend }}</span>
            </p>
            
            {% if a.sazonalidade_texto %}
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⏳ <strong style="color:var(--mudo)">SAZONALIDADE (10A):</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sazonalidade do Mês Atual (10 Anos)</strong>
                        Auditoria estatística baseada em fluxos recorrentes de capital histórico.
                    </span>
                </span>
                {{ a.sazonalidade_texto | safe }}
            </p>
            {% endif %}

            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🎯 <strong style="color:var(--mudo)">CONSENSO ANALISTAS:</strong>
                    <span class="dica-texto" style="width: 300px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sentimento Coletivo (Sell-Side)</strong>
                        O consenso agregado dos analistas institucionais globais para esta cotada.
                    </span>
                </span>
                Recomendação Bancária: <span style="font-weight:bold; color:var(--texto);">{{ a.recom }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛑 <strong style="color:var(--mudo)">INVALIDAÇÃO TÁCTICA:</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Fuga baseada em Volatilidade Recente</strong>
                        Stop Loss Dinâmico ancorado a 2.5 desvios padrão do preço para absorver o ruído e proteger o capital contra reversões estruturais.
                    </span>
                </span>
                Stop Absoluto sugerido: <span style="font-weight:bold; color:var(--vermelho);">{{ a.stop_price }} {{ a.moeda }}</span> <span style="color:var(--mudo); font-size:11px;">(a -{{ a.stop_pct }})</span>
            </p>
        </div>
    <p></p>
    <p style="margin: 0; font-size: 12.5px;">
    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
        📅 <strong style="color:var(--mudo)">PRÓXIMOS RESULTADOS:</strong>
        <span class="dica-texto" style="width: 320px;">
            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Risco de Gap de Earnings</strong>
            Apresentação trimestral de resultados. Evitar abrir posições novas a menos de 7 dias desta data devido à volatilidade extrema e risco de gap contra a posição.
        </span>
    </span>
    Status: <span style="font-weight:bold; color:{{ a.earn_cor }};">{{ a.earn_txt }}</span>
</p><p></p>
    


                            <div style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 4px; padding: 10px 12px; font-size: 12px; margin-top: auto; width: 100%; box-sizing: border-box;">
                                <div style="color:var(--mudo); text-transform:uppercase; font-size:10px; margin-bottom: 6px; border-bottom: 1px dashed var(--linha); padding-bottom: 4px;">
                                    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                                        📡 Raio-X Técnico
                                        <span class="dica-texto" style="width: 280px;">
                                            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Força Gravitacional do Preço</strong>
                                            Mede o desvio face aos eixos centrais de suporte.<br><br>
                                            <span style="color: var(--vermelho);">Afastamentos da M50 (&gt;15%)</span> sinalizam exaustão e atraem correções (Mean Reversion).
                                        </span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>RSI (14d):</span> <strong style="color:{{ a.cor_rsi }}">{{ a.rsi }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Top 52 Sem:</span> <strong style="color:#fff">{{ a.d_max52 }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Vs Média 50d:</span> <strong style="color:{{ a.cor_m50 }}">{{ a.d_m50 }}</strong></div>
                                <div style="display:flex; justify-content:space-between;"><span>Vs Média 200d:</span> <strong style="color:{{ a.cor_m200 }}">{{ a.d_m200 }}</strong></div>
                            </div>

                            <div style="display: flex; justify-content: space-between; align-items: center; background: #11151c; border: 1px solid var(--linha); padding: 10px 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px;">
                                <div style="text-align: left; flex: 1; min-width: 0; padding-right: 8px;">
                                    <div style="font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.nome }}</div>
                                    <div style="font-size: 9px; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.industria }}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div style="text-align: right; padding-right: 10px; border-right: 1px dashed var(--linha);">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Var (24H)</div>
                                        <div style="font-size: 22px; font-weight: bold; font-family: monospace; color: {{ a.var_cor }};">{{ a.var_dia }}</div>
                                    </div>
                                    <div style="text-align: right; min-width: 65px;">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Cotação</div>
                                        <div style="font-size: 22px; font-weight: bold; color: #fff; font-family: monospace;">{{ a.preco_atual }} <span style="font-size: 9px; color: var(--mudo);">{{ a.moeda }}</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="flex: 1.5; display: flex; flex-direction: column; gap: 15px;">
         {% if a.grafico %}<img src="{{ a.grafico }}" style="width: 100%; border-radius: 4px; border: 1px solid var(--linha);">{% endif %}
         {% if a.radar %}<img src="{{ a.radar }}" style="width: 100%; border-radius: 4px;" alt="Radar">{% endif %}
    </div>
                        
                    </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
      </div>
      {% endif %}
      <div class="seccao">
          <div class="seccao-titulo t-verde">🟢 Tier A: Oportunidades (Momentum + Qualidade)</div>
          <div class="seccao-subtitulo">Líderes de mercado com forte momentum e balanço resiliente. Quadrante Ideal: Alta Força, Baixo Risco.</div>
          {% if tier_a %}
          <table>
            <thead><tr>
              <th>Ticker</th><th>Setor</th><th>Notícias</th>
              <th>
                  <span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">6M Perf (Alpha)<span class="dica-texto" style="width:280px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Alpha Relativo vs S&P 500</strong><br>Mede o desempenho real do ativo descontando a subida do mercado. Se o Alpha for positivo (Verde), a ação está a gerar Alpha real; se for negativo (Vermelho), é um ativo fraco que está a render menos que o índice passivo.</span></span>
              </th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Vol<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Volatilidade Anualizada</strong><br>Mede o "batimento cardíaco" da ação. Valores altos exigem <em>stops</em> mais largos e tamanhos de posição menores.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Max Drawdown<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Perda Máxima (1 Ano)</strong><br>A maior queda do topo ao fundo. Mede o "Risco de Ruína" histórico. Drawdowns altos destroem a composição do capital.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">ROE<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Return on Equity</strong><br>A medida pura da eficiência: quanto lucro o negócio gera por cada euro de capital. Acima de 15% indica vantagem competitiva real.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Margem Op<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Margem Operacional</strong><br>O fosso do negócio. De cada 100€ de vendas, quanto sobra após os custos. Margens altas protegem a empresa contra a inflação.</span></span></th>
              <th><span class="dica-edu dica-desce dica-ancora-dir" style="border-bottom:1px dotted var(--mudo); cursor:help;">P/E Fwd<span class="dica-texto" style="width:260px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Múltiplo Projetado</strong><br>O custo do bilhete de entrada: quanto pagas hoje pelos lucros do próximo ano. Valores muito altos não perdoam desilusões.</span></span></th>
            </tr></thead>
            <tbody>
              {% for a in tier_a %}
              <tr class="linha-dados" onclick="toggleRow('nlg-a-{{ a.ticker }}', 'seta-a-{{ a.ticker }}')">
                <td class="ticker">
                    <div style="display: flex; align-items: center;">
                        <span class="seta" id="seta-a-{{ a.ticker }}">▶</span>
                        <span style="font-size: 14px;">{{ a.ticker }}</span>
                    </div>
                    {% if a.badges %}
                    <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; margin-left: 16px;">
                        {% for b in a.badges %}
                        <span class="dica-edu dica-ancora-esq" style="border-bottom: none; cursor: help; margin-right: 4px;">
                            <span style="background: {{ b.bg }}; color: {{ b.cor }}; font-size: 8.5px; padding: 2px 5px; border-radius: 3px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid {{ b.cor }}33; white-space: nowrap;">{{ b.txt }}</span>
                            <span class="dica-texto" style="width: 250px; text-transform: none; letter-spacing: normal; font-weight: normal; margin-bottom: 5px;">
                                <strong style="color: {{ b.cor }}; font-size: 11px; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{{ b.txt }}</strong>
                                {{ b.desc }}
                            </span>
                        </span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </td>
                <td style="color:var(--mudo)">{{ a.setor }}</td>
                <td style="font-weight: bold; color: {{ a.sent_cor }};">{{ a.sent_txt }}</td>
                <td style="font-weight: bold; white-space: nowrap;">
                    {{ a.perf }} <span style="font-size: 11px; color: {{ a.cor_alpha }}; font-family: monospace;">({{ a.alpha }})</span>
                </td>
                <td><div class="td-flex"><span>{{ a.vol }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.vol_w }}" height="14" fill="var(--amarelo)"/></svg></div></td>
                <td><div class="td-flex"><span style="color:#e06a5a">{{ a.mdd }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.mdd_w }}" height="14" fill="var(--vermelho)"/></svg></div></td>
                <td><div class="td-flex"><span>{{ a.roe }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.roe_w }}" height="14" fill="var(--verde)"/></svg></div></td>
                <td>{{ a.margem }}</td><td>{{ a.pe_fwd }}</td>
              </tr>
              <tr id="nlg-a-{{ a.ticker }}" class="nlg-row">
                <td colspan="9">
                    <div class="conteudo-flex" style="display: flex; gap: 20px; padding: 20px; align-items: stretch; border-left: 3px solid var(--verde);"> 
                        
                        <div class="texto-analise" style="flex: 1.3; display: flex; flex-direction: column; gap: 12px;">
                            
                            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                <span style="background: #1a2133; color: var(--azul); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Convicção: {{ a.conv }}/100</span>
                                <span style="background: #232d3f; color: var(--verde); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Alocação: {{ a.position_size }}</span>
                                <span style="background: {% if a.upside == 'N/A' %}#151a23{% elif a.upside_raw > 0 %}#1a2b24{% else %}#2d1a1a{% endif %}; color: {% if a.upside == 'N/A' %}var(--mudo){% elif a.upside_raw > 0 %}var(--verde){% else %}var(--vermelho){% endif %}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Target: {{ a.upside }}</span>
                            </div>
                            
                            <p style="margin: 0;"><strong style="color:var(--mudo)">LEITURA:</strong> {{ a.leitura }}</p>
                            <p style="margin: 0;"><strong style="color:var(--vermelho)">RESERVAS:</strong> {{ a.reservas }}</p>

                            <!-- CÓDIGO A INSERIR ABAIXO DA DIV "RESERVAS" DO ATIVO -->

<details style="margin-top: 15px; border-top: 1px dashed #2d333b; padding-top: 15px;">
    <!-- O BOTÃO DE ABRIR/FECHAR -->
    <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
        <span style="color: #f0b90b; font-size: 14px;">▸</span> EXPANDIR DIAGNÓSTICO
    </summary>
    
    <!-- O CONTEÚDO QUE FICA ESCONDIDO ATÉ AO CLIQUE -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; cursor: default;">
        
        <!-- BLOCO 1: DIAGNÓSTICO FUNDAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Motor Fundamental
                    <span class="dica-texto" style="left: 0; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O objetivo é detetar fraudes narrativas. Usa esta secção para cruzar a qualidade real do negócio com o seu preço. Procura <i>"Assimetrias de Valor"</i> e foge de <i>"Dissonâncias"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_fundo_txt | safe }}
            </div>
        </div>

        <!-- BLOCO 2: CONTEXTO TÁTICO E COMPORTAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #3fbf8f;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Contexto Tático
                    <span class="dica-texto" style="right: 0; left: auto; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O <i>timing</i> dita a sobrevivência. Usa esta secção para decidir a ação imediata: entrar num <i>"Equilíbrio"</i>, cortar a posição devido a alta volatilidade, ou ficar de fora numa <i>"Exaustão Parabólica"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_tatica_txt | safe }}
            </div>
        </div>

    </div>
</details>
                            
                            <div style="margin-top: 5px; padding-top: 10px; border-top: 1px dashed var(--linha); display: flex; flex-direction: column; gap: 10px;">
            
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛡️ <strong style="color:var(--mudo)">RISCO CORPORATIVO & LIQUIDEZ:</strong>
                    <span class="dica-texto" style="width: 350px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Insolvência e Filtro de Liquidez ADV</strong>
                        Cruza a alavancagem com a liquidez de proteção institucional.<br><br>
                        <span style="color: var(--vermelho);">■ Dívida/CP &gt; 1.5x:</span> Alavancagem perigosa.<br>
                        <span style="color: var(--azul);">■ ADV (Average Daily Volume):</span> Volume diário médio transacionado em dólares. O robô rejeita automaticamente qualquer ativo abaixo de 10M$ para evitar perdas com spreads (slippage).
                    </span>
                </span>
                Dívida/CP: <span style="font-weight:bold; color:{% if a.debt_raw > 1.5 %}var(--vermelho){% else %}var(--texto){% endif %};">{{ a.debt_eq }}</span> 
                | M.Liq: <span style="font-weight:bold; color:var(--azul);">{{ a.margem_liq }}</span>
                | ADV: <span style="font-weight:bold; color:var(--texto);">{{ a.adv }} USD/dia</span>
            </p>

            <p style="margin: 3px 0 0 0; font-size: 12.5px; border-top: 1px dashed var(--linha); padding-top: 6px; margin-top: 6px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🕵️ <strong style="color:var(--mudo)">FLUXOS OCULTOS:</strong>
                    <span class="dica-texto" style="width: 380px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Short Interest & Posicionamento Insider</strong>
                        Mede quem está a apostar contra ou a favor da empresa com o próprio dinheiro.<br><br>
                        <span style="color: var(--vermelho);">■ Short Interest (&gt;15%):</span> Risco de volatilidade extrema. Elevada probabilidade de <i style="color:#b388ff;">Short Squeeze</i> se existirem catalisadores positivos.<br>
                        <span style="color: var(--azul);">■ Insiders (&gt;10%):</span> Positivo. A gestão detém grande parte do capital, alinhando os seus interesses com a valorização do preço da ação para o retalho.
                    </span>
                </span>
                Short Interest: <span style="font-weight:bold; color:{{ a.short_cor }};">{{ a.short_pct }}</span> 
                | Detenção Insider: <span style="font-weight:bold; color:{{ a.insider_cor }};">{{ a.insider_pct }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⚖️ <strong style="color:var(--mudo)">VALUATION & REVISIONS TREND:</strong>
                    <span class="dica-texto" style="width: 360px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Percentil de Múltiplos e Revisão de Lucros</strong>
                        Mede o prémio do preço face ao histórico e o sentido das estimativas.<br><br>
                        <span style="color: var(--verde);">■ Percentil &lt; 20%:</span> Pechincha histórica relativa.<br>
                        <span style="color: var(--verde);">■ Momentum de EPS (Growth):</span> Se o crescimento operacional estiver a acelerar (Verde), valida o prémio pago e evita armadilhas de valor (Value Traps).
                    </span>
                </span>
                Percentil P/E: <strong style="color:{% if a.pe_pctl == -1 %}var(--mudo){% elif a.pe_pctl > 80 %}var(--vermelho){% elif a.pe_pctl < 20 %}var(--verde){% else %}var(--amarelo){% endif %};">{{ a.pe_pctl_fmt }}</strong>
                | Módulo EPS Trend: <span style="font-weight:bold; color:{{ a.cor_trend }}">{{ a.earnings_trend }}</span>
            </p>
            
            {% if a.sazonalidade_texto %}
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⏳ <strong style="color:var(--mudo)">SAZONALIDADE (10A):</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sazonalidade do Mês Atual (10 Anos)</strong>
                        Auditoria estatística baseada em fluxos recorrentes de capital histórico.
                    </span>
                </span>
                {{ a.sazonalidade_texto | safe }}
            </p>
            {% endif %}

            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🎯 <strong style="color:var(--mudo)">CONSENSO ANALISTAS:</strong>
                    <span class="dica-texto" style="width: 300px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sentimento Coletivo (Sell-Side)</strong>
                        O consenso agregado dos analistas institucionais globais para esta cotada.
                    </span>
                </span>
                Recomendação Bancária: <span style="font-weight:bold; color:var(--texto);">{{ a.recom }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛑 <strong style="color:var(--mudo)">INVALIDAÇÃO TÁCTICA:</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Fuga baseada em Volatilidade Recente</strong>
                        Stop Loss Dinâmico ancorado a 2.5 desvios padrão do preço para absorver o ruído e proteger o capital contra reversões estruturais.
                    </span>
                </span>
                Stop Absoluto sugerido: <span style="font-weight:bold; color:var(--vermelho);">{{ a.stop_price }} {{ a.moeda }}</span> <span style="color:var(--mudo); font-size:11px;">(a -{{ a.stop_pct }})</span>
            </p>
        </div>
    <p></p>
    <p style="margin: 0; font-size: 12.5px;">
    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
        📅 <strong style="color:var(--mudo)">PRÓXIMOS RESULTADOS:</strong>
        <span class="dica-texto" style="width: 320px;">
            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Risco de Gap de Earnings</strong>
            Apresentação trimestral de resultados. Evitar abrir posições novas a menos de 7 dias desta data devido à volatilidade extrema e risco de gap contra a posição.
        </span>
    </span>
    Status: <span style="font-weight:bold; color:{{ a.earn_cor }};">{{ a.earn_txt }}</span>
</p><p></p>
    


                            <div style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 4px; padding: 10px 12px; font-size: 12px; margin-top: auto; width: 100%; box-sizing: border-box;">
                                <div style="color:var(--mudo); text-transform:uppercase; font-size:10px; margin-bottom: 6px; border-bottom: 1px dashed var(--linha); padding-bottom: 4px;">
                                    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                                        📡 Raio-X Técnico
                                        <span class="dica-texto" style="width: 280px;">
                                            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Força Gravitacional do Preço</strong>
                                            Mede o desvio face aos eixos centrais de suporte.<br><br>
                                            <span style="color: var(--vermelho);">Afastamentos da M50 (&gt;15%)</span> sinalizam exaustão e atraem correções (Mean Reversion).
                                        </span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>RSI (14d):</span> <strong style="color:{{ a.cor_rsi }}">{{ a.rsi }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Top 52 Sem:</span> <strong style="color:#fff">{{ a.d_max52 }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Vs Média 50d:</span> <strong style="color:{{ a.cor_m50 }}">{{ a.d_m50 }}</strong></div>
                                <div style="display:flex; justify-content:space-between;"><span>Vs Média 200d:</span> <strong style="color:{{ a.cor_m200 }}">{{ a.d_m200 }}</strong></div>
                            </div>

                            <div style="display: flex; justify-content: space-between; align-items: center; background: #11151c; border: 1px solid var(--linha); padding: 10px 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px;">
                                <div style="text-align: left; flex: 1; min-width: 0; padding-right: 8px;">
                                    <div style="font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.nome }}</div>
                                    <div style="font-size: 9px; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.industria }}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div style="text-align: right; padding-right: 10px; border-right: 1px dashed var(--linha);">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Var (24H)</div>
                                        <div style="font-size: 22px; font-weight: bold; font-family: monospace; color: {{ a.var_cor }};">{{ a.var_dia }}</div>
                                    </div>
                                    <div style="text-align: right; min-width: 65px;">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Cotação</div>
                                        <div style="font-size: 22px; font-weight: bold; color: #fff; font-family: monospace;">{{ a.preco_atual }} <span style="font-size: 9px; color: var(--mudo);">{{ a.moeda }}</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="flex: 1.5; display: flex; flex-direction: column; gap: 15px;">
         {% if a.grafico %}<img src="{{ a.grafico }}" style="width: 100%; border-radius: 4px; border: 1px solid var(--linha);">{% endif %}
         {% if a.radar %}<img src="{{ a.radar }}" style="width: 100%; border-radius: 4px;" alt="Radar">{% endif %}
    </div>
                        
                    </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          {% else %}<div class="vazio">Nenhuma ação cumpre os critérios.</div>{% endif %}
      </div>
      
      <div class="seccao">
          <div class="seccao-titulo t-amarelo">🟡 Tier B: Radar de Valor (Ouro na Lama)</div>
          <div class="seccao-subtitulo">Empresas excepcionais esmagadas temporariamente abaixo da M200. Vigiar inversão técnica.</div>
          {% if tier_b %}
          <table>
            <thead><tr>
              <th>Ticker</th><th>Setor</th><th>Notícias</th>
              <th>
                  <span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">6M Perf (Alpha)<span class="dica-texto" style="width:280px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Alpha Relativo vs S&P 500</strong><br>Mede o desempenho real do ativo descontando a subida do mercado. Se o Alpha for positivo (Verde), a ação está a gerar Alpha real; se for negativo (Vermelho), é um ativo fraco que está a render menos que o índice passivo.</span></span>
              </th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Vol<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Volatilidade Anualizada</strong><br>Mede o "batimento cardíaco" da ação. Valores altos exigem <em>stops</em> mais largos e tamanhos de posição menores.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Max Drawdown<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Perda Máxima (1 Ano)</strong><br>A maior queda do topo ao fundo. Mede o "Risco de Ruína" histórico. Drawdowns altos destroem a composição do capital.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">ROE<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Return on Equity</strong><br>A medida pura da eficiência: quanto lucro o negócio gera por cada euro de capital. Acima de 15% indica vantagem competitiva real.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Margem Op<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Margem Operacional</strong><br>O fosso do negócio. De cada 100€ de vendas, quanto sobra após os custos. Margens altas protegem a empresa contra a inflação.</span></span></th>
              <th><span class="dica-edu dica-desce dica-ancora-dir" style="border-bottom:1px dotted var(--mudo); cursor:help;">P/E Fwd<span class="dica-texto" style="width:260px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Múltiplo Projetado</strong><br>O custo do bilhete de entrada: quanto pagas hoje pelos lucros do próximo ano. Valores muito altos não perdoam desilusões.</span></span></th>
            </tr></thead>
            <tbody>
              {% for a in tier_b %}
              <tr class="linha-dados" onclick="toggleRow('nlg-b-{{ a.ticker }}', 'seta-b-{{ a.ticker }}')">
                <td class="ticker">
                    <div style="display: flex; align-items: center;">
                        <span class="seta" id="seta-b-{{ a.ticker }}">▶</span>
                        <span style="font-size: 14px;">{{ a.ticker }}</span>
                    </div>
                    {% if a.badges %}
                    <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; margin-left: 16px;">
                        {% for b in a.badges %}
                        <span class="dica-edu dica-ancora-esq" style="border-bottom: none; cursor: help; margin-right: 4px;">
                            <span style="background: {{ b.bg }}; color: {{ b.cor }}; font-size: 8.5px; padding: 2px 5px; border-radius: 3px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid {{ b.cor }}33; white-space: nowrap;">{{ b.txt }}</span>
                            <span class="dica-texto" style="width: 250px; text-transform: none; letter-spacing: normal; font-weight: normal; margin-bottom: 5px;">
                                <strong style="color: {{ b.cor }}; font-size: 11px; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{{ b.txt }}</strong>
                                {{ b.desc }}
                            </span>
                        </span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </td>
                <td style="color:var(--mudo)">{{ a.setor }}</td>
                <td style="font-weight: bold; color: {{ a.sent_cor }};">{{ a.sent_txt }}</td>
                <td style="font-weight: bold; white-space: nowrap;">
                    {{ a.perf }} <span style="font-size: 11px; color: {{ a.cor_alpha }}; font-family: monospace;">({{ a.alpha }})</span>
                </td>
                <td><div class="td-flex"><span>{{ a.vol }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.vol_w }}" height="14" fill="var(--amarelo)"/></svg></div></td>
                <td><div class="td-flex"><span style="color:#e06a5a">{{ a.mdd }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.mdd_w }}" height="14" fill="var(--vermelho)"/></svg></div></td>
                <td><div class="td-flex"><span>{{ a.roe }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.roe_w }}" height="14" fill="var(--verde)"/></svg></div></td>
                <td>{{ a.margem }}</td><td>{{ a.pe_fwd }}</td>
              </tr>
              <tr id="nlg-b-{{ a.ticker }}" class="nlg-row">
                <td colspan="9">
                    <div class="conteudo-flex" style="display: flex; gap: 20px; padding: 20px; align-items: stretch; border-left: 3px solid var(--amarelo);"> 
                        
                        <div class="texto-analise" style="flex: 1.3; display: flex; flex-direction: column; gap: 12px;">
                            
                            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                <span style="background: #1a2133; color: var(--azul); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Convicção: {{ a.conv }}/100</span>
                                <span style="background: #232d3f; color: var(--verde); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Alocação: {{ a.position_size }}</span>
                                <span style="background: {% if a.upside == 'N/A' %}#151a23{% elif a.upside_raw > 0 %}#1a2b24{% else %}#2d1a1a{% endif %}; color: {% if a.upside == 'N/A' %}var(--mudo){% elif a.upside_raw > 0 %}var(--verde){% else %}var(--vermelho){% endif %}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Target: {{ a.upside }}</span>
                            </div>
                            
                            <p style="margin: 0;"><strong style="color:var(--mudo)">LEITURA:</strong> {{ a.leitura }}</p>
                            <p style="margin: 0;"><strong style="color:var(--vermelho)">RESERVAS:</strong> {{ a.reservas }}</p>


                            <!-- CÓDIGO A INSERIR ABAIXO DA DIV "RESERVAS" DO ATIVO -->

<details style="margin-top: 15px; border-top: 1px dashed #2d333b; padding-top: 15px;">
    <!-- O BOTÃO DE ABRIR/FECHAR -->
    <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
        <span style="color: #f0b90b; font-size: 14px;">▸</span> EXPANDIR DIAGNÓSTICO
    </summary>
    
    <!-- O CONTEÚDO QUE FICA ESCONDIDO ATÉ AO CLIQUE -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; cursor: default;">
        
        <!-- BLOCO 1: DIAGNÓSTICO FUNDAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Motor Fundamental
                    <span class="dica-texto" style="left: 0; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O objetivo é detetar fraudes narrativas. Usa esta secção para cruzar a qualidade real do negócio com o seu preço. Procura <i>"Assimetrias de Valor"</i> e foge de <i>"Dissonâncias"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_fundo_txt | safe }}
            </div>
        </div>

        <!-- BLOCO 2: CONTEXTO TÁTICO E COMPORTAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #3fbf8f;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Contexto Tático
                    <span class="dica-texto" style="right: 0; left: auto; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O <i>timing</i> dita a sobrevivência. Usa esta secção para decidir a ação imediata: entrar num <i>"Equilíbrio"</i>, cortar a posição devido a alta volatilidade, ou ficar de fora numa <i>"Exaustão Parabólica"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_tatica_txt | safe }}
            </div>
        </div>

    </div>
</details>
                            
                            <div style="margin-top: 5px; padding-top: 10px; border-top: 1px dashed var(--linha); display: flex; flex-direction: column; gap: 10px;">
            
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛡️ <strong style="color:var(--mudo)">RISCO CORPORATIVO & LIQUIDEZ:</strong>
                    <span class="dica-texto" style="width: 350px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Insolvência e Filtro de Liquidez ADV</strong>
                        Cruza a alavancagem com a liquidez de proteção institucional.<br><br>
                        <span style="color: var(--vermelho);">■ Dívida/CP &gt; 1.5x:</span> Alavancagem perigosa.<br>
                        <span style="color: var(--azul);">■ ADV (Average Daily Volume):</span> Volume diário médio transacionado em dólares. O robô rejeita automaticamente qualquer ativo abaixo de 10M$ para evitar perdas com spreads (slippage).
                    </span>
                </span>
                Dívida/CP: <span style="font-weight:bold; color:{% if a.debt_raw > 1.5 %}var(--vermelho){% else %}var(--texto){% endif %};">{{ a.debt_eq }}</span> 
                | M.Liq: <span style="font-weight:bold; color:var(--azul);">{{ a.margem_liq }}</span>
                | ADV: <span style="font-weight:bold; color:var(--texto);">{{ a.adv }} USD/dia</span>
            </p>

            <p style="margin: 3px 0 0 0; font-size: 12.5px; border-top: 1px dashed var(--linha); padding-top: 6px; margin-top: 6px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🕵️ <strong style="color:var(--mudo)">FLUXOS OCULTOS:</strong>
                    <span class="dica-texto" style="width: 380px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Short Interest & Posicionamento Insider</strong>
                        Mede quem está a apostar contra ou a favor da empresa com o próprio dinheiro.<br><br>
                        <span style="color: var(--vermelho);">■ Short Interest (&gt;15%):</span> Risco de volatilidade extrema. Elevada probabilidade de <i style="color:#b388ff;">Short Squeeze</i> se existirem catalisadores positivos.<br>
                        <span style="color: var(--azul);">■ Insiders (&gt;10%):</span> Positivo. A gestão detém grande parte do capital, alinhando os seus interesses com a valorização do preço da ação para o retalho.
                    </span>
                </span>
                Short Interest: <span style="font-weight:bold; color:{{ a.short_cor }};">{{ a.short_pct }}</span> 
                | Detenção Insider: <span style="font-weight:bold; color:{{ a.insider_cor }};">{{ a.insider_pct }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⚖️ <strong style="color:var(--mudo)">VALUATION & REVISIONS TREND:</strong>
                    <span class="dica-texto" style="width: 360px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Percentil de Múltiplos e Revisão de Lucros</strong>
                        Mede o prémio do preço face ao histórico e o sentido das estimativas.<br><br>
                        <span style="color: var(--verde);">■ Percentil &lt; 20%:</span> Pechincha histórica relativa.<br>
                        <span style="color: var(--verde);">■ Momentum de EPS (Growth):</span> Se o crescimento operacional estiver a acelerar (Verde), valida o prémio pago e evita armadilhas de valor (Value Traps).
                    </span>
                </span>
                Percentil P/E: <strong style="color:{% if a.pe_pctl == -1 %}var(--mudo){% elif a.pe_pctl > 80 %}var(--vermelho){% elif a.pe_pctl < 20 %}var(--verde){% else %}var(--amarelo){% endif %};">{{ a.pe_pctl_fmt }}</strong>
                | Módulo EPS Trend: <span style="font-weight:bold; color:{{ a.cor_trend }}">{{ a.earnings_trend }}</span>
            </p>
            
            {% if a.sazonalidade_texto %}
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⏳ <strong style="color:var(--mudo)">SAZONALIDADE (10A):</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sazonalidade do Mês Atual (10 Anos)</strong>
                        Auditoria estatística baseada em fluxos recorrentes de capital histórico.
                    </span>
                </span>
                {{ a.sazonalidade_texto | safe }}
            </p>
            {% endif %}

            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🎯 <strong style="color:var(--mudo)">CONSENSO ANALISTAS:</strong>
                    <span class="dica-texto" style="width: 300px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sentimento Coletivo (Sell-Side)</strong>
                        O consenso agregado dos analistas institucionais globais para esta cotada.
                    </span>
                </span>
                Recomendação Bancária: <span style="font-weight:bold; color:var(--texto);">{{ a.recom }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛑 <strong style="color:var(--mudo)">INVALIDAÇÃO TÁCTICA:</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Fuga baseada em Volatilidade Recente</strong>
                        Stop Loss Dinâmico ancorado a 2.5 desvios padrão do preço para absorver o ruído e proteger o capital contra reversões estruturais.
                    </span>
                </span>
                Stop Absoluto sugerido: <span style="font-weight:bold; color:var(--vermelho);">{{ a.stop_price }} {{ a.moeda }}</span> <span style="color:var(--mudo); font-size:11px;">(a -{{ a.stop_pct }})</span>
            </p>
        </div>
    <p></p>
    <p style="margin: 0; font-size: 12.5px;">
    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
        📅 <strong style="color:var(--mudo)">PRÓXIMOS RESULTADOS:</strong>
        <span class="dica-texto" style="width: 320px;">
            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Risco de Gap de Earnings</strong>
            Apresentação trimestral de resultados. Evitar abrir posições novas a menos de 7 dias desta data devido à volatilidade extrema e risco de gap contra a posição.
        </span>
    </span>
    Status: <span style="font-weight:bold; color:{{ a.earn_cor }};">{{ a.earn_txt }}</span>
</p><p></p>
    



                            <div style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 4px; padding: 10px 12px; font-size: 12px; margin-top: auto; width: 100%; box-sizing: border-box;">
                                <div style="color:var(--mudo); text-transform:uppercase; font-size:10px; margin-bottom: 6px; border-bottom: 1px dashed var(--linha); padding-bottom: 4px;">
                                    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                                        📡 Raio-X Técnico
                                        <span class="dica-texto" style="width: 280px;">
                                            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Força Gravitacional do Preço</strong>
                                            Mede o desvio face aos eixos centrais de suporte.<br><br>
                                            <span style="color: var(--vermelho);">Afastamentos da M50 (&gt;15%)</span> sinalizam exaustão e atraem correções (Mean Reversion).
                                        </span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>RSI (14d):</span> <strong style="color:{{ a.cor_rsi }}">{{ a.rsi }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Top 52 Sem:</span> <strong style="color:#fff">{{ a.d_max52 }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Vs Média 50d:</span> <strong style="color:{{ a.cor_m50 }}">{{ a.d_m50 }}</strong></div>
                                <div style="display:flex; justify-content:space-between;"><span>Vs Média 200d:</span> <strong style="color:{{ a.cor_m200 }}">{{ a.d_m200 }}</strong></div>
                            </div>

                            <div style="display: flex; justify-content: space-between; align-items: center; background: #11151c; border: 1px solid var(--linha); padding: 10px 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px;">
                                <div style="text-align: left; flex: 1; min-width: 0; padding-right: 8px;">
                                    <div style="font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.nome }}</div>
                                    <div style="font-size: 9px; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.industria }}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div style="text-align: right; padding-right: 10px; border-right: 1px dashed var(--linha);">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Var (24H)</div>
                                        <div style="font-size: 22px; font-weight: bold; font-family: monospace; color: {{ a.var_cor }};">{{ a.var_dia }}</div>
                                    </div>
                                    <div style="text-align: right; min-width: 65px;">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Cotação</div>
                                        <div style="font-size: 22px; font-weight: bold; color: #fff; font-family: monospace;">{{ a.preco_atual }} <span style="font-size: 9px; color: var(--mudo);">{{ a.moeda }}</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="flex: 1.5; display: flex; flex-direction: column; gap: 15px;">
         {% if a.grafico %}<img src="{{ a.grafico }}" style="width: 100%; border-radius: 4px; border: 1px solid var(--linha);">{% endif %}
         {% if a.radar %}<img src="{{ a.radar }}" style="width: 100%; border-radius: 4px;" alt="Radar">{% endif %}
    </div>
                        
                    </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          {% else %}<div class="vazio">Sem oportunidades de alto valor com desconto detetadas.</div>{% endif %}
      </div>


      <div class="seccao">
          <div class="seccao-titulo" style="color: var(--mudo);">⚪ Quarentena: Zona Cinzenta (Especulação & Observação)</div>
          <div class="seccao-subtitulo">Ativos que não cumprem os padrões estritos de qualidade (Tier A/B), mas não confirmam falência técnica (Blacklist).</div>
          {% if quarentena %}
          <table>
            <thead><tr>
              <th>Ticker</th><th>Setor</th><th>Notícias</th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">6M Perf (Alpha)<span class="dica-texto">...</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Vol<span class="dica-texto">...</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Max Drawdown<span class="dica-texto">...</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">ROE<span class="dica-texto">...</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Margem Op<span class="dica-texto">...</span></span></th>
              <th><span class="dica-edu dica-desce dica-ancora-dir" style="border-bottom:1px dotted var(--mudo); cursor:help;">P/E Fwd<span class="dica-texto">...</span></span></th>
            </tr></thead>
            <tbody>
              {% for a in quarentena %}
              <tr class="linha-dados" onclick="toggleRow('nlg-q-{{ a.ticker }}', 'seta-q-{{ a.ticker }}')">
                <td class="ticker">
                    <div style="display: flex; align-items: center;">
                        <span class="seta" id="seta-q-{{ a.ticker }}">▶</span>
                        <span style="font-size: 14px;">{{ a.ticker }}</span>
                    </div>
                    {% if a.badges %}
                    <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; margin-left: 16px;">
                        {% for b in a.badges %}
                        <!-- Insere o mesmo bloco dos badges que tens no Tier A/B -->
                        <span class="dica-edu dica-ancora-esq" style="border-bottom: none; cursor: help; margin-right: 4px;">
                            <span style="background: {{ b.bg }}; color: {{ b.cor }}; font-size: 8.5px; padding: 2px 5px; border-radius: 3px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid {{ b.cor }}33; white-space: nowrap;">{{ b.txt }}</span>
                            <span class="dica-texto" style="width: 250px; text-transform: none; letter-spacing: normal; font-weight: normal; margin-bottom: 5px;">
                                <strong style="color: {{ b.cor }}; font-size: 11px; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{{ b.txt }}</strong>
                                {{ b.desc }}
                            </span>
                        </span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </td>
                <td style="color:var(--mudo)">{{ a.setor }}</td>
                <td style="font-weight: bold; color: {{ a.sent_cor }};">{{ a.sent_txt }}</td>
                <td style="font-weight: bold; white-space: nowrap;">
                    {{ a.perf }} <span style="font-size: 11px; color: {{ a.cor_alpha }}; font-family: monospace;">({{ a.alpha }})</span>
                </td>
                <td><div class="td-flex"><span>{{ a.vol }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.vol_w }}" height="14" fill="var(--amarelo)"/></svg></div></td>
                <td><div class="td-flex"><span style="color:#e06a5a">{{ a.mdd }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.mdd_w }}" height="14" fill="var(--vermelho)"/></svg></div></td>
                <td><div class="td-flex"><span>{{ a.roe }}</span><svg viewBox="0 0 100 14" preserveAspectRatio="none" style="width: 50px; height: 6px; margin-left: 8px; border-radius: 2px;"><rect width="100" height="14" fill="#1a212c"/><rect width="{{ a.roe_w }}" height="14" fill="var(--verde)"/></svg></div></td>
                <td>{{ a.margem }}</td><td>{{ a.pe_fwd }}</td>
              </tr>
              <!-- Adiciona a lógica da expansão 'nlg-q-ticker' replicando o comportamento dos restantes tiers, mudando o id e mantendo o border-left a var(--mudo) -->
              <tr id="nlg-q-{{ a.ticker }}" class="nlg-row">
                 <td colspan="9">
                    <!-- Mesma estrutura de conteúdo flexível dos Tiers -->
                    <div class="conteudo-flex" style="display: flex; gap: 20px; padding: 20px; align-items: stretch; border-left: 3px solid var(--vermelho);"> 
                        
                        <div class="texto-analise" style="flex: 1.3; display: flex; flex-direction: column; gap: 12px;">
                            
                            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                <span style="background: #1a2133; color: var(--azul); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Convicção: {{ a.conv }}/100</span>
                                <span style="background: #232d3f; color: var(--verde); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Alocação: {{ a.position_size }}</span>
                                <span style="background: {% if a.upside == 'N/A' %}#151a23{% elif a.upside_raw > 0 %}#1a2b24{% else %}#2d1a1a{% endif %}; color: {% if a.upside == 'N/A' %}var(--mudo){% elif a.upside_raw > 0 %}var(--verde){% else %}var(--vermelho){% endif %}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Target: {{ a.upside }}</span>
                            </div>
                            
                            <p style="margin: 0;"><strong style="color:var(--mudo)">LEITURA:</strong> {{ a.leitura }}</p>
                            <p style="margin: 0;"><strong style="color:var(--vermelho)">RESERVAS:</strong> {{ a.reservas }}</p>

                            <!-- CÓDIGO A INSERIR ABAIXO DA DIV "RESERVAS" DO ATIVO -->

<details style="margin-top: 15px; border-top: 1px dashed #2d333b; padding-top: 15px;">
    <!-- O BOTÃO DE ABRIR/FECHAR -->
    <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
        <span style="color: #f0b90b; font-size: 14px;">▸</span> EXPANDIR DIAGNÓSTICO
    </summary>
    
    <!-- O CONTEÚDO QUE FICA ESCONDIDO ATÉ AO CLIQUE -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; cursor: default;">
        
        <!-- BLOCO 1: DIAGNÓSTICO FUNDAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Motor Fundamental
                    <span class="dica-texto" style="left: 0; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O objetivo é detetar fraudes narrativas. Usa esta secção para cruzar a qualidade real do negócio com o seu preço. Procura <i>"Assimetrias de Valor"</i> e foge de <i>"Dissonâncias"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_fundo_txt | safe }}
            </div>
        </div>

        <!-- BLOCO 2: CONTEXTO TÁTICO E COMPORTAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #3fbf8f;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Contexto Tático
                    <span class="dica-texto" style="right: 0; left: auto; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O <i>timing</i> dita a sobrevivência. Usa esta secção para decidir a ação imediata: entrar num <i>"Equilíbrio"</i>, cortar a posição devido a alta volatilidade, ou ficar de fora numa <i>"Exaustão Parabólica"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_tatica_txt | safe }}
            </div>
        </div>

    </div>
</details>

                            
                            <div style="margin-top: 5px; padding-top: 10px; border-top: 1px dashed var(--linha); display: flex; flex-direction: column; gap: 10px;">
            
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛡️ <strong style="color:var(--mudo)">RISCO CORPORATIVO & LIQUIDEZ:</strong>
                    <span class="dica-texto" style="width: 350px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Insolvência e Filtro de Liquidez ADV</strong>
                        Cruza a alavancagem com a liquidez de proteção institucional.<br><br>
                        <span style="color: var(--vermelho);">■ Dívida/CP &gt; 1.5x:</span> Alavancagem perigosa.<br>
                        <span style="color: var(--azul);">■ ADV (Average Daily Volume):</span> Volume diário médio transacionado em dólares. O robô rejeita automaticamente qualquer ativo abaixo de 10M$ para evitar perdas com spreads (slippage).
                    </span>
                </span>
                Dívida/CP: <span style="font-weight:bold; color:{% if a.debt_raw > 1.5 %}var(--vermelho){% else %}var(--texto){% endif %};">{{ a.debt_eq }}</span> 
                | M.Liq: <span style="font-weight:bold; color:var(--azul);">{{ a.margem_liq }}</span>
                | ADV: <span style="font-weight:bold; color:var(--texto);">{{ a.adv }} USD/dia</span>
            </p>

            <p style="margin: 3px 0 0 0; font-size: 12.5px; border-top: 1px dashed var(--linha); padding-top: 6px; margin-top: 6px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🕵️ <strong style="color:var(--mudo)">FLUXOS OCULTOS:</strong>
                    <span class="dica-texto" style="width: 380px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Short Interest & Posicionamento Insider</strong>
                        Mede quem está a apostar contra ou a favor da empresa com o próprio dinheiro.<br><br>
                        <span style="color: var(--vermelho);">■ Short Interest (&gt;15%):</span> Risco de volatilidade extrema. Elevada probabilidade de <i style="color:#b388ff;">Short Squeeze</i> se existirem catalisadores positivos.<br>
                        <span style="color: var(--azul);">■ Insiders (&gt;10%):</span> Positivo. A gestão detém grande parte do capital, alinhando os seus interesses com a valorização do preço da ação para o retalho.
                    </span>
                </span>
                Short Interest: <span style="font-weight:bold; color:{{ a.short_cor }};">{{ a.short_pct }}</span> 
                | Detenção Insider: <span style="font-weight:bold; color:{{ a.insider_cor }};">{{ a.insider_pct }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⚖️ <strong style="color:var(--mudo)">VALUATION & REVISIONS TREND:</strong>
                    <span class="dica-texto" style="width: 360px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Percentil de Múltiplos e Revisão de Lucros</strong>
                        Mede o prémio do preço face ao histórico e o sentido das estimativas.<br><br>
                        <span style="color: var(--verde);">■ Percentil &lt; 20%:</span> Pechincha histórica relativa.<br>
                        <span style="color: var(--verde);">■ Momentum de EPS (Growth):</span> Se o crescimento operacional estiver a acelerar (Verde), valida o prémio pago e evita armadilhas de valor (Value Traps).
                    </span>
                </span>
                Percentil P/E: <strong style="color:{% if a.pe_pctl == -1 %}var(--mudo){% elif a.pe_pctl > 80 %}var(--vermelho){% elif a.pe_pctl < 20 %}var(--verde){% else %}var(--amarelo){% endif %};">{{ a.pe_pctl_fmt }}</strong>
                | Módulo EPS Trend: <span style="font-weight:bold; color:{{ a.cor_trend }}">{{ a.earnings_trend }}</span>
            </p>
            
            {% if a.sazonalidade_texto %}
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⏳ <strong style="color:var(--mudo)">SAZONALIDADE (10A):</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sazonalidade do Mês Atual (10 Anos)</strong>
                        Auditoria estatística baseada em fluxos recorrentes de capital histórico.
                    </span>
                </span>
                {{ a.sazonalidade_texto | safe }}
            </p>
            {% endif %}

            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🎯 <strong style="color:var(--mudo)">CONSENSO ANALISTAS:</strong>
                    <span class="dica-texto" style="width: 300px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sentimento Coletivo (Sell-Side)</strong>
                        O consenso agregado dos analistas institucionais globais para esta cotada.
                    </span>
                </span>
                Recomendação Bancária: <span style="font-weight:bold; color:var(--texto);">{{ a.recom }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛑 <strong style="color:var(--mudo)">INVALIDAÇÃO TÁCTICA:</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Fuga baseada em Volatilidade Recente</strong>
                        Stop Loss Dinâmico ancorado a 2.5 desvios padrão do preço para absorver o ruído e proteger o capital contra reversões estruturais.
                    </span>
                </span>
                Stop Absoluto sugerido: <span style="font-weight:bold; color:var(--vermelho);">{{ a.stop_price }} {{ a.moeda }}</span> <span style="color:var(--mudo); font-size:11px;">(a -{{ a.stop_pct }})</span>
            </p>
        </div>
    <p></p>
    <p style="margin: 0; font-size: 12.5px;">
    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
        📅 <strong style="color:var(--mudo)">PRÓXIMOS RESULTADOS:</strong>
        <span class="dica-texto" style="width: 320px;">
            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Risco de Gap de Earnings</strong>
            Apresentação trimestral de resultados. Evitar abrir posições novas a menos de 7 dias desta data devido à volatilidade extrema e risco de gap contra a posição.
        </span>
    </span>
    Status: <span style="font-weight:bold; color:{{ a.earn_cor }};">{{ a.earn_txt }}</span>
</p><p></p>
    



                            <div style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 4px; padding: 10px 12px; font-size: 12px; margin-top: auto; width: 100%; box-sizing: border-box;">
                                <div style="color:var(--mudo); text-transform:uppercase; font-size:10px; margin-bottom: 6px; border-bottom: 1px dashed var(--linha); padding-bottom: 4px;">
                                    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                                        📡 Raio-X Técnico
                                        <span class="dica-texto" style="width: 280px;">
                                            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Força Gravitacional do Preço</strong>
                                            Mede o desvio face aos eixos centrais de suporte.<br><br>
                                            <span style="color: var(--vermelho);">Afastamentos da M50 (&gt;15%)</span> sinalizam exaustão e atraem correções (Mean Reversion).
                                        </span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>RSI (14d):</span> <strong style="color:{{ a.cor_rsi }}">{{ a.rsi }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Top 52 Sem:</span> <strong style="color:#fff">{{ a.d_max52 }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Vs Média 50d:</span> <strong style="color:{{ a.cor_m50 }}">{{ a.d_m50 }}</strong></div>
                                <div style="display:flex; justify-content:space-between;"><span>Vs Média 200d:</span> <strong style="color:{{ a.cor_m200 }}">{{ a.d_m200 }}</strong></div>
                            </div>

                            <div style="display: flex; justify-content: space-between; align-items: center; background: #11151c; border: 1px solid var(--linha); padding: 10px 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px;">
                                <div style="text-align: left; flex: 1; min-width: 0; padding-right: 8px;">
                                    <div style="font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.nome }}</div>
                                    <div style="font-size: 9px; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.industria }}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div style="text-align: right; padding-right: 10px; border-right: 1px dashed var(--linha);">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Var (24H)</div>
                                        <div style="font-size: 22px; font-weight: bold; font-family: monospace; color: {{ a.var_cor }};">{{ a.var_dia }}</div>
                                    </div>
                                    <div style="text-align: right; min-width: 65px;">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Cotação</div>
                                        <div style="font-size: 22px; font-weight: bold; color: #fff; font-family: monospace;">{{ a.preco_atual }} <span style="font-size: 9px; color: var(--mudo);">{{ a.moeda }}</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="flex: 1.5; display: flex; flex-direction: column; gap: 15px;">
         {% if a.grafico %}<img src="{{ a.grafico }}" style="width: 100%; border-radius: 4px; border: 1px solid var(--linha);">{% endif %}
         {% if a.radar %}<img src="{{ a.radar }}" style="width: 100%; border-radius: 4px;" alt="Radar">{% endif %}
    </div>
                        
                    </div>
                 </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          {% else %}<div class="vazio">Sem ativos retidos na quarentena.</div>{% endif %}
      </div>


      <div class="seccao">
          <div class="seccao-titulo t-vermelho">🔴 Blacklist: Alertas de Risco</div>
          <div class="seccao-subtitulo">Empresas com tendência destrutiva e balanço insolvente. Manter distância.</div>
          {% if blacklist %}
          <table>
            <thead><tr>
              <th>Ticker</th><th>Setor</th><th>Notícias</th>
              <th>
                  <span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">6M Perf (Alpha)<span class="dica-texto" style="width:280px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Alpha Relativo vs S&P 500</strong><br>Mede o desempenho real do ativo descontando a subida do mercado. Se o Alpha for positivo (Verde), a ação está a gerar Alpha real; se for negativo (Vermelho), é um ativo fraco que está a render menos que o índice passivo.</span></span>
              </th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Vol<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Volatilidade Anualizada</strong><br>Mede o "batimento cardíaco" da ação. Valores altos exigem <em>stops</em> mais largos e tamanhos de posição menores.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Max Drawdown<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Perda Máxima (1 Ano)</strong><br>A maior queda do topo ao fundo. Mede o "Risco de Ruína" histórico. Drawdowns altos destroem a composição do capital.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">ROE<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Return on Equity</strong><br>A medida pura da eficiência: quanto lucro o negócio gera por cada euro de capital. Acima de 15% indica vantagem competitiva real.</span></span></th>
              <th><span class="dica-edu dica-desce" style="border-bottom:1px dotted var(--mudo); cursor:help;">Margem Op<span class="dica-texto" style="width:250px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Margem Operacional</strong><br>O fosso do negócio. De cada 100€ de vendas, quanto sobra após os custos. Margens altas protegem a empresa contra a inflação.</span></span></th>
              <th><span class="dica-edu dica-desce dica-ancora-dir" style="border-bottom:1px dotted var(--mudo); cursor:help;">P/E Fwd<span class="dica-texto" style="width:260px; text-transform:none; font-weight:normal; letter-spacing:0;"><strong style="color:var(--texto);">Múltiplo Projetado</strong><br>O custo do bilhete de entrada: quanto pagas hoje pelos lucros do próximo ano. Valores muito altos não perdoam desilusões.</span></span></th>
            </tr></thead>
            <tbody>
              {% for a in blacklist %}
              <tr class="linha-dados" onclick="toggleRow('nlg-bl-{{ a.ticker }}', 'seta-bl-{{ a.ticker }}')">
                <td class="ticker">
                    <div style="display: flex; align-items: center;">
                        <span class="seta" id="seta-bl-{{ a.ticker }}">▶</span>
                        <span style="font-size: 14px;">{{ a.ticker }}</span>
                    </div>
                    {% if a.badges %}
                    <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; margin-left: 16px;">
                        {% for b in a.badges %}
                        <span class="dica-edu dica-ancora-esq" style="border-bottom: none; cursor: help; margin-right: 4px;">
                            <span style="background: {{ b.bg }}; color: {{ b.cor }}; font-size: 8.5px; padding: 2px 5px; border-radius: 3px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid {{ b.cor }}33; white-space: nowrap;">{{ b.txt }}</span>
                            <span class="dica-texto" style="width: 250px; text-transform: none; letter-spacing: normal; font-weight: normal; margin-bottom: 5px;">
                                <strong style="color: {{ b.cor }}; font-size: 11px; display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{{ b.txt }}</strong>
                                {{ b.desc }}
                            </span>
                        </span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </td>
                <td style="color:var(--mudo)">{{ a.setor }}</td>
                <td style="font-weight: bold; color: {{ a.sent_cor }};">{{ a.sent_txt }}</td>
                <td style="font-weight: bold; white-space: nowrap;">
                    {{ a.perf }} <span style="font-size: 11px; color: {{ a.cor_alpha }}; font-family: monospace;">({{ a.alpha }})</span>
                </td>
                <td>{{ a.vol }}</td>
                <td style="color:#e06a5a">{{ a.mdd }}</td>
                <td>{{ a.roe }}</td>
                <td>{{ a.margem }}</td>
                <td>{{ a.pe_fwd }}</td>
              </tr>
              <tr id="nlg-bl-{{ a.ticker }}" class="nlg-row">
                <td colspan="9">
                    <div class="conteudo-flex" style="display: flex; gap: 20px; padding: 20px; align-items: stretch; border-left: 3px solid var(--vermelho);"> 
                        
                        <div class="texto-analise" style="flex: 1.3; display: flex; flex-direction: column; gap: 12px;">
                            
                            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                <span style="background: #1a2133; color: var(--azul); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Convicção: {{ a.conv }}/100</span>
                                <span style="background: #232d3f; color: var(--verde); padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Alocação: {{ a.position_size }}</span>
                                <span style="background: {% if a.upside == 'N/A' %}#151a23{% elif a.upside_raw > 0 %}#1a2b24{% else %}#2d1a1a{% endif %}; color: {% if a.upside == 'N/A' %}var(--mudo){% elif a.upside_raw > 0 %}var(--verde){% else %}var(--vermelho){% endif %}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; border: 1px solid var(--linha);">Target: {{ a.upside }}</span>
                            </div>
                            
                            <p style="margin: 0;"><strong style="color:var(--mudo)">LEITURA:</strong> {{ a.leitura }}</p>
                            <p style="margin: 0;"><strong style="color:var(--vermelho)">RESERVAS:</strong> {{ a.reservas }}</p>
                            
                            <!-- CÓDIGO A INSERIR ABAIXO DA DIV "RESERVAS" DO ATIVO -->

<details style="margin-top: 15px; border-top: 1px dashed #2d333b; padding-top: 15px;">
    <!-- O BOTÃO DE ABRIR/FECHAR -->
    <summary style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; outline: none;">
        <span style="color: #f0b90b; font-size: 14px;">▸</span> EXPANDIR DIAGNÓSTICO
    </summary>
    
    <!-- O CONTEÚDO QUE FICA ESCONDIDO ATÉ AO CLIQUE -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; cursor: default;">
        
        <!-- BLOCO 1: DIAGNÓSTICO FUNDAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #f0b90b;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Motor Fundamental
                    <span class="dica-texto" style="left: 0; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O objetivo é detetar fraudes narrativas. Usa esta secção para cruzar a qualidade real do negócio com o seu preço. Procura <i>"Assimetrias de Valor"</i> e foge de <i>"Dissonâncias"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_fundo_txt | safe }}
            </div>
        </div>

        <!-- BLOCO 2: CONTEXTO TÁTICO E COMPORTAMENTAL -->
        <div style="background: rgba(13, 17, 23, 0.5); padding: 12px; border-radius: 6px; border-left: 3px solid #3fbf8f;">
            <div style="font-size: 11px; font-weight: bold; color: #8a94a8; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                <span class="dica-edu dica-desce" style="border-bottom:1px dotted #8a94a8; cursor:help; position: relative;">
                    Contexto Tático
                    <span class="dica-texto" style="right: 0; left: auto; transform: none; min-width: 280px; white-space: normal; text-align: left; text-transform: none; font-weight: normal; font-size: 12px;">
                        <b>COMO LER:</b> O <i>timing</i> dita a sobrevivência. Usa esta secção para decidir a ação imediata: entrar num <i>"Equilíbrio"</i>, cortar a posição devido a alta volatilidade, ou ficar de fora numa <i>"Exaustão Parabólica"</i>.
                    </span>
                </span>
            </div>
            <div style="font-size: 12px; line-height: 1.6; color: #c9d1d9;">
                {{ a.analise_tatica_txt | safe }}
            </div>
        </div>

    </div>
</details>

                            <div style="margin-top: 5px; padding-top: 10px; border-top: 1px dashed var(--linha); display: flex; flex-direction: column; gap: 10px;">
            
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛡️ <strong style="color:var(--mudo)">RISCO CORPORATIVO & LIQUIDEZ:</strong>
                    <span class="dica-texto" style="width: 350px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Insolvência e Filtro de Liquidez ADV</strong>
                        Cruza a alavancagem com a liquidez de proteção institucional.<br><br>
                        <span style="color: var(--vermelho);">■ Dívida/CP &gt; 1.5x:</span> Alavancagem perigosa.<br>
                        <span style="color: var(--azul);">■ ADV (Average Daily Volume):</span> Volume diário médio transacionado em dólares. O robô rejeita automaticamente qualquer ativo abaixo de 10M$ para evitar perdas com spreads (slippage).
                    </span>
                </span>
                Dívida/CP: <span style="font-weight:bold; color:{% if a.debt_raw > 1.5 %}var(--vermelho){% else %}var(--texto){% endif %};">{{ a.debt_eq }}</span> 
                | M.Liq: <span style="font-weight:bold; color:var(--azul);">{{ a.margem_liq }}</span>
                | ADV: <span style="font-weight:bold; color:var(--texto);">{{ a.adv }} USD/dia</span>
            </p>

            <p style="margin: 3px 0 0 0; font-size: 12.5px; border-top: 1px dashed var(--linha); padding-top: 6px; margin-top: 6px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🕵️ <strong style="color:var(--mudo)">FLUXOS OCULTOS:</strong>
                    <span class="dica-texto" style="width: 380px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Short Interest & Posicionamento Insider</strong>
                        Mede quem está a apostar contra ou a favor da empresa com o próprio dinheiro.<br><br>
                        <span style="color: var(--vermelho);">■ Short Interest (&gt;15%):</span> Risco de volatilidade extrema. Elevada probabilidade de <i style="color:#b388ff;">Short Squeeze</i> se existirem catalisadores positivos.<br>
                        <span style="color: var(--azul);">■ Insiders (&gt;10%):</span> Positivo. A gestão detém grande parte do capital, alinhando os seus interesses com a valorização do preço da ação para o retalho.
                    </span>
                </span>
                Short Interest: <span style="font-weight:bold; color:{{ a.short_cor }};">{{ a.short_pct }}</span> 
                | Detenção Insider: <span style="font-weight:bold; color:{{ a.insider_cor }};">{{ a.insider_pct }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⚖️ <strong style="color:var(--mudo)">VALUATION & REVISIONS TREND:</strong>
                    <span class="dica-texto" style="width: 360px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Percentil de Múltiplos e Revisão de Lucros</strong>
                        Mede o prémio do preço face ao histórico e o sentido das estimativas.<br><br>
                        <span style="color: var(--verde);">■ Percentil &lt; 20%:</span> Pechincha histórica relativa.<br>
                        <span style="color: var(--verde);">■ Momentum de EPS (Growth):</span> Se o crescimento operacional estiver a acelerar (Verde), valida o prémio pago e evita armadilhas de valor (Value Traps).
                    </span>
                </span>
                Percentil P/E: <strong style="color:{% if a.pe_pctl == -1 %}var(--mudo){% elif a.pe_pctl > 80 %}var(--vermelho){% elif a.pe_pctl < 20 %}var(--verde){% else %}var(--amarelo){% endif %};">{{ a.pe_pctl_fmt }}</strong>
                | Módulo EPS Trend: <span style="font-weight:bold; color:{{ a.cor_trend }}">{{ a.earnings_trend }}</span>
            </p>
            
            {% if a.sazonalidade_texto %}
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    ⏳ <strong style="color:var(--mudo)">SAZONALIDADE (10A):</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sazonalidade do Mês Atual (10 Anos)</strong>
                        Auditoria estatística baseada em fluxos recorrentes de capital histórico.
                    </span>
                </span>
                {{ a.sazonalidade_texto | safe }}
            </p>
            {% endif %}

            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🎯 <strong style="color:var(--mudo)">CONSENSO ANALISTAS:</strong>
                    <span class="dica-texto" style="width: 300px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Sentimento Coletivo (Sell-Side)</strong>
                        O consenso agregado dos analistas institucionais globais para esta cotada.
                    </span>
                </span>
                Recomendação Bancária: <span style="font-weight:bold; color:var(--texto);">{{ a.recom }}</span>
            </p>
            <p></p>
            <p style="margin: 0; font-size: 12.5px;">
                <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                    🛑 <strong style="color:var(--mudo)">INVALIDAÇÃO TÁCTICA:</strong>
                    <span class="dica-texto" style="width: 320px;">
                        <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Fuga baseada em Volatilidade Recente</strong>
                        Stop Loss Dinâmico ancorado a 2.5 desvios padrão do preço para absorver o ruído e proteger o capital contra reversões estruturais.
                    </span>
                </span>
                Stop Absoluto sugerido: <span style="font-weight:bold; color:var(--vermelho);">{{ a.stop_price }} {{ a.moeda }}</span> <span style="color:var(--mudo); font-size:11px;">(a -{{ a.stop_pct }})</span>
            </p>
        </div>
    <p></p>
    <p style="margin: 0; font-size: 12.5px;">
    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
        📅 <strong style="color:var(--mudo)">PRÓXIMOS RESULTADOS:</strong>
        <span class="dica-texto" style="width: 320px;">
            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Risco de Gap de Earnings</strong>
            Apresentação trimestral de resultados. Evitar abrir posições novas a menos de 7 dias desta data devido à volatilidade extrema e risco de gap contra a posição.
        </span>
    </span>
    Status: <span style="font-weight:bold; color:{{ a.earn_cor }};">{{ a.earn_txt }}</span>
</p><p></p>
    



                            <div style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 4px; padding: 10px 12px; font-size: 12px; margin-top: auto; width: 100%; box-sizing: border-box;">
                                <div style="color:var(--mudo); text-transform:uppercase; font-size:10px; margin-bottom: 6px; border-bottom: 1px dashed var(--linha); padding-bottom: 4px;">
                                    <span class="dica-edu dica-ancora-esq" style="border-bottom: 1px dotted var(--mudo); cursor: help;">
                                        📡 Raio-X Técnico
                                        <span class="dica-texto" style="width: 280px;">
                                            <strong style="color: #fff; font-size: 12px; display: block; margin-bottom: 6px; border-bottom: 1px solid var(--linha); padding-bottom: 4px;">Força Gravitacional do Preço</strong>
                                            Mede o desvio face aos eixos centrais de suporte.<br><br>
                                            <span style="color: var(--vermelho);">Afastamentos da M50 (&gt;15%)</span> sinalizam exaustão e atraem correções (Mean Reversion).
                                        </span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>RSI (14d):</span> <strong style="color:{{ a.cor_rsi }}">{{ a.rsi }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Top 52 Sem:</span> <strong style="color:#fff">{{ a.d_max52 }}</strong></div>
                                <div style="display:flex; justify-content:space-between; margin-bottom: 3px;"><span>Vs Média 50d:</span> <strong style="color:{{ a.cor_m50 }}">{{ a.d_m50 }}</strong></div>
                                <div style="display:flex; justify-content:space-between;"><span>Vs Média 200d:</span> <strong style="color:{{ a.cor_m200 }}">{{ a.d_m200 }}</strong></div>
                            </div>

                            <div style="display: flex; justify-content: space-between; align-items: center; background: #11151c; border: 1px solid var(--linha); padding: 10px 12px; border-radius: 4px; width: 100%; box-sizing: border-box; margin-top: 10px;">
                                <div style="text-align: left; flex: 1; min-width: 0; padding-right: 8px;">
                                    <div style="font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.nome }}</div>
                                    <div style="font-size: 9px; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ a.industria }}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div style="text-align: right; padding-right: 10px; border-right: 1px dashed var(--linha);">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Var (24H)</div>
                                        <div style="font-size: 22px; font-weight: bold; font-family: monospace; color: {{ a.var_cor }};">{{ a.var_dia }}</div>
                                    </div>
                                    <div style="text-align: right; min-width: 65px;">
                                        <div style="font-size: 15px; color: var(--mudo); text-transform: uppercase; margin-bottom: 1px;">Cotação</div>
                                        <div style="font-size: 22px; font-weight: bold; color: #fff; font-family: monospace;">{{ a.preco_atual }} <span style="font-size: 9px; color: var(--mudo);">{{ a.moeda }}</span></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="flex: 1.5; display: flex; flex-direction: column; gap: 15px;">
         {% if a.grafico %}<img src="{{ a.grafico }}" style="width: 100%; border-radius: 4px; border: 1px solid var(--linha);">{% endif %}
         {% if a.radar %}<img src="{{ a.radar }}" style="width: 100%; border-radius: 4px;" alt="Radar">{% endif %}
    </div>
                        
                    </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          {% else %}<div class="vazio">O sistema não detetou ativos insolventes na listagem.</div>{% endif %}
      </div>


    <!-- MAPA DE COBERTURA (UNIVERSO DE TICKERS) -->
      <div style="margin-top: 40px; margin-bottom: 20px;">
          <details style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 6px; padding: 15px; cursor: pointer;">
              <summary style="font-size: 13px; font-weight: bold; color: var(--texto); text-transform: uppercase; list-style: none; display: flex; align-items: center; outline: none; letter-spacing: 0.5px;">
                  <span style="color: var(--azul); font-size: 16px; margin-right: 8px;">▸</span> UNIVERSO DE COBERTURA (MAPA SETORIAL)
              </summary>
              
              <div style="margin-top: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; cursor: default;">
                  {% for key, setor in universo.items() %}
                  <div style="background: var(--painel); border: 1px solid var(--linha); border-radius: 4px; padding: 12px; display: flex; flex-direction: column;">
                      
                      <div style="font-size: 11px; font-weight: bold; color: var(--mudo); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; border-bottom: 1px dashed var(--linha); padding-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                          {{ setor.nome }}
                          <span style="background: #1a2133; color: var(--azul); padding: 2px 6px; border-radius: 3px; font-size: 9px;">{{ setor.tickers|length }}</span>
                      </div>
                      
                      <div style="font-size: 11px; color: {% if setor.tickers %}#fff{% else %}var(--mudo){% endif %}; display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start; flex-grow: 1;">
                          {% if setor.tickers %}
                              {% for t in setor.tickers %}
                              <span class="dica-edu dica-desce" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); padding: 4px 8px; border-radius: 3px; font-family: monospace; letter-spacing: 0.5px; border-bottom: 1px solid rgba(255,255,255,0.08); cursor: crosshair;">
                                  {{ t }}
                                  <span class="dica-texto" style="width: auto; white-space: nowrap; font-size: 10px; color: var(--mudo); text-transform: none;">Ativo monitorizado na matriz base</span>
                              </span>
                              {% endfor %}
                          {% else %}
                              <span style="font-style: italic; opacity: 0.5; width: 100%; text-align: center; padding: 10px 0;">Setor sem cobertura</span>
                          {% endif %}
                      </div>
                      
                  </div>
                  {% endfor %}
              </div>
          </details>
      </div>


    <div style="margin-top: 50px; border-top: 1px solid var(--linha); padding-top: 20px;">
          <details style="background: var(--painel-dark); border: 1px solid var(--linha); border-radius: 6px; padding: 15px; cursor: pointer;">
              <summary style="font-size: 13px; font-weight: bold; color: var(--amarelo); user-select: none;">
                  ⚠️ Termo de Isenção de Responsabilidade & Verificação de Autoria
              </summary>
              <div style="margin-top: 15px; font-size: 12px; color: var(--mudo); cursor: default; line-height: 1.6; text-align: justify;">
                  <p><strong>Isenção de Responsabilidade (Disclaimer):</strong> O conteúdo deste relatório gerado automaticamente por via algorítmica destina-se exclusivamente a fins informativos e educacionais. Nenhuma das informações, métricas ou sugestões de dimensionamento de posição aqui expostas constitui uma recomendação de compra, venda ou investimento em ativos financeiros. O mercado de capitais envolve riscos elevados e perdas potenciais de capital. Cabe ao utilizador validar os dados e tomar decisões de forma independente.</p>
                  <p style="border-top: 1px dashed var(--linha); padding-top: 10px; margin-top: 10px;">
                      <strong>Assinatura Digital de Integridade:</strong> <code style="background: #151a23; color: var(--azul); padding: 2px 6px; border-radius: 3px; font-weight: bold; font-size: 11px;">{{ hash_autoria }}</code>
                  </p>
              </div>
          </details>
      </div>
    </main>
    </body>
    </html>
"""

def funcao_legado_remover_se_desnecessario():
    # Nota: Este bloco de gravação estava solto no código original gerando falhas. 
    # Está desativado mas as linhas foram preservadas na íntegra a seu pedido.
    pass
    """
    html_saida = Template(radar_states_escolhidos.html).render(
        risco=risco, tier_a=formatar_tabela(tier_a), tier_b=formatar_tabela(tier_b), 
        blacklist=formatar_tabela(blacklist), graf_disp=graf_disp, graf_backtest=graf_backtest,
        data=datetime.now().strftime("%d de %B de %Y")
    )
    with open("radar_states_escolhidos.html", "w", encoding="utf-8") as f: f.write(html_saida)
    print("\n✅ Relatório integral gerado. Tier B e Blacklist restaurados com sucesso.")
    """

   

if __name__ == "__main__":

    # --- VARIÁVEIS DE FALLBACK ---
    # Garantem que o HTML renderiza sempre, mesmo em execuções parciais ou via CMD
    dados_breadth = None
    alertas_diarios = []

    # 1. Calcular o Regime Global
    risco_global = avaliar_risco_mercado()
    breadth_global = avaliar_breadth_macro() # <-- NOVA LINHA
    smart_money = avaliar_smart_money()
    curva_juros = avaliar_curva_juros()
    
    data_hoje = datetime.now().strftime("%d de %B de %Y")
    # Passa esta variável no bloco de renderização do Jinja
    grafico_rrg = gerar_rrg_setorial()

    
    # 1.5 Capturar o pulso diário dos Índices Globais
    dados_idx_raw = yf.download(["SPY", "QQQ", "IWM", "^VIX", "PSI20.LS"], period="5d", progress=False, threads=False)['Close']
    indices_diarios = []
    for nome, t in [("S&P 500", "SPY"), ("Nasdaq 100", "QQQ"), ("Russell 2000", "IWM"), ("Volatilidade VIX", "^VIX"), ("PSI 20 (Lisboa)", "PSI20.LS")]:
        try:
            # Isola a coluna do ticker e apaga os buracos (NaNs). Assim o iloc[-1] será sempre o último fecho real.
            serie_limpa = dados_idx_raw[t].dropna() 
            perf = ((serie_limpa.iloc[-1] / serie_limpa.iloc[-2]) - 1) * 100
            indices_diarios.append({"nome": nome, "perf": round(perf, 2)})
        except: pass

    print("=== MODO NEWSLETTER GLOBAL ===")
    

    # Passas a descompactar 10 variáveis
    
    
    
    
    t_a, t_b, t_q, bl, g_disp, g_back, movers_diarios, correlacao_a, alertas_diarios, dados_breadth, breadth_macro, mapa_cobertura = executar_screener()


      

    gravar_historico_auditoria(t_a, t_b)
    
    # 3. Processar Destaques a Pedido se houver argumentos no terminal
    destaques_html = []
    if len(sys.argv) > 1:
        # sys.argv[1] será algo como "ENR.DE,TMV.DE,ADS.DE"
        lista_pedidos = analisar_destaques_pedido(sys.argv[1])
        destaques_html = formatar_tabela(lista_pedidos)

    # 4. Calcular os dados para os 3 Cartões de Métricas no topo
    alocacao_total = sum([float(str(a.get('position_size', '0')).replace('%', '')) for a in t_a]) if t_a else 0
    liquidez_restante = max(0, 100 - alocacao_total)
    
    dados_carteira = {
        "total_alocado": f"{alocacao_total:.1f}",
        "liquidez": f"{liquidez_restante:.1f}"
    }

    dados_screener = {
        "total_ativos": len(t_a) + len(t_b),
        "tier_a": len(t_a),
        "tier_b": len(t_b)
    }

    # Gerar o gráfico Donut de setores usando o Tier A
    grafico_donut = gerar_grafico_setores(t_a)

    

    # 4.5 Gerar Assinatura Digital de Autoria Inalterável
    chave_secreta = "Luís Reis"
    string_verificacao = f"{chave_secreta}-{data_hoje}-{len(t_a)}"
    # Cria um hash hexadecimal único e extrai os 16 caracteres mais fortes
    hash_autoria = "RADAR-" + hashlib.sha256(string_verificacao.encode()).hexdigest()[:16].upper()


    # CONTROLADOR MACRO (Atualizar manualmente para garantir que o script nunca estoira)
    datas_macro = {
        "inflacao": "12 AGOSTO",
        "juros": "18 SETEMBRO",
        "emprego": "02 AGOSTO"
    }


    html_final = Template(html_template).render(
        risco=risco_global,
        breadth=breadth_global,
        fluxo=smart_money,
        curva=curva_juros,          # <-- NOVA LINHA
        correlacao=correlacao_a, 
        data=data_hoje,
        carteira=dados_carteira,
        screener=dados_screener,
        movers=movers_diarios, 
        indices=indices_diarios, # <--- NOVA LINHA AQUI
        destaques=destaques_html,
        graf_setores=grafico_donut,
        excecoes=alertas_diarios,
        tier_a=formatar_tabela(t_a), 
        tier_b=formatar_tabela(t_b),
        quarentena=formatar_tabela(t_q), # <-- Passa a Quarentena formatada 
        blacklist=formatar_tabela(bl),
        g_disp=g_disp,
        #graf_disp=g_disp, 
        graf_backtest=g_back,
        hash_autoria=hash_autoria,
        # Novas variáveis para o KPI
        total_ativos = len(t_a) + len(t_b) + len(t_q) + len(bl),
        q_a = len(t_a),
        q_b = len(t_b),
        q_q = len(t_q),
        q_bl = len(bl),
        breadth_interno=dados_breadth,
        barras_sp500=breadth_macro,
        grafico_rrg=grafico_rrg,
        macro=datas_macro,
        universo=mapa_cobertura
        
    )
    
    # 1. Gera a etiqueta de data (ex: 21jul26) formatando a data de hoje e forçando minúsculas
    sufixo_data = datetime.now().strftime("%d%b%y").lower()
    nome_ficheiro = f"radar_states_escolhidos_{sufixo_data}.html"
    
    # 2. Grava o ficheiro com o nome dinâmico criado
    with open(nome_ficheiro, "w", encoding="utf-8") as f_out:
        f_out.write(html_final)
        
    print(f"=== SUCESSO: Newsletter Global gerada em {nome_ficheiro} ===")