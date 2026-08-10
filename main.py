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
