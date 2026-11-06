"""
escola_discord.py — «Pergunta do dia» da Escola no Discord (chamado pelo agendador a cada minuto).

Dias úteis, à hora definida (por omissão 12:30, Lisboa):
    1. Revela a resposta da pergunta do dia anterior, escondida em spoiler (||…||) para quem ainda não fez a lição.
    2. Publica uma pergunta do quiz da lição de HOJE, como sondagem do Discord (os membros votam com um toque).
       Se a pergunta ou as opções forem longas demais para uma sondagem (o Discord aceita 300 caracteres na pergunta
       e 55 em cada opção), sai como mensagem normal com as opções A), B), C)…
Sábado: revela a resposta de sexta e lembra a revisão semanal. Domingo: nada.

As respostas no Discord NÃO contam para os pontos da Escola: os pontos são só do portal (1.ª tentativa).

Travões:
    - Uma única vez por dia (fica registado em escola/discord_estado.json).
    - Só entre a hora definida e as 22:00. Se falhar, tenta mais 2 vezes com 30 min de intervalo.
    - Revelações com mais de 4 dias são descartadas (ex.: servidor desligado vários dias).

Configuração:
    WEBHOOK_ESCOLA   webhook da sala do Discord onde sai a pergunta (obrigatório; sem ele não envia nada)
    PORTAL_URL       endereço do portal para o link (ex.: https://portalbolsa.discloud.app). Se não existir,
                     é deduzido de DISCORD_REDIRECT_URI.
    Na Área de Gestão: ligar/desligar e mudar a hora (fica em escola/discord.json).
"""

import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import jsonify, request

import escola

ARQ_CONFIG = os.path.join(escola.PASTA, "discord.json")
ARQ_ESTADO = os.path.join(escola.PASTA, "discord_estado.json")
HORA_FIM = 22
MAX_TENTATIVAS = 3
INTERVALO_MIN = 30
MAX_ATRASO_REVELAR = 4
LIM_PERGUNTA, LIM_OPCAO, MAX_OPCOES = 300, 55, 10
COR_PERGUNTA, COR_RESPOSTA = 0xF28B24, 0x3FB950
_lock = threading.Lock()
LETRAS = "ABCDEFGHIJ"


# ---------------------------------------------------------------
# FICHEIROS
# ---------------------------------------------------------------
def _ler(caminho, omissao):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return omissao


def _gravar(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def config():
    c = _ler(ARQ_CONFIG, {})
    return {"ativo": c.get("ativo", True), "hora": c.get("hora", "12:30")}


def _hora_cfg():
    try:
        h, m = config()["hora"].split(":")
        return int(h), int(m)
    except Exception:
        return 12, 30


def estado():
    return _ler(ARQ_ESTADO, {})


def _webhook():
    return os.environ.get("WEBHOOK_ESCOLA")


def portal_url():
    url = (os.environ.get("PORTAL_URL") or "").strip().rstrip("/")
    if url:
        return url
    r = os.environ.get("DISCORD_REDIRECT_URI") or ""
    p = urlparse(r)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


# ---------------------------------------------------------------
# ESCOLHER A PERGUNTA
# ---------------------------------------------------------------
def licao_do_dia(dia):
    dados = escola.carregar()
    for l in dados["licoes"]:
        if l.get("publicada") and l.get("quiz") and escola.data_licao(dados, l["semana"], l["dia"]) == dia:
            return dados, l
    return dados, None


def _cabe_em_sondagem(q):
    return (len(q["pergunta"]) <= LIM_PERGUNTA and 2 <= len(q["opcoes"]) <= MAX_OPCOES
            and all(len(o) <= LIM_OPCAO for o in q["opcoes"]))


def escolher_pergunta(l, dia):
    """Prefere as perguntas que cabem numa sondagem; entre elas, roda de dia para dia."""
    quiz = l.get("quiz") or []
    if not quiz:
        return None, None
    candidatas = [i for i, q in enumerate(quiz) if _cabe_em_sondagem(q)] or list(range(len(quiz)))
    i = candidatas[dia.toordinal() % len(candidatas)]
    return i, quiz[i]


def _corta(t, n):
    t = str(t or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------
# MENSAGENS
# ---------------------------------------------------------------
def _textos(dados, l):
    url = portal_url()
    tema = escola._tema(dados, l["semana"]).get("tema", "")
    link = f"{url}/escola" if url else "a Escola do portal"
    cab = (f"🎓 **Pergunta do dia** · Semana {l['semana']}{' · ' + tema if tema else ''}\n"
           f"Lição de hoje: **{_corta(l['titulo'], 120)}**")
    rodape = (f"\n\nFaz a lição completa em {link} — lá é que contam os pontos (só a 1.ª tentativa). "
              f"A resposta sai no próximo dia, à mesma hora. 🔒")
    return cab, rodape


def mensagem_pergunta(dados, l, q, simples=False):
    """Devolve (payload, é_sondagem)."""
    cab, rodape = _textos(dados, l)
    if not simples and _cabe_em_sondagem(q):
        return {"username": "Escola · Portal Bolsa", "content": cab + rodape,
                "poll": {"question": {"text": q["pergunta"]},
                         "answers": [{"poll_media": {"text": o}} for o in q["opcoes"]],
                         "duration": 23, "allow_multiselect": False}}, True
    opcoes = "\n".join(f"**{LETRAS[i]})** {_corta(o, 250)}" for i, o in enumerate(q["opcoes"][:MAX_OPCOES]))
    return {"username": "Escola · Portal Bolsa", "content": cab,
            "embeds": [{"title": "❓ " + _corta(q["pergunta"], 250), "description": opcoes + rodape,
                        "color": COR_PERGUNTA}]}, False


def mensagem_resposta(pend, sabado=False):
    certa = pend["certa"]
    letra = LETRAS[certa] if certa < len(LETRAS) else str(certa + 1)
    desc = (f"**{_corta(pend['pergunta'], 300)}**\n\n"
            f"Resposta certa: ||**{letra})** {_corta(pend['opcoes'][certa], 250)}||")
    if pend.get("explicacao"):
        desc += f"\n\nPorquê: ||{_corta(pend['explicacao'], 1200)}||"
    url = portal_url()
    if sabado:
        desc += (f"\n\n📚 Hoje é dia de **revisão semanal**: {PERGUNTAS_REVISAO_TXT} da semana para fixar a matéria"
                 + (f" em {url}/escola" if url else "") + ".")
    elif url:
        desc += f"\n\nAinda não fizeste a lição de {pend.get('dia_txt', 'ontem')}? Está em {url}/escola"
    return {"username": "Escola · Portal Bolsa",
            "embeds": [{"title": f"✅ Resposta da pergunta de {pend.get('dia_txt', 'ontem')}",
                        "description": desc, "color": COR_RESPOSTA,
                        "footer": {"text": f"Lição: {_corta(pend.get('titulo', ''), 150)} · toca nas barras pretas para ver"}}]}


PERGUNTAS_REVISAO_TXT = f"{escola.PERGUNTAS_REVISAO} perguntas"
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _enviar(payload):
    url = _webhook()
    if not url:
        raise RuntimeError("Falta WEBHOOK_ESCOLA.")
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord respondeu {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------
# ROTINA DO DIA
# ---------------------------------------------------------------
def executar(agora, manual=False):
    """Revela a resposta pendente e publica a pergunta de hoje. Devolve (ok, mensagem)."""
    with _lock:
        hoje = agora.date()
        est = estado()
        if est.get("dia_envio") == hoje.isoformat():
            return True, "Já foi enviado hoje."
        feito = []
        # 1) revelar a resposta pendente (de um dia anterior)
        pend = est.get("pendente")
        if pend and pend.get("data") != hoje.isoformat():
            idade = (hoje - date.fromisoformat(pend["data"])).days
            if 0 < idade <= MAX_ATRASO_REVELAR:
                _enviar(mensagem_resposta(pend, sabado=hoje.weekday() == 5))
                feito.append("resposta revelada")
            est["pendente"] = None
            _gravar(ARQ_ESTADO, est)
        # 2) pergunta de hoje (dias úteis)
        if hoje.weekday() <= 4:
            dados, l = licao_do_dia(hoje)
            if l:
                i, q = escolher_pergunta(l, hoje)
                payload, sondagem = mensagem_pergunta(dados, l, q)
                try:
                    _enviar(payload)
                except RuntimeError as e:
                    if not sondagem or "respondeu 400" not in str(e):
                        raise
                    # o Discord recusou a sondagem: volta a tentar como mensagem normal
                    payload, sondagem = mensagem_pergunta(dados, l, q, simples=True)
                    _enviar(payload)
                est["pendente"] = {"data": hoje.isoformat(), "dia_txt": DIAS_SEMANA[hoje.weekday()], "lid": l["id"],
                                   "titulo": l["titulo"], "indice": i, "pergunta": q["pergunta"], "opcoes": q["opcoes"],
                                   "certa": q["certa"], "explicacao": q.get("explicacao", "")}
                feito.append("pergunta publicada" + (" (sondagem)" if sondagem else ""))
            else:
                feito.append("sem lição publicada para hoje")
        est["dia_envio"] = hoje.isoformat()
        est["ultimo_envio"] = datetime.now().isoformat(timespec="seconds")
        est["envio_manual"] = manual
        est["ultimo_resultado"] = ", ".join(feito) or "nada a enviar"
        est.pop("ultimo_erro", None)
        _gravar(ARQ_ESTADO, est)
        return True, est["ultimo_resultado"].capitalize() + "."


def diario(agora):
    """Chamado pelo agendador a cada minuto (hora de Lisboa, sem fuso)."""
    cfg = config()
    if not cfg["ativo"] or not _webhook() or agora.weekday() == 6:
        return
    h, m = _hora_cfg()
    inicio = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (inicio <= agora < agora.replace(hour=HORA_FIM, minute=0, second=0, microsecond=0)):
        return
    est = estado()
    hoje = agora.date().isoformat()
    if est.get("dia_envio") == hoje:
        return
    if est.get("dia_tentativas") == hoje:
        if est.get("tentativas", 0) >= MAX_TENTATIVAS:
            return
        try:
            if datetime.now() - datetime.fromisoformat(est["ultima_tentativa"]) < timedelta(minutes=INTERVALO_MIN):
                return
        except Exception:
            pass
    else:
        est["tentativas"] = 0
    est["dia_tentativas"] = hoje
    est["tentativas"] = est.get("tentativas", 0) + 1
    est["ultima_tentativa"] = datetime.now().isoformat(timespec="seconds")
    _gravar(ARQ_ESTADO, est)
    try:
        ok, msg = executar(agora)
        print(f"[escola-discord] {msg}")
    except Exception as e:
        est = estado()
        est["ultimo_erro"] = f"{datetime.now():%d/%m %H:%M} · {str(e)[:300]}"
        _gravar(ARQ_ESTADO, est)
        print(f"[escola-discord] falhou: {e}")


# ---------------------------------------------------------------
# ÁREA DE GESTÃO
# ---------------------------------------------------------------
def painel(agora):
    hoje = agora.date()
    dados, l = licao_do_dia(hoje)
    prox = None
    if not l:  # mostra a próxima lição publicada, para o Admin ver o que vai sair
        futuras = sorted((escola.data_licao(dados, x["semana"], x["dia"]), x) for x in dados["licoes"]
                         if x.get("publicada") and x.get("quiz") and escola.data_licao(dados, x["semana"], x["dia"]) > hoje)
        if futuras:
            prox = futuras[0]
    dia_ver, l_ver = (hoje, l) if l else (prox if prox else (None, None))
    pre = None
    if l_ver:
        i, q = escolher_pergunta(l_ver, dia_ver)
        pre = {"data": dia_ver.isoformat(), "titulo": l_ver["titulo"], "pergunta": q["pergunta"], "opcoes": q["opcoes"],
               "certa": q["certa"], "sondagem": _cabe_em_sondagem(q), "hoje": dia_ver == hoje}
    est = estado()
    cfg = config()
    return {**cfg, "webhook": bool(_webhook()), "portal_url": portal_url(), "previsao": pre,
            "pendente": (est.get("pendente") or {}).get("titulo"), "dia_envio": est.get("dia_envio"),
            "ultimo_envio": est.get("ultimo_envio"), "envio_manual": est.get("envio_manual"),
            "ultimo_resultado": est.get("ultimo_resultado"), "ultimo_erro": est.get("ultimo_erro")}


def _agora():
    return (datetime.now(escola._TZ) if escola._TZ else datetime.now()).replace(tzinfo=None)


def registar(app, e_admin):
    def negado():
        if not e_admin():
            return jsonify({"erro": "Acesso negado. Apenas Admin."}), 403
        if request.method != "GET" and not escola._mesma_origem():
            return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        return None

    @app.route("/api/admin/escola/discord", methods=["GET", "POST"])
    def escola_discord_admin():
        n = negado()
        if n:
            return n
        if request.method == "POST":
            b = request.get_json(silent=True) or {}
            c = _ler(ARQ_CONFIG, {})
            if "ativo" in b:
                c["ativo"] = bool(b["ativo"])
            if "hora" in b:
                try:
                    h, m = str(b["hora"]).split(":")
                    h, m = int(h), int(m)
                    assert 6 <= h <= 21 and 0 <= m <= 59
                except Exception:
                    return jsonify({"erro": "Hora inválida: usa HH:MM entre 06:00 e 21:59."}), 400
                c["hora"] = f"{h:02d}:{m:02d}"
            _gravar(ARQ_CONFIG, c)
        return jsonify(painel(_agora()))

    @app.route("/api/admin/escola/discord/enviar", methods=["POST"])
    def escola_discord_enviar():
        n = negado()
        if n:
            return n
        if not _webhook():
            return jsonify({"erro": "Falta a variável WEBHOOK_ESCOLA no Discloud."}), 400
        try:
            ok, msg = executar(_agora(), manual=True)
            return jsonify({"sucesso": ok, "mensagem": msg})
        except Exception as e:
            est = estado()
            est["ultimo_erro"] = f"{datetime.now():%d/%m %H:%M} · {str(e)[:300]}"
            _gravar(ARQ_ESTADO, est)
            return jsonify({"erro": str(e)[:300]}), 502
