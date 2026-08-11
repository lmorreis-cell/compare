import os
import requests
import glob
from dotenv import load_dotenv
from functools import wraps
from flask_caching import Cache
from flask import Flask, render_template, jsonify, request, Response, send_file, render_template_string, redirect, session, url_for

load_dotenv()

app = Flask(__name__)

# ==========================================
# MOTOR DE CACHE (PROTEÇÃO DE INFRAESTRUTURA)
# ==========================================
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300 # 300 segundos = 5 minutos
cache = Cache(app)

# O Flask precisa de uma chave secreta para assinar os cookies do browser
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "chave_fallback_insegura")

# ==========================================
# MOTOR OAUTH2 DISCORD E RBAC (CASCATA DE PRIVILÉGIOS)
# ==========================================
CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
GUILD_ID = os.environ.get("GUILD_ID")
ROLE_ATIVO = os.environ.get("ROLE_ATIVO")
ROLE_PATROCINADOR = os.environ.get("ROLE_PATROCINADOR")

API_BASE_URL = "https://discord.com/api"

# O HTML da barreira (Upsell)
HTML_UPSELL = """
<!DOCTYPE html><html><body style="background:#0b0e14; color:#d7dce6; font-family:sans-serif; text-align:center; padding:100px;">
    <h1 style="color:#f28b24;">Acesso Bloqueado</h1>
    <p>A ferramenta do Radar Interativo e Comparador de Ativos é um benefício exclusivo dos <strong>Trader Patrocinador</strong>.</p>
    <a href="/" style="color:#3fbf8f; text-decoration:none;">← Voltar ao Portal</a>
</body></html>
"""

def requer_cargo(nivel_minimo):
    """
    Nível 1 = Trader Ativo (Newsletters)
    Nível 2 = Trader Patrocinador (Newsletters + Interativo)
    A matemática garante que o nível 2 herda acesso ao nível 1 automaticamente.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            nivel_atual = session.get('nivel_acesso', 0)
            
            if nivel_atual == 0:
                # Não está logado: manda para o Discord
                return redirect(url_for('login_discord'))
                
            if nivel_atual < nivel_minimo:
                # Está logado mas não tem cargo suficiente: mostra o Upsell
                return render_template_string(HTML_UPSELL)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route('/login')
def login_discord():
    # Envia o utilizador para o ecrã oficial do Discord pedindo autorização para ler os seus cargos no teu servidor
    url = f"{API_BASE_URL}/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds.members.read"
    return redirect(url)

@app.route('/callback')
def callback_discord():
    codigo = request.args.get('code')
    if not codigo:
        return "Erro: O Discord não devolveu um código de acesso.", 400

    # 1. Trocar o código temporário por um Token de Acesso permanente
    dados_token = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': codigo,
        'redirect_uri': REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    r_token = requests.post(f"{API_BASE_URL}/oauth2/token", data=dados_token, headers=headers)
    
    if r_token.status_code != 200:
        return "Falha na autenticação com o servidor do Discord.", 500
        
    token = r_token.json()['access_token']

    # 2. Perguntar ao Discord quais são os cargos deste utilizador no teu servidor (Guild)
    headers_auth = {'Authorization': f'Bearer {token}'}
    r_membro = requests.get(f"{API_BASE_URL}/users/@me/guilds/{GUILD_ID}/member", headers=headers_auth)

    if r_membro.status_code != 200:
        return "Acesso Negado: Não fazes parte do servidor de Discord.", 403

    cargos_do_utilizador = r_membro.json().get('roles', [])

    # 3. Matemática da Cascata de Privilégios
    nivel = 0
    if ROLE_PATROCINADOR in cargos_do_utilizador:
        nivel = 2
    elif ROLE_ATIVO in cargos_do_utilizador:
        nivel = 1

    # 4. Grava a "pulseira de acesso" no browser
    session['nivel_acesso'] = nivel
    
    return redirect(url_for('dashboard_central'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('dashboard_central'))
# ==========================================


# 2. Importa os teus motores de cálculo (O QUE FALTAVA)
from Regime import avaliar_regime_mercado
from MeanReversion import calcular_radar_reversao
from Radar import calcular_radar_momentum_v2, comparar_ativos






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


# O Dashboard base exige que sejas pelo menos Nível 1 (Trader Ativo)
@app.route('/')
# ATENÇÃO: Retirámos o @requer_cargo daqui para o robô do Discord poder entrar e ler as meta tags!
def dashboard_central():
    nivel_atual = session.get('nivel_acesso', 0)

    # 1. AS ETIQUETAS PARA OS ROBÔS DAS REDES SOCIAIS (OPEN GRAPH)
    meta_tags = """
        <meta property="og:title" content="Portal Bolsa - partilha de ideias">
        <meta property="og:description" content="Ferramentas de análise quantitativa, relatórios de mercado e comparador de ativos.">
        <meta property="og:image" content="https://comparativo.discloud.app/static/preview.png">
        <meta property="og:url" content="https://comparativo.discloud.app/">
        <meta name="twitter:card" content="summary_large_image">
    """

    # 2. LOBBY PÚBLICO: O QUE APARECE A QUEM NÃO FEZ LOGIN (E AO ROBÔ DO DISCORD)
    if nivel_atual == 0:
        html_login = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            {meta_tags}
            <title>Entrar - Portal Bolsa</title>
            <style>
                body {{ background: #0b0e14; color: #d7dce6; font-family: sans-serif; text-align: center; padding-top: 15vh; }}
                .btn-discord {{ background: #5865F2; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px; display: inline-block; margin-top: 20px; border: none; cursor: pointer; }}
            </style>
        </head>
        <body>
            <h1>Portal Bolsa - partilha de ideias</h1>
            <p style="color: #8a94a8;">Acesso restrito aos membros da comunidade.</p>
            <a href="/login" class="btn-discord">Entrar com o Discord</a>
        </body>
        </html>
        """
        return render_template_string(html_login)

    # 3. DASHBOARD PRIVADO: O TEU CÓDIGO INTACTO COM MARCA DE ÁGUA E VÍDEO
    # (Uso f-strings para injetar as chaves css/html sem quebrar o Python, nota os duplos {{ }} no CSS)
    html_dashboard = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        {meta_tags}
        <title>Portal Bolsa - partilha de ideias</title>
        <style>
            :root{{--fundo:#0b0e14;--painel:#151a23;--linha:#232d3f;--texto:#d7dce6;--verde:#3fbf8f;--azul:#4da6ff;--laranja:#f28b24;--mudo:#8a94a8;}}
            
            body {{
                font-family: -apple-system, sans-serif;
                background: var(--fundo);
                color: var(--texto);
                padding: 40px;
                text-align: center;
                position: relative;
                min-height: 100vh;
            }}

            /* MARCA DE ÁGUA INSTITUCIONAL IDÊNTICA ÀS NEWSLETTERS */
            .marca-agua {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                z-index: -1;
                pointer-events: none;
                user-select: none;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Ctext x='50%25' y='50%25' transform='rotate(-35 150 150)' dominant-baseline='middle' text-anchor='middle' font-family='Arial, sans-serif' font-size='20' font-weight='900' fill='rgba(255, 255, 255, 0.08)'%3EPartilha de Ideias - Luís Reis%3C/text%3E%3C/svg%3E");
                background-repeat: repeat;
            }}

            main{{max-width:800px;margin:0 auto; position: relative; z-index: 1;}}
            .btn {{ display: inline-block; padding: 15px 30px; margin: 10px; background: var(--verde); color: #121212; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 15px; transition: opacity 0.2s;}}
            .btn:hover {{ opacity: 0.9; }}
            .btn-states {{ background: var(--azul); }}
            .btn-interativo {{ background: var(--laranja); }}
            .box {{ background: var(--painel); border: 1px solid var(--linha); padding: 35px; border-radius: 8px; margin-top: 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
            h1 {{ font-size: 24px; margin-bottom: 10px; color: #fff; text-transform: uppercase; letter-spacing: -0.5px; }}
            p.sub {{ color: var(--mudo); font-size: 13px; margin-bottom: 25px; }}
        </style>
    </head>
    <body>
        <!-- INJEÇÃO DA MARCA DE ÁGUA NO FUNDO -->
        <div class="marca-agua"></div>

        <main>
            <!-- Botão de Sair elegante no topo direito -->
            <div style="text-align: right; margin-bottom: 20px;">
                <a href="/logout" style="color: #8a94a8; text-decoration: none; font-size: 12px; border: 1px solid #232d3f; padding: 5px 10px; border-radius: 4px;">Sair da Conta</a>
            </div>

            <h1>Portal Bolsa - partilha de ideias</h1>
            <p class="sub">Aceda aos relatórios de mercado atualizados e ferramentas de análise quantitativa.</p>
            
            <div class="box">
                <h2 style="font-size: 16px; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 20px; color: #fff; border-bottom: 1px solid var(--linha); padding-bottom: 10px;">Área de Leitura & Ferramentas</h2>
                <div>
                    <a href="/ver/europa" class="btn">Visualizar Radar Europa</a>
                    <a href="/ver/states" class="btn btn-states">Visualizar Radar States</a>
                </div>
                <div style="margin-top: 15px; border-top: 1px dashed var(--linha); padding-top: 15px;">
                    <a href="/interativo" class="btn btn-interativo">⚡ Abrir Ferramenta Interativa (Radar & Comparador)</a>
                </div>
            </div>
            
            <!-- INJEÇÃO DO VÍDEO CENTRAL EM LOOP -->
            <div style="margin-top: 50px; text-align: center;">
                <video autoplay loop muted playsinline style="max-width: 400px; height: auto; opacity: 0.8; border-radius: 8px;">
                    <!-- O Flask vai procurar o vídeo na pasta /static/ -->
                    <source src="/static/Black Simple Record Vlog Youtube Intro.mp4" type="video/mp4">
                    O teu navegador não suporta a reprodução de vídeo.
                </video>
            </div>
        </main>
    </body>
    </html>
    """
    
    return render_template_string(html_dashboard)

@app.route('/ver/<regiao>')
@requer_cargo(nivel_minimo=1)
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

@app.route('/interativo')
@requer_cargo(nivel_minimo=2)
def ferramenta_interativa():
    # Aqui colocas a lógica original que renderiza o 'index.html' dinâmico com o screener a correr em tempo real
    return render_template('index.html')

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
