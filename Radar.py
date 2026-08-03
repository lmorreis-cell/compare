import yfinance as yf
import pandas as pd
import numpy as np

def calcular_rsi(serie, periodo=14):
    """Cálculo do RSI usando Pandas puro (Exponential Moving Average)"""
    delta = serie.diff()
    ganhos = delta.clip(lower=0).ewm(com=periodo-1, adjust=False).mean()
    perdas = -1 * delta.clip(upper=0).ewm(com=periodo-1, adjust=False).mean()
    
    rs = ganhos / perdas.replace(0, np.nan)
    rsi = 100 - (100 / (1.0 + rs))
    
    return rsi.fillna(100)

def calcular_radar_momentum_v2(lista_tickers, ticker_indice="^GSPC"):
    print("A descarregar dados do índice de referência...")
    # Adicionado threads=True
    indice = yf.download(ticker_indice, period="2y", progress=False, threads=True)['Close']
    
    if indice.empty:
        print("Erro ao obter o índice.")
        return []

    resultados = []
    print(f"A processar o radar para {len(lista_tickers)} ativos...")
    # Adicionado threads=True para paralelizar o download maciço
    dados_acoes = yf.download(lista_tickers, period="2y", progress=False, threads=True)['Close']

    for ticker in lista_tickers:
        try:
            fechos = dados_acoes if len(lista_tickers) == 1 else dados_acoes[ticker]
            fechos = fechos.dropna()
            
            if len(fechos) < 252:
                continue
                
            roc_6m = fechos.pct_change(periods=126).iloc[-1] * 100
            
            serie_rsi = calcular_rsi(fechos, 14)
            rsi_14 = serie_rsi.iloc[-1]
            
            dados_alinhados = pd.concat([fechos, indice], axis=1).dropna()
            dados_alinhados.columns = ['Acao', 'Indice']
            rs_base = dados_alinhados['Acao'] / dados_alinhados['Indice']
            sma_rs = rs_base.rolling(window=252).mean()
            mansfield = ((rs_base / sma_rs) - 1) * 100
            mansfield_atual = mansfield.iloc[-1]

            if roc_6m > 0 and rsi_14 < 65 and mansfield_atual > 0:
                resultados.append({
                    'Ticker': ticker,
                    'ROC_6M (%)': round(roc_6m, 2),
                    'RSI_14': round(rsi_14, 2),
                    'Mansfield RS': round(mansfield_atual, 2)
                })
                
        except Exception:
            continue

    df_resultados = pd.DataFrame(resultados)
    if not df_resultados.empty:
        df_resultados = df_resultados.sort_values(by='Mansfield RS', ascending=False)
        
    return df_resultados

def comparar_ativos(ticker1, ticker2, ticker_indice="^GSPC"):
    lista = [ticker1.upper(), ticker2.upper()]
    # Adicionado threads=True
    indice = yf.download(ticker_indice, period="2y", progress=False, threads=True)['Close']
    
    # Adicionado threads=True
    dados = yf.download(lista, period="2y", progress=False, threads=True)
    
    resultados = []
    for ticker in lista:
        try:
            fechos = dados['Close'][ticker].dropna()
            high = dados['High'][ticker].dropna()
            low = dados['Low'][ticker].dropna()
            
            if len(fechos) < 252: continue
            
            preco_atual = fechos.iloc[-1]
            
            tr = pd.concat([
                high - low,
                (high - fechos.shift(1)).abs(),
                (low - fechos.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr_14 = tr.rolling(window=14).mean().iloc[-1]
            
            roc_6m = fechos.pct_change(periods=126).iloc[-1] * 100
            rsi_14 = calcular_rsi(fechos, 14).iloc[-1]
            
            alinhados = pd.concat([fechos, indice], axis=1).dropna()
            alinhados.columns = ['Acao', 'Indice']
            rs = alinhados['Acao'] / alinhados['Indice']
            sma_rs = rs.rolling(window=252).mean()
            mansfield = (((rs / sma_rs) - 1) * 100).iloc[-1]
            
            alvo_t1 = preco_atual + (1.5 * atr_14)
            alvo_t2 = preco_atual + (3.0 * atr_14)
            stop_loss = preco_atual - (1.5 * atr_14)
            
            resultados.append({
                'Ticker': ticker,
                'Preço': round(preco_atual, 2),
                'Mansfield RS': round(mansfield, 2),
                'ROC 6M (%)': round(roc_6m, 2),
                'RSI (14)': round(rsi_14, 2),
                'Alvo T1 (€)': round(alvo_t1, 2),
                'Alvo T2 (€)': round(alvo_t2, 2),
                'Stop Loss (€)': round(stop_loss, 2)
            })
        except Exception:
            continue
            
    return pd.DataFrame(resultados)
