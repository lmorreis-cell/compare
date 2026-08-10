import os
from dotenv import load_dotenv

# 1. Carrega as variáveis de ambiente (resolve a Porta 8080)
load_dotenv()

# NOVO: Adicionar request e Response às importações do Flask
from flask import Flask, render_template, jsonify, request, Response

# 2. Importa os teus motores de cálculo (O QUE FALTAVA)
from Regime import avaliar_regime_mercado
from MeanReversion import calcular_radar_reversao
from Radar import calcular_radar_momentum_v2, comparar_ativos


# ... resto do teu código para baixo fica igual ...
app = Flask(__name__)

# ==========================================
# MOTOR DE SEGURANÇA (HTTP BASIC AUTH)
# ==========================================
def check_auth(username, password):
    # O username será sempre 'admin'
    # A senha é puxada do teu ficheiro .env
    senha_correta = os.environ.get("APP_PASSWORD", "bloqueado")
    return username == 'admin' and password == senha_correta

def authenticate():
    # Envia o comando para o browser abrir o pop-up de login
    return Response(
    'Acesso restrito. Área quantitativa privada.\n', 401,
    {'WWW-Authenticate': 'Basic realm="Acesso Reservado"'})

@app.before_request
def require_login():
    # Interceta TODOS os pedidos antes de chegarem às rotas
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/analisar')
def api_analisar():
    caminho_ficheiro = "tickers_comparacao.txt"
    try:
        with open(caminho_ficheiro, 'r') as ficheiro:
            meus_tickers = [linha.strip() for linha in ficheiro if linha.strip()]
    except FileNotFoundError:
        return jsonify({"erro": "Ficheiro tickers.txt não encontrado."}), 500

    indice_ref = "^GSPC"
    
    try:
        estado_mercado = avaliar_regime_mercado(indice_ref)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    resposta = {
        "regime": estado_mercado['regime'],
        "adx": estado_mercado['adx_atual'],
        "estrategia": "",
        "ativos": []
    }

    # O cérebro toma a decisão de forma autónoma
    if "Tendência Alta" in estado_mercado['regime']:
        resposta["estrategia"] = "Estratégia Ativa: Trend Following (Momentum)"
        oportunidades = calcular_radar_momentum_v2(meus_tickers, indice_ref)
    else:
        resposta["estrategia"] = "Estratégia Ativa: Mean Reversion (Ressaltos em Suporte)"
        oportunidades = calcular_radar_reversao(meus_tickers)
        
    if not oportunidades.empty:
        resposta["ativos"] = oportunidades.to_dict(orient='records')

    return jsonify(resposta)

@app.route('/api/comparar/<ticker1>/<ticker2>')
def api_comparar(ticker1, ticker2):
    df_comparacao = comparar_ativos(ticker1, ticker2)
    
    if df_comparacao.empty:
        return jsonify({"erro": "Não foi possível obter dados para um ou ambos os tickers."}), 400
        
    return jsonify(df_comparacao.to_dict(orient='records'))

@app.route('/api/universo')
def api_universo():
    import yfinance as yf
    import requests
    import json
    import os
    import time
    
    caminho_ficheiro = "tickers_comparacao.txt"
    ficheiro_cache = "setores_cache.json"

    try:
        with open(caminho_ficheiro, 'r') as ficheiro:
            meus_tickers = [linha.strip() for linha in ficheiro if linha.strip()]
    except FileNotFoundError:
        return jsonify({"erro": "Ficheiro tickers_comparacao.txt não encontrado."}), 500

    # 1. Carrega a memória (Cache) se ela já existir no servidor
    cache_setores = {}
    if os.path.exists(ficheiro_cache):
        try:
            with open(ficheiro_cache, 'r') as f:
                cache_setores = json.load(f)
        except Exception:
            pass

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

    # Disfarça o pedido web para não ser detetado como Bot pelo Yahoo
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'})

    atualizou_cache = False

    for ticker in meus_tickers:
        setor_raw = "Unknown"
        
        # 2. Se a ação já estiver na nossa memória, usamos sem ir à internet
        if ticker in cache_setores:
            setor_raw = cache_setores[ticker]
        else:
            # 3. Se for uma ação nova, perguntamos ao Yahoo e guardamos
            try:
                info = yf.Ticker(ticker, session=session).info
                setor_raw = info.get('sector', 'Unknown')
                
                cache_setores[ticker] = setor_raw
                atualizou_cache = True
                time.sleep(0.1) # Pausa de 100ms para não engatilhar o bloqueio do Yahoo
            except Exception:
                pass

        if setor_raw in universo_setorial:
            universo_setorial[setor_raw]["tickers"].append(ticker)
        else:
            universo_setorial["Unknown"]["tickers"].append(ticker)

    # 4. Grava a nova memória no disco para usos futuros
    if atualizou_cache:
        try:
            with open(ficheiro_cache, 'w') as f:
                json.dump(cache_setores, f)
        except Exception:
            pass

    resultado_final = {}
    for key, setor in universo_setorial.items():
        if setor["tickers"]:
            setor["tickers"].sort()
            resultado_final[key] = setor

    return jsonify(resultado_final)

    # Varre a lista mestre
    for ticker in meus_tickers:
        try:
            info = yf.Ticker(ticker).info
            setor_raw = info.get('sector', 'Unknown')
            if setor_raw in universo_setorial:
                universo_setorial[setor_raw]["tickers"].append(ticker)
            else:
                universo_setorial["Unknown"]["tickers"].append(ticker)
        except Exception:
            universo_setorial["Unknown"]["tickers"].append(ticker)

    # Limpar setores vazios e ordenar alfabeticamente
    resultado_final = {}
    for key, setor in universo_setorial.items():
        if setor["tickers"]:
            setor["tickers"].sort()
            resultado_final[key] = setor

    return jsonify(resultado_final)

if __name__ == "__main__":
    # Verifica se a variável PORT existe (o Discloud cria isto automaticamente)
    porta = int(os.environ.get("PORT", 8080))
    if "PORT" in os.environ:
        # Ambiente Cloud (Produção)
        porta = int(os.environ.get("PORT"))
        app.run(host="0.0.0.0", port=porta)
    else:
        # Ambiente Local (O teu PC)
        # Mantém a porta 5000 e ativa o reinício automático (debug)
        app.run(debug=True, port=5000)
