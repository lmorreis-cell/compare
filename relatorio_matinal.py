"""
relatorio_matinal.py — Briefing Matinal automático para o Discord.

Constrói a mensagem a partir do Snapshot diário (zero pedidos ao Yahoo) e envia-a para o
webhook definido na variável de ambiente WEBHOOK_RELATORIO (ou, se não existir, WEBHOOK_SNIPER).

Uso:
    import relatorio_matinal as rel
    rel.construir_relatorio()        # devolve o payload (para pré-visualizar)
    rel.enviar_relatorio()           # envia (no máximo 1 vez por dia, salvo forcar=True)
"""

import json
import os
from datetime import datetime

import requests

import snapshot_diario as snap

ARQUIVO_ESTADO = os.path.join(snap.PASTA, "estado_relatorio.json")
DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _webhook():
    return os.environ.get("WEBHOOK_RELATORIO") or os.environ.get("WEBHOOK_SNIPER")


def _ler_estado():
    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _gravar_estado(est):
    os.makedirs(snap.PASTA, exist_ok=True)
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False)


def estado():
    est = _ler_estado()
    est["webhook_configurado"] = bool(_webhook())
    est["webhook_dedicado"] = bool(os.environ.get("WEBHOOK_RELATORIO"))
    return est


def _pct(v):
    if v is None:
        return "N/A"
    seta = "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")
    return f"{seta} {v:+.2f}%"


def _data_curta(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m")
    except Exception:
        return iso or "?"


def _juntar_sinais(universos):
    """Junta os sinais do S&P 500 e do Nasdaq 100 sem repetir tickers. Fundamentos limpos primeiro,
    depois os de maior força relativa (Mansfield)."""
    juntos = {est: {} for est in snap.ESTRATEGIAS}
    ativos = {}
    for u in universos:
        if not u:
            continue
        ativos.update(u.get("ativos", {}))
        for est in snap.ESTRATEGIAS:
            for s in u.get("sinais", {}).get(est, []):
                juntos[est].setdefault(s["ticker"], s)
    ordenados = {}
    for est, d in juntos.items():
        ordenados[est] = sorted(d.values(), key=lambda s: (s.get("is_toxic", False), -((ativos.get(s["ticker"], {}) or {}).get("mansfield") or -999)))
    return ordenados, ativos


def _linhas_setup(sinais, ativos, maximo=5):
    if not sinais:
        return "Nenhum ativo cumpre os critérios hoje. Mantém-te líquido."
    linhas = []
    for s in sinais[:maximo]:
        a = ativos.get(s["ticker"], {}) or {}
        selo = "⚠️" if s.get("is_toxic") else "✅"
        rsi = f" · RSI {a['rsi']:.0f}" if a.get("rsi") is not None else ""
        linhas.append(f"{selo} **{s['ticker']}** ${s['preco']:.2f}{rsi}")
    if len(sinais) > maximo:
        linhas.append(f"*+{len(sinais) - maximo} no Screener do Terminal*")
    return "\n".join(linhas)


def _linha_track(tr, est):
    if not tr or not tr.get("s5"):
        return ""
    s5 = tr["s5"]
    if est == "squeeze":
        return f"\n📊 *Histórico: movimento médio de ±{s5['media_abs']:.1f}% em 5 sessões ({s5['n']} sinais/ano)*"
    return f"\n📊 *Histórico: {s5['media']:+.2f}% em 5 sessões, {s5['taxa_acerto']:.0f}% positivos ({s5['n']} sinais/ano)*"


def construir_relatorio():
    """Monta o payload do Discord. Devolve (payload, erro)."""
    macro = snap.carregar("macro")
    if not snap.esta_fresco(macro):
        return None, "Ainda não existe uma fotografia diária recente do mercado (snapshot)."

    sp500 = snap.carregar("sp500")
    ndx = snap.carregar("ndx")
    universos = [u for u in (sp500, ndx) if snap.esta_fresco(u)]

    hoje = datetime.now()
    titulo = f"☀️ Briefing Matinal — {DIAS_SEMANA[hoje.weekday()]}, {hoje.day} de {MESES[hoje.month - 1]}"

    # 1. Mercados no fecho
    linhas_idx = []
    for i in macro.get("indices", []):
        if i["ticker"] == "^VIX":
            continue
        preco = f"{i['preco']:,.2f}".replace(",", " ")
        linhas_idx.append(f"**{i['nome']}** `{preco}` {_pct(i['var'])}")
    descricao = f"**Fecho de {_data_curta(macro.get('data_mercado'))}**\n" + "\n".join(linhas_idx)

    # 2. Saúde do mercado (mesma leitura do painel Market Breadth do Terminal)
    b = macro.get("breadth", {})
    bull, total = b.get("acima_ema50", 0), b.get("total", 11)
    if bull >= 8:
        txt_breadth, cor = "Saúde estrutural **robusta**: a maré institucional favorece setups de compra.", 6076508  # verde
    elif bull >= 4:
        txt_breadth, cor = "Regime **misto**: liderança dividida, exige seletividade e proteção cedo dos lucros.", 15773006
    else:
        txt_breadth, cor = "**Fraqueza estrutural**: prioridade à preservação de capital.", 14242639

    vix = macro.get("vix") or {}
    v = vix.get("preco")
    if v is None:
        txt_vix = ""
    elif v > 25:
        txt_vix = f"\n🌋 VIX em **{v:.2f}** ({vix.get('var', 0):+.1f}%): stress sistémico — corta o tamanho das posições e alarga os stops."
    elif v > 18:
        txt_vix = f"\n⚠️ VIX em **{v:.2f}** ({vix.get('var', 0):+.1f}%): prémio de volatilidade ativo — respeita os stops."
    else:
        txt_vix = f"\n😌 VIX em **{v:.2f}** ({vix.get('var', 0):+.1f}%): volatilidade contida."

    campos = [{
        "name": "🧭 Saúde do Mercado",
        "value": f"**{bull}/{total}** setores acima da EMA 50. {txt_breadth}{txt_vix}",
        "inline": False,
    }]

    # 3. Rotação setorial
    quadrantes = {"Líderes": [], "A Melhorar": [], "A Enfraquecer": [], "Atrasados": []}
    for r in macro.get("rrg", []):
        quadrantes.setdefault(r["quadrante"], []).append(r["setor"])
    icones = {"Líderes": "🟢", "A Melhorar": "🔵", "A Enfraquecer": "🟡", "Atrasados": "🔴"}
    linhas_rrg = [f"{icones[q]} **{q}:** {', '.join(s) if s else '—'}" for q, s in quadrantes.items() if q in icones]
    if linhas_rrg:
        campos.append({"name": "🌀 Rotação Setorial (21 dias)", "value": "\n".join(linhas_rrg), "inline": False})

    # 4. Setups do dia
    if universos:
        sinais, ativos = _juntar_sinais(universos)
        tr_ref = (universos[0].get("track_record") or {})
        nomes = {"pullback": "📉 Pullback Tático (EMA 20)", "squeeze": "🗜️ Bollinger Squeeze", "oversold": "🩸 Capitulação (RSI < 30)"}
        for est in snap.ESTRATEGIAS:
            valor = _linhas_setup(sinais[est], ativos) + _linha_track(tr_ref.get(est), est)
            campos.append({"name": nomes[est], "value": valor[:1024], "inline": True})

        # 5. Força relativa
        ref = universos[0]
        rk = ref.get("rankings", {})
        maximos = rk.get("novos_max52", [])
        nome_ref = "S&P 500" if ref.get("universo") == "sp500" else "Nasdaq 100"
        txt_forca = f"**{len(maximos)}** ativos do {nome_ref} em novos máximos de 52 semanas"
        if maximos:
            txt_forca += f" ({', '.join(maximos[:6])}{'…' if len(maximos) > 6 else ''})"
        if rk.get("top_mansfield"):
            txt_forca += f"\n🏅 Maior força relativa: {', '.join(rk['top_mansfield'][:5])}"
        campos.append({"name": "🚀 Força Relativa", "value": txt_forca[:1024], "inline": False})

    payload = {
        "embeds": [{
            "title": titulo,
            "color": cor,
            "description": descricao[:4000],
            "fields": campos[:25],
            "footer": {"text": "Portal Bolsa · Briefing automático · ✅ fundamentos limpos ⚠️ alertas fundamentais · Informação educativa, não é recomendação de investimento"},
        }]
    }
    return payload, None


def enviar_relatorio(forcar=False):
    """Envia o briefing. Devolve (sucesso, mensagem)."""
    url = _webhook()
    if not url:
        return False, "Webhook não configurado. Define WEBHOOK_RELATORIO nas Variáveis da Discloud."

    est = _ler_estado()
    hoje = datetime.now().strftime("%Y-%m-%d")
    if not forcar and est.get("dia_envio") == hoje:
        return False, "O briefing de hoje já foi enviado."

    payload, erro = construir_relatorio()
    if erro:
        return False, erro

    macro = snap.carregar("macro") or {}
    if not forcar and est.get("data_mercado_enviada") == macro.get("data_mercado"):
        # Ex.: feriado nos EUA — não repete o mesmo briefing duas manhãs seguidas
        est["dia_envio"] = hoje
        _gravar_estado(est)
        return False, "Sem sessão nova desde o último briefing (feriado?). Envio ignorado."

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        est["ultimo_erro"] = f"{datetime.now().isoformat(timespec='seconds')}: {e}"
        _gravar_estado(est)
        return False, f"Falha ao enviar para o Discord: {e}"

    est.update({
        "dia_envio": hoje,
        "ultimo_envio": datetime.now().isoformat(timespec='seconds'),
        "data_mercado_enviada": macro.get("data_mercado"),
    })
    _gravar_estado(est)
    return True, "Briefing Matinal enviado para o Discord."
