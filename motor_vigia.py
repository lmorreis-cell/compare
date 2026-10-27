import os
import json
import threading
import time
import requests
import pandas as pd
import yahoo_guard as yg
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ARQUIVO_WATCHLIST = "watchlist.json"
WEBHOOK_WATCHLIST = os.environ.get("WEBHOOK_WATCHLIST")

# ==========================================
# TRAVÕES ANTI-LOOP (a causa provável do bloqueio do Yahoo)
# ==========================================
# 1. Só pode existir UMA execução de cada vez (o cron já não consegue empilhar threads).
# 2. Intervalo mínimo entre execuções, persistido em disco para sobreviver a reinícios
#    (protege contra um cron mal configurado a disparar de minuto a minuto).
_LOCK_VIGIA = threading.Lock()
ARQUIVO_ULTIMA_EXECUCAO = "vigia_ultima_execucao.txt"
INTERVALO_MIN_EXECUCOES_SEG = int(os.environ.get("VIGIA_INTERVALO_MIN_SEG", 20 * 60))


def _segundos_desde_ultima_execucao():
    try:
        with open(ARQUIVO_ULTIMA_EXECUCAO, 'r') as f:
            return time.time() - float(f.read().strip())
    except Exception:
        return float('inf')


def _marcar_execucao():
    try:
        with open(ARQUIVO_ULTIMA_EXECUCAO, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass


def vigia_em_execucao():
    return _LOCK_VIGIA.locked()


def pode_executar_agora():
    """Devolve (pode, motivo) — usado pela rota do cron para responder sem lançar threads inúteis."""
    if _LOCK_VIGIA.locked():
        return False, "O Motor de Vigia já está em execução."
    decorrido = _segundos_desde_ultima_execucao()
    if decorrido < INTERVALO_MIN_EXECUCOES_SEG:
        faltam = int((INTERVALO_MIN_EXECUCOES_SEG - decorrido) // 60) + 1
        return False, f"Execução recente. Próxima permitida dentro de {faltam} min."
    if yg.esta_bloqueado():
        return False, "Yahoo Finance em pausa de proteção (disjuntor aberto)."
    return True, ""


def processar_vigia():
    """Ponto de entrada público: aplica os travões e só depois corre o motor."""
    if not _LOCK_VIGIA.acquire(blocking=False):
        print(f"[{datetime.now()}] Motor de Vigia já em execução. Pedido ignorado.")
        return
    try:
        decorrido = _segundos_desde_ultima_execucao()
        if decorrido < INTERVALO_MIN_EXECUCOES_SEG:
            print(f"[{datetime.now()}] Execução ignorada: a última foi há {int(decorrido)}s "
                  f"(mínimo {INTERVALO_MIN_EXECUCOES_SEG}s).")
            return
        _marcar_execucao()  # marca ANTES de correr: se rebentar a meio, não volta a disparar logo
        _processar_vigia_interno()
    except yg.YahooIndisponivel as e:
        print(f"[{datetime.now()}] Motor de Vigia abortado: {e}")
    except Exception as e:
        print(f"[{datetime.now()}] Erro inesperado no Motor de Vigia: {e}")
    finally:
        _LOCK_VIGIA.release()


def _processar_vigia_interno():
    agora = datetime.now()
    dia_semana = agora.weekday() # 0 = Seg, ..., 5 = Sáb, 6 = Dom
    print(f"[{agora}] A iniciar Motor de Vigia Algorítmico...")

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

    # 1. FILTRO DE FIM DE SEMANA NA RAIZ (Poupa a API do Yahoo)
    tickers_unicos = set()
    for user_id, alertas in watchlist.items():
        for alerta in alertas:
            ticker = alerta['ticker']
            is_crypto = "-" in ticker
            
            # Se for Sábado (5) ou Domingo (6) e NÃO for cripto, ignoramos o ticker
            if dia_semana in [5, 6] and not is_crypto:
                continue
                
            tickers_unicos.add(ticker)

    if not tickers_unicos:
        print("Nenhum ativo elegível para processamento neste momento (Fim de semana em vigor para TradFi).")
        return

    tickers_lista = list(tickers_unicos)
    string_tickers = " ".join(tickers_lista)
    
    print(f"A descarregar dados para {len(tickers_lista)} ativos...")
    # Download em lote protegido (sequencial + disjuntor). Se o Yahoo bloquear, aborta limpo.
    dados = yg.download(string_tickers, period="1y", interval="1d", group_by="ticker")
    if dados is None or dados.empty:
        print("Sem dados do Yahoo neste ciclo. Nada a processar.")
        return

    gatilhos_acionados = {}
    info_mercado = {} # Dicionário novo para guardar Fechos e ATRs e usar no Cooldown

    for ticker in tickers_lista:
        try:
            df = yg.fatia(dados, ticker).dropna().copy()
            if df.empty or len(df) < 200:
                continue

            # --- CÁLCULO DE ATR (Volatilidade/Ruído) ---
            df['PrevClose'] = df['Close'].shift(1)
            df['TR'] = df[['High', 'PrevClose']].max(axis=1) - df[['Low', 'PrevClose']].min(axis=1)
            df['ATR'] = df['TR'].rolling(window=14).mean()

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

            df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
            df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
            df['Max_50'] = df['High'].shift(1).rolling(50).max()

            fecho_atual = float(df['Close'].iloc[-1])
            atr_atual = float(df['ATR'].iloc[-1])
            
            # Guarda info vital para a máquina de cooldown
            info_mercado[ticker] = {'fecho': fecho_atual, 'atr': atr_atual}
            gatilhos_acionados[ticker] = []

            if fecho_atual > df['SMA200'].iloc[-1]:
                if abs(fecho_atual - df['EMA20'].iloc[-1]) / fecho_atual <= 0.015:
                    gatilhos_acionados[ticker].append('pullback')

            if df['BB_Width'].iloc[-1] < df['BB_Width'].tail(100).quantile(0.10):
                gatilhos_acionados[ticker].append('squeeze')

            if df['RSI'].iloc[-1] < 30:
                gatilhos_acionados[ticker].append('oversold')

            if df['Volume'].iloc[-1] > (df['Vol_SMA20'].iloc[-1] * 3):
                gatilhos_acionados[ticker].append('volume_spike')

            if df['RSI'].iloc[-1] > 75 and fecho_atual > df['BB_Upper'].iloc[-1]:
                gatilhos_acionados[ticker].append('overbought')

            cruzamento_hoje = df['EMA9'].iloc[-1] > df['EMA20'].iloc[-1]
            cruzamento_ontem = df['EMA9'].iloc[-2] <= df['EMA20'].iloc[-2]
            if cruzamento_hoje and cruzamento_ontem:
                gatilhos_acionados[ticker].append('golden_cross_tatico')

            if fecho_atual >= df['Max_50'].iloc[-1]:
                gatilhos_acionados[ticker].append('breakout_50d')

        except Exception as e:
            print(f"Erro a processar {ticker}: {e}")
            continue

    alertas_enviados = 0
    mensagens_discord = []
    houve_alteracao_json = False

    descricoes_setup = {
        'pullback': "📉 **Pullback Tático Confirmado:** O ativo suportou milimetricamente na média móvel de 20 dias (EMA 20). Setup clássico de Trend Following de baixo risco.",
        'squeeze': "🗜️ **Bollinger Squeeze Iminente:** O mercado está sem liquidez direcional e a mola está comprimida ao máximo. Prepara-te para uma explosão de volatilidade.",
        'oversold': "🩸 **Capitulação Extrema (RSI < 30):** Pânico total instalado. O ativo está sobrevendido face à média. Possibilidade matemática de ressalto de curto prazo.",
        'volume_spike': "🐋 **Anomalia de Liquidez:** O volume transacionado hoje excedeu em mais de 300% a média mensal. Forte presença institucional detetada.",
        'overbought': "⚠️ **Risco de Exaustão (Take Profit):** O ativo encontra-se severamente sobrecomprado (RSI > 75) e a perfurar a Banda de Bollinger Superior. Considera proteger os teus lucros.",
        'golden_cross_tatico': "🚀 **Ignição de Momentum:** A EMA 9 acabou de cruzar acima da EMA 20. O ativo ativou um regime de tendência de alta tática.",
        'breakout_50d': "📈 **Breakout Estrutural:** O ativo acaba de quebrar a resistência máxima dos últimos 50 dias. Limpeza de oferta confirmada, caminho aberto."
    }

    for user_id, alertas_user in watchlist.items():
        for alerta in alertas_user:
            ticker = alerta['ticker']
            setup = alerta['setup']

            # Verifica se o ticker tem algum gatilho acionado hoje
            if ticker in gatilhos_acionados:
                
                fecho_atual = info_mercado[ticker]['fecho']
                atr_atual = info_mercado[ticker]['atr']
                
                # A LÓGICA DO "QUALQUER" ANOMALIA
                gatilho_valido = None
                if setup == 'qualquer' and len(gatilhos_acionados[ticker]) > 0:
                    gatilho_valido = gatilhos_acionados[ticker][0]
                elif setup in gatilhos_acionados[ticker]:
                    gatilho_valido = setup

                # Se encontrámos um gatilho válido para notificar
                if gatilho_valido:
                    
                    # ==========================================
                    # NOVO COOLDOWN CONDICIONAL (DIVERGÊNCIA DE ATR)
                    # ==========================================
                    ultimo_preco = alerta.get('preco_alerta')
                    ultima_data_str = alerta.get('data_alerta')
                    pode_enviar = True

                    if ultimo_preco and ultima_data_str:
                        try:
                            ultima_data = datetime.fromisoformat(ultima_data_str)
                            horas_desde_alerta = (agora - ultima_data).total_seconds() / 3600
                            distancia_movimento = abs(fecho_atual - ultimo_preco)
                            margem_ruido = atr_atual * 1.5
                            
                            # Proteção contra Stock Splits (se o preço diferir >40% face ao alerta anterior, limpa a memória)
                            if abs(fecho_atual - ultimo_preco) / ultimo_preco > 0.4:
                                pode_enviar = True 
                            # Se o preço não fugiu da margem de ruído E ainda não passaram 72h, bloqueia o alerta
                            elif (distancia_movimento < margem_ruido) and (horas_desde_alerta < 72):
                                pode_enviar = False
                        except ValueError:
                            pass # Em caso de erro na data, envia o alerta por segurança

                    if pode_enviar:
                        texto_alerta = descricoes_setup.get(gatilho_valido, "Gatilho ativado.")
                        
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

                        # Atualiza as âncoras temporais e espaciais no ficheiro JSON
                        alerta['preco_alerta'] = fecho_atual
                        alerta['data_alerta'] = agora.isoformat()
                        # Remove a chave antiga se existir
                        if 'ultimo_alerta' in alerta:
                            del alerta['ultimo_alerta']
                            
                        houve_alteracao_json = True

    if mensagens_discord:
        print(f"A transmitir {len(mensagens_discord)} alertas para o servidor Discord...")
        for msg in mensagens_discord:
            try:
                resp = requests.post(WEBHOOK_WATCHLIST, json=msg, timeout=10)
                time.sleep(0.5)  # respeita também o rate limit do Discord
                resp.raise_for_status()
                alertas_enviados += 1
            except Exception as e:
                print(f"Falha ao enviar webhook: {e}")
    else:
        print("Nenhum setup atingiu as condições matemáticas ou os ativos encontram-se bloqueados pela margem de ruído (Cooldown Condicional).")

    # ESCRITA NO DISCO
    if houve_alteracao_json:
        try:
            with open(ARQUIVO_WATCHLIST, 'w') as f:
                json.dump(watchlist, f, indent=4)
        except Exception as e:
            print(f"Erro ao atualizar estado da watchlist no disco: {e}")

    print(f"[{datetime.now()}] Ciclo fechado. {alertas_enviados} alertas entregues com sucesso.")

if __name__ == "__main__":
    processar_vigia()
