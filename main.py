import os
import subprocess
import glob
from dotenv import load_dotenv
from functools import wraps
from flask import Flask, render_template, jsonify, request, Response, send_file, render_template_string

load_dotenv()



# 2. Importa os teus motores de cálculo (O QUE FALTAVA)
from Regime import avaliar_regime_mercado
from MeanReversion import calcular_radar_reversao
from Radar import calcular_radar_momentum_v2, comparar_ativos


# ... resto do teu código para baixo fica igual ...
app = Flask(__name__)

# ==========================================
# MOTOR DE SEGURANÇA MULTI-PERFIL
# ==========================================
def check_auth(username, password, requer_admin=False):
    senha_admin = os.environ.get("APP_PASSWORD", "bloqueado_admin")
    senha_user = os.environ.get("USER_PASSWORD", "bloqueado_user")

    if requer_admin:
        # Acesso estrito: apenas o admin pode entrar
        return username == 'admin' and password == senha_admin
    else:
        # Acesso amplo: tanto o admin como o utilizador normal podem entrar
        valido_como_admin = (username == 'admin' and password == senha_admin)
        valido_como_user = (username == 'leitor' and password == senha_user)
        return valido_como_admin or valido_como_user

def authenticate():
    return Response('Acesso restrito.\n', 401, {'WWW-Authenticate': 'Basic realm="Login Necessário"'})

def requer_login(requer_admin=False):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password, requer_admin):
                return authenticate()
            return f(*args, **kwargs)
        return decorated_function
    return decorator
# ==========================================

# @app.route('/')
# def home():
#    return render_template('index.html')

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

@app.route('/')
@requer_login(requer_admin=False) # Qualquer pessoa com login válido chega aqui
def dashboard_central():
    is_admin = request.authorization.username == 'admin'
    
    html_dashboard = """
    <!DOCTYPE html>
    <html><head><title>Portal Quantitativo</title>
    <style>
        body { font-family: sans-serif; background: #121212; color: white; padding: 40px; text-align: center; }
        .btn { display: inline-block; padding: 15px 30px; margin: 10px; background: #3fbf8f; color: #121212; text-decoration: none; border-radius: 5px; font-weight: bold; cursor: pointer; border: none; font-size: 16px;}
        .btn-admin { background: #f28b24; }
        .box { background: #1e1e1e; padding: 30px; border-radius: 8px; margin-bottom: 20px; }
        #status { margin-top: 20px; color: #ff9800; font-family: monospace; }
    </style>
    </head><body>
        <h1>Portal Central de Relatórios</h1>
        
        <div class="box">
            <h2>Últimos Relatórios (Área de Leitura)</h2>
            <a href="/ver/europa" class="btn">Visualizar Radar Europa</a>
            <a href="/ver/states" class="btn">Visualizar Radar States</a>
        </div>

        {% if is_admin %}
        <div class="box" style="border: 1px solid #f28b24;">
            <h2 style="color: #f28b24;">Central de Comando (Acesso Restrito)</h2>
            <p style="font-size: 12px; color: #888;">Estes botões executam algoritmos pesados no servidor. Demora ~5 min.</p>
            <button onclick="correrScript('europa')" class="btn btn-admin">Executar Robô Europa</button>
            <button onclick="correrScript('states')" class="btn btn-admin">Executar Robô States</button>
            <div id="status"></div>
        </div>
        
        <script>
            async function correrScript(regiao) {
                document.getElementById('status').innerText = `A iniciar extração de dados do Yahoo Finance para ${regiao}... Por favor aguarde.`;
                const btnEuropa = document.querySelectorAll('.btn-admin')[0];
                const btnStates = document.querySelectorAll('.btn-admin')[1];
                btnEuropa.disabled = true; btnStates.disabled = true;
                
                try {
                    // A CORREÇÃO: 'credentials: include' obriga o browser a anexar a senha de admin ao clique
                    const resposta = await fetch(`/executar/${regiao}`, {
                        credentials: 'include'
                    });
                    
                    if (resposta.status === 401) {
                        throw new Error("Acesso Negado: O pedido não transportou as credenciais de Administrador.");
                    }

                    const dados = await resposta.json();
                    document.getElementById('status').innerText = dados.mensagem || dados.erro;
                } catch (e) {
                    if (e.message.includes("Acesso Negado")) {
                        document.getElementById('status').innerText = e.message;
                    } else {
                        document.getElementById('status').innerText = "Falha crítica de execução: O robô crashou ou o servidor excedeu o tempo limite.";
                    }
                }
                btnEuropa.disabled = false; btnStates.disabled = false;
            }
        </script>
        {% endif %}
    </body></html>
    """
    return render_template_string(html_dashboard, is_admin=is_admin)

@app.route('/executar/<regiao>')
@requer_login(requer_admin=True) # SEGREDO: Se um Leitor tentar aceder diretamente por URL, é bloqueado.
def executar_script(regiao):
    if regiao == "europa":
        ficheiro_py = "Newsletter_Escolhidos.py"
    elif regiao == "states":
        ficheiro_py = "radar_states_escolhidos.py" # Certifica-te que o nome bate certo com o teu ficheiro
    else:
        return jsonify({"erro": "Região inválida"}), 400

    if not os.path.exists(ficheiro_py):
        return jsonify({"erro": f"O ficheiro {ficheiro_py} não foi encontrado no servidor."}), 404

    try:
        # Puxa o gatilho: corre o ficheiro Python selecionado como um processo independente
        processo = subprocess.run(["python", ficheiro_py], capture_output=True, text=True, timeout=600)
        
        if processo.returncode == 0:
            return jsonify({"mensagem": f"Sucesso! O robô gerou o HTML da {regiao}. Acede à Área de Leitura para o ver."})
        else:
            return jsonify({"erro": f"O robô crashou durante a execução: {processo.stderr}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"erro": "O Yahoo Finance demorou demasiado tempo a responder (>10 minutos). O processo foi abortado."}), 504

@app.route('/ver/<regiao>')
@requer_login(requer_admin=False)
def visualizar_html(regiao):
    if regiao == "europa":
        padrao = "radar_europeu_escolhidos_*.html"
    elif regiao == "states":
        padrao = "radar_states_escolhidos_*.html"
    else:
        return "Região inválida", 400

    # Procura na pasta atual ficheiros que correspondam ao padrão
    lista_ficheiros = glob.glob(padrao)
    
    if not lista_ficheiros:
        return "Ainda não existe nenhum relatório gerado para esta região. Pede ao administrador para executar o robô.", 404

    # Ordena os ficheiros por data de modificação para encontrar o mais recente
    ficheiro_mais_recente = max(lista_ficheiros, key=os.path.getmtime)
    
    # Envia o HTML cru diretamente para o ecrã do utilizador
    return send_file(ficheiro_mais_recente)

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
