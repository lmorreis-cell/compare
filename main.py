import os
import json
import requests
import glob
import yfinance as yf
import pandas as pd
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

ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID")
ARQUIVO_CONTADOR = "contador_visitas.json"

def carregar_contador():
    if os.path.exists(ARQUIVO_CONTADOR):
        try:
            with open(ARQUIVO_CONTADOR, 'r') as f:
                return json.load(f).get('visitas', 0)
        except Exception:
            return 0
    return 0

def incrementar_contador():
    visitas = carregar_contador() + 1
    try:
        with open(ARQUIVO_CONTADOR, 'w') as f:
            json.dump({'visitas': visitas}, f)
    except Exception:
        pass
    return visitas

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

    # NOVO: Grava também o teu ID de utilizador para te reconhecer como Admin
    session['user_id'] = r_membro.json().get('user', {}).get('id')
    
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

@app.route('/api/ticker_tape')
@cache.cached(timeout=120) # Cache de 2 minutos para poupar recursos
def api_ticker_tape():
    import yfinance as yf
    import requests
    
    resultados = []
    
    # 1. CABAZ BASE MACRO (Europa, States, Matérias-Primas, Cripto)
    tickers_base = ["^GSPC", "^IXIC", "^GDAXI", "^STOXX50E", "PSI20.LS", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]
    
    try:
        for t in tickers_base:
            tk = yf.Ticker(t)
            preco = tk.fast_info.get('lastPrice', 0)
            prev_close = tk.fast_info.get('previousClose', 1) 
            
            if preco > 0:
                var_pct = ((preco / prev_close) - 1) * 100
                
                # Nomes limpos para a interface
                nome = t
                if t == "^GSPC": nome = "S&P 500"
                if t == "^IXIC": nome = "NASDAQ"
                if t == "^GDAXI": nome = "DAX 40"
                if t == "^STOXX50E": nome = "EURO STOXX 50"
                if t == "PSI20.LS": nome = "PSI 20"  # <--- ADICIONA ESTA LINHA
                if t == "GC=F": nome = "OURO"
                if t == "CL=F": nome = "PETRÓLEO"
                
                resultados.append({"ticker": nome, "preco": preco, "var": var_pct, "tipo": "macro"})
    except Exception as e:
        print(f"Erro no Ticker Tape (Base): {e}")

    # 2. TOP GAINERS E LOSERS (Reaproveita a ligação à API oculta do Yahoo Finance)
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        def buscar_yf_movers(scr_id):
            url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds={scr_id}&count=5"
            resp = requests.get(url, headers=headers, timeout=3)
            if resp.status_code == 200:
                quotes = resp.json().get('finance', {}).get('result', [])[0].get('quotes', [])
                return [{"ticker": q.get('symbol'), "preco": q.get('regularMarketPrice', 0), "var": q.get('regularMarketChangePercent', 0)} for q in quotes]
            return []

        gainers = buscar_yf_movers("day_gainers")
        for g in gainers:
            g["tipo"] = "gainer"
            resultados.append(g)

        losers = buscar_yf_movers("day_losers")
        for l in losers:
            l["tipo"] = "loser"
            resultados.append(l)

    except Exception as e:
        print(f"Erro no Ticker Tape (Movers): {e}")
        
    return jsonify(resultados)

@app.route('/api/market_movers')
@cache.cached(timeout=300) # Atualiza a cada 5 minutos
def api_market_movers():
    try:
        # Disfarçamos o nosso servidor como um browser normal para não sermos bloqueados pelo Yahoo
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        
        def buscar_yf(scr_id):
            # Acesso direto à API oculta do Yahoo Finance
            url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds={scr_id}&count=5"
            resp = requests.get(url, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                dados = resp.json()
                quotes = dados.get('finance', {}).get('result', [])[0].get('quotes', [])
                
                # Traduzimos o formato do Yahoo para o formato exato que o teu ecrã já está à espera
                return [{
                    "symbol": q.get('symbol'),
                    "name": q.get('shortName', q.get('symbol')),
                    "price": q.get('regularMarketPrice', 0),
                    "changesPercentage": q.get('regularMarketChangePercent', 0)
                } for q in quotes]
            return []

        # Extrai os três pilares do mercado
        gainers = buscar_yf("day_gainers")
        losers = buscar_yf("day_losers")
        actives = buscar_yf("most_actives")
        
        return jsonify({
            "gainers": gainers,
            "losers": losers,
            "actives": actives
        })
        
    except Exception as e:
        return jsonify({"erro": f"Falha na API do Yahoo Finance: {str(e)}"}), 500


@app.route('/api/analisar')
@cache.cached(timeout=300) # <-- ADICIONA ESTA LINHA AQUI
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
    user_id = session.get('user_id', '')

    # Lógica de contagem
    if nivel_atual > 0:
        total_visitas = incrementar_contador()
    else:
        total_visitas = carregar_contador()

    # BLINDAGEM: Converte ambos para string (texto puro) e limpa espaços vazios
    admin_env = str(ADMIN_USER_ID).strip()
    user_sess = str(user_id).strip()
    
    # Verifica se os IDs batem certo e ignora se estiverem vazios
    is_admin = (user_sess == admin_env) and (user_sess != "None") and (user_sess != "")

    # Cria a etiqueta visual
    badge_admin = ""
    if is_admin:
        badge_admin = f"""
        <div style="position: absolute; top: 20px; left: 20px; background: #f28b24; color: #121212; padding: 8px 15px; border-radius: 6px; font-size: 13px; font-weight: bold; box-shadow: 0 4px 12px rgba(242, 139, 36, 0.3); z-index: 1000;">
            👑 Admin | {total_visitas} Acessos Globais
        </div>
        """

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
        <!-- INJEÇÃO DA ETIQUETA DE ADMIN (Só aparece para ti) -->
        {badge_admin}
    
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
                    <a href="/interativo" class="btn btn-interativo">⚡ Terminal Analítico Integrado (Radar, Ações e ETFs, CriptoAtivos)</a>
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
@cache.cached(timeout=300) 
def api_comparar(ticker1, ticker2):
    # BARREIRA: Bloqueia Criptomoedas no Duelo de Ações
    if "-" in ticker1 or "-" in ticker2:
        return jsonify({"erro": "Ativo Inválido! Usa o 'Laboratório de Ativos Digitais' mais abaixo para comparar criptomoedas."}), 400
        
    df_comparacao = comparar_ativos(ticker1, ticker2)
    
    if df_comparacao.empty:
        return jsonify({"erro": "Não foi possível obter dados para um ou ambos os tickers."}), 400
    
    # Converte para dicionário para podermos injetar dados extra
    dados = df_comparacao.to_dict(orient='records')
    
    # --- INJEÇÃO: PRICE TARGETS DE WALL STREET (Via Yahoo Finance Gratuito) ---
    for ativo in dados:
        try:
            tk = yf.Ticker(ativo['Ticker'])
            target = tk.info.get('targetMeanPrice', 0)
            preco_atual = float(ativo['Preço'])
            
            if target > 0 and preco_atual > 0:
                upside = ((target / preco_atual) - 1) * 100
                ativo['WallSt Target'] = f"${target:.2f}"
                ativo['WallSt Upside'] = f"{upside:+.1f}%"
            else:
                ativo['WallSt Target'] = "N/A"
                ativo['WallSt Upside'] = "N/A"
        except:
            ativo['WallSt Target'] = "N/A"
            ativo['WallSt Upside'] = "N/A"
    # -------------------------------------------------------------------------
            
    return jsonify(dados)

@app.route('/api/comparar_cripto/<ticker1>/<ticker2>')
@cache.cached(timeout=300) 
def api_comparar_cripto(ticker1, ticker2):
    # ==========================================================
    # BARREIRA: Exige pelo menos uma Criptomoeda no Spot vs Proxy
    # ==========================================================
    if "-" not in ticker1 and "-" not in ticker2:
        return jsonify({"erro": "O duelo Spot vs Proxy exige pelo menos um criptoativo com paridade (ex: ETH-USD)."}), 400
        
    df_comparacao = comparar_ativos(ticker1, ticker2)
    
    if df_comparacao.empty:
        return jsonify({"erro": "Não foi possível obter dados para um ou ambos os tickers."}), 400
        
    return jsonify(df_comparacao.to_dict(orient='records'))

@app.route('/api/breadth')
@cache.cached(timeout=3600) # Fica em cache durante 1 hora para não abusar do Yahoo
def api_breadth():
    import yfinance as yf
    
    # Os 11 ETFs Setoriais do S&P500 + VIX
    tickers = "XLK XLV XLF XLE XLY XLP XLI XLB XLRE XLU XLC ^VIX"
    
    try:
        # Puxa os dados todos de uma só vez (muito mais rápido que um a um)
        dados = yf.download(tickers, period="100d")['Close']
        
        setores = ['XLK', 'XLV', 'XLF', 'XLE', 'XLY', 'XLP', 'XLI', 'XLB', 'XLRE', 'XLU', 'XLC']
        bull_count = 0
        
        for setor in setores:
            if setor in dados.columns and not dados[setor].isna().all():
                fecho_atual = dados[setor].dropna().iloc[-1]
                ema50 = dados[setor].dropna().ewm(span=50, adjust=False).mean().iloc[-1]
                if fecho_atual > ema50:
                    bull_count += 1
                    
        # Extracção do VIX e cálculo da variação percentual diária
        vix_atual = 0
        vix_pct = 0
        if '^VIX' in dados.columns and not dados['^VIX'].dropna().empty:
            vix_serie = dados['^VIX'].dropna()
            vix_atual = float(vix_serie.iloc[-1])
            if len(vix_serie) >= 2:
                vix_pct = float(((vix_serie.iloc[-1] / vix_serie.iloc[-2]) - 1) * 100)
        
        return jsonify({
            "bull_count": bull_count,
            "total_setores": len(setores),
            "vix": vix_atual,
            "vix_pct": vix_pct
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/backtest/<ticker>/<estrategia>')
@cache.cached(timeout=3600) # Mantém em memória durante 1 hora
def api_backtest(ticker, estrategia):
    import yfinance as yf
    import numpy as np
    
    try:
        df = yf.Ticker(ticker).history(period="5y", interval="1d")
        if df.empty or len(df) < 50:
            return jsonify({"erro": "Histórico insuficiente para simulação de 5 anos."}), 400
            
        # 1. Cálculo de todos os Indicadores necessários
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['BB_Lower'] = df['SMA20'] - (df['STD20'] * 2)
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 2. Máquina de Estados (A Estratégia Escolhida)
        df['Sinal'] = 0
        nome_estrategia = ""
        
        if estrategia == 'reversion_rsi':
            # Compra pânico (RSI < 30), Vende no ressalto (RSI > 50)
            df.loc[df['RSI'] < 30, 'Sinal'] = 1
            df.loc[df['RSI'] > 50, 'Sinal'] = -1
            df['Sinal'] = df['Sinal'].replace(0, np.nan).ffill().fillna(0)
            df['Sinal'] = np.where(df['Sinal'] == 1, 1, 0)
            nome_estrategia = "Mean Reversion (RSI < 30)"
            
        elif estrategia == 'bb_dip':
            # Compra exaustão da Banda Inferior, Vende na regressão à Média 20
            df.loc[df['Close'] < df['BB_Lower'], 'Sinal'] = 1
            df.loc[df['Close'] > df['SMA20'], 'Sinal'] = -1
            df['Sinal'] = df['Sinal'].replace(0, np.nan).ffill().fillna(0)
            df['Sinal'] = np.where(df['Sinal'] == 1, 1, 0)
            nome_estrategia = "Bollinger Dip (Caça Fundos)"
            
        else: # trend_ema20 (Default)
            df['Sinal'] = np.where(df['Close'] > df['EMA20'], 1, 0)
            nome_estrategia = "Trend Following (EMA 20)"

        # 3. Execução da Simulação Algorítmica
        df['Retorno_Diario'] = df['Close'].pct_change()
        df['Retorno_Estrategia'] = df['Sinal'].shift(1) * df['Retorno_Diario']
        
        # Gestão de Risco e Drawdown
        capital_inicial = 10000
        df['Capital'] = capital_inicial * (1 + df['Retorno_Estrategia']).cumprod()
        df['Pico'] = df['Capital'].cummax()
        df['Drawdown'] = (df['Capital'] - df['Pico']) / df['Pico']
        max_dd = df['Drawdown'].min() * 100
        
        df['Mudanca'] = df['Sinal'].diff()
        total_trades = len(df[df['Mudanca'] == 1]) 
        
        dias_ganho = len(df[(df['Sinal'].shift(1) == 1) & (df['Retorno_Diario'] > 0)])
        dias_perda = len(df[(df['Sinal'].shift(1) == 1) & (df['Retorno_Diario'] < 0)])
        win_rate = (dias_ganho / (dias_ganho + dias_perda) * 100) if (dias_ganho + dias_perda) > 0 else 0
        
        retorno_total = ((df['Capital'].iloc[-1] - capital_inicial) / capital_inicial) * 100
        retorno_bh = ((df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100
        
        return jsonify({
            "ticker": ticker.upper(),
            "estrategia_nome": nome_estrategia,
            "win_rate": f"{win_rate:.1f}",
            "total_trades": total_trades,
            "max_dd": f"{max_dd:.1f}",
            "retorno_total": f"{retorno_total:.1f}",
            "retorno_bh": f"{retorno_bh:.1f}",
            "anos": 5
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/cotacao/<ticker>')
def cotacao_live(ticker):
    try:
        ativo = yf.Ticker(ticker)
        # fast_info devolve o preço ao segundo
        preco_atual = ativo.fast_info['last_price']
        return jsonify({"preco": preco_atual})
    except Exception as e:
        return jsonify({"erro": str(e)}), 400

@app.route('/api/cambio/<data>')
def api_cambio(data):
    import yfinance as yf
    import pandas as pd
    
    try:
        # 1. Lê a data enviada pelo HTML (ex: 2025-06-17)
        data_alvo = pd.to_datetime(data)
        
        # 2. Abre uma janela de 7 dias para trás para garantir que apanha fins de semana/feriados
        data_inicio = data_alvo - pd.Timedelta(days=7)
        data_fim = data_alvo + pd.Timedelta(days=1)
        
        # 3. MUDANÇA CRÍTICA: Usa .history() em vez de .download(). É 100% fiável para extrações únicas.
        motor_cambio = yf.Ticker("EURUSD=X")
        df = motor_cambio.history(start=data_inicio.strftime('%Y-%m-%d'), end=data_fim.strftime('%Y-%m-%d'))
        
        if df.empty:
            print(f"Aviso: Yahoo não devolveu dados de câmbio para {data}")
            return jsonify({"cambio": 1.08})
            
        # 4. Extrai o último fecho válido antes ou no próprio dia
        taxa = float(df['Close'].dropna().iloc[-1])
        
        # 5. O BCE usa tipicamente 4 casas decimais para o par EUR/USD
        return jsonify({"cambio": round(taxa, 4)})
        
    except Exception as e:
        print(f"Erro grave no motor de câmbio: {str(e)}")
        return jsonify({"cambio": 1.08}), 500

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

@app.route('/api/search/<query>')
@cache.cached(timeout=3600, key_prefix=lambda: f"search_{request.view_args['query']}")
def api_search_ticker(query):
    # Proteção para não fazer pesquisas vazias ou de 1 letra
    if len(query) < 2:
        return jsonify([])
        
    fmp_key = os.environ.get("FMP_API_KEY")
    resultados = []
    
    if fmp_key:
        try:
            # O endpoint revelado no email do FMP
            url = f"https://financialmodelingprep.com/stable/search-name?query={query}&apikey={fmp_key}"
            resp = requests.get(url, timeout=2)
            
            if resp.status_code == 200:
                dados = resp.json()
                # Vamos limitar a 5 resultados para não poluir o ecrã
                for ativo in dados[:5]:
                    resultados.append({
                        "symbol": ativo.get("symbol", ""),
                        "name": ativo.get("name", ""),
                        "exchange": ativo.get("exchangeShortName", "")
                    })
        except Exception as e:
            print(f"Erro na pesquisa FMP: {e}")
            
    return jsonify(resultados)

@app.route('/api/sniper/<ticker>/<timeframe>')
@cache.cached(timeout=300) 
def api_sniper(ticker, timeframe):
    import numpy as np
    import yfinance as yf
    import matplotlib
    matplotlib.use('Agg') # Fundamental para não estoirar a RAM do servidor
    import matplotlib.pyplot as plt
    import io
    import base64
    
    if timeframe == '1d':
        periodo = "1y"
        intervalo = "1d"
    elif timeframe == '4h' or timeframe == '1h':
        periodo = "730d"
        intervalo = "1h"
    else:
        return jsonify({"erro": "Timeframe inválido."}), 400

    # ==========================================================
    # BARREIRA DE SEGURANÇA BACKEND (BLOQUEIA CRIPTO NAS AÇÕES)
    # ==========================================================
    if "-" in ticker:
        return jsonify({"erro": "Ativo Inválido! Usa o 'Laboratório de Ativos Digitais' para analisar criptomoedas."}), 400
    # ==========================================================

    try:
        # Extração limpa e Filtro Anti-NaN europeu
        df = yf.Ticker(ticker).history(period=periodo, interval=intervalo)
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        if df.empty:
            return jsonify({"erro": "Sem dados para este ativo."}), 404
            
        # --- 1. COTAÇÃO AO VIVO (Redundância FMP -> YFinance) ---
        fmp_key = os.environ.get("FMP_API_KEY")
        preco_oficial = 0
        
        if fmp_key:
            try:
                url_quote = f"https://financialmodelingprep.com/stable/quote?symbol={ticker}&apikey={fmp_key}"
                resp_quote = requests.get(url_quote, timeout=2) # Timeout agressivo para não bloquear o servidor
                if resp_quote.status_code == 200 and resp_quote.json():
                    preco_oficial = float(resp_quote.json()[0].get('price', 0))
            except Exception as e:
                print(f"Erro Cotação FMP: {e} - A comutar para YFinance.")
                
        # Fallback YFinance se o FMP falhar ou estoirar o limite
        if preco_oficial == 0:
            df_diario = yf.Ticker(ticker).history(period="5d", interval="1d").dropna(subset=['Close'])
            try:
                preco_oficial = float(yf.Ticker(ticker).fast_info['lastPrice'])
            except:
                preco_oficial = float(df_diario['Close'].iloc[-1]) if not df_diario.empty else float(df['Close'].iloc[-1])


        # --- 2. PERFIL INSTITUCIONAL ENRIQUECIDO (FMP -> YFinance) ---
        logo_url, setor, mkt_cap, exchange = "", "Desconhecido", 0, ""
        
        # Tentativa 1: FMP (Procurando várias chaves possíveis do JSON)
        if fmp_key:
            try:
                url_profile = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={fmp_key}"
                resp_profile = requests.get(url_profile, timeout=2)
                if resp_profile.status_code == 200 and resp_profile.json():
                    p = resp_profile.json()[0]
                    logo_url = p.get('image', p.get('logo', ''))
                    setor = p.get('sector', 'Desconhecido')
                    mkt_cap = float(p.get('mktCap', p.get('marketCap', 0)))
                    exchange = p.get('exchangeShortName', p.get('exchange', ''))
            except Exception as e:
                pass

        # Tentativa 2 (Redundância): YFinance
        # O objeto tk = yf.Ticker(ticker) já é criado no início da tua função
        try:
            tk = yf.Ticker(ticker)
            if mkt_cap == 0 or mkt_cap is None:
                mkt_cap = float(tk.info.get('marketCap', 0))
            if setor == "Desconhecido" or setor == "":
                setor = tk.info.get('sector', 'Desconhecido')
            if exchange == "":
                exchange = tk.info.get('exchange', '')
        except:
            pass


        # --- 3. INCOME STATEMENT & FINANCIAL METRICS (YFINANCE AVANÇADO) ---
        eps_atual, gross_margin, net_margin, debt_equity = "N/A", "N/A", "N/A", "N/A"
        waterfall_data = {}
        
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            
            # Extração de Métricas Chave
            eps_val = info.get('trailingEps')
            eps_atual = f"{eps_val:.2f}" if eps_val else "N/A"
            
            gm_val = info.get('grossMargins')
            gross_margin = f"{gm_val * 100:.2f}%" if gm_val else "N/A"
            
            nm_val = info.get('profitMargins')
            net_margin = f"{nm_val * 100:.2f}%" if nm_val else "N/A"
            
            de_val = info.get('debtToEquity')
            debt_equity = f"{de_val:.2f}%" if de_val else "N/A"

            # Extração para Gráfico Waterfall (Demonstração de Resultados)
            inc_stmt = tk.income_stmt
            if not inc_stmt.empty:
                col = inc_stmt.columns[0] # Puxa o ano ou TTM mais recente
                
                def safe_get(idx):
                    return float(inc_stmt.loc[idx, col]) if idx in inc_stmt.index and pd.notna(inc_stmt.loc[idx, col]) else 0.0

                rev = safe_get('Total Revenue')
                if rev == 0: rev = safe_get('Operating Revenue')
                cost = safe_get('Cost Of Revenue')
                gross = safe_get('Gross Profit')
                net = safe_get('Net Income')
                
                if gross == 0 and rev > 0: gross = rev - cost
                other_exp = gross - net # Custos operacionais, impostos e juros agregados

                def fmt_money(val):
                    v = abs(val)
                    if v >= 1e9: return f"${v/1e9:.2f}B"
                    if v >= 1e6: return f"${v/1e6:.2f}M"
                    return f"${v:.2f}"

                if rev > 0:
                    waterfall_data = {
                        "revenue": rev,
                        "cost_of_revenue": -cost, # Força negativo para a cascata descer
                        "gross_profit": gross,
                        "other_expenses": -other_exp, # Força negativo
                        "net_income": net,
                        "fmt_revenue": fmt_money(rev),
                        "fmt_corev": "-" + fmt_money(cost),
                        "fmt_gross": fmt_money(gross),
                        "fmt_other": "-" + fmt_money(other_exp),
                        "fmt_net": fmt_money(net)
                    }
        except Exception as e:
            print(f"Aviso - Falha ao extrair fundamentos profundos: {e}")

        # --- EXTRAÇÃO DO VALUATION RISK ---
        try:
            pe_ratio = info.get('forwardPE') or info.get('trailingPE') or 0
            peg_ratio = info.get('pegRatio') or 0
            pe_min_5y = pe_ratio * 0.6 # Simplificação para garantir execução se a API falhar
        except:
            pe_ratio, pe_min_5y, peg_ratio = 0, 0, 0
            
        # --- DATAS DE RESULTADOS (EARNINGS) ---
        last_earnings_date, next_earnings_date = "N/A", "N/A"
        data_resultados = None
        import datetime
        hoje = datetime.date.today()
        
        try:
            ed = tk.get_earnings_dates(limit=15)
            if ed is not None and not ed.empty:
                hoje_ts = pd.Timestamp(hoje)
                if ed.index.tz is not None:
                    ed.index = ed.index.tz_localize(None)
                
                # Próximos Resultados
                ed_futuras = ed[ed.index >= hoje_ts]
                if not ed_futuras.empty:
                    data_resultados = ed_futuras.index.min().date()
                    next_earnings_date = data_resultados.strftime('%b %d, %Y')
                
                # Últimos Resultados Reportados
                ed_passadas = ed[ed.index < hoje_ts]
                if not ed_passadas.empty:
                    last_earnings_date = ed_passadas.index.max().strftime('%b %d, %Y')
        except Exception as e:
            pass

        earnings_warning = ""
        if data_resultados is not None:
            dias_restantes = (data_resultados - hoje).days
            if dias_restantes <= 7:
                earnings_warning = f"⚠️ ALERTA DE RISCO: Apresentação de Resultados em {dias_restantes} dias ({next_earnings_date}). A volatilidade anulará suportes técnicos."
            else:
                earnings_warning = f"📅 Próximos Resultados: {next_earnings_date} (faltam {dias_restantes} dias)"
                
        
        # Compressão 4H
        if timeframe == '4h':
            df = df.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna(subset=['Close', 'High', 'Low'])
            
        # Injeção da Cotação Real
        df.loc[df.index[-1], 'Close'] = preco_oficial
        fecho_atual = preco_oficial
        
        # --- NOVOS INDICADORES DE MOMENTUM ---
        df['PrevClose'] = df['Close'].shift(1)
        df['TR'] = df[['High', 'PrevClose']].max(axis=1) - df[['Low', 'PrevClose']].min(axis=1)
        atr_14 = float(df['TR'].rolling(window=14).mean().iloc[-1])
        
        # Cálculo RSI (14)
        delta = df['Close'].diff()
        up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        down = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rs = up / down
        rsi_atual = float(100 - (100 / (1 + rs)).iloc[-1])
        
        # ... (mantém o cálculo do ATR e RSI que já lá tens) ...
        
        ema_9 = float(df['Close'].ewm(span=9, adjust=False).mean().iloc[-1])
        ema_20 = float(df['Close'].ewm(span=20, adjust=False).mean().iloc[-1])

       # --- RAIO-X GRAVITACIONAL ---
        sma_50 = df['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = df['Close'].rolling(window=200).mean().iloc[-1]
        max_absoluto = df['High'].max()

        import math
        dist_m50 = ((fecho_atual / sma_50) - 1) * 100 if not math.isnan(sma_50) else 0
        dist_m200 = ((fecho_atual / sma_200) - 1) * 100 if not math.isnan(sma_200) else 0
        dist_max = ((fecho_atual / max_absoluto) - 1) * 100 if not math.isnan(max_absoluto) else 0

        # --- NOVA INJEÇÃO: MATRIZ DE MOMENTUM (VELOCIDADE) ---
        try:
            perf_1w = ((fecho_atual / float(df['Close'].iloc[-6])) - 1) * 100 if len(df) >= 6 else 0
        except: perf_1w = 0
        try:
            perf_1m = ((fecho_atual / float(df['Close'].iloc[-22])) - 1) * 100 if len(df) >= 22 else 0
        except: perf_1m = 0
        try:
            perf_3m = ((fecho_atual / float(df['Close'].iloc[-64])) - 1) * 100 if len(df) >= 64 else 0
        except: perf_3m = 0
        # -----------------------------------------------------


        # --- NOVA INJEÇÃO: FMP E EXTRAS YFINANCE (TARGETS, NEWS, INSIDERS) ---
        
        earnings_warning = ""
        insider_signal = "Sem dados recentes"
        target_consensus = 0
        target_upside = 0
        news_data = []
        
        import datetime
        import pandas as pd
        hoje = datetime.date.today()
                
        # A partir daqui, usamos o objeto 'tk' (yfinance) já criado no topo para evitar bloqueios de APIs externas
        try:
            # 2. Price Targets de Wall Street (YF)
            target_consensus = info.get('targetMeanPrice', 0)
            if target_consensus > 0 and fecho_atual > 0:
                target_upside = ((target_consensus / fecho_atual) - 1) * 100

            # 3. Notícias (YF - Correção de Estrutura Dupla)
            raw_news = tk.news
            if raw_news:
                for n in raw_news[:3]:
                    # O YF muda o JSON frequentemente. Este código lê os dois formatos conhecidos.
                    if 'content' in n:
                        titulo = n['content'].get('title', 'Notícia Wall Street')
                        link = n['content'].get('canonicalUrl', n['content'].get('clickThroughUrl', '#'))
                        pub_time = n['content'].get('pubDate', '')
                    else:
                        titulo = n.get('title', 'Notícia Wall Street')
                        link = n.get('link', '#')
                        pub_time = n.get('providerPublishTime', '')

                    # Bloqueador do Erro 1969 (Unix Epoch 0)
                    if isinstance(pub_time, (int, float)) and pub_time > 0:
                        data_pub = datetime.datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d')
                    elif isinstance(pub_time, str) and len(pub_time) >= 10:
                        data_pub = pub_time[:10]
                    else:
                        data_pub = hoje.strftime('%Y-%m-%d')

                    news_data.append({"title": titulo, "url": link, "date": data_pub})

            # 4. Insider Trading (YF - Correção de Análise Semântica)
            insiders = tk.insider_transactions
            if insiders is not None and not insiders.empty:
                # Conversão blindada item a item: garante que mesmo números ou células vazias (NaN/floats) viram texto
                textos = insiders.head(15).apply(lambda x: ' '.join(str(v) for v in x), axis=1).str.lower()
                
                compras = len(textos[textos.str.contains('buy|purchase|award')])
                vendas = len(textos[textos.str.contains('sell|sale|disposition')])
                
                if compras == 0 and vendas == 0:
                    pass # Mantém o "Sem dados recentes"
                elif compras >= vendas * 2 and compras > 0:
                    insider_signal = f"Acumulação Forte ({compras}C / {vendas}V)"
                elif vendas >= compras * 2 and vendas > 0:
                    insider_signal = f"Distribuição Forte ({vendas}V / {compras}C)"
                else:
                    insider_signal = f"Fluxo Misto ({compras}C / {vendas}V)"

        except Exception as e:
            print(f"Erro YF Extras para {ticker}: {e}")

        # 5. Puxar Próximos Resultados (Motor Duplo: YF -> FMP)
        data_resultados = None
        try:
            ed = tk.get_earnings_dates(limit=10)
            if ed is not None and not ed.empty:
                hoje_ts = pd.Timestamp(hoje)
                if ed.index.tz is not None:
                    ed.index = ed.index.tz_localize(None)
                ed_futuras = ed[ed.index >= hoje_ts]
                if not ed_futuras.empty:
                    data_resultados = ed_futuras.index.min().date()
        except Exception as e:
            pass

        try:
            if data_resultados is None and fmp_key:
                url_earn = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{ticker}?apikey={fmp_key}"
                resp_earn = requests.get(url_earn, timeout=5)
                if resp_earn.status_code == 200:
                    dados_earn = resp_earn.json()
                    if isinstance(dados_earn, list):
                        futuros = [e for e in dados_earn if e.get('date', '') >= hoje.strftime('%Y-%m-%d')]
                        if futuros:
                            futuros.sort(key=lambda x: x['date'])
                            data_resultados = datetime.datetime.strptime(futuros[0]['date'], '%Y-%m-%d').date()
        except Exception as e:
            pass

        # Construção do Motor de Alerta de Volatilidade
        if data_resultados is not None:
            dias_restantes = (data_resultados - hoje).days
            prox_data_str = data_resultados.strftime('%Y-%m-%d')
            if dias_restantes <= 7:
                earnings_warning = f"⚠️ ALERTA DE RISCO: Apresentação de Resultados em {dias_restantes} dias ({prox_data_str}). A volatilidade anulará suportes técnicos."
            else:
                earnings_warning = f"📅 Próximos Resultados: {prox_data_str} (faltam {dias_restantes} dias)"
        # -----------------------------------------------------
     
        
        # --- 1. MATEMÁTICA DE COMPRESSÃO (BOLLINGER BANDS) E VOLUME ---
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
        # O "Band Width" mede a distância percentual entre as bandas
        df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
        
        bw_atual = float(df['Band_Width'].iloc[-1])
        bw_medio = float(df['Band_Width'].tail(50).mean())
        
        vol_atual = float(df['Volume'].iloc[-1])
        vol_medio = float(df['Volume'].tail(20).mean())

        # --- 2. ALGORITMO DE SUPORTES E RESISTÊNCIAS (Auto-Leveling) ---
        highs = df['High'].rolling(window=10, center=True).max().dropna().unique()
        lows = df['Low'].rolling(window=10, center=True).min().dropna().unique()
        todos_niveis = sorted(list(set(highs).union(set(lows))))
        
        niveis_limpos = []
        for n in todos_niveis:
            if not niveis_limpos or abs(n - niveis_limpos[-1])/n > 0.01:
                niveis_limpos.append(float(n))
                
        suportes = sorted([n for n in niveis_limpos if n < fecho_atual], reverse=True)[:5]
        resistencias = sorted([n for n in niveis_limpos if n > fecho_atual])[:5]

        if not suportes: suportes = [fecho_atual - atr_14, fecho_atual - (atr_14*2)]
        if not resistencias: resistencias = [fecho_atual + atr_14, fecho_atual + (atr_14*2)]

        # --- 3. TRADE PLANS & MATEMÁTICA R:R ---
        bull_pt1 = fecho_atual + (1.5 * atr_14)
        bull_pt2 = fecho_atual + (3.0 * atr_14)
        bull_stop = fecho_atual - (1.0 * atr_14)
        
        bear_pt1 = fecho_atual - (1.5 * atr_14)
        bear_pt2 = fecho_atual - (3.0 * atr_14)
        bear_stop = fecho_atual + (1.0 * atr_14)

        risco_bull = resistencias[0] - bull_stop
        recompensa_bull = bull_pt1 - resistencias[0]
        rr_bull = (recompensa_bull / risco_bull) if risco_bull > 0 else 0

        risco_bear = bear_stop - suportes[0]
        recompensa_bear = suportes[0] - bear_pt1
        rr_bear = (recompensa_bear / risco_bear) if risco_bear > 0 else 0

        # --- 4. MOTOR NLG (NARRATIVA COMPORTAMENTAL COM TOOLTIPS) ---
        tendencia = "Alta" if ema_9 > ema_20 else "Baixa"
        
        # Auditoria de Volume
        if vol_atual > vol_medio * 1.5:
            txt_vol = "<span class='sniper-tt'><strong>🟢 Forte influxo de volume institucional</strong><span class='sniper-tt-text'><strong style='color:#4da6ff; font-size:13px; display:block; border-bottom:1px solid #333; padding-bottom:4px; margin-bottom:5px;'>Anomalia de Liquidez</strong>O volume atual excede em mais de 50% a média móvel das últimas 20 velas. Isto valida categoricamente a direção do preço, pois mãos fracas não conseguem gerar esta amplitude de transações.</span></span> detetado na sessão atual."
        elif vol_atual < vol_medio * 0.6:
            txt_vol = "<span class='sniper-tt'><strong>🔴 Volume anémico. Ausência de convicção</strong><span class='sniper-tt-text'><strong style='color:#d9534f; font-size:13px; display:block; border-bottom:1px solid #333; padding-bottom:4px; margin-bottom:5px;'>Aviso de Falso Breakout</strong>O mercado está a mover-se sem participação institucional. Rompimentos de resistência ou quebras de suporte com volume fraco são frequentemente armadilhas de liquidez (bull/bear traps).</span></span> (risco de falsos rompimentos)."
        else:
            txt_vol = "Volume transacionado dentro da normalidade estatística."

        # Auditoria de Volatilidade (Bandas de Bollinger)
        if bw_atual < bw_medio * 0.7:
            txt_bb = " <span class='sniper-tt'><strong>⚡ COMPRESSÃO EXTREMA (Squeeze):</strong><span class='sniper-tt-text'><strong style='color:#f28b24; font-size:13px; display:block; border-bottom:1px solid #333; padding-bottom:4px; margin-bottom:5px;'>Bollinger Squeeze</strong>As Bandas de Bollinger estreitaram drasticamente. O mercado está a acumular energia direcional. A história prova que períodos de letargia aguda antecedem movimentos explosivos iminentes. Prepara os gatilhos.</span></span> As bandas estão a estrangular o preço."
        elif fecho_atual > df['BB_Upper'].iloc[-1]:
            txt_bb = " O preço perfurou a Banda de Bollinger superior (Ruptura Estatística). Risco imediato de exaustão compradora."
        elif fecho_atual < df['BB_Lower'].iloc[-1]:
            txt_bb = " O preço cota abaixo da Banda de Bollinger inferior. Pressão vendedora anómala instalada."
        else:
            txt_bb = " Volatilidade contida nos eixos centrais."

        nlg_notes = (
            f"O ativo encontra-se a negociar nos {fecho_atual:.2f} no gráfico de {timeframe}. "
            f"A tendência tática é de {tendencia} (EMA 9 {'acima' if tendencia == 'Alta' else 'abaixo'} da EMA 20). "
            f"O nível crítico de defesa algorítmica está nos {suportes[0]:.2f}.<br><br>"
            f"{txt_vol}{txt_bb}"
        )

        # --- 5. EXTRAÇÃO DE DADOS PARA GRÁFICO PLOTLY (FRONTEND) ---
        dados_grafico = {}
        try:
            hist_recente = df.tail(60)
            
            # Formata a data: se for 1D, mostra só dia; se for 4H/1H, mostra dia e hora
            formato_data = '%Y-%m-%d' if timeframe == '1d' else '%Y-%m-%d %H:%M'
            
            dados_grafico = {
                "datas": hist_recente.index.strftime(formato_data).tolist(),
                "closes": hist_recente['Close'].round(2).tolist(),
                "ema9": hist_recente['Close'].ewm(span=9).mean().round(2).tolist(),
                "ema20": hist_recente['Close'].ewm(span=20).mean().round(2).tolist(),
                "volumes": hist_recente['Volume'].tolist(),
                # Lógica de cor: Vela verde = Volume verde, Vela vermelha = Volume vermelho
                "cores_vol": ['#5cb85c' if hist_recente['Close'].iloc[i] >= hist_recente['Open'].iloc[i] else '#d9534f' for i in range(len(hist_recente))]
            }
        except Exception as e:
            print(f"Erro a extrair dados do gráfico: {e}")

        # --- 6. EMPACOTAMENTO JSON ---
        return jsonify({
            "ticker": ticker.upper(),
            "timeframe": timeframe.upper(),
            "preco": f"{fecho_atual:.2f}",
            "rsi": f"{rsi_atual:.1f}",
            "atr": f"{atr_14:.2f}",
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else 0,
            "peg_ratio": round(peg_ratio, 2) if peg_ratio else 0,  
            "pe_min_5y": round(pe_min_5y, 2) if pe_min_5y else 0,

            # --- FMP VARIAVEIS ---
            "logo_url": logo_url,
            "earnings_warning": earnings_warning,
            "insider_signal": insider_signal,
            "target_consensus": target_consensus,
            "target_upside": f"{target_upside:+.1f}%",
            "news_data": news_data,

            # Adiciona estas variáveis ao pacote JSON existente
            "setor": setor,
            "mkt_cap": mkt_cap,
            "exchange": exchange,
            "net_margin": f"{fmp_net_margin:.1f}%" if fmp_net_margin != 0 else "N/A",

            # ---> INJETA ESTAS LINHAS AQUI <---
            "eps_atual": eps_atual,
            "gross_margin": gross_margin,
            "net_margin_final": net_margin,
            "debt_equity": debt_equity,
            "last_earnings_date": last_earnings_date,
            "next_earnings_date": next_earnings_date,
            "waterfall_data": waterfall_data,
            # ----------------------------------
            
            # --- NOVAS VARIÁVEIS A ENVIAR ---
            "dist_m50": f"{dist_m50:+.1f}%",
            "cor_m50": "#5cb85c" if dist_m50 > 0 else "#d9534f",
            "dist_m200": f"{dist_m200:+.1f}%",
            "cor_m200": "#5cb85c" if dist_m200 > 0 else "#d9534f",
            "dist_max": f"{dist_max:+.1f}%",
            # --------------------------------
                        
            # --- NOVAS VARIÁVEIS A ENVIAR ---
            "perf_1w": f"{perf_1w:+.1f}%",
            "cor_1w": "#5cb85c" if perf_1w > 0 else "#d9534f",
            "perf_1m": f"{perf_1m:+.1f}%",
            "cor_1m": "#5cb85c" if perf_1m > 0 else "#d9534f",
            "perf_3m": f"{perf_3m:+.1f}%",
            "cor_3m": "#5cb85c" if perf_3m > 0 else "#d9534f",
            # --------------------------------
            "dados_grafico": dados_grafico,  # <--- NOVA VARIÁVEL AQUI
            
            "suportes": [f"{s:.2f}" for s in suportes],
            
            "suportes": [f"{s:.2f}" for s in suportes],
            "resistencias": [f"{r:.2f}" for r in resistencias],
            "notas": nlg_notes,
            "bull_plan": {
                "entrada": f"Rutura confirmada acima de {resistencias[0]:.2f}",
                "pt": [f"{bull_pt1:.2f}", f"{bull_pt2:.2f}"],
                "stop": f"{bull_stop:.2f}",
                "rr": f"1:{rr_bull:.1f}"
            },
            "bear_plan": {
                "entrada": f"Quebra confirmada abaixo de {suportes[0]:.2f}",
                "pt": [f"{bear_pt1:.2f}", f"{bear_pt2:.2f}"],
                "stop": f"{bear_stop:.2f}",
                "rr": f"1:{rr_bear:.1f}"
            }
        })

    except Exception as e:
        return jsonify({"erro": f"Falha na execução quantitativa: {str(e)}"}), 500


@app.route('/api/screener/<universo>/<estrategia>/<int:lote>')
def api_screener_paginado(universo, estrategia, lote):
    import yfinance as yf
    import pandas as pd
    import numpy as np

    if universo == 'sp500':
        caminho = 'sp500.txt'
    elif universo == 'ndx':
        caminho = 'ndx.txt'
    elif universo == 'cripto':
        tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'AVAX-USD', 'DOGE-USD', 'DOT-USD', 'LINK-USD']
        caminho = None
    else:
        return jsonify({"erro": "Universo inválido."}), 400

    if caminho:
        try:
            with open(caminho, 'r') as f:
                tickers = [linha.strip().upper() for linha in f if linha.strip()]
        except FileNotFoundError:
            return jsonify({"erro": f"Ficheiro {caminho} não encontrado no servidor."}), 400

    tamanho_lote = 50
    inicio = lote * tamanho_lote
    fim = inicio + tamanho_lote
    lote_atual = tickers[inicio:fim]
    
    is_last = fim >= len(tickers)
    resultados = []

    if not lote_atual:
        return jsonify({"resultados": [], "concluido": True, "total_processado": len(tickers), "total_universo": len(tickers)})

    try:
        string_tickers = " ".join(lote_atual)
        # O yfinance descarrega apenas as 50 ações e o Python processa-as em <3 segundos!
        dados = yf.download(string_tickers, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
        
        for ticker in lote_atual:
            try:
                df = dados.dropna() if len(lote_atual) == 1 else dados[ticker].dropna()
                if df.empty or len(df) < 200: 
                    continue 

                df['SMA200'] = df['Close'].rolling(200).mean()
                df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
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
                
                # 1. AVALIAÇÃO TÉCNICA (O que já tinhas)
                passou_filtro = False
                metrica_tec = ""
                
                if estrategia == 'pullback':
                    if fecho_atual > df['SMA200'].iloc[-1] and fecho_atual > df['EMA50'].iloc[-1]:
                        if abs(fecho_atual - df['EMA20'].iloc[-1]) / fecho_atual < 0.015: 
                            passou_filtro = True
                            metrica_tec = f"RSI: {df['RSI'].iloc[-1]:.1f} | Base de Suporte (EMA 20)"
                elif estrategia == 'squeeze':
                    if df['BB_Width'].iloc[-1] < df['BB_Width'].quantile(0.10):
                        passou_filtro = True
                        metrica_tec = f"Risco de Explosão | Largura BB: {df['BB_Width'].iloc[-1]*100:.1f}%"
                elif estrategia == 'oversold':
                    if df['RSI'].iloc[-1] < 30 and fecho_atual < df['BB_Lower'].iloc[-1]:
                        passou_filtro = True
                        metrica_tec = f"Capitulação | RSI Extremo: {df['RSI'].iloc[-1]:.1f}"

                # 2. AVALIAÇÃO FUNDAMENTAL (Só executa se passar no teste técnico)
                if passou_filtro:
                    alertas_fund = []
                    
                    if universo != 'cripto': # Cripto não tem EPS ou Cash Flow
                        try:
                            info = yf.Ticker(ticker).info
                            eps = info.get('trailingEps', 0)
                            fcf = info.get('freeCashflow', 0)
                            peg = info.get('pegRatio', 0)
                            
                            # Formatação e Injeção de Valores
                            if eps is None or eps < 0:
                                val_eps = f"${eps:.2f}" if eps is not None else "N/A"
                                alertas_fund.append({
                                    "tipo": "EPS Negativo", 
                                    "desc": f"A empresa destrói valor operacional. O Lucro por Ação (EPS) atual é de {val_eps}."
                                })
                                
                            if fcf is None or fcf < 0:
                                # Função para converter números gigantes em M ou B
                                def formata_caixa(v):
                                    if v is None: return "N/A"
                                    if abs(v) >= 1e9: return f"${v/1e9:.2f}B"
                                    if abs(v) >= 1e6: return f"${v/1e6:.2f}M"
                                    return f"${v:.2f}"
                                
                                alertas_fund.append({
                                    "tipo": "Cash Flow Destrutivo", 
                                    "desc": f"Queima de caixa ativa. O Free Cash Flow está negativo em {formata_caixa(fcf)}. A sobrevivência pode exigir diluição de capital."
                                })
                                
                            if peg is None or peg > 2 or peg < 0:
                                val_peg = f"{peg:.2f}" if peg is not None else "N/A"
                                alertas_fund.append({
                                    "tipo": "PEG Especulativo", 
                                    "desc": f"Múltiplo de crescimento (PEG) em {val_peg}. Valores > 2.0 indicam que a cotação está inflacionada face ao crescimento real estimado."
                                })
                        except:
                            alertas_fund.append({
                                "tipo": "Dados Ocultos", 
                                "desc": "O algoritmo não conseguiu extrair a métrica financeira (N/A). Avaliação fundamental no escuro."
                            })
                            
                    # 3. EMPACOTAMENTO DA INFORMAÇÃO
                    is_toxic = len(alertas_fund) > 0

                    resultados.append({
                        "ticker": ticker, 
                        "preco": fecho_atual, 
                        "metricas": metrica_tec,
                        "fundamentos": alertas_fund, # Agora envia uma lista de dicionários!
                        "is_toxic": is_toxic
                    })
            except:
                continue 
        
        return jsonify({
            "resultados": resultados, 
            "concluido": is_last, 
            "total_processado": min(fim, len(tickers)), 
            "total_universo": len(tickers)
        })
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/sniper_cripto/<ticker>/<timeframe>')
@cache.cached(timeout=60) # Timeout mais curto (60s) devido à volatilidade cripto
def api_sniper_cripto(ticker, timeframe):
    import numpy as np
    import yfinance as yf
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import io
    import base64
    
    if timeframe == '1d':
        periodo, intervalo = "1y", "1d"
    elif timeframe in ['4h', '1h']:
        periodo, intervalo = "60d", "1h" # yfinance limita intraday a 60-730 dias
    else:
        return jsonify({"erro": "Timeframe inválido."}), 400

    # ==========================================================
    # BARREIRA DE SEGURANÇA BACKEND (BLOQUEIA AÇÕES TRADICIONAIS)
    # ==========================================================
    if "-" not in ticker:
        return jsonify({"erro": f"Formato inválido! O motor cripto exige a paridade (Ex: {ticker.upper()}-USD). Ações tradicionais não são suportadas neste laboratório."}), 400
    # ==========================================================

    try:
        df = yf.Ticker(ticker).history(period=periodo, interval=intervalo)
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        if df.empty:
            return jsonify({"erro": "Sem dados para este criptoativo. Tenta adicionar '-USD' (Ex: SOL-USD)."}), 404
            
        if timeframe == '4h':
            df = df.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna(subset=['Close', 'High', 'Low'])
            
        fecho_atual = float(df['Close'].iloc[-1])
        
        # Matemática Básica (RSI e ATR)
        df['PrevClose'] = df['Close'].shift(1)
        df['TR'] = df[['High', 'PrevClose']].max(axis=1) - df[['Low', 'PrevClose']].min(axis=1)
        atr_14 = float(df['TR'].rolling(window=14).mean().iloc[-1])
        
        delta = df['Close'].diff()
        up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        down = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rsi_atual = float(100 - (100 / (1 + (up / down))).iloc[-1])
        
        # Níveis Automáticos
        highs = df['High'].rolling(window=14, center=True).max().dropna().unique()
        lows = df['Low'].rolling(window=14, center=True).min().dropna().unique()
        todos_niveis = sorted(list(set(highs).union(set(lows))))
        
        niveis_limpos = []
        for n in todos_niveis:
            if not niveis_limpos or abs(n - niveis_limpos[-1])/n > 0.015:
                niveis_limpos.append(float(n))
                
        suportes = sorted([n for n in niveis_limpos if n < fecho_atual], reverse=True)[:5]
        resistencias = sorted([n for n in niveis_limpos if n > fecho_atual])[:5]

        if not suportes: suportes = [fecho_atual - atr_14]
        if not resistencias: resistencias = [fecho_atual + atr_14]

        # Trade Plans baseados em Volatilidade Extrema (Múltiplos Maiores)
        bull_pt1, bull_pt2 = fecho_atual + (2.0 * atr_14), fecho_atual + (4.0 * atr_14)
        bull_stop = fecho_atual - (1.5 * atr_14)
        bear_pt1, bear_pt2 = fecho_atual - (2.0 * atr_14), fecho_atual - (4.0 * atr_14)
        bear_stop = fecho_atual + (1.5 * atr_14)

        risco_bull = resistencias[0] - bull_stop
        rr_bull = ((bull_pt1 - resistencias[0]) / risco_bull) if risco_bull > 0 else 0
        risco_bear = bear_stop - suportes[0]
        rr_bear = ((suportes[0] - bear_pt1) / risco_bear) if risco_bear > 0 else 0

        # Notas Narrativas Cripto-Nativas
        nlg_notes = (
            f"<strong>Ativo Operando em Regime 24/7.</strong> O nível institucional crítico reside nos ${suportes[0]:.2f}. "
            f"No ecossistema cripto, os falsos rompimentos (Wicks/Pavio) são utilizados para liquidar alavancagens altas. "
            f"Nunca entrar em <i>Breakout</i> sem aguardar o fecho da vela no TF selecionado. O stop-loss nos ativos digitais "
            f"tem de acomodar choques de liquidez não programados."
        )

        # Preparação de Dados Gráficos (Sem Matplotlib, puro JSON para Plotly)
        hist_recente = df.tail(80)
        formato_data = '%Y-%m-%d' if timeframe == '1d' else '%Y-%m-%d %H:%M'
        
        dados_grafico = {
            "is_crypto": True, # A CHAVE MÁGICA PARA O EIXO X 24/7
            "datas": hist_recente.index.strftime(formato_data).tolist(),
            "closes": hist_recente['Close'].round(2).tolist(),
            "ema9": hist_recente['Close'].ewm(span=9).mean().round(2).tolist(),
            "ema20": hist_recente['Close'].ewm(span=20).mean().round(2).tolist(),
            "volumes": hist_recente['Volume'].tolist(),
            "cores_vol": ['#00ffcc' if hist_recente['Close'].iloc[i] >= hist_recente['Open'].iloc[i] else '#b388ff' for i in range(len(hist_recente))]
        }

        return jsonify({
            "ticker": ticker.upper(),
            "timeframe": timeframe.upper(),
            "preco": f"{fecho_atual:.2f}",
            "rsi": f"{rsi_atual:.1f}",
            "atr": f"{atr_14:.2f}",
            "dist_m50": "N/A", "cor_m50": "#fff", "dist_m200": "N/A", "cor_m200": "#fff", "dist_max": "N/A",
            "perf_1w": "N/A", "cor_1w": "#fff", "perf_1m": "N/A", "cor_1m": "#fff", "perf_3m": "N/A", "cor_3m": "#fff",
            "dados_grafico": dados_grafico,
            "suportes": [f"{s:.2f}" for s in suportes],
            "resistencias": [f"{r:.2f}" for r in resistencias],
            "notas": nlg_notes,
            "bull_plan": {"entrada": f"Rutura acima de {resistencias[0]:.2f}", "pt": [f"{bull_pt1:.2f}", f"{bull_pt2:.2f}"], "stop": f"{bull_stop:.2f}", "rr": f"1:{rr_bull:.1f}"},
            "bear_plan": {"entrada": f"Quebra abaixo de {suportes[0]:.2f}", "pt": [f"{bear_pt1:.2f}", f"{bear_pt2:.2f}"], "stop": f"{bear_stop:.2f}", "rr": f"1:{rr_bear:.1f}"}
        })
    except Exception as e:
        return jsonify({"erro": f"Falha Quantitativa Cripto: {str(e)}"}), 500

@app.route('/api/webhook/sniper', methods=['POST'])
def webhook_sniper():
    dados = request.json
    webhook_url = os.environ.get("WEBHOOK_SNIPER")
    
    if not webhook_url:
        return jsonify({"erro": "Webhook não configurado no servidor."}), 500

    # Limpar as tags HTML que injetámos no Python para não sujarem o texto do Discord
    import re
    notas_limpas = re.sub(r'<[^>]+>', '', dados.get('notas', ''))

    bull = dados['bull_plan']
    bear = dados['bear_plan']

    embed = {
        "embeds": [
            {
                "title": f"🎯 SNIPER BLUEPRINT: {dados['ticker']} ({dados['timeframe']})",
                "color": 11765967, # Roxo Portal Bolsa
                "description": f"**Cotação Atual:** ${dados['preco']} | **RSI:** {dados['rsi']} | **ATR:** ${dados['atr']}\n\n**Sniper Notes:**\n{notas_limpas}",
                "fields": [
                    {
                        "name": "📈 Bull Plan",
                        "value": f"**Gatilho:** {bull['entrada']}\n**Alvos:** {bull['pt'][0]} → {bull['pt'][1]}\n**Stop:** {bull['stop']} \n**R:R:** {bull['rr']}",
                        "inline": True
                    },
                    {
                        "name": "📉 Bear Plan",
                        "value": f"**Gatilho:** {bear['entrada']}\n**Alvos:** {bear['pt'][0]} → {bear['pt'][1]}\n**Stop:** {bear['stop']} \n**R:R:** {bear['rr']}",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "Portal Bolsa - Risco Quântico Algorítmico"
                }
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=embed)
        response.raise_for_status()
        return jsonify({"sucesso": True})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/webhook/duelo', methods=['POST'])
def webhook_duelo():
    dados = request.json
    import os
    import requests
    from flask import jsonify
    
    webhook_url = os.environ.get("WEBHOOK_DUELO")
    
    if not webhook_url:
        return jsonify({"erro": "Webhook não configurado no servidor."}), 500

    t1 = dados['t1']
    t2 = dados['t2']
    
    # Determina o vencedor matemático
    vencedor = t1 if float(t1['Mansfield RS']) > float(t2['Mansfield RS']) else t2
    perdedor = t2 if float(t1['Mansfield RS']) > float(t2['Mansfield RS']) else t1

    # Constrói o Veredicto Comportamental para apoiar a decisão na mensagem
    if float(t1['Mansfield RS']) < 0 and float(t2['Mansfield RS']) < 0:
        justificacao = f"⚠️ **Alerta de Degradação:** Ambas as ações apresentam Força Relativa institucional negativa. O capital está a fugir de ambas as frentes. A alocação na **{vencedor['Ticker']}** é apenas o 'mal menor' matemático, mas estruturalmente o mercado está a rejeitar ambos os ativos neste momento."
    else:
        justificacao = f"📊 **Veredicto do Sistema:** O racional quantitativo apoia inequivocamente a alocação na **{vencedor['Ticker']}** e a liquidação/rejeição da **{perdedor['Ticker']}**. A {vencedor['Ticker']} está a bater o mercado, demonstrando força institucional sustentada face ao índice de referência."

    embed = {
        "embeds": [
            {
                #"author": {
                #    "name": "Partilha de Ideias - Luís Reis",
                #    "icon_url": "https://cdn-icons-png.flaticon.com/512/3594/3594191.png" # Ícone elegante de bolsa/finanças
                #},
                "title": f"⚔️ ROTAÇÃO TÁTICA DE CAPITAL: {t1['Ticker']} vs {t2['Ticker']}",
                "color": 15965184, # Laranja Portal Bolsa
                "description": justificacao,
                "fields": [
                    {
                        "name": f"🟢 ALOCAÇÃO: {vencedor['Ticker']}",
                        "value": f"**Cotação:** {vencedor['Preço']} €\n**Mansfield RS:** {vencedor['Mansfield RS']}\n**ROC 6M:** {vencedor['ROC 6M (%)']}%\n**RSI (14):** {vencedor['RSI (14)']}\n\n**Alvos (PT1/PT2):** {vencedor['Alvo T1 (€)']} € / {vencedor['Alvo T2 (€)']} €\n**Stop Loss:** Abaixo de {vencedor['Stop Loss (€)']} €",
                        "inline": True
                    },
                    {
                        "name": f"🔴 LIQUIDAÇÃO: {perdedor['Ticker']}",
                        "value": f"**Cotação:** {perdedor['Preço']} €\n**Mansfield RS:** {perdedor['Mansfield RS']}\n**ROC 6M:** {perdedor['ROC 6M (%)']}%\n**RSI (14):** {perdedor['RSI (14)']}\n\n**Alvos (PT1/PT2):** {perdedor['Alvo T1 (€)']} € / {perdedor['Alvo T2 (€)']} €\n**Stop Loss:** Acima de {perdedor['Stop Loss (€)']} €",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "© Portal Bolsa | Algoritmo de Momentum"
                }
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=embed)
        response.raise_for_status()
        return jsonify({"sucesso": True})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

if __name__ == "__main__":
    # Verifica se a variável PORT existe (o Discloud cria isto automaticamente)
    if "PORT" in os.environ:
        # Ambiente Cloud (Produção): Usa o motor profissional Waitress
        porta = int(os.environ.get("PORT"))
        from waitress import serve
        print(f"[*] A iniciar servidor de produção WSGI na porta {porta}...")
        serve(app, host="0.0.0.0", port=porta)
    else:
        # Ambiente Local (O teu PC): Usa o motor de testes do Flask
        app.run(debug=True, port=5000)
