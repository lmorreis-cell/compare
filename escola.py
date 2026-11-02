"""
escola.py — Escola do Portal Bolsa: uma lição por dia útil + revisão ao sábado.

Tudo num único ficheiro de conteúdo: escola/licoes.json
    {
      "config":  {"inicio": "AAAA-MM-DD"},          # segunda-feira da Semana 1
      "semanas": [{"n": 1, "trimestre": 1, "tema": "..."}, ...],   # plano das 52 semanas
      "licoes":  [{"id": "s01d1", "semana": 1, "dia": 1, "titulo": "...", "publicada": true,
                   "resumo": "...", "quiz": [{"pergunta", "opcoes": [...], "certa": 0, "explicacao"}],
                   "teoria": "markdown", "grafico": {...} | null, "experimenta": {"texto", "url"} | null}]
    }

Na primeira execução, se escola/licoes.json não existir, é criado a partir de licoes_base.json
(o ficheiro que vem com o código). A partir daí, o editor da Área de Gestão escreve só em
escola/licoes.json e guarda uma cópia de segurança a cada gravação (escola/backups/, últimas 30).

Outros ficheiros:
    escola/progresso.json      respostas de cada membro (1.ª tentativa conta para a pontuação)
    escola/graficos/<id>.png   gráficos gerados UMA vez pelo Admin (os membros nunca vão ao Yahoo)
    escola/imagens/<nome>      imagens carregadas no editor

Integração no main.py:
    import escola
    escola.registar(app, requer_cargo=requer_cargo, e_admin=_e_admin)
"""

import json
import os
import random
import re
import shutil
import threading
import uuid
from datetime import date, datetime, timedelta

from flask import abort, jsonify, redirect, render_template, request, send_file, session
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Lisbon")
except Exception:  # pragma: no cover
    _TZ = None

PASTA = "escola"
ARQ_LICOES = os.path.join(PASTA, "licoes.json")
ARQ_BASE = "licoes_base.json"
ARQ_PROGRESSO = os.path.join(PASTA, "progresso.json")
ARQ_ALUNOS = os.path.join(PASTA, "alunos.json")      # {user_id: nome}, para o painel de alunos
PASTA_BACKUPS = os.path.join(PASTA, "backups")
PASTA_GRAFICOS = os.path.join(PASTA, "graficos")
PASTA_IMAGENS = os.path.join(PASTA, "imagens")
NIVEL_MINIMO = 1                 # Trader Ativo já tem acesso à Escola
PERGUNTAS_REVISAO = 6
EXT_IMAGEM = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
INDICADORES = ("ema20", "ema50", "sma200", "bollinger", "volume", "rsi")

_lock = threading.Lock()
_cache = {}


# =====================================================================
# DISCO
# =====================================================================
def _ler_json(caminho, omissao):
    try:
        mtime = os.path.getmtime(caminho)
    except OSError:
        return omissao
    em_cache = _cache.get(caminho)
    if em_cache and em_cache[0] == mtime:
        return em_cache[1]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return omissao
    _cache[caminho] = (mtime, dados)
    return dados


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)
    _cache.pop(caminho, None)


def _vazio():
    return {"config": {"inicio": _proxima_segunda().isoformat()}, "semanas": [], "licoes": []}


def carregar():
    """Conteúdo da Escola (cria escola/licoes.json a partir de licoes_base.json na 1.ª vez)."""
    if not os.path.exists(ARQ_LICOES):
        os.makedirs(PASTA, exist_ok=True)
        if os.path.exists(ARQ_BASE):
            shutil.copyfile(ARQ_BASE, ARQ_LICOES)
        else:
            _gravar_json(ARQ_LICOES, _vazio())
    dados = _ler_json(ARQ_LICOES, None) or _vazio()
    dados.setdefault("config", {}).setdefault("inicio", _proxima_segunda().isoformat())
    dados.setdefault("semanas", [])
    dados.setdefault("licoes", [])
    return dados


def _gravar_licoes(dados):
    """Grava o conteúdo e guarda uma cópia de segurança (mantém as últimas 30)."""
    with _lock:
        if os.path.exists(ARQ_LICOES):
            os.makedirs(PASTA_BACKUPS, exist_ok=True)
            carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            shutil.copyfile(ARQ_LICOES, os.path.join(PASTA_BACKUPS, f"licoes_{carimbo}.json"))
            antigos = sorted(os.listdir(PASTA_BACKUPS))
            for velho in antigos[:-30]:
                try:
                    os.remove(os.path.join(PASTA_BACKUPS, velho))
                except OSError:
                    pass
        dados["licoes"].sort(key=lambda l: (l["semana"], l["dia"]))
        _gravar_json(ARQ_LICOES, dados)


def _progresso():
    return _ler_json(ARQ_PROGRESSO, {})


def _gravar_progresso(user_id, chave, registo):
    with _lock:
        todos = dict(_ler_json(ARQ_PROGRESSO, {}))
        meu = dict(todos.get(user_id, {}))
        if chave in meu:          # a 1.ª tentativa é a que conta
            return meu[chave]
        meu[chave] = registo
        todos[user_id] = meu
        _gravar_json(ARQ_PROGRESSO, todos)
        nomes = dict(_ler_json(ARQ_ALUNOS, {}))
        nome = str(session.get("username") or "").strip()
        if nome and nomes.get(user_id) != nome:
            nomes[user_id] = nome
            _gravar_json(ARQ_ALUNOS, nomes)
        return registo


def _repor_progresso(user_id, chave=None):
    """Apaga o progresso de um membro: só uma lição/revisão (chave) ou tudo (chave=None)."""
    with _lock:
        todos = dict(_ler_json(ARQ_PROGRESSO, {}))
        if user_id not in todos:
            return False
        if chave is None:
            del todos[user_id]
        else:
            meu = dict(todos[user_id])
            if chave not in meu:
                return False
            del meu[chave]
            if meu:
                todos[user_id] = meu
            else:
                del todos[user_id]
        _gravar_json(ARQ_PROGRESSO, todos)
        return True


# =====================================================================
# DATAS
# =====================================================================
def hoje():
    return (datetime.now(_TZ) if _TZ else datetime.now()).date()


def _proxima_segunda(d=None):
    d = d or hoje()
    return d + timedelta(days=(7 - d.weekday()) % 7 or 0)


def _inicio(dados):
    try:
        d = date.fromisoformat(dados["config"]["inicio"])
    except Exception:
        d = _proxima_segunda()
    return d - timedelta(days=d.weekday())   # garante que é segunda-feira


def data_licao(dados, semana, dia):
    return _inicio(dados) + timedelta(days=(semana - 1) * 7 + (dia - 1))


def data_revisao(dados, semana):
    return _inicio(dados) + timedelta(days=(semana - 1) * 7 + 5)


def _licoes_por_id(dados):
    return {l["id"]: l for l in dados["licoes"]}


def _disponivel(dados, l, admin=False):
    if admin:
        return True
    return bool(l.get("publicada")) and data_licao(dados, l["semana"], l["dia"]) <= hoje()


def _tema(dados, semana):
    for s in dados["semanas"]:
        if s.get("n") == semana:
            return s
    return {"n": semana, "tema": "", "trimestre": (semana - 1) // 13 + 1}


# =====================================================================
# UTILIZADOR
# =====================================================================
def _uid():
    return str(session.get("user_id", "")).strip()


def _nivel():
    return session.get("nivel_acesso", 0)


def _sequencia(meu):
    """Dias úteis seguidos com pelo menos uma lição feita (o fim de semana não quebra)."""
    dias = set()
    for reg in meu.values():
        try:
            dias.add(date.fromisoformat(reg.get("quando", "")[:10]))
        except Exception:
            pass
    if not dias:
        return 0
    d = hoje()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    if d not in dias:           # hoje ainda não fez: conta a partir do último dia útil
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    n = 0
    while d in dias:
        n += 1
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return n


def _estatisticas(dados, meu):
    licoes = [l for l in dados["licoes"] if _disponivel(dados, l)]
    feitas = [meu[l["id"]] for l in licoes if l["id"] in meu]
    perguntas = sum(len(r.get("respostas", [])) for r in feitas)
    certas = sum(r.get("acertos", 0) for r in feitas)
    revisoes = [v for k, v in meu.items() if k.startswith("rev")]
    pontos = certas + 2 * len(feitas) + sum(r.get("acertos", 0) for r in revisoes)
    return {
        "feitas": len(feitas), "disponiveis": len(licoes),
        "taxa": round(certas / perguntas * 100) if perguntas else None,
        "sequencia": _sequencia(meu), "pontos": pontos,
    }


# =====================================================================
# SEGURANÇA
# =====================================================================
def _mesma_origem():
    """Recusa pedidos de escrita vindos de outro site (o cookie de sessão viaja sozinho)."""
    origem = request.headers.get("Origin") or request.headers.get("Referer")
    if not origem:
        return False
    return urlparse(origem).netloc == request.host


def _texto(v, maximo):
    return str(v or "").strip()[:maximo]


def _validar_licao(bruta):
    """Normaliza e valida uma lição vinda do editor. Devolve (licao, erro)."""
    try:
        semana, dia = int(bruta.get("semana")), int(bruta.get("dia"))
    except Exception:
        return None, "Semana e dia têm de ser números."
    if not (1 <= semana <= 52 and 1 <= dia <= 5):
        return None, "A semana vai de 1 a 52 e o dia de 1 (segunda) a 5 (sexta)."
    titulo = _texto(bruta.get("titulo"), 140)
    if not titulo:
        return None, "Falta o título."

    quiz = []
    for i, q in enumerate(bruta.get("quiz") or [], 1):
        pergunta = _texto(q.get("pergunta"), 400)
        opcoes = [_texto(o, 250) for o in (q.get("opcoes") or []) if _texto(o, 250)]
        if not pergunta and not opcoes:
            continue
        if not pergunta or len(opcoes) < 2:
            return None, f"A pergunta {i} precisa de texto e de pelo menos 2 opções."
        try:
            certa = int(q.get("certa", 0))
        except Exception:
            certa = -1
        if not 0 <= certa < len(opcoes):
            return None, f"Na pergunta {i}, marca qual é a opção certa."
        quiz.append({"pergunta": pergunta, "opcoes": opcoes, "certa": certa,
                     "explicacao": _texto(q.get("explicacao"), 800)})
    if bruta.get("publicada") and not quiz:
        return None, "Uma lição publicada precisa de pelo menos uma pergunta no quiz."

    grafico = None
    g = bruta.get("grafico") or {}
    if _texto(g.get("ticker"), 20):
        marcas = []
        for m in g.get("marcas") or []:
            if _texto(m.get("data"), 10):
                marcas.append({"data": _texto(m.get("data"), 10), "texto": _texto(m.get("texto"), 60)})
        grafico = {
            "ticker": _texto(g.get("ticker"), 20).upper(),
            "inicio": _texto(g.get("inicio"), 10),
            "fim": _texto(g.get("fim"), 10),
            "indicadores": [i for i in (g.get("indicadores") or []) if i in INDICADORES],
            "titulo": _texto(g.get("titulo"), 120),
            "legenda": _texto(g.get("legenda"), 400),
            "marcas": marcas[:8],
        }
        for campo in ("inicio", "fim"):
            if grafico[campo]:
                try:
                    date.fromisoformat(grafico[campo])
                except ValueError:
                    return None, f"Data do gráfico inválida ({campo}). Usa AAAA-MM-DD."

    exp = bruta.get("experimenta") or {}
    experimenta = None
    if _texto(exp.get("texto"), 200):
        url = _texto(exp.get("url"), 300)
        if url and not (url.startswith("/") or url.startswith("https://")):
            return None, "O link do 'Experimenta' tem de começar por / ou https://"
        experimenta = {"texto": _texto(exp.get("texto"), 200), "url": url}

    return {
        "id": f"s{semana:02d}d{dia}",
        "semana": semana, "dia": dia,
        "titulo": titulo,
        "publicada": bool(bruta.get("publicada")),
        "resumo": _texto(bruta.get("resumo"), 300),
        "quiz": quiz,
        "teoria": str(bruta.get("teoria") or "")[:30000],
        "grafico": grafico,
        "experimenta": experimenta,
    }, None


# =====================================================================
# GRÁFICOS (gerados uma vez pelo Admin)
# =====================================================================
def _caminho_grafico(lid):
    return os.path.join(PASTA_GRAFICOS, f"{lid}.png")


def gerar_grafico(licao):
    """Desenha o gráfico da lição a partir do Yahoo e guarda-o em PNG. Devolve (ok, mensagem)."""
    g = licao.get("grafico")
    if not g:
        return False, "Esta lição não tem gráfico definido."

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    import yahoo_guard as yg

    fim = date.fromisoformat(g["fim"]) if g.get("fim") else hoje()
    inicio = date.fromisoformat(g["inicio"]) if g.get("inicio") else fim - timedelta(days=365)
    aquecimento = inicio - timedelta(days=420)       # histórico extra para a SMA 200 já vir calculada

    try:
        try:
            dados = yg.download(g["ticker"], start=aquecimento.isoformat(), end=(fim + timedelta(days=1)).isoformat(),
                                interval="1d", usar_cache=False)
        except TypeError:
            dados = yg.download(g["ticker"], period="max", interval="1d", usar_cache=False)
    except Exception as e:
        return False, f"Não foi possível obter dados de {g['ticker']}: {e}"
    if dados is None or len(dados) == 0:
        return False, f"O Yahoo não devolveu dados para {g['ticker']}."
    if isinstance(dados.columns, pd.MultiIndex):
        dados = yg.fatia(dados, g["ticker"])
    df = dados.dropna(subset=["Close"]).copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)

    c = df["Close"]
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["sma200"] = c.rolling(200).mean()
    mid, std = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_sup"], df["bb_inf"] = mid + 2 * std, mid - 2 * std
    delta = c.diff()
    ganho = delta.where(delta > 0, 0).rolling(14).mean()
    perda = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["rsi"] = 100 - 100 / (1 + ganho / perda)
    df = df[(df.index >= pd.Timestamp(inicio)) & (df.index <= pd.Timestamp(fim))]
    if len(df) < 5:
        return False, "Há poucos dados no intervalo escolhido."

    ind = set(g.get("indicadores") or [])
    paineis = ["preco"] + (["volume"] if "volume" in ind else []) + (["rsi"] if "rsi" in ind else [])
    alturas = {"preco": 3.2, "volume": 0.9, "rsi": 1.1}

    FUNDO, GRELHA, TEXTO, SUAVE = "#0b0d12", "#1f2430", "#e6e8ec", "#8b93a3"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, eixos = plt.subplots(len(paineis), 1, figsize=(11, 2.0 + 1.35 * sum(alturas[p] for p in paineis)),
                              sharex=True, gridspec_kw={"height_ratios": [alturas[p] for p in paineis], "hspace": 0.06})
    if len(paineis) == 1:
        eixos = [eixos]
    fig.patch.set_facecolor(FUNDO)
    fig.subplots_adjust(left=0.02, right=0.93, top=0.9, bottom=0.08)
    for ax in eixos:
        ax.set_facecolor(FUNDO)
        ax.grid(color=GRELHA, linewidth=0.7)
        ax.tick_params(colors=SUAVE, labelsize=9)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.yaxis.tick_right()

    ax = eixos[0]
    if "bollinger" in ind:
        ax.fill_between(df.index, df["bb_inf"], df["bb_sup"], color="#5865F2", alpha=0.12, linewidth=0, label="Bandas de Bollinger")
        ax.plot(df.index, df["bb_sup"], color="#5865F2", linewidth=0.8, alpha=0.6)
        ax.plot(df.index, df["bb_inf"], color="#5865F2", linewidth=0.8, alpha=0.6)
    ax.plot(df.index, df["Close"], color=TEXTO, linewidth=1.6, label="Preço")
    cores = {"ema20": ("#f59e0b", "EMA 20"), "ema50": ("#22c55e", "EMA 50"), "sma200": ("#ef4444", "SMA 200")}
    for chave, (cor, nome) in cores.items():
        if chave in ind:
            ax.plot(df.index, df[chave], color=cor, linewidth=1.3, label=nome)
    if len(ax.get_legend_handles_labels()[0]) > 1:
        leg = ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=4)
        for t in leg.get_texts():
            t.set_color(TEXTO)
    titulo = g.get("titulo") or g["ticker"]
    ax.set_title(titulo, color=TEXTO, fontsize=13, fontweight="bold", loc="left", pad=12)

    for p, eixo in zip(paineis[1:], eixos[1:]):
        if p == "volume":
            cores_v = ["#22c55e" if a >= b else "#ef4444" for a, b in zip(df["Close"], df["Close"].shift(1).fillna(df["Close"]))]
            eixo.bar(df.index, df["Volume"], color=cores_v, width=1.0, alpha=0.7)
            eixo.set_ylabel("Volume", color=SUAVE, fontsize=9)
            eixo.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                lambda v, _: f"{v/1e6:.0f}M" if v >= 1e6 else f"{v/1e3:.0f}k"))
        if p == "rsi":
            eixo.plot(df.index, df["rsi"], color="#a78bfa", linewidth=1.3)
            eixo.axhline(70, color="#ef4444", linewidth=0.9, linestyle="--")
            eixo.axhline(30, color="#22c55e", linewidth=0.9, linestyle="--")
            eixo.fill_between(df.index, 30, 70, color="#a78bfa", alpha=0.06)
            eixo.set_ylim(0, 100)
            eixo.set_yticks([30, 50, 70])
            eixo.set_ylabel("RSI 14", color=SUAVE, fontsize=9)

    for m in g.get("marcas") or []:
        try:
            x = pd.Timestamp(m["data"])
        except Exception:
            continue
        if not (df.index[0] <= x <= df.index[-1]):
            continue
        for eixo in eixos:
            eixo.axvline(x, color="#f59e0b", linewidth=1, linestyle=":", alpha=0.9)
        if m.get("texto"):
            ax.annotate(m["texto"], xy=(x, 1.0), xycoords=("data", "axes fraction"), xytext=(4, -14),
                        textcoords="offset points", color="#f59e0b", fontsize=9, fontweight="bold")

    eixos[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y" if (df.index[-1] - df.index[0]).days > 120 else "%d %b"))
    fig.text(0.01, 0.01, "Portal Bolsa · Escola", color="#3a4152", fontsize=8)
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    fig.savefig(_caminho_grafico(licao["id"]), dpi=110, facecolor=FUNDO, bbox_inches="tight")
    plt.close(fig)
    return True, f"Gráfico gerado com {len(df)} sessões de {g['ticker']}."


def _url_grafico(lid):
    caminho = _caminho_grafico(lid)
    if not os.path.exists(caminho):
        return None
    return f"/escola/grafico/{lid}.png?v={int(os.path.getmtime(caminho))}"


# =====================================================================
# SERIALIZAÇÃO PARA O MEMBRO
# =====================================================================
def _licao_para_membro(dados, l, registo, admin=False):
    base = {
        "id": l["id"], "semana": l["semana"], "dia": l["dia"], "titulo": l["titulo"],
        "data": data_licao(dados, l["semana"], l["dia"]).isoformat(),
        "tema": _tema(dados, l["semana"]).get("tema", ""),
        "quiz": [{"pergunta": q["pergunta"], "opcoes": q["opcoes"]} for q in l.get("quiz", [])],
        "feita": registo is not None,
        "rascunho": not l.get("publicada"),
    }
    ordem = [x["id"] for x in dados["licoes"] if _disponivel(dados, x, admin)]
    if l["id"] in ordem:
        i = ordem.index(l["id"])
        base["anterior"] = ordem[i - 1] if i > 0 else None
        base["seguinte"] = ordem[i + 1] if i + 1 < len(ordem) else None
    if registo is not None:
        base.update(_conteudo_completo(l, registo["respostas"]))
        base["acertos"] = registo.get("acertos")
    return base


def _conteudo_completo(l, respostas):
    correcao = []
    for i, q in enumerate(l.get("quiz", [])):
        r = respostas[i] if i < len(respostas) else None
        correcao.append({"certa": q["certa"], "escolhida": r, "acertou": r == q["certa"], "explicacao": q.get("explicacao", "")})
    return {
        "correcao": correcao,
        "teoria": l.get("teoria", ""),
        "resumo": l.get("resumo", ""),
        "grafico": ({"url": _url_grafico(l["id"]), "legenda": (l.get("grafico") or {}).get("legenda", "")}
                    if _url_grafico(l["id"]) else None),
        "experimenta": l.get("experimenta"),
    }


def _perguntas_revisao(dados, semana):
    banco = []
    for l in dados["licoes"]:
        if l["semana"] == semana and l.get("publicada"):
            for i, q in enumerate(l.get("quiz", [])):
                banco.append((f"{l['id']}:{i}", l, q))
    rnd = random.Random(f"revisao-{semana}")
    rnd.shuffle(banco)
    return banco[:PERGUNTAS_REVISAO]


# =====================================================================
# ROTAS
# =====================================================================
def registar(app, requer_cargo, e_admin):

    def so_admin_json():
        if not e_admin():
            return jsonify({"erro": "Acesso negado. Apenas Admin."}), 403
        if request.method != "GET" and not _mesma_origem():
            return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        return None

    def membro_json():
        if _nivel() < NIVEL_MINIMO and not e_admin():
            return jsonify({"erro": "Precisas de sessão iniciada com cargo de membro."}), 403
        return None

    # ---------------- Páginas
    @app.route("/escola")
    @requer_cargo(nivel_minimo=NIVEL_MINIMO)
    def escola_pagina():
        return render_template("escola.html", username=session.get("username", "Membro"), is_admin=e_admin())

    @app.route("/admin/escola")
    def escola_editor():
        if not e_admin():
            return redirect("/")
        return render_template("admin_escola.html", username=session.get("username", "Admin"))

    # ---------------- Ficheiros
    @app.route("/escola/grafico/<lid>.png")
    def escola_grafico(lid):
        if _nivel() < NIVEL_MINIMO and not e_admin():
            abort(403)
        if not re.fullmatch(r"s\d{2}d[1-5]", lid) or not os.path.exists(_caminho_grafico(lid)):
            abort(404)
        return send_file(os.path.abspath(_caminho_grafico(lid)), mimetype="image/png", max_age=86400)

    @app.route("/escola/imagem/<nome>")
    def escola_imagem(nome):
        if _nivel() < NIVEL_MINIMO and not e_admin():
            abort(403)
        if not re.fullmatch(r"[a-f0-9]{12}\.(png|jpe?g|gif|webp)", nome):
            abort(404)
        caminho = os.path.join(PASTA_IMAGENS, nome)
        if not os.path.exists(caminho):
            abort(404)
        return send_file(os.path.abspath(caminho), max_age=86400)

    # ---------------- API do membro
    @app.route("/api/escola/calendario")
    def escola_calendario():
        negado = membro_json()
        if negado:
            return negado
        dados, admin = carregar(), e_admin()
        meu = _progresso().get(_uid(), {})
        por_semana = {}
        for l in dados["licoes"]:
            por_semana.setdefault(l["semana"], []).append(l)
        licoes = []
        for l in dados["licoes"]:
            if not l.get("publicada") and not admin:
                continue
            reg = meu.get(l["id"])
            licoes.append({
                "id": l["id"], "semana": l["semana"], "dia": l["dia"], "titulo": l["titulo"],
                "data": data_licao(dados, l["semana"], l["dia"]).isoformat(),
                "disponivel": _disponivel(dados, l, admin), "feita": reg is not None,
                "acertos": reg.get("acertos") if reg else None, "total": len(l.get("quiz", [])),
                "rascunho": not l.get("publicada"),
            })
        revisoes = []
        for s in sorted(por_semana):
            if not any(l.get("publicada") for l in por_semana[s]):
                continue
            d = data_revisao(dados, s)
            reg = meu.get(f"rev{s:02d}")
            revisoes.append({"semana": s, "data": d.isoformat(), "disponivel": admin or d <= hoje(),
                             "feita": reg is not None, "acertos": reg.get("acertos") if reg else None,
                             "total": len(_perguntas_revisao(dados, s))})
        return jsonify({
            "hoje": hoje().isoformat(),
            "inicio": _inicio(dados).isoformat(),
            "semanas": dados["semanas"],
            "licoes": licoes,
            "revisoes": revisoes,
            "estatisticas": _estatisticas(dados, meu),
            "admin": admin,
        })

    @app.route("/api/escola/licao/<lid>")
    def escola_licao(lid):
        negado = membro_json()
        if negado:
            return negado
        dados, admin = carregar(), e_admin()
        l = _licoes_por_id(dados).get(lid)
        if not l or not _disponivel(dados, l, admin):
            return jsonify({"erro": "Esta lição ainda não está disponível."}), 404
        reg = _progresso().get(_uid(), {}).get(lid)
        return jsonify(_licao_para_membro(dados, l, reg, admin))

    @app.route("/api/escola/licao/<lid>/responder", methods=["POST"])
    def escola_responder(lid):
        negado = membro_json()
        if negado:
            return negado
        if not _mesma_origem():
            return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        dados, admin = carregar(), e_admin()
        l = _licoes_por_id(dados).get(lid)
        if not l or not _disponivel(dados, l, admin):
            return jsonify({"erro": "Esta lição ainda não está disponível."}), 404
        respostas = (request.get_json(silent=True) or {}).get("respostas") or []
        if len(respostas) != len(l.get("quiz", [])):
            return jsonify({"erro": "Responde a todas as perguntas."}), 400
        try:
            respostas = [int(r) for r in respostas]
        except Exception:
            return jsonify({"erro": "Respostas inválidas."}), 400
        acertos = sum(1 for q, r in zip(l["quiz"], respostas) if q["certa"] == r)
        registo = _gravar_progresso(_uid(), lid, {
            "respostas": respostas, "acertos": acertos,
            "quando": (datetime.now(_TZ) if _TZ else datetime.now()).isoformat(timespec="seconds"),
        })
        resposta = _licao_para_membro(dados, l, registo, admin)
        if registo["respostas"] != respostas:         # já tinha feito: mostra a tentativa de treino
            resposta.update(_conteudo_completo(l, respostas))
            resposta["treino"] = {"acertos": acertos}
        return jsonify(resposta)

    @app.route("/api/escola/revisao/<int:semana>", methods=["GET", "POST"])
    def escola_revisao(semana):
        negado = membro_json()
        if negado:
            return negado
        dados, admin = carregar(), e_admin()
        if not admin and data_revisao(dados, semana) > hoje():
            return jsonify({"erro": "A revisão desta semana abre no sábado."}), 404
        perguntas = _perguntas_revisao(dados, semana)
        if not perguntas:
            return jsonify({"erro": "Ainda não há perguntas para esta semana."}), 404
        chave = f"rev{semana:02d}"
        reg = _progresso().get(_uid(), {}).get(chave)
        base = {"semana": semana, "tema": _tema(dados, semana).get("tema", ""),
                "data": data_revisao(dados, semana).isoformat(),
                "quiz": [{"pergunta": q["pergunta"], "opcoes": q["opcoes"], "licao": l["id"], "licao_titulo": l["titulo"]}
                         for _, l, q in perguntas]}

        def correcao(resp):
            return [{"certa": q["certa"], "escolhida": r, "acertou": r == q["certa"], "explicacao": q.get("explicacao", "")}
                    for (_, _, q), r in zip(perguntas, resp)]

        if request.method == "GET":
            if reg:
                base.update({"feita": True, "acertos": reg["acertos"], "correcao": correcao(reg["respostas"])})
            return jsonify(base)

        if not _mesma_origem():
            return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        respostas = (request.get_json(silent=True) or {}).get("respostas") or []
        if len(respostas) != len(perguntas):
            return jsonify({"erro": "Responde a todas as perguntas."}), 400
        respostas = [int(r) for r in respostas]
        acertos = sum(1 for (_, _, q), r in zip(perguntas, respostas) if q["certa"] == r)
        guardado = _gravar_progresso(_uid(), chave, {
            "respostas": respostas, "acertos": acertos,
            "quando": (datetime.now(_TZ) if _TZ else datetime.now()).isoformat(timespec="seconds")})
        base.update({"feita": True, "acertos": acertos, "correcao": correcao(respostas),
                     "treino": guardado["respostas"] != respostas})
        return jsonify(base)

    # ---------------- API do editor (Admin)
    @app.route("/api/admin/escola")
    def escola_admin_tudo():
        negado = so_admin_json()
        if negado:
            return negado
        dados = carregar()
        prog = _progresso()
        estat = {}
        for l in dados["licoes"]:
            regs = [p[l["id"]] for p in prog.values() if l["id"] in p]
            total = sum(len(r.get("respostas", [])) for r in regs)
            estat[l["id"]] = {"alunos": len(regs),
                              "taxa": round(sum(r.get("acertos", 0) for r in regs) / total * 100) if total else None}
        licoes = []
        for l in dados["licoes"]:
            x = dict(l)
            x["data"] = data_licao(dados, l["semana"], l["dia"]).isoformat()
            x["grafico_url"] = _url_grafico(l["id"])
            licoes.append(x)
        return jsonify({"config": dados["config"], "inicio": _inicio(dados).isoformat(), "hoje": hoje().isoformat(),
                        "semanas": dados["semanas"], "licoes": licoes, "estatisticas": estat,
                        "alunos": len(prog)})

    @app.route("/api/admin/escola/licao", methods=["POST"])
    def escola_admin_gravar():
        negado = so_admin_json()
        if negado:
            return negado
        licao, erro = _validar_licao(request.get_json(silent=True) or {})
        if erro:
            return jsonify({"erro": erro}), 400
        dados = json.loads(json.dumps(carregar()))       # cópia
        dados["licoes"] = [l for l in dados["licoes"] if l["id"] != licao["id"]] + [licao]
        _gravar_licoes(dados)
        licao["data"] = data_licao(dados, licao["semana"], licao["dia"]).isoformat()
        licao["grafico_url"] = _url_grafico(licao["id"])
        return jsonify({"sucesso": True, "mensagem": "Lição gravada.", "licao": licao})

    @app.route("/api/admin/escola/licao/<lid>/apagar", methods=["POST"])
    def escola_admin_apagar(lid):
        negado = so_admin_json()
        if negado:
            return negado
        dados = json.loads(json.dumps(carregar()))
        antes = len(dados["licoes"])
        dados["licoes"] = [l for l in dados["licoes"] if l["id"] != lid]
        if len(dados["licoes"]) == antes:
            return jsonify({"erro": "Lição não encontrada."}), 404
        _gravar_licoes(dados)
        return jsonify({"sucesso": True, "mensagem": "Lição apagada (há cópia de segurança)."})

    @app.route("/api/admin/escola/config", methods=["POST"])
    def escola_admin_config():
        negado = so_admin_json()
        if negado:
            return negado
        corpo = request.get_json(silent=True) or {}
        dados = json.loads(json.dumps(carregar()))
        if "inicio" in corpo:
            try:
                d = date.fromisoformat(corpo["inicio"])
            except Exception:
                return jsonify({"erro": "Data de início inválida."}), 400
            if d.weekday() != 0:
                return jsonify({"erro": "A data de início tem de ser uma segunda-feira."}), 400
            dados["config"]["inicio"] = d.isoformat()
        if "semanas" in corpo:
            semanas = []
            for s in corpo["semanas"]:
                try:
                    n, t = int(s.get("n")), int(s.get("trimestre") or 0)
                except Exception:
                    continue
                if 1 <= n <= 52:
                    semanas.append({"n": n, "trimestre": t or (n - 1) // 13 + 1, "tema": _texto(s.get("tema"), 120)})
            dados["semanas"] = sorted(semanas, key=lambda s: s["n"])
        _gravar_licoes(dados)
        return jsonify({"sucesso": True, "mensagem": "Configuração gravada.", "inicio": _inicio(dados).isoformat()})

    @app.route("/api/admin/escola/grafico/<lid>", methods=["POST"])
    def escola_admin_grafico(lid):
        negado = so_admin_json()
        if negado:
            return negado
        l = _licoes_por_id(carregar()).get(lid)
        if not l:
            return jsonify({"erro": "Grava a lição antes de gerar o gráfico."}), 404
        try:
            ok, msg = gerar_grafico(l)
        except Exception as e:
            ok, msg = False, f"Erro ao gerar o gráfico: {e}"
        return jsonify({"sucesso": ok, "mensagem": msg, "url": _url_grafico(lid) if ok else None}), (200 if ok else 400)

    @app.route("/api/admin/escola/graficos_em_falta", methods=["POST"])
    def escola_admin_graficos_em_falta():
        """Gera, um a um e com pausa entre eles, os gráficos definidos que ainda não existem."""
        negado = so_admin_json()
        if negado:
            return negado
        import time
        feitos, erros = [], []
        pendentes = [l for l in carregar()["licoes"] if l.get("grafico") and not os.path.exists(_caminho_grafico(l["id"]))]
        for n, l in enumerate(pendentes[:10]):       # no máximo 10 por clique, para não pesar no Yahoo
            if n:
                time.sleep(2)
            try:
                ok, msg = gerar_grafico(l)
            except Exception as e:
                ok, msg = False, str(e)
            (feitos if ok else erros).append(l["id"] if ok else f"{l['id']}: {msg}")
        resto = max(0, len(pendentes) - 10)
        msg = f"{len(feitos)} gráficos gerados." + (f" {len(erros)} com erro." if erros else "") + (f" Faltam {resto} — clica outra vez." if resto else "")
        return jsonify({"sucesso": not erros, "mensagem": msg, "feitos": feitos, "erros": erros, "faltam": resto})

    @app.route("/api/admin/escola/alunos")
    def escola_admin_alunos():
        """Pontos e respostas de cada membro (para corrigir testes ou ajudar alguém)."""
        negado = so_admin_json()
        if negado:
            return negado
        dados = carregar()
        por_id = _licoes_por_id(dados)
        nomes = _ler_json(ARQ_ALUNOS, {})
        eu = _uid()
        alunos = []
        for uid, meu in _progresso().items():
            registos = []
            for chave, reg in meu.items():
                if chave.startswith("rev"):
                    sem = int(chave[3:])
                    titulo, total = f"Revisão da semana {sem}", len(reg.get("respostas", []))
                else:
                    l = por_id.get(chave)
                    titulo = l["titulo"] if l else f"{chave} (lição apagada)"
                    total = len(reg.get("respostas", []))
                registos.append({"chave": chave, "titulo": titulo, "acertos": reg.get("acertos", 0),
                                 "total": total, "quando": reg.get("quando", "")})
            registos.sort(key=lambda r: r["quando"], reverse=True)
            alunos.append({"uid": uid, "nome": nomes.get(uid) or f"Membro {uid[-4:]}", "eu": uid == eu,
                           "estatisticas": _estatisticas(dados, meu),
                           "ultima": registos[0]["quando"] if registos else None, "registos": registos})
        alunos.sort(key=lambda a: (not a["eu"], -a["estatisticas"]["pontos"]))
        return jsonify({"alunos": alunos})

    @app.route("/api/admin/escola/alunos/<uid>/repor", methods=["POST"])
    def escola_admin_repor(uid):
        """Repõe o progresso de um membro: uma lição/revisão ({"chave": "s01d1"}) ou tudo ({})."""
        negado = so_admin_json()
        if negado:
            return negado
        chave = (request.get_json(silent=True) or {}).get("chave")
        if chave is not None and not re.fullmatch(r"s\d{2}d[1-5]|rev\d{2}", str(chave)):
            return jsonify({"erro": "Lição inválida."}), 400
        if not _repor_progresso(uid, chave):
            return jsonify({"erro": "Não havia nada para repor."}), 404
        return jsonify({"sucesso": True, "mensagem": "Lição reposta: pode voltar a responder e a 1.ª tentativa volta a contar."
                        if chave else "Progresso apagado: o membro recomeça do zero."})

    @app.route("/api/admin/escola/imagem", methods=["POST"])
    def escola_admin_imagem():
        negado = so_admin_json()
        if negado:
            return negado
        f = request.files.get("imagem")
        if not f or not f.filename:
            return jsonify({"erro": "Nenhuma imagem recebida."}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in EXT_IMAGEM:
            return jsonify({"erro": "Formato não suportado (usa PNG, JPG, GIF ou WEBP)."}), 400
        conteudo = f.read(5 * 1024 * 1024 + 1)
        if len(conteudo) > 5 * 1024 * 1024:
            return jsonify({"erro": "Imagem demasiado grande (máximo 5 MB)."}), 400
        nome = uuid.uuid4().hex[:12] + (".jpg" if ext == ".jpeg" else ext)
        os.makedirs(PASTA_IMAGENS, exist_ok=True)
        with open(os.path.join(PASTA_IMAGENS, nome), "wb") as out:
            out.write(conteudo)
        return jsonify({"sucesso": True, "url": f"/escola/imagem/{nome}"})

    @app.route("/api/admin/escola/exportar")
    def escola_admin_exportar():
        negado = so_admin_json()
        if negado:
            return negado
        carregar()
        return send_file(os.path.abspath(ARQ_LICOES), as_attachment=True,
                         download_name=f"licoes_{hoje().isoformat()}.json", mimetype="application/json")

    @app.route("/api/admin/escola/importar", methods=["POST"])
    def escola_admin_importar():
        negado = so_admin_json()
        if negado:
            return negado
        novo = request.get_json(silent=True)
        if not isinstance(novo, dict) or not isinstance(novo.get("licoes"), list):
            return jsonify({"erro": "Ficheiro inválido: não parece um licoes.json."}), 400
        licoes, erros = [], []
        for bruta in novo["licoes"]:
            l, erro = _validar_licao(bruta)
            if erro:
                erros.append(f"{bruta.get('id', '?')}: {erro}")
            else:
                licoes.append(l)
        if erros:
            return jsonify({"erro": "Importação cancelada. " + " | ".join(erros[:5])}), 400
        dados = {"config": novo.get("config") or carregar()["config"], "semanas": novo.get("semanas") or [], "licoes": licoes}
        _gravar_licoes(dados)
        return jsonify({"sucesso": True, "mensagem": f"Importadas {len(licoes)} lições (a versão anterior ficou em cópia de segurança)."})
