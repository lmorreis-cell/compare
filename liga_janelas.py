# -*- coding: utf-8 -*-
"""
liga_janelas.py — Edições, janelas de inscrição e pontuação da Liga Mensal.

Regras (únicas para todo o portal):
  • Uma EDIÇÃO é o mês em que a carteira compete (ex.: "2026-11" = Novembro 2026) e termina no último dia desse mês.
  • As inscrições de uma edição decorrem numa JANELA [início, fim] (datas inclusivas), definida pelo Admin.
    Sem configuração, usa o padrão: do dia 20 do mês anterior ao dia 5 do próprio mês.
  • Nevoeiro: os ativos e a tese de cada carteira ficam ocultos até ao fim da janela da sua edição.
  • Preço de partida (p0) = preço no momento da submissão.
  • Alvos (✅ / 🎯🔥) só contam a partir do dia SEGUINTE à submissão (evita contar máximos/mínimos anteriores à entrada).
  • A edição só é fechada (Hall of Fame, medalhas) depois de o mês da edição terminar.
"""
import calendar
import json
import os
import threading
from datetime import date, datetime, timedelta

ARQ_CONFIG = "liga_config.json"
ARQ_LIGA = "liga_carteiras.json"
ARQ_HISTORICO = "liga_historico.json"
_lock_cfg = threading.Lock()
_lock_migracao = threading.Lock()

CONFIG_INICIAL = {
    "padrao": {"dia_inicio": 20, "dia_fim": 5},
    # 1.ª edição: inscrições de 20 de outubro a 5 de novembro, a competir em novembro
    "edicoes": {"2026-11": {"inicio": "2026-10-20", "fim": "2026-11-05"}},
    "migracoes": [],
}

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
            "Setembro", "Outubro", "Novembro", "Dezembro"]


# ---------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------
def carregar_config():
    if os.path.exists(ARQ_CONFIG):
        try:
            with open(ARQ_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("padrao", dict(CONFIG_INICIAL["padrao"]))
            cfg.setdefault("edicoes", {})
            cfg.setdefault("migracoes", [])
            return cfg
        except Exception:
            pass
    return json.loads(json.dumps(CONFIG_INICIAL))


def gravar_config(cfg):
    tmp = ARQ_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ARQ_CONFIG)


# ---------------------------------------------------------------
# DATAS
# ---------------------------------------------------------------
def mes_seguinte(m):
    a, n = map(int, m.split("-"))
    return f"{a + 1}-01" if n == 12 else f"{a}-{n + 1:02d}"


def mes_anterior(m):
    a, n = map(int, m.split("-"))
    return f"{a - 1}-12" if n == 1 else f"{a}-{n - 1:02d}"


def ultimo_dia(m):
    a, n = map(int, m.split("-"))
    return date(a, n, calendar.monthrange(a, n)[1])


def primeiro_dia(m):
    a, n = map(int, m.split("-"))
    return date(a, n, 1)


def nome_edicao(m):
    a, n = map(int, m.split("-"))
    return f"{MESES_PT[n - 1]} {a}"


def _hoje(agora=None):
    return (agora or datetime.now()).date()


def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()


# ---------------------------------------------------------------
# JANELAS
# ---------------------------------------------------------------
def janela(edicao, cfg=None):
    """Devolve (inicio, fim, origem) da janela de inscrição de uma edição."""
    cfg = cfg or carregar_config()
    e = cfg["edicoes"].get(edicao)
    if e:
        return _parse(e["inicio"]), _parse(e["fim"]), "config"
    p = cfg["padrao"]
    ant = mes_anterior(edicao)
    ini = primeiro_dia(ant).replace(day=min(int(p["dia_inicio"]), ultimo_dia(ant).day))
    fim = primeiro_dia(edicao).replace(day=min(int(p["dia_fim"]), ultimo_dia(edicao).day))
    return ini, fim, "padrao"


def edicao_em_curso(agora=None):
    """Edição cuja competição decorre agora (o mês do calendário)."""
    return (agora or datetime.now()).strftime("%Y-%m")


def edicao_inscricao(agora=None, cfg=None):
    """Edição com inscrições abertas hoje (ou None)."""
    cfg = cfg or carregar_config()
    hoje = _hoje(agora)
    atual = edicao_em_curso(agora)
    for ed in (atual, mes_seguinte(atual)):
        ini, fim, _ = janela(ed, cfg)
        if ini <= hoje <= fim:
            return ed
    return None


def proxima_janela(agora=None, cfg=None):
    """Próxima janela que ainda não abriu: (edicao, inicio, fim) ou None."""
    cfg = cfg or carregar_config()
    hoje = _hoje(agora)
    ed = edicao_em_curso(agora)
    for _ in range(4):
        ini, fim, _o = janela(ed, cfg)
        if ini > hoje:
            return ed, ini, fim
        ed = mes_seguinte(ed)
    return None


def em_nevoeiro(edicao, agora=None, cfg=None):
    """True enquanto as inscrições da edição não fecharam (ativos e tese ocultos)."""
    _ini, fim, _ = janela(edicao, cfg)
    return _hoje(agora) <= fim


def info_janela(edicao, agora=None, cfg=None):
    cfg = cfg or carregar_config()
    ini, fim, origem = janela(edicao, cfg)
    hoje = _hoje(agora)
    estado = "aberta" if ini <= hoje <= fim else ("por abrir" if hoje < ini else "fechada")
    return {"edicao": edicao, "nome": nome_edicao(edicao), "inicio": ini.isoformat(), "fim": fim.isoformat(),
            "origem": origem, "estado": estado, "fim_competicao": ultimo_dia(edicao).isoformat()}


def validar_janela(edicao, inicio, fim, cfg):
    """Devolve uma mensagem de erro, ou None se a janela for válida."""
    try:
        primeiro_dia(edicao)
    except Exception:
        return "Edição inválida (formato AAAA-MM)."
    if inicio > fim:
        return "A data de início tem de ser anterior (ou igual) à data de fim."
    if fim > ultimo_dia(edicao):
        return f"As inscrições têm de fechar até ao último dia da edição ({ultimo_dia(edicao).strftime('%d/%m/%Y')})."
    if inicio < primeiro_dia(mes_anterior(edicao)):
        return "As inscrições não podem abrir antes do mês anterior ao da edição."
    if (fim - inicio).days > 45:
        return "A janela de inscrição não pode ter mais de 45 dias."
    # Sem sobreposição com as edições vizinhas
    for viz in (mes_anterior(edicao), mes_seguinte(edicao)):
        vi, vf, _ = janela(viz, cfg)
        if not (fim < vi or inicio > vf):
            return f"A janela sobrepõe-se à da edição de {nome_edicao(viz)} ({vi.strftime('%d/%m')} a {vf.strftime('%d/%m')})."
    return None


# ---------------------------------------------------------------
# DATA DE ENTRADA DA CARTEIRA
# ---------------------------------------------------------------
def data_entrada(carteira):
    v = carteira.get("submetido_em")
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).date()
    except Exception:
        return None


def _datas_df(df):
    try:
        return [t.date() for t in df.index]
    except Exception:
        return []


def inferir_data_entrada(carteira, fatia_fn, inicio, limite):
    """Para carteiras antigas sem data de submissão: o p0 é o preço no momento da submissão, por isso
    a data de entrada é um dia em que os 3 preços p0 estavam dentro do intervalo [mínimo, máximo] do dia.
    Escolhe o ÚLTIMO dia compatível até ao limite (critério prudente: não conta máximos/mínimos anteriores)."""
    tol = 0.005
    minimo = _parse(carteira["entrada_minima"]) if carteira.get("entrada_minima") else None
    if minimo and minimo > inicio:
        inicio = minimo
    candidatos = None
    for s in carteira.get("slots", []):
        df = fatia_fn(s["ticker"])
        if df is None or getattr(df, "empty", True):
            continue
        p0 = float(s["p0"])
        dias = set()
        for t, row in df.dropna(subset=["High", "Low"]).iterrows():
            d = t.date()
            if inicio <= d <= limite and row["Low"] * (1 - tol) <= p0 <= row["High"] * (1 + tol):
                dias.add(d)
        candidatos = dias if candidatos is None else (candidatos & dias)
    if candidatos:
        return max(candidatos)
    # Sem dia compatível (ex.: ticker sem dados): critério prudente = a data mais tardia possível,
    # para nunca contar máximos/mínimos que possam ter acontecido antes da entrada.
    return limite


# ---------------------------------------------------------------
# PONTUAÇÃO DE UM SLOT (comum à classificação ao vivo e ao fecho da edição)
# ---------------------------------------------------------------
def pontuar_slot(s, df, entrada, fim_mes=None):
    """df = OHLC diário desde antes da entrada. Os alvos só contam a partir do dia seguinte à entrada.
    fim_mes: se indicado, ignora dados posteriores (fecho da edição). Lança ValueError se não houver preços."""
    df = df.dropna(subset=["Close"]) if df is not None and not df.empty else None
    if df is None or df.empty:
        raise ValueError("sem dados")
    datas = _datas_df(df)
    if fim_mes:
        mask = [d <= fim_mes for d in datas]
        df = df[mask]
        datas = [d for d in datas if d <= fim_mes]
        if df.empty:
            raise ValueError("sem dados")
    p_atual = float(df["Close"].iloc[-1])
    p0, alvo = float(s["p0"]), float(s["alvo"])
    is_long = alvo > p0
    ret = ((p_atual - p0) / p0) * 100.0
    if not is_long:
        ret = -ret
    apos = df[[d > entrada for d in datas]] if entrada else df
    if apos.empty:
        tocou = False
    else:
        max_m, min_m = float(apos["High"].max()), float(apos["Low"].min())
        tocou = (max_m >= alvo and p_atual > p0) if is_long else (min_m <= alvo and p_atual < p0)
    sniper = tocou and (abs(alvo - p_atual) / p_atual * 100.0 <= 1.0)
    bonus = (0.5 if tocou else 0.0) + (1.0 if sniper else 0.0)
    return {
        **s, "p_atual": round(p_atual, 2), "ret": round(ret, 2), "bonus": bonus,
        "tocou": bool(tocou), "sniper": bool(sniper), "direcao": "LONG" if is_long else "SHORT",
        "badge": "🎯🔥" if sniper else ("✅" if tocou else ("📈" if is_long else "📉")),
    }


# ---------------------------------------------------------------
# COMPARAÇÃO COM O MERCADO, EVOLUÇÃO DIÁRIA E RISCO
# ---------------------------------------------------------------
BENCHMARK = "^GSPC"          # S&P 500
BENCHMARK_NOME = "S&P 500"


def _closes(df):
    """Série {data: fecho} de um OHLC diário."""
    if df is None or getattr(df, "empty", True):
        return {}
    out = {}
    for t, v in df["Close"].dropna().items():
        out[t.date()] = float(v)
    return out


def metricas_carteira(slots, fatia_fn, entrada, fim=None):
    """Evolução diária do retorno da carteira (média dos 3 slots, como na classificação), o mesmo
    para o S&P 500 desde o fecho do dia de entrada, a queda máxima e a eficiência.
    Não grava nada: tudo se reconstrói a partir das cotações diárias."""
    bench = _closes(fatia_fn(BENCHMARK))
    series = []
    for s in slots:
        c = _closes(fatia_fn(s["ticker"]))
        p0 = float(s["p0"])
        is_long = float(s["alvo"]) > p0
        series.append((c, p0, is_long))
    dias = sorted({d for c, _, _ in series for d in c if d > entrada and (fim is None or d <= fim)})
    if not dias:
        return None

    # Base do S&P 500: fecho do dia de entrada (ou o último antes dele)
    base_b = None
    for d in sorted(bench):
        if d <= entrada:
            base_b = bench[d]
    if base_b is None and bench:
        base_b = bench[min(bench)]

    # Ponto de partida: no momento da entrada a carteira vale exatamente o p0 (0%) e o S&P 500 o fecho desse dia
    serie, ultimos, ult_b = [[entrada.isoformat(), 0.0, 0.0 if base_b else None]], [None] * len(series), base_b
    for d in dias:
        rets = []
        for i, (c, p0, is_long) in enumerate(series):
            if d in c:
                ultimos[i] = c[d]
            if ultimos[i] is None:
                rets.append(0.0)
                continue
            r = (ultimos[i] - p0) / p0 * 100.0
            rets.append(r if is_long else -r)
        if d in bench:
            ult_b = bench[d]
        rb = round((ult_b / base_b - 1) * 100.0, 2) if (ult_b and base_b) else None
        serie.append([d.isoformat(), round(sum(rets) / len(rets), 2), rb])

    # Queda máxima: maior descida desde um pico (o ponto de partida conta como pico, valor 100)
    pico, queda = 100.0, 0.0
    for _, r, _ in serie:
        v = 100.0 + r
        pico = max(pico, v)
        queda = max(queda, (pico - v) / pico * 100.0)
    bench_ret = serie[-1][2]
    ret = serie[-1][1]
    return {
        "serie": serie,
        "bench_ret": bench_ret,
        "alfa": round(ret - bench_ret, 2) if bench_ret is not None else None,
        "queda_max": round(queda, 2),
    }


def eficiencia(score, queda_max):
    """Score por cada 1% de queda máxima sofrida (queda mínima considerada: 1%)."""
    if score is None or queda_max is None:
        return None
    return round(score / max(queda_max, 1.0), 2)


# ---------------------------------------------------------------
# MIGRAÇÃO ÚNICA: a 1.ª ronda (20 out – 5 nov) ficou partida entre "2026-10" e "2026-11"
# ---------------------------------------------------------------
def migrar_primeira_edicao_se_preciso():
    """Move as carteiras guardadas em "2026-10" para a edição "2026-11" e apaga a edição de outubro
    do histórico (fechada por engano a 1 de novembro). Corre uma única vez."""
    if not _lock_migracao.acquire(blocking=False):
        return False
    try:
        cfg = carregar_config()
        if "primeira_edicao_2026_11" in cfg["migracoes"]:
            return False
        liga = {}
        if os.path.exists(ARQ_LIGA):
            with open(ARQ_LIGA, "r", encoding="utf-8") as f:
                liga = json.load(f)
        antigas = liga.pop("2026-10", {}) or {}
        novas = liga.setdefault("2026-11", {})
        movidas = 0
        for c in novas.values():
            if not c.get("submetido_em"):
                c["entrada_minima"] = "2026-11-01"  # gravada já em novembro (estava na chave 2026-11)
        for uid, c in antigas.items():
            if uid in novas:
                continue  # o membro voltou a submeter já em novembro: fica a versão mais recente
            c = dict(c)
            c["mes_ref"] = "2026-11"
            c["entrada_limite"] = "2026-10-31"  # sabemos que foi submetida até ao fim de outubro
            novas[uid] = c
            movidas += 1
        tmp = ARQ_LIGA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(liga, f, indent=4, ensure_ascii=False)
        os.replace(tmp, ARQ_LIGA)

        if os.path.exists(ARQ_HISTORICO):
            with open(ARQ_HISTORICO, "r", encoding="utf-8") as f:
                hist = json.load(f)
            if hist.pop("2026-10", None) is not None:
                tmp = ARQ_HISTORICO + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(hist, f, indent=2, ensure_ascii=False)
                os.replace(tmp, ARQ_HISTORICO)

        cfg["edicoes"].setdefault("2026-11", dict(CONFIG_INICIAL["edicoes"]["2026-11"]))
        cfg["migracoes"].append("primeira_edicao_2026_11")
        gravar_config(cfg)
        print(f"[liga] Migração da 1.ª edição: {movidas} carteiras movidas de 2026-10 para 2026-11.")
        return True
    finally:
        _lock_migracao.release()
