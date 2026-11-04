"""
relatorio_semanal.py — Briefing Semanal (sábado de manhã) para o Discord.

Junta numa só mensagem a semana do portal:
    1. A semana nos mercados  → índices e setores (variação de sexta a sexta)
    2. Rotação setorial       → quadrantes do RRG (da fotografia diária)
    3. Sinais do Screener     → os setups que apareceram esta semana e como se portaram desde então
    4. Liga Mensal            → pódio ao vivo, inscrições e líder da temporada
    5. Escola                 → lições da semana e a revisão de sábado

Pedidos ao Yahoo: UM só por semana (índices + 11 setores, 1 mês de histórico). Se o Yahoo estiver
em pausa, usa só a fotografia diária e avisa no rodapé.

Webhook: WEBHOOK_SEMANAL (ou, se não existir, WEBHOOK_RELATORIO; depois WEBHOOK_SNIPER).
Envio automático: sábados às HORA_SEMANAL (por omissão 10:00, Lisboa), pelo agendador.py.
"""

import json
import os
import time
from datetime import datetime, timedelta, date

import requests

import snapshot_diario as snap
import yahoo_guard as yg

ARQUIVO_ESTADO = os.path.join(snap.PASTA, "estado_relatorio_semanal.json")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
NOMES_SETUP = {"pullback": "📉 Pullback", "squeeze": "🗜️ Squeeze", "oversold": "🩸 Capitulação"}


def _webhook():
    return os.environ.get("WEBHOOK_SEMANAL") or os.environ.get("WEBHOOK_RELATORIO") or os.environ.get("WEBHOOK_SNIPER")


def hora_envio():
    try:
        h, m = (int(x) for x in os.environ.get("HORA_SEMANAL", "10:00").split(":"))
        return h, m
    except Exception:
        return 10, 0


def _ler_estado():
    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _gravar_estado(est):
    os.makedirs(snap.PASTA, exist_ok=True)
    tmp = ARQUIVO_ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False)
    os.replace(tmp, ARQUIVO_ESTADO)


def _semana_id(d):
    a, s, _ = d.isocalendar()
    return f"{a}-S{s:02d}"


def estado():
    est = _ler_estado()
    est["webhook_configurado"] = bool(_webhook())
    est["webhook_dedicado"] = bool(os.environ.get("WEBHOOK_SEMANAL"))
    est["hora_envio"] = "%02d:%02d" % hora_envio()
    return est


def _pct(v, casas=2):
    if v is None:
        return "N/A"
    seta = "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")
    return f"{seta} {v:+.{casas}f}%"


# ------------------------------------------------------------------ 1. mercados
def _variacoes_semana():
    """{ticker: (fecho, variação desde a sexta anterior)} com um único pedido ao Yahoo."""
    tickers = list(snap.INDICES) + list(snap.SETORES_USA)
    dados = yg.download(tickers, period="1mo", interval="1d", group_by="ticker", usar_cache=False)
    out = {}
    for t in tickers:
        try:
            c = yg.fatia(dados, t)["Close"].dropna()
            if len(c) < 3:
                continue
            ultimo_dia = c.index[-1]
            base = c[c.index <= ultimo_dia - timedelta(days=7)]
            if base.empty:
                continue
            out[t] = (float(c.iloc[-1]), (float(c.iloc[-1]) / float(base.iloc[-1]) - 1) * 100)
        except Exception:
            continue
    return out


def _campo_mercados(var):
    linhas = []
    for t, nome in snap.INDICES.items():
        if t in var and t != "^VIX":
            preco, v = var[t]
            p = f"{preco:,.2f}".replace(",", " ")
            linhas.append(f"**{nome}** `{p}` {_pct(v)}")
    if "^VIX" in var:
        preco, v = var["^VIX"]
        estado = "stress elevado" if preco > 25 else ("volatilidade ativa" if preco > 18 else "volatilidade contida")
        linhas.append(f"**VIX** `{preco:.2f}` ({v:+.1f}% na semana) · {estado}")
    return "\n".join(linhas)


def _campo_setores(var):
    sets = [(snap.SETORES_USA[t], var[t][1]) for t in snap.SETORES_USA if t in var]
    if len(sets) < 4:
        return None
    sets.sort(key=lambda x: -x[1])
    melhores = " · ".join(f"{n} {v:+.1f}%" for n, v in sets[:3])
    piores = " · ".join(f"{n} {v:+.1f}%" for n, v in sets[-3:][::-1])
    positivos = sum(1 for _, v in sets if v > 0)
    return f"🟢 **Melhores:** {melhores}\n🔴 **Piores:** {piores}\n**{positivos}/{len(sets)}** setores subiram na semana."


# ------------------------------------------------------------------ 3. sinais
def _campo_sinais(hoje):
    """Sinais que surgiram nesta semana (S&P 500 + Nasdaq 100) e o retorno desde o sinal."""
    inicio_semana = (hoje - timedelta(days=hoje.weekday())).isoformat()
    linhas = []
    for est in snap.ESTRATEGIAS:
        vistos = {}
        for u in ("sp500", "ndx"):
            d = snap.carregar(u)
            if not snap.esta_fresco(d):
                continue
            for e in (d.get("track_record", {}).get(est, {}) or {}).get("recentes", []):
                if e.get("data", "") >= inicio_semana and e.get("desde") is not None:
                    vistos.setdefault(e["ticker"], e)
        if not vistos:
            linhas.append(f"{NOMES_SETUP[est]}: nenhum sinal novo esta semana.")
            continue
        evs = sorted(vistos.values(), key=lambda e: -e["desde"])
        media = sum(e["desde"] for e in evs) / len(evs)
        positivos = sum(1 for e in evs if e["desde"] > 0)
        melhor = evs[0]
        if est == "squeeze":
            amp = sum(abs(e["desde"]) for e in evs) / len(evs)
            linhas.append(f"{NOMES_SETUP[est]}: **{len(evs)}** {'sinal' if len(evs) == 1 else 'sinais'} · movimento médio ±{amp:.1f}% desde o sinal "
                          f"(maior: {melhor['ticker']} {melhor['desde']:+.1f}%)")
        else:
            linhas.append(f"{NOMES_SETUP[est]}: **{len(evs)}** {'sinal' if len(evs) == 1 else 'sinais'} · média {media:+.1f}% desde o sinal · "
                          f"{positivos}/{len(evs)} positivos (melhor: {melhor['ticker']} {melhor['desde']:+.1f}%)")
    return "\n".join(linhas) + "\n*Retorno desde o fecho do dia do sinal até ontem. Resultados passados não garantem resultados futuros.*"


# ------------------------------------------------------------------ 4. liga
def _campo_liga(agora):
    try:
        import liga_janelas as lj
        import liga_gamificacao as gam
        with open(lj.ARQ_LIGA, "r", encoding="utf-8") as f:
            liga = json.load(f)
    except Exception:
        return None
    ed = lj.edicao_em_curso(agora)
    cs = sorted((liga.get(ed) or {}).values(), key=lambda c: -(c.get("score_total") or 0))
    partes = []
    if cs:
        med = ["🥇", "🥈", "🥉"]
        partes.append(f"**Edição de {lj.nome_edicao(ed)}** · {len(cs)} carteiras\n" +
                      "\n".join(f"{med[i]} {c.get('username')} {float(c.get('score_total') or 0):+.2f}%" for i, c in enumerate(cs[:3])))
    ins = lj.edicao_inscricao(agora)
    if ins:
        _i, fim, _o = lj.janela(ins)
        partes.append(f"🟢 Inscrições abertas para **{lj.nome_edicao(ins)}** até {fim.strftime('%d/%m')}.")
    else:
        prox = lj.proxima_janela(agora)
        if prox:
            partes.append(f"📅 Próximas inscrições ({lj.nome_edicao(prox[0])}): {prox[1].strftime('%d/%m')} a {prox[2].strftime('%d/%m')}.")
    temp = gam.calcular_temporadas(gam.carregar_historico()).get(str(agora.year)) or []
    if temp:
        partes.append(f"🏁 Temporada {agora.year}: lidera **{temp[0]['username']}** com {temp[0]['pontos']} pts.")
    return "\n".join(partes) if partes else None


# ------------------------------------------------------------------ 5. escola
def _campo_escola(hoje):
    try:
        import escola
        dados = escola.carregar()
        inicio = escola._inicio(dados)
    except Exception:
        return None
    semana = (hoje - inicio).days // 7 + 1
    if semana < 1 or semana > 52:
        return None
    licoes = [l for l in dados["licoes"] if l["semana"] == semana and l.get("publicada")
              and escola.data_licao(dados, l["semana"], l["dia"]) <= hoje]
    if not licoes:
        return None
    tema = escola._tema(dados, semana).get("tema", "")
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex"]
    txt = (f"**Semana {semana}**" + (f" · {tema}" if tema else "") + "\n" +
           "\n".join(f"• {dias[l['dia'] - 1]}: {l['titulo']}" for l in sorted(licoes, key=lambda l: l["dia"])))
    if escola.data_revisao(dados, semana) <= hoje:
        txt += "\n📝 **A revisão da semana já está disponível**, com perguntas sobre as lições acima."
    return txt + "\n➡️ Portal → 🎓 Escola"


# ------------------------------------------------------------------ montagem
def _campo_macro_oficial():
    """Curva dos EUA (Tesouro), extremos de posicionamento (CFTC) e ciclo (OCDE). Só lê cópias locais."""
    try:
        import fontes_mundo
        d = fontes_mundo.painel()
    except Exception:
        return ""
    linhas = []
    t = d.get("tesouro") or {}
    s3 = (t.get("spreads") or {}).get("10A-3M")
    if t.get("sinal") and s3:
        ic = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}[t["sinal"]["cor"]]
        linhas.append(f"{ic} **Curva dos EUA (10a − 3m):** {s3['atual']:+.2f}".replace(".", ",") + f" p.p. ({'invertida' if s3['invertida'] else 'positiva'})")
    rec = t.get("recessao")
    if rec:
        linhas.append(f"📉 **Probabilidade de recessão nos EUA a 12 meses (modelo da Fed de NY):** {rec['prob']:.0f}%")
    try:
        import fontes_bce
        jb = fontes_bce.painel()
        st = next((x for x in jb.get("stress", []) if x["id"] == "U2"), None)
        if st:
            linhas.append(f"🌡️ **Stress financeiro na área do euro (BCE):** {st['icone']} {st['valor']:.2f}".replace(".", ",") + f" ({st['nivel']})")
        pt = next((x for x in jb.get("divida", []) if x["id"] == "PT"), None)
        if pt and pt.get("spread_de") is not None:
            taxa, premio = f"{pt['taxa']:.2f}".replace(".", ","), f"{pt['spread_de']:+.2f}".replace(".", ",")
            linhas.append(f"🇵🇹 **Dívida portuguesa a 10 anos:** {taxa}% · prémio vs Alemanha {premio} p.p. ({pt['mes']})")
    except Exception:
        pass
    ext = [m for m in (d.get("cot") or {}).get("mercados", []) if m.get("extremo")]
    if ext:
        linhas.append("🧭 **Especuladores em extremo (CFTC):** " + ", ".join(
            f"{m['nome']} {'muito comprados' if m['indice'] >= 90 else 'muito vendidos'}" for m in ext[:5]))
    areas = {a["id"]: a for a in (d.get("ocde") or {}).get("areas", [])}
    fases = [f"{ {'USA': '🇺🇸', 'EA20': '🇪🇺', 'PRT': '🇵🇹'}[k]} {areas[k]['nome']} {areas[k]['icone']} {areas[k]['fase_nome'].lower()}" for k in ("USA", "EA20", "PRT") if k in areas]
    if fases:
        linhas.append("🌍 **Ciclo (OCDE):** " + " · ".join(fases))
    return "\n".join(linhas)


def construir_relatorio(agora=None):
    agora = agora or datetime.now()
    hoje = agora.date()
    macro = snap.carregar("macro")
    avisos = []
    try:
        if yg.esta_bloqueado():
            raise yg.YahooIndisponivel("pausa de proteção")
        var = _variacoes_semana()
    except Exception as e:
        var = {}
        avisos.append("variações semanais indisponíveis (Yahoo em pausa)")
    if not var and not snap.esta_fresco(macro):
        return None, "Sem dados da semana: o Yahoo está em pausa e não há fotografia diária recente."

    sexta = hoje - timedelta(days=(hoje.weekday() - 4) % 7)
    titulo = f"🗓️ Briefing Semanal: semana de {sexta - timedelta(days=4):%d/%m} a {sexta.day} de {MESES[sexta.month - 1]}"

    if var:
        descricao = "**A semana nos mercados** (sexta a sexta)\n" + _campo_mercados(var)
    else:
        descricao = "**Fecho de sexta** (variação do dia)\n" + "\n".join(
            f"**{i['nome']}** {_pct(i['var'])}" for i in (macro or {}).get("indices", []) if i["ticker"] != "^VIX")

    campos = []
    cor = 5793266
    s = _campo_setores(var)
    if s:
        campos.append({"name": "🏭 Setores da semana (EUA)", "value": s, "inline": False})
        positivos = sum(1 for t in snap.SETORES_USA if t in var and var[t][1] > 0)
        cor = 6076508 if positivos >= 7 else (15773006 if positivos >= 4 else 14242639)
    if snap.esta_fresco(macro):
        quadrantes = {"Líderes": [], "A Melhorar": [], "A Enfraquecer": [], "Atrasados": []}
        for r in macro.get("rrg", []):
            quadrantes.setdefault(r["quadrante"], []).append(r["setor"])
        icones = {"Líderes": "🟢", "A Melhorar": "🔵", "A Enfraquecer": "🟡", "Atrasados": "🔴"}
        rrg = "\n".join(f"{icones[q]} **{q}:** {', '.join(v) if v else '—'}" for q, v in quadrantes.items() if q in icones)
        b = macro.get("breadth", {})
        rrg += f"\n🧭 **{b.get('acima_ema50', 0)}/{b.get('total', 11)}** setores acima da EMA 50 no fecho de sexta."
        campos.append({"name": "🌀 Rotação setorial (21 dias)", "value": rrg[:1024], "inline": False})
    mo = _campo_macro_oficial()
    if mo:
        campos.append({"name": "🏦 Dados oficiais (Tesouro · BCE · CFTC · OCDE)", "value": mo[:1024], "inline": False})
    campos.append({"name": "🔎 Sinais do Screener desta semana", "value": _campo_sinais(hoje)[:1024], "inline": False})
    liga = _campo_liga(agora)
    if liga:
        campos.append({"name": "🏆 Liga Mensal", "value": liga[:1024], "inline": False})
    esc = _campo_escola(hoje)
    if esc:
        campos.append({"name": "🎓 Escola", "value": esc[:1024], "inline": False})

    rodape = "Portal Bolsa · Briefing Semanal · Informação educativa, não é recomendação de investimento"
    if avisos:
        rodape += " · " + "; ".join(avisos)
    return {"embeds": [{"title": titulo, "color": cor, "description": descricao[:4000],
                        "fields": campos[:25], "footer": {"text": rodape}}]}, None


def enviar_relatorio(forcar=False, agora=None):
    url = _webhook()
    if not url:
        return False, "Webhook não configurado. Define WEBHOOK_SEMANAL (ou WEBHOOK_RELATORIO) nas Variáveis da Discloud."
    agora = agora or datetime.now()
    semana = _semana_id(agora.date())
    est = _ler_estado()
    if not forcar and est.get("semana_envio") == semana:
        return False, "O briefing semanal desta semana já foi enviado."
    payload, erro = construir_relatorio(agora)
    if erro:
        est["ultimo_erro"] = f"{agora.isoformat(timespec='seconds')}: {erro}"
        _gravar_estado(est)
        return False, erro
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e:
        est["ultimo_erro"] = f"{agora.isoformat(timespec='seconds')}: {e}"
        _gravar_estado(est)
        return False, f"Falha ao enviar para o Discord: {e}"
    est.update({"semana_envio": semana if not forcar else est.get("semana_envio"),
                "ultimo_envio": agora.isoformat(timespec="seconds"), "ultimo_erro": None, "envio_manual": bool(forcar)})
    if not forcar:
        est["dia_envio"] = agora.date().isoformat()
    _gravar_estado(est)
    return True, "Briefing Semanal enviado para o Discord."


# ------------------------------------------------------------------ agendador
_tentativas = {}


def envio_agendado(agora):
    """Sábados à hora marcada (janela de 3 h), no máximo 3 tentativas espaçadas de 10 minutos."""
    if agora.weekday() != 5:
        return None
    h, m = hora_envio()
    inicio = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (inicio <= agora < inicio + timedelta(hours=3)):
        return None
    semana = _semana_id(agora.date())
    if _ler_estado().get("semana_envio") == semana:
        return None
    t = _tentativas.get(semana, {"n": 0, "ultima": 0.0})
    if t["n"] >= 3 or time.time() - t["ultima"] < 600:
        return None
    os.makedirs(snap.PASTA, exist_ok=True)
    trinco = os.path.join(snap.PASTA, f".semanal_{semana}.lock")
    try:
        fd = os.open(trinco, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if time.time() - os.path.getmtime(trinco) < 600:
            return None
        os.utime(trinco)
    _tentativas[semana] = {"n": t["n"] + 1, "ultima": time.time()}
    ok, msg = enviar_relatorio(agora=agora)
    print(f"[Briefing Semanal] {agora:%H:%M} tentativa {t['n'] + 1}: {msg}", flush=True)
    return msg
