import os
import json
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# Carrega as variáveis de ambiente (o teu ficheiro .env)
load_dotenv()

ARQUIVO_WATCHLIST = "watchlist.json"
WEBHOOK_WATCHLIST = os.environ.get("WEBHOOK_WATCHLIST")

def processar_vigia():
    print(f"[{datetime.now()}] A iniciar Motor de Vigia Algorítmico...")

    if not WEBHOOK_WATCHLIST:
        print("Erro: WEBHOOK_WATCHLIST não configurado no .env")
        return

    if not os.path.exists(ARQUIVO_WATCHLIST):
        print("Watchlist vazia ou ficheiro inexistente. Operação abortada.")
        return

    with open(ARQUIVO_WATCHLIST, 'r') as f:
        watchlist = json.load(f)

    if not watchlist:
        print("Nenhum utilizador com ativos na watchlist.")
        return

    # 1. Agrupar todos os tickers únicos para não massacrar a API do Yahoo
    # (Se 10 pessoas vigiam a TSLA, o algoritmo só faz o download 1 vez)
    tickers_unicos = set()
    for user_id, alertas in watchlist.items():
        for alerta in alertas:
            tickers_unicos.add(alerta['ticker'])

    if not tickers_unicos:
        print("Nenhum ticker para verificar.")
        return

    tickers_lista = list(tickers_unicos)
    string_tickers = " ".join(tickers_lista)
    
    print(f"A descarregar dados para {len(tickers_lista)} ativos...")
    dados = yf.download(string_tickers, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)

    # 2. Armazém de Resultados: quem é que cumpriu o setup hoje?
    gatilhos_acionados = {}

    for ticker in tickers_lista:
        try:
            # Tratamento da estrutura do Pandas dependendo se é 1 ou vários tickers
            df = dados.dropna() if len(tickers_lista) == 1 else dados[ticker].dropna()
            if df.empty or len(df) < 200:
                continue

            # --- MATEMÁTICA PESADA ---
            df['SMA200'] = df['Close'].rolling(200).mean()
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            # Bollinger Bands
            df['BB_Mid'] = df['Close'].rolling(20).mean()
            df['BB_Std'] = df['Close'].rolling(20).std()
            df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
            df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']

            fecho_atual = float(df['Close'].iloc[-1])
            
            # --- VALIDAÇÃO DOS SETUPS TÁTICOS ---
            gatilhos_acionados[ticker] = []

            # Setup 1: Pullback Tático
            # Regra: Preço numa tendência primária de alta (> SMA200) e a tocar na EMA20 (margem de 1.5%)
            if fecho_atual > df['SMA200'].iloc[-1]:
                distancia_ema20 = abs(fecho_atual - df['EMA20'].iloc[-1]) / fecho_atual
                if distancia_ema20 <= 0.015:
                    gatilhos_acionados[ticker].append('pullback')

            # Setup 2: Bollinger Squeeze
            # Regra: Largura da banda atual está no percentil 10 (mínimos dos últimos tempos)
            if df['BB_Width'].iloc[-1] < df['BB_Width'].tail(100).quantile(0.10):
                gatilhos_acionados[ticker].append('squeeze')

            # Setup 3: Capitulação Extrema (Oversold)
            # Regra: RSI < 30
            if df['RSI'].iloc[-1] < 30:
                gatilhos_acionados[ticker].append('oversold')

        except Exception as e:
            print(f"Erro a processar {ticker}: {e}")
            continue

    # 3. Cruzamento e Disparo de Alertas
    alertas_enviados = 0
    mensagens_discord = []

    # Textos formatados para o Discord (O Efeito Educacional)
    descricoes_setup = {
        'pullback': "📉 **Pullback Tático Confirmado:** O ativo suportou milimetricamente na média móvel de 20 dias (EMA 20). Setup clássico de Trend Following de baixo risco.",
        'squeeze': "🗜️ **Bollinger Squeeze Iminente:** O mercado está sem liquidez direcional e a mola está comprimida ao máximo. Prepara-te para uma explosão de volatilidade.",
        'oversold': "🩸 **Capitulação Extrema (RSI < 30):** Pânico total instalado. O ativo está sobrevendido face à média. Possibilidade matemática de ressalto de curto prazo."
    }

    for user_id, alertas_user in watchlist.items():
        for alerta in alertas_user:
            ticker = alerta['ticker']
            setup = alerta['setup']

            # Se este ticker acionou hoje a anomalia que este utilizador procurava
            if ticker in gatilhos_acionados and setup in gatilhos_acionados[ticker]:
                
                texto_alerta = descricoes_setup[setup]
                
                # A MAGIA DA ENGENHARIA SOCIAL: Fazemos o PING do utilizador fora do Embed para o telemóvel dele tocar!
                payload = {
                    "content": f"🚨 <@{user_id}> O teu gatilho de mercado foi ativado!",
                    "embeds": [
                        {
                            "title": f"🎯 ALVO TÁTICO: {ticker}",
                            "color": 15965184, # Laranja do Portal
                            "description": texto_alerta,
                            "footer": {
                                "text": "Portal Bolsa - Motor de Vigia Algorítmico"
                            }
                        }
                    ]
                }
                mensagens_discord.append(payload)

    # 4. Envio Sequencial para o Discord
    if mensagens_discord:
        print(f"A transmitir {len(mensagens_discord)} alertas para o servidor Discord...")
        for msg in mensagens_discord:
            try:
                resp = requests.post(WEBHOOK_WATCHLIST, json=msg)
                resp.raise_for_status()
                alertas_enviados += 1
            except Exception as e:
                print(f"Falha ao enviar webhook: {e}")
    else:
        print("Nenhum setup da Watchlist atingiu as condições matemáticas hoje.")

    print(f"[{datetime.now()}] Ciclo fechado. {alertas_enviados} alertas entreges com sucesso.")

if __name__ == "__main__":
    processar_vigia()
