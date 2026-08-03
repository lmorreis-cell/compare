import yfinance as yf
import pandas as pd
import numpy as np

def avaliar_regime_mercado(ticker_indice="^GSPC", periodo="1y"):
    """
    Avalia o regime de mercado usando o ADX (Average Directional Index)
    calculado com Pandas e Numpy puros, sem dependência do pandas_ta.
    """
    print(f"A extrair dados do índice de referência: {ticker_indice}...")
    
    indice = yf.Ticker(ticker_indice)
    df = indice.history(period=periodo)
    
    if df.empty:
        raise ValueError("Falha na extração de dados. Verifica o ticker.")

    # 1. Preparar os dados de preço
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # 2. Calcular o True Range (TR)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 3. Calcular o Movimento Direcional (+DM e -DM)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # 4. Aplicar a Média Móvel Exponencial (aproximação ao Wilder's Smoothing, período 14)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr)
    
    # 5. Calcular o DX e finalmente o ADX
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1/14, adjust=False).mean()
    
    # 6. Extrair os valores atuais
    ultimo_adx = adx.iloc[-1]
    di_positivo = plus_di.iloc[-1]
    di_negativo = minus_di.iloc[-1]
    
    # 7. Lógica de Decisão do Regime
    regime = "Indefinido"
    if ultimo_adx > 25:
        if di_positivo > di_negativo:
            regime = "Tendência Alta (Trend Following)"
        else:
            regime = "Tendência Baixa (Short/Cash)"
    else:
        regime = "Mercado Lateral (Mean Reversion)"
        
    return {
        "ticker": ticker_indice,
        "adx_atual": round(ultimo_adx, 2),
        "regime": regime
    }