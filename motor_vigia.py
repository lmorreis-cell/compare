import os
import json
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ARQUIVO_WATCHLIST = "watchlist.json"
WEBHOOK_WATCHLIST = os.environ.get("WEBHOOK_WATCHLIST")

def processar_vigia():
    print(f"[{datetime.now()}] A iniciar Motor de Vigia Algorítmico...")

    if not WEBHOOK_WATCHLIST:
        print("Erro: WEBHOOK_WATCHLIST não configurado no .env")
        return

    if not os.path.exists(ARQUIVO_WATCHLIST):
        print("Watchlist vazia ou ficheiro inexistente.")
        return

    with open(ARQUIVO_WATCHLIST, 'r') as f:
        watchlist = json.load(f)

    if not watchlist:
        return

    tickers_unicos = set()
    for user_id, alertas in watchlist.items():
        for alerta in alertas:
            tickers_unicos.add(alerta['ticker'])

    if not tickers_unicos:
        return

    tickers_lista = list(tickers_unicos)
    string_tickers = " ".join(tickers_lista)
    
    print(f"A descarregar dados para {len(tickers_lista)} ativos...")
    dados = yf.download(string_tickers, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)

    gatilhos_acionados = {}

    for ticker in tickers_lista:
        try:
            df = dados.dropna() if len(tickers_lista) == 1 else dados[ticker].dropna()
            if df.empty or len(df) < 200:
                continue

            df['SMA200'] = df['Close'].rolling(200).mean()
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            df['BB_Mid'] = df['Close'].rolling(20).mean()
            df['BB_Std'] = df['Close'].rolling(20).std()
            df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
            df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']

            fecho_atual = float(df['Close'].iloc[-1])
            gatilhos_acionados[ticker] = []

            if fecho_atual > df['SMA200'].iloc[-1]:
                if abs(fecho_atual - df['EMA20'].iloc[-1]) / fecho_atual <= 0.015:
                    gatilhos_acionados[ticker].append('pullback')

            if df['BB_Width'].iloc[-1] < df['BB_Width'].tail(100).quantile(0.10):
                gatilhos_acionados[ticker].append('squeeze')

            if df['RSI'].iloc[-1] < 30:
                gatilhos_acionados[ticker].append('oversold')

        except Exception as e:
            print(f"Erro a processar {ticker}: {e}")
            continue

    alertas_enviados = 0
    mensagens_discord = []
    houve_alteracao_json = False
    agora = datetime.now()

    descricoes_setup = {
        'pullback': "📉 **Pullback Tático Confirmado:** O ativo suportou milimetricamente na média móvel de 20 dias (EMA 20). Setup clássico de Trend Following de baixo risco.",
        'squeeze': "🗜️ **Bollinger Squeeze Iminente:** O mercado está sem liquidez direcional e a mola está comprimida ao máximo. Prepara-te para uma explosão de volatilidade.",
        'oversold': "🩸 **Capitulação Extrema (RSI < 30):** Pânico total instalado. O ativo está sobrevendido face à média. Possibilidade matemática de ressalto de curto prazo."
    }

    for user_id, alertas_user in watchlist.items():
        for alerta in alertas_user:
            ticker = alerta['ticker']
            setup = alerta['setup']

            # Verifica se o ticker tem algum gatilho acionado hoje
            if ticker in gatilhos_acionados:
                
                # A LÓGICA DO "QUALQUER" ANOMALIA
                gatilho_valido = None
                if setup == 'qualquer' and len(gatilhos_acionados[ticker]) > 0:
                    # O utilizador quer qualquer anomalia. Apanhamos a primeira que ocorreu no array.
                    gatilho_valido = gatilhos_acionados[ticker][0]
                elif setup in gatilhos_acionados[ticker]:
                    # O utilizador pediu um setup específico e ele ocorreu.
                    gatilho_valido = setup

                # Se encontrámos um gatilho válido para notificar
                if gatilho_valido:
                    
                    # BARREIRA DE ESTADO: Verificação das últimas 24 horas
                    ultimo_alerta_str = alerta.get('ultimo_alerta')
                    pode_enviar = True

                    if ultimo_alerta_str:
                        try:
                            ultimo_alerta_data = datetime.fromisoformat(ultimo_alerta_str)
                            if agora - ultimo_alerta_data < timedelta(hours=24):
                                pode_enviar = False
                        except ValueError:
                            pass # Ignora bloqueio se a string de data estiver corrompida

                    if pode_enviar:
                        texto_alerta = descricoes_setup.get(gatilho_valido, "Gatilho ativado.")
                        
                        # Se a opção original era "qualquer", adicionamos um aviso visual para o utilizador saber o que disparou
                        if setup == 'qualquer':
                            texto_alerta = f"*(Monitorização Ampla)*\n\n" + texto_alerta

                        payload = {
                            "content": f"🚨 <@{user_id}> O teu gatilho de mercado foi ativado!",
                            "embeds": [{
                                "title": f"🎯 ALVO TÁTICO: {ticker}",
                                "color": 15965184,
                                "description": texto_alerta,
                                "footer": {"text": "Portal Bolsa - Motor de Vigia Algorítmico"}
                            }]
                        }
                        mensagens_discord.append(payload)

                        # Atualiza o carimbo de tempo no dicionário em memória
                        alerta['ultimo_alerta'] = agora.isoformat()
                        houve_alteracao_json = True

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
        print("Nenhum setup atingiu as condições matemáticas ou os alertas encontram-se em período de cooldown (24h).")

    # ESCRITA NO DISCO: Guarda as alterações de estado se novos alertas foram disparados
    if houve_alteracao_json:
        try:
            with open(ARQUIVO_WATCHLIST, 'w') as f:
                json.dump(watchlist, f, indent=4)
        except Exception as e:
            print(f"Erro ao atualizar estado da watchlist no disco: {e}")

    print(f"[{datetime.now()}] Ciclo fechado. {alertas_enviados} alertas entregues com sucesso.")

if __name__ == "__main__":
    processar_vigia()
