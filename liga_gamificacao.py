"""
liga_gamificacao.py — Histórico de edições, Hall of Fame e medalhas da Liga Mensal.

Como funciona:
  1. Quando um mês termina, a edição é "fechada" UMA única vez: as carteiras são pontuadas com
     os preços até ao último dia desse mês (mesma fórmula da classificação ao vivo) e o resultado
     final fica gravado em liga_historico.json. Depois disso nunca mais pede nada ao Yahoo.
  2. O Hall of Fame, as medalhas e as sequências calculam-se a partir desse histórico (zero pedidos).

Uso no main.py:
    import liga_gamificacao as gam
    gam.fechar_meses_pendentes(dados_liga, mes_atual)   # pontua meses passados ainda não fechados
    gam.calcular_hall_of_fame(user_id)                  # tudo o que a interface precisa
"""

import copy
import json
import os
import threading
from datetime import datetime

import yahoo_guard as yg

ARQUIVO_HISTORICO = "liga_historico.json"
_lock = threading.Lock()


# ---------------------------------------------------------------
# PERSISTÊNCIA
# ---------------------------------------------------------------
def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _gravar_historico(hist):
    tmp = ARQUIVO_HISTORICO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ARQUIVO_HISTORICO)


def _mes_seguinte(mes_ref):
    a, m = map(int, mes_ref.split("-"))
    return f"{a + 1}-01" if m == 12 else f"{a}-{m + 1:02d}"


# ---------------------------------------------------------------
# FECHO DE UMA EDIÇÃO (mesma fórmula de pontuação da Liga ao vivo)
# ---------------------------------------------------------------
def _pontuar_slot(s, df):
    """Devolve o slot com o resultado final. df = OHLC do mês da edição."""
    p0, alvo = float(s['p0']), float(s['alvo'])
    is_long = alvo > p0
    df = df.dropna(subset=['Close']) if df is not None and not df.empty else None
    if df is None or df.empty:
        # Sem dados: mantém o último valor conhecido da classificação ao vivo
        ret = float(s.get('ret', 0.0) or 0.0)
        bonus = float(s.get('bonus', 0.0) or 0.0)
        badge = s.get('badge', '')
        return {**s, "ret": ret, "bonus": bonus, "tocou": badge in ("✅", "🎯🔥"), "sniper": badge == "🎯🔥",
                "p_final": s.get('p_atual', p0), "direcao": "LONG" if is_long else "SHORT"}

    p_final = float(df['Close'].iloc[-1])
    max_m, min_m = float(df['High'].max()), float(df['Low'].min())
    ret = ((p_final - p0) / p0) * 100.0
    if not is_long:
        ret = -ret
    tocou = (max_m >= alvo and p_final > p0) if is_long else (min_m <= alvo and p_final < p0)
    sniper = tocou and (abs(alvo - p_final) / p_final * 100.0 <= 1.0)
    bonus = (0.5 if tocou else 0.0) + (1.0 if sniper else 0.0)
    return {
        **s, "p_final": round(p_final, 2), "ret": round(ret, 2), "bonus": bonus,
        "tocou": bool(tocou), "sniper": bool(sniper), "direcao": "LONG" if is_long else "SHORT",
        "badge": "🎯🔥" if sniper else ("✅" if tocou else ("📈" if is_long else "📉")),
    }


def _fechar_mes(mes_ref, carteiras_mes):
    carteiras = copy.deepcopy(carteiras_mes)
    tickers = sorted({s['ticker'] for c in carteiras.values() for s in c.get('slots', [])})
    dados = None
    if tickers:
        dados = yg.download(tickers, start=f"{mes_ref}-01", end=f"{_mes_seguinte(mes_ref)}-01",
                            interval="1d", group_by="ticker", usar_cache=False)

    ranking = []
    for uid, c in carteiras.items():
        slots = [_pontuar_slot(s, yg.fatia(dados, s['ticker']) if dados is not None else None) for s in c.get('slots', [])]
        retorno = round(sum(s['ret'] for s in slots) / 3.0, 2)  # igual à Liga ao vivo: média dos 3 slots
        bonus = round(sum(s['bonus'] for s in slots), 2)
        ranking.append({
            "user_id": str(c.get('user_id', uid)),
            "username": c.get('username', 'Trader'),
            "tese": c.get('tese', ''),
            "slots": slots,
            "retorno_base": retorno,
            "bonus_total": bonus,
            "score_total": round(retorno + bonus, 2),
        })
    ranking.sort(key=lambda x: x['score_total'], reverse=True)
    for i, r in enumerate(ranking, 1):
        r['posicao'] = i
    return {"mes": mes_ref, "fechado_em": datetime.now().isoformat(timespec='seconds'),
            "participantes": len(ranking), "ranking": ranking}


def fechar_meses_pendentes(dados_liga, mes_atual):
    """Fecha (uma única vez) todas as edições anteriores ao mês atual. Devolve a lista de meses
    que ficaram por fechar (ex.: Yahoo em pausa) para a interface o poder dizer."""
    if not _lock.acquire(blocking=False):
        return []  # outro pedido já está a fechar; a próxima visita vê o resultado
    pendentes = []
    try:
        hist = carregar_historico()
        alterado = False
        for mes in sorted(dados_liga):
            if mes >= mes_atual or mes in hist or not dados_liga.get(mes):
                continue
            try:
                hist[mes] = _fechar_mes(mes, dados_liga[mes])
                alterado = True
                print(f"[liga] Edição {mes} fechada: {hist[mes]['participantes']} participantes.")
            except yg.YahooIndisponivel:
                pendentes.append(mes)
                break  # não insiste com o Yahoo; tenta na próxima visita
            except Exception as e:
                print(f"[liga] Falha ao fechar {mes}: {e}")
                pendentes.append(mes)
        if alterado:
            _gravar_historico(hist)
    finally:
        _lock.release()
    return pendentes


# ---------------------------------------------------------------
# MEDALHAS
# ---------------------------------------------------------------
# Cada medalha: id, ícone, nome por nível, limiares, descrição (tooltip) e a estatística que a mede
MEDALHAS = [
    {"id": "campeao", "icone": "👑", "stat": "titulos", "niveis": [1, 3, 5],
     "nomes": ["Campeão do Mês", "Tricampeão", "Dinastia"],
     "desc": "Terminar uma edição da Liga em 1.º lugar."},
    {"id": "podio", "icone": "🏅", "stat": "podios", "niveis": [1, 5, 10],
     "nomes": ["No Pódio", "Habitué do Pódio", "Lenda do Pódio"],
     "desc": "Terminar uma edição nos 3 primeiros lugares."},
    {"id": "sequencia", "icone": "🔥", "stat": "melhor_sequencia", "niveis": [2, 3, 6],
     "nomes": ["Em Chamas", "Imparável", "Inabalável"],
     "desc": "Meses consecutivos no pódio. Basta falhar o pódio (ou faltar) num mês para a sequência recomeçar."},
    {"id": "sniper", "icone": "🎯", "stat": "sniper_hits", "niveis": [1, 3, 10],
     "nomes": ["Primeiro Tiro Certeiro", "3 Sniper Hits", "Atirador de Elite"],
     "desc": "Sniper Hit: o preço tocou no teu alvo durante o mês E fechou a menos de 1% dele. Vale +1.5% de bónus."},
    {"id": "alvos", "icone": "✅", "stat": "alvos_tocados", "niveis": [3, 10, 25],
     "nomes": ["Na Mira", "Mão Firme", "Visão de Águia"],
     "desc": "Slots em que o preço atingiu o teu preço-alvo durante o mês (+0.5% de bónus cada)."},
    {"id": "pleno", "icone": "💚", "stat": "plenos_verdes", "niveis": [1, 3, 6],
     "nomes": ["Pleno Verde", "Mãos de Ferro", "Gestor Impecável"],
     "desc": "Edição em que os 3 ativos da carteira terminaram o mês com retorno positivo."},
    {"id": "presenca", "icone": "📅", "stat": "participacoes", "niveis": [3, 6, 12],
     "nomes": ["Regular", "Veterano", "Pilar da Comunidade"],
     "desc": "Número de edições da Liga em que participaste."},
    # Medalhas únicas (só um membro as tem de cada vez)
    {"id": "shorts", "icone": "🐻", "unica": True, "nomes": ["Campeão de Shorts"],
     "desc": "O melhor retorno médio em posições SHORT (alvo abaixo da cotação), com pelo menos 3 shorts feitos. Só um membro a detém de cada vez."},
    {"id": "recorde", "icone": "💎", "unica": True, "nomes": ["Recorde Absoluto"],
     "desc": "A maior pontuação de sempre numa única edição da Liga. Só um membro a detém de cada vez."},
]
MIN_SHORTS = 3


def _estatisticas(hist):
    meses = sorted(hist)
    stats = {}

    def novo(uid, nome):
        return {"user_id": uid, "username": nome, "participacoes": 0, "titulos": 0, "podios": 0,
                "melhor_sequencia": 0, "sequencia_atual": 0, "sniper_hits": 0, "alvos_tocados": 0,
                "plenos_verdes": 0, "melhor_score": None, "mes_melhor_score": None, "soma_score": 0.0,
                "shorts": [], "longs": [], "meses": []}

    for mes in meses:
        ranking = hist[mes].get("ranking", [])
        no_podio = set()
        for r in ranking:
            uid = r["user_id"]
            s = stats.setdefault(uid, novo(uid, r["username"]))
            s["username"] = r["username"]  # usa sempre o nome mais recente
            s["participacoes"] += 1
            s["soma_score"] += r["score_total"]
            s["meses"].append({"mes": mes, "posicao": r["posicao"], "score": r["score_total"], "total": len(ranking)})
            if r["posicao"] == 1:
                s["titulos"] += 1
            if r["posicao"] <= 3:
                s["podios"] += 1
                no_podio.add(uid)
            if s["melhor_score"] is None or r["score_total"] > s["melhor_score"]:
                s["melhor_score"], s["mes_melhor_score"] = r["score_total"], mes
            slots = r.get("slots", [])
            s["sniper_hits"] += sum(1 for x in slots if x.get("sniper"))
            s["alvos_tocados"] += sum(1 for x in slots if x.get("tocou"))
            if len(slots) == 3 and all(x.get("ret", 0) > 0 for x in slots):
                s["plenos_verdes"] += 1
            for x in slots:
                (s["shorts"] if x.get("direcao") == "SHORT" else s["longs"]).append(x.get("ret", 0))
        # Sequências no pódio: quem não está no pódio (ou não participou) recomeça do zero
        for uid, s in stats.items():
            if uid in no_podio:
                s["sequencia_atual"] += 1
                s["melhor_sequencia"] = max(s["melhor_sequencia"], s["sequencia_atual"])
            else:
                s["sequencia_atual"] = 0

    for s in stats.values():
        s["media_score"] = round(s["soma_score"] / s["participacoes"], 2) if s["participacoes"] else 0
        s["media_shorts"] = round(sum(s["shorts"]) / len(s["shorts"]), 2) if s["shorts"] else None
        s["n_shorts"] = len(s["shorts"])
    return stats


def _medalhas_do_membro(s, detentores):
    resultado = []
    for m in MEDALHAS:
        if m.get("unica"):
            tem = detentores.get(m["id"]) == s["user_id"]
            if m["id"] == "shorts":
                prog = f"{min(s['n_shorts'], MIN_SHORTS)}/{MIN_SHORTS} shorts para te qualificares" if s["n_shorts"] < MIN_SHORTS else (
                    f"Média em shorts: {s['media_shorts']:+.2f}%" if s["media_shorts"] is not None else "")
            else:
                prog = f"O teu melhor: {s['melhor_score']:+.2f}%" if s["melhor_score"] is not None else ""
            resultado.append({"id": m["id"], "icone": m["icone"], "nome": m["nomes"][0], "nivel": 1 if tem else 0,
                              "niveis_total": 1, "desbloqueada": tem, "progresso": prog, "desc": m["desc"], "unica": True})
            continue
        valor = s.get(m["stat"], 0)
        nivel = sum(1 for lim in m["niveis"] if valor >= lim)
        proximo = next((lim for lim in m["niveis"] if valor < lim), None)
        nome = m["nomes"][nivel - 1] if nivel else m["nomes"][0]
        prog = f"{valor}/{proximo} para «{m['nomes'][m['niveis'].index(proximo)]}»" if proximo is not None else f"{valor} — nível máximo atingido!"
        resultado.append({"id": m["id"], "icone": m["icone"], "nome": nome, "nivel": nivel, "niveis_total": len(m["niveis"]),
                          "desbloqueada": nivel > 0, "progresso": prog, "desc": m["desc"], "valor": valor, "unica": False})
    return resultado


def calcular_hall_of_fame(user_id=None):
    hist = carregar_historico()
    stats = _estatisticas(hist)
    user_id = str(user_id) if user_id is not None else None

    # Detentores das medalhas únicas
    detentores = {}
    elegiveis_shorts = [s for s in stats.values() if s["n_shorts"] >= MIN_SHORTS and (s["media_shorts"] or 0) > 0]
    if elegiveis_shorts:
        detentores["shorts"] = max(elegiveis_shorts, key=lambda s: s["media_shorts"])["user_id"]
    com_score = [s for s in stats.values() if s["melhor_score"] is not None]
    if com_score:
        detentores["recorde"] = max(com_score, key=lambda s: s["melhor_score"])["user_id"]

    geral = []
    icones = {}
    for s in stats.values():
        meds = _medalhas_do_membro(s, detentores)
        desbloqueadas = [m for m in meds if m["desbloqueada"]]
        icones[s["user_id"]] = "".join(m["icone"] for m in desbloqueadas)
        geral.append({
            "user_id": s["user_id"], "username": s["username"], "participacoes": s["participacoes"],
            "titulos": s["titulos"], "podios": s["podios"], "melhor_sequencia": s["melhor_sequencia"],
            "sequencia_atual": s["sequencia_atual"], "sniper_hits": s["sniper_hits"], "alvos_tocados": s["alvos_tocados"],
            "media_score": s["media_score"], "melhor_score": s["melhor_score"],
            "n_medalhas": len(desbloqueadas), "icones": icones[s["user_id"]],
        })
    geral.sort(key=lambda g: (-g["titulos"], -g["podios"], -g["media_score"]))

    def destaque(chave, filtro=lambda s: True):
        cands = [s for s in stats.values() if filtro(s)]
        if not cands:
            return None
        # Desempate justo: mais pódios, depois melhor média
        top = max(cands, key=lambda s: (s[chave] if s[chave] is not None else -1e9, s["podios"], s["media_score"]))
        return {"username": top["username"], "valor": top[chave], "user_id": top["user_id"],
                "extra": top.get("mes_melhor_score") if chave == "melhor_score" else None}

    recordes = {
        "recorde_absoluto": destaque("melhor_score", lambda s: s["melhor_score"] is not None),
        "mais_titulos": destaque("titulos", lambda s: s["titulos"] > 0),
        "maior_sequencia": destaque("melhor_sequencia", lambda s: s["melhor_sequencia"] > 0),
        "rei_snipers": destaque("sniper_hits", lambda s: s["sniper_hits"] > 0),
        "campeao_shorts": None,
    }
    if "shorts" in detentores:
        s = stats[detentores["shorts"]]
        recordes["campeao_shorts"] = {"username": s["username"], "valor": s["media_shorts"], "user_id": s["user_id"], "extra": s["n_shorts"]}

    edicoes = []
    for mes in sorted(hist, reverse=True):
        h = hist[mes]
        edicoes.append({"mes": mes, "participantes": h.get("participantes", 0), "fechado_em": h.get("fechado_em"),
                        "ranking": h.get("ranking", [])})

    minhas = None
    if user_id:
        s = stats.get(user_id)
        if s:
            minhas = {"medalhas": _medalhas_do_membro(s, detentores), "stats": next(g for g in geral if g["user_id"] == user_id),
                      "historico": s["meses"]}
        else:
            vazio = {"user_id": user_id, "n_shorts": 0, "media_shorts": None, "melhor_score": None,
                     **{m["stat"]: 0 for m in MEDALHAS if "stat" in m}}
            minhas = {"medalhas": _medalhas_do_membro(vazio, detentores), "stats": None, "historico": []}

    return {"edicoes": edicoes, "geral": geral, "recordes": recordes, "minhas": minhas, "icones": icones,
            "catalogo": [{"id": m["id"], "icone": m["icone"], "nomes": m["nomes"], "niveis": m.get("niveis"), "desc": m["desc"]} for m in MEDALHAS]}
