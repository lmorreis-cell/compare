"""
liga_avisos.py — Avisos automáticos da Liga Mensal no Discord (chamado pelo agendador a cada minuto).

Quatro avisos por edição, cada um enviado UMA única vez (fica registado em liga_avisos.json):
  1. abertura  → "Inscrições abertas" (no dia em que a janela abre, a partir das 10:00)
  2. ultimo_dia → "Último dia para inscrições" (no dia do fecho, a partir das 10:00)
  3. nevoeiro  → "O nevoeiro levantou" com as carteiras reveladas (no dia a seguir ao fecho)
  4. resumo    → resumo da edição terminada: pódio, prémios e destaques (quando o mês acaba)

Travões de segurança:
  - Só envia entre as 10:00 e as 21:59 (hora de Lisboa): nada de avisos de madrugada.
  - Avisos com mais de 2 dias de atraso são marcados como enviados sem enviar (ex.: servidor desligado).
  - Na primeira execução marca como "já enviado" tudo o que já devia ter acontecido (não repete o passado).
  - Usa o webhook WEBHOOK_LIGA (ou WEBHOOK_SNIPER se esse não existir).
  - LIGA_AVISOS_ATIVO=0 desliga tudo.
"""

import json
import os
import threading
from datetime import datetime, timedelta

import requests

import liga_janelas as lj
import liga_gamificacao as gam

ARQ_AVISOS = "liga_avisos.json"
HORA_INICIO, HORA_FIM = 10, 22
ATRASO_MAX_DIAS = 2
_lock = threading.Lock()

COR = {"abertura": 3066993, "ultimo_dia": 15105570, "nevoeiro": 5793266, "resumo": 15844367}


def _carregar_estado():
    if os.path.exists(ARQ_AVISOS):
        try:
            with open(ARQ_AVISOS, "r", encoding="utf-8") as f:
                e = json.load(f)
                e.setdefault("enviados", {})
                return e
        except Exception:
            pass
    return None


def _gravar_estado(e):
    tmp = ARQ_AVISOS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ARQ_AVISOS)


def _carteiras():
    try:
        with open(lj.ARQ_LIGA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _webhook():
    return os.environ.get("WEBHOOK_LIGA") or os.environ.get("WEBHOOK_SNIPER")


def _ddmm(d):
    return d.strftime("%d/%m")


# ---------------------------------------------------------------
# QUE AVISOS DEVIAM EXISTIR HOJE
# ---------------------------------------------------------------
def _eventos(hoje, cfg):
    """Lista de (chave, tipo, edicao, data_prevista) para as edições à volta de hoje."""
    atual = lj.edicao_em_curso(datetime.combine(hoje, datetime.min.time()))
    eds = [lj.mes_anterior(atual), atual, lj.mes_seguinte(atual)]
    out = []
    for ed in eds:
        ini, fim, _ = lj.janela(ed, cfg)
        out.append((f"abertura:{ed}", "abertura", ed, ini))
        if fim > ini:
            out.append((f"ultimo_dia:{ed}", "ultimo_dia", ed, fim))
        out.append((f"nevoeiro:{ed}", "nevoeiro", ed, fim + timedelta(days=1)))
        out.append((f"resumo:{ed}", "resumo", ed, lj.ultimo_dia(ed) + timedelta(days=1)))
    return out


# ---------------------------------------------------------------
# MENSAGENS
# ---------------------------------------------------------------
def _msg_abertura(ed, cfg):
    ini, fim, _ = lj.janela(ed, cfg)
    return {
        "title": f"🟢 Liga Mensal: inscrições abertas para {lj.nome_edicao(ed)}",
        "description": (
            f"Já podes registar a tua carteira de 3 ativos até **{_ddmm(fim)} às 23:59**.\n\n"
            "📍 **Entras ao preço do momento em que gravas.** Podes alterar a carteira até ao fecho; conta sempre a última versão.\n"
            "🌫️ Até ao fecho, as carteiras dos outros ficam ocultas.\n"
            f"🏁 A edição conta até ao fecho de {lj.ultimo_dia(ed).strftime('%d/%m')}.\n\n"
            "➡️ Terminal → separador **Liga**"),
    }


def _msg_ultimo_dia(ed, cfg, carteiras):
    _ini, fim, _ = lj.janela(ed, cfg)
    n = len(carteiras.get(ed, {}) or {})
    return {
        "title": f"⏰ Último dia: inscrições para {lj.nome_edicao(ed)} fecham hoje",
        "description": (
            f"As inscrições fecham **hoje ({_ddmm(fim)}) às 23:59**. Já há **{n} carteira{'s' if n != 1 else ''}** em prova.\n\n"
            "Ainda vais a tempo de entrar ou de afinar a tua carteira. Amanhã o nevoeiro levanta e todas as carteiras ficam visíveis.\n\n"
            "➡️ Terminal → separador **Liga**"),
    }


def _msg_nevoeiro(ed, carteiras):
    cs = sorted((carteiras.get(ed, {}) or {}).values(), key=lambda c: c.get("username", "").lower())
    if not cs:
        return None
    linhas = []
    for c in cs[:25]:
        ativos = " · ".join(
            f"{s['ticker']} {'📈' if float(s['alvo']) > float(s['p0']) else '📉'}" for s in c.get("slots", []))
        linhas.append(f"**{c.get('username', 'Membro')}**: {ativos}")
    if len(cs) > 25:
        linhas.append(f"… e mais {len(cs) - 25}.")
    return {
        "title": f"🌤️ O nevoeiro levantou: as {len(cs)} carteiras de {lj.nome_edicao(ed)}",
        "description": ("\n".join(linhas) +
                        "\n\n📈 LONG (alvo acima da entrada) · 📉 SHORT (alvo abaixo).\n"
                        "As teses completas e a classificação ao vivo estão no separador **Liga**."),
    }


def _msg_resumo(ed):
    hist = gam.carregar_historico()
    h = hist.get(ed)
    if not h or not h.get("ranking"):
        return None
    rk = h["ranking"]
    med = ["🥇", "🥈", "🥉"]
    podio = "\n".join(f"{med[i]} **{r['username']}** {r['score_total']:+.2f}%" for i, r in enumerate(rk[:3]))
    campos = [{"name": "🏆 Pódio", "value": podio, "inline": False}]

    slots = [(r["username"], s) for r in rk for s in r.get("slots", [])]
    if slots:
        best = max(slots, key=lambda x: x[1].get("ret", 0))
        worst = min(slots, key=lambda x: x[1].get("ret", 0))
        campos.append({"name": "🚀 Melhor ativo", "value": f"{best[1]['ticker']} {best[1]['ret']:+.2f}% ({best[0]})", "inline": True})
        campos.append({"name": "🧊 Pior ativo", "value": f"{worst[1]['ticker']} {worst[1]['ret']:+.2f}% ({worst[0]})", "inline": True})
    alvos = sum(1 for _, s in slots if s.get("tocou"))
    snipers = [u for u, s in slots if s.get("sniper")]
    campos.append({"name": "🎯 Alvos", "value": f"{alvos} alvo{'s' if alvos != 1 else ''} atingido{'s' if alvos != 1 else ''}"
                   + (f" · Sniper Hit: {', '.join(sorted(set(snipers)))}" if snipers else ""), "inline": False})
    prud = next((r for r in rk if r.get("premio_prudente")), None)
    if prud:
        campos.append({"name": "🛡️ Gestor Prudente", "value": f"**{prud['username']}**: eficiência {prud.get('eficiencia', 0):.2f} "
                       f"(score ÷ queda máxima de {prud.get('queda_max', 0):.1f}%)", "inline": False})
    com_alfa = [r for r in rk if r.get("alfa") is not None]
    if com_alfa:
        bateram = [r for r in com_alfa if r["alfa"] > 0]
        campos.append({"name": "📊 vs S&P 500", "value": f"{len(bateram)} de {len(com_alfa)} carteiras bateram o S&P 500 no mesmo período.", "inline": False})

    # Temporada: líder após esta edição
    temp = gam.calcular_temporadas(hist).get(ed[:4]) or []
    if temp:
        lider = temp[0]
        campos.append({"name": f"🏁 Temporada {ed[:4]}", "value": f"Líder: **{lider['username']}** com {lider['pontos']} pts", "inline": False})

    return {
        "title": f"🏁 Fim da edição de {lj.nome_edicao(ed)}: {h.get('participantes', len(rk))} participantes",
        "description": "Resultados finais (fecho do último dia do mês). As medalhas já estão atribuídas no Hall of Fame.",
        "fields": campos,
    }


def _enviar(tipo, embed):
    url = _webhook()
    if not url:
        return False, "sem webhook (define WEBHOOK_LIGA)"
    embed = {**embed, "color": COR.get(tipo, 15844367),
             "footer": {"text": "Portal Bolsa · Liga Mensal · conteúdo educativo, não é recomendação de investimento"}}
    try:
        r = requests.post(url, json={"username": "Liga Mensal", "embeds": [embed]}, timeout=15)
        return (r.status_code < 300), f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------
# CICLO (chamado pelo agendador)
# ---------------------------------------------------------------
def verificar(agora):
    """agora = hora de Lisboa (naive). Devolve a lista de avisos enviados nesta passagem."""
    if os.environ.get("LIGA_AVISOS_ATIVO", "1") == "0":
        return []
    if not _lock.acquire(blocking=False):
        return []
    try:
        hoje = agora.date()
        cfg = lj.carregar_config()
        estado = _carregar_estado()
        eventos = _eventos(hoje, cfg)

        if estado is None:
            # Primeira execução: não repete o passado (marca o que já devia ter acontecido)
            estado = {"enviados": {}, "criado_em": agora.isoformat(timespec="seconds")}
            for chave, _t, _e, data in eventos:
                if data <= hoje:
                    estado["enviados"][chave] = "ignorado (anterior à ativação dos avisos)"
            _gravar_estado(estado)
            return []

        if not (HORA_INICIO <= agora.hour < HORA_FIM):
            return []

        enviados = []
        carteiras = None
        for chave, tipo, ed, data in eventos:
            if chave in estado["enviados"] or data > hoje:
                continue
            if (hoje - data).days > ATRASO_MAX_DIAS:
                estado["enviados"][chave] = "ignorado (atrasado)"
                _gravar_estado(estado)
                continue
            if carteiras is None:
                carteiras = _carteiras()

            if tipo == "abertura":
                embed = _msg_abertura(ed, cfg)
            elif tipo == "ultimo_dia":
                embed = _msg_ultimo_dia(ed, cfg, carteiras)
            elif tipo == "nevoeiro":
                embed = _msg_nevoeiro(ed, carteiras)
                if embed is None:
                    estado["enviados"][chave] = "sem carteiras"
                    _gravar_estado(estado)
                    continue
            else:  # resumo: garante que a edição está fechada (1 download, uma única vez)
                if ed not in gam.carregar_historico() and (carteiras.get(ed) or {}):
                    gam.fechar_meses_pendentes(carteiras, lj.edicao_em_curso(agora))
                if ed not in gam.carregar_historico():
                    if not (carteiras.get(ed) or {}):
                        estado["enviados"][chave] = "sem carteiras"
                        _gravar_estado(estado)
                    continue  # Yahoo em pausa: tenta no minuto seguinte
                embed = _msg_resumo(ed)
                if embed is None:
                    estado["enviados"][chave] = "sem resultados"
                    _gravar_estado(estado)
                    continue

            ok, info = _enviar(tipo, embed)
            if ok:
                estado["enviados"][chave] = agora.isoformat(timespec="seconds")
                estado["ultimo_envio"] = {"chave": chave, "em": agora.isoformat(timespec="seconds")}
                estado.pop("ultimo_erro", None)
                enviados.append(chave)
                print(f"[liga-avisos] Enviado: {chave}")
            else:
                estado["ultimo_erro"] = {"chave": chave, "em": agora.isoformat(timespec="seconds"), "erro": info}
                print(f"[liga-avisos] Falhou {chave}: {info}")
            _gravar_estado(estado)
            if not ok:
                break  # tenta de novo no minuto seguinte
        return enviados
    finally:
        _lock.release()


def resumo_estado(agora):
    """Para a Área de Gestão: próximos avisos e último envio."""
    estado = _carregar_estado() or {"enviados": {}}
    cfg = lj.carregar_config()
    hoje = agora.date()
    nomes = {"abertura": "Inscrições abertas", "ultimo_dia": "Último dia de inscrições",
             "nevoeiro": "Nevoeiro levantou", "resumo": "Resumo da edição"}
    proximos = []
    for chave, tipo, ed, data in sorted(_eventos(hoje, cfg), key=lambda e: e[3]):
        if chave in estado["enviados"] or data < hoje:
            continue
        proximos.append({"chave": chave, "nome": f"{nomes[tipo]} · {lj.nome_edicao(ed)}", "data": data.isoformat()})
    return {
        "ativo": os.environ.get("LIGA_AVISOS_ATIVO", "1") != "0",
        "webhook": bool(_webhook()),
        "proximos": proximos[:4],
        "ultimo_envio": estado.get("ultimo_envio"),
        "ultimo_erro": estado.get("ultimo_erro"),
        "janela_horaria": f"{HORA_INICIO:02d}:00–{HORA_FIM - 1:02d}:59",
    }
