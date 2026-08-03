import yfinance as yf
import pandas as pd
import numpy as np

def calcular_rsi_pandas(serie, periodo=4):
    delta = serie.diff()
    ganhos = delta.clip(lower=0).ewm(com=periodo-1, adjust=False).mean()
    perdas = -1 * delta.clip(upper=0).ewm(com=periodo-1, adjust=False).mean()
    rs = ganhos / perdas.replace(0, np.nan)
    return (100 - (100 / (1.0 + rs))).fillna(100)

def calcular_radar_reversao(lista_tickers):
    resultados = []
    print(f"A processar radar de Mean Reversion para {len(lista_tickers)} ativos...")
    
    dados_acoes = yf.download(lista_tickers, period="6mo", progress=False)['Close']
    
    for ticker in lista_tickers:
        try:
            fechos = dados_acoes if len(lista_tickers) == 1 else dados_acoes[ticker]
            fechos = fechos.dropna().copy()
            
            if len(fechos) < 30:
                continue

            # NOVO: Ir buscar a cotação em tempo real (fast_info) para corrigir desfasamentos
            try:
                ticker_obj = yf.Ticker(ticker)
                preco_real = ticker_obj.fast_info['lastPrice']
                if preco_real and not np.isnan(preco_real):
                    # Substitui o último valor do histórico pelo preço real instantâneo
                    fechos.iloc[-1] = preco_real
            except Exception:
                pass # Se falhar o tempo real, mantemos o último fecho histórico
                
            preco_atual = fechos.iloc[-1]
            
            # 1. RSI Curto Prazo (4 dias) com o preço real injetado
            rsi_4 = calcular_rsi_pandas(fechos, 4).iloc[-1]
            
            # 2. Bollinger Bands
            sma_20 = fechos.rolling(window=20).mean()
            std_20 = fechos.rolling(window=20).std()
            banda_inferior = sma_20 - (2 * std_20)
            
            distancia_banda = ((preco_atual / banda_inferior.iloc[-1]) - 1) * 100
            
            # 3. Filtros
            if rsi_4 < 30 and distancia_banda < 1.5: 
                resultados.append({
                    'Ticker': ticker,
                    'Preço': round(preco_atual, 2),
                    'RSI (4)': round(rsi_4, 2),
                    'Dist. Banda Inf. (%)': round(distancia_banda, 2)
                })
                
        except Exception:
            continue

    df_resultados = pd.DataFrame(resultados)
    if not df_resultados.empty:
        df_resultados = df_resultados.sort_values(by='RSI (4)', ascending=True)
        
    return df_resultados