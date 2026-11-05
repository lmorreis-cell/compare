"""
calendario_macro.py — Agenda macro automática, a partir das páginas oficiais (sem introduzir datas à mão):

    • BCE: reuniões de política monetária (dia da decisão e conferência de imprensa)
    • Reserva Federal (FOMC): reuniões e as que trazem projeções económicas (*)
    • BLS (EUA): emprego (Employment Situation), inflação (CPI), preços no produtor (PPI), ofertas de emprego (JOLTS)…

Horas convertidas para Lisboa. Atualizado uma vez por dia (06:00); se uma fonte falhar mantém as datas que já tinha.
Ficheiro: calendario_macro.json.
"""

import html
import json
import os
import re
import time
from datetime import date, datetime, timedelta

import requests

try:
    from zoneinfo import ZoneInfo
    NY, LX = ZoneInfo("America/New_York"), ZoneInfo("Europe/Lisbon")
except Exception:  # sem base de fusos: as horas ficam aproximadas (ET + 5 h)
    NY = LX = None

ARQ = "calendario_macro.json"
URL_BCE = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
URL_FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
URL_BLS = "https://www.bls.gov/schedule/news_release/bls.ics"
MESES_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
# Publicações do BLS que interessam aos mercados (o resto do calendário é ignorado)
BLS_IMPORTANTES = {
    "Employment Situation": ("Emprego nos EUA (payrolls e taxa de desemprego)", "alta",
                             "O relatório mensal de emprego: quantos empregos foram criados e a taxa de desemprego. Costuma mexer muito com o mercado, porque condiciona as decisões da Fed."),
    "Consumer Price Index": ("Inflação nos EUA (CPI)", "alta",
                             "Inflação no consumidor. Uma surpresa para cima costuma fazer subir os juros e cair as ações, e vice-versa."),
    "Producer Price Index": ("Preços no produtor nos EUA (PPI)", "media",
                             "Inflação nos preços à saída da fábrica: costuma antecipar a inflação no consumidor."),
    "Job Openings and Labor Turnover": ("Ofertas de emprego nos EUA (JOLTS)", "media",
                                       "Número de vagas por preencher: mostra se o mercado de trabalho está a aquecer ou a arrefecer."),
    "Employment Cost Index": ("Custo do trabalho nos EUA (ECI)", "media",
                              "Evolução dos salários e benefícios: um dos indicadores de inflação que a Fed mais acompanha."),
    "Real Earnings": None,
}
_diag = {}


def _ler():
    try:
        with open(ARQ, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"eventos": [], "fontes": {}}


def _gravar(d):
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, ARQ)


def _ua():
    contacto = (os.environ.get("SEC_USER_AGENT") or "").strip()  # o BLS pede identificação com contacto
    return {"User-Agent": contacto or "PortalBolsa/1.0 (dados educativos)", "Accept": "text/html,text/calendar,*/*"}


def _get(url):
    r = requests.get(url, headers=_ua(), timeout=40)
    if r.status_code != 200:
        _diag[url] = f"HTTP {r.status_code}: {r.text[:200]}"
        raise RuntimeError(f"respondeu {r.status_code}")
    return r.text


def _para_lisboa(dia, hhmm, origem_ny=True):
    """dia 'AAAA-MM-DD' + 'HH:MM' (hora de Nova Iorque) → (dia, hora) em Lisboa."""
    if not hhmm:
        return dia, None
    h, m = map(int, hhmm.split(":"))
    dt = datetime.fromisoformat(dia).replace(hour=h, minute=m)
    if NY and origem_ny:
        dt = dt.replace(tzinfo=NY).astimezone(LX)
    elif origem_ny:
        dt = dt + timedelta(hours=5)
    return dt.date().isoformat(), dt.strftime("%H:%M")


def _bce():
    t = _get(URL_BCE)
    ev = []
    for dia, corpo in re.findall(r"<dt[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd[^>]*>([\s\S]*?)</dd>", t):
        txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", corpo))).strip()
        if "monetary policy meeting" in txt.lower() and "press conference" in txt.lower() and "non-monetary" not in txt.lower():
            iso = f"{dia[6:]}-{dia[3:5]}-{dia[:2]}"
            ev.append({"data": iso, "hora": "13:15", "fonte": "BCE", "titulo": "Decisão de juros do BCE (e conferência de imprensa às 13:45)",
                       "nivel": "alta", "explica": "O Conselho do BCE decide as taxas de juro da área do euro: mexe com a Euribor, os depósitos, o crédito à habitação e o euro."})
    return ev


def _fed():
    t = re.sub(r"\s+", " ", _get(URL_FED))
    ev, ano = [], None
    for m in re.finditer(r"(\d{4}) FOMC Meetings|fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<", t):
        if m.group(1):
            ano = int(m.group(1))
            continue
        if not ano:
            continue
        mes_txt, dias_txt = m.group(2).strip().lower(), m.group(3).strip()
        projecoes = "*" in dias_txt
        dias = re.findall(r"\d{1,2}", dias_txt)
        if not dias or "notation" in dias_txt.lower():
            continue
        mes_nome = mes_txt.split("/")[-1]  # «April/May» → a decisão é no 2.º mês
        mes = MESES_EN.get(mes_nome)
        if not mes:
            continue
        dia = date(ano, mes, int(dias[-1])).isoformat()
        d_lx, h_lx = _para_lisboa(dia, "14:00")
        ev.append({"data": d_lx, "hora": h_lx, "fonte": "Fed", "nivel": "alta",
                   "titulo": "Decisão de juros da Fed (FOMC)" + (" + projeções económicas" if projecoes else ""),
                   "explica": "A Reserva Federal decide a taxa de juro dos EUA. A conferência de imprensa do presidente da Fed é meia hora depois. "
                              + ("Nesta reunião saem também as projeções dos membros (o «gráfico de pontos»), que costumam mexer mais com o mercado." if projecoes else "")})
    return ev


def _bls():
    t = _get(URL_BLS)
    ev = []
    for bloco in t.split("BEGIN:VEVENT")[1:]:
        resumo = (re.search(r"SUMMARY:([^\r\n]*)", bloco) or [None, ""])[1].strip()
        m = re.search(r"DTSTART[^:]*:(\d{8})(?:T(\d{2})(\d{2}))?", bloco)
        if not m:
            continue
        info = next((v for k, v in BLS_IMPORTANTES.items() if resumo.startswith(k)), None)
        if not info:
            continue
        dia = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
        d_lx, h_lx = _para_lisboa(dia, f"{m.group(2)}:{m.group(3)}" if m.group(2) else None)
        ev.append({"data": d_lx, "hora": h_lx, "fonte": "BLS", "titulo": info[0], "nivel": info[1], "explica": info[2]})
    return ev


def atualizar(forcar=False):
    d = _ler()
    if not forcar and d.get("eventos") and (d.get("atualizado_em") or "")[:10] == date.today().isoformat():
        return True, "Já atualizado hoje."
    eventos_por_fonte = {}
    for e in d.get("eventos", []):
        eventos_por_fonte.setdefault(e["fonte"], []).append(e)
    erros = []
    for nome, f in (("BCE", _bce), ("Fed", _fed), ("BLS", _bls)):
        try:
            novos = f()
            if novos:
                eventos_por_fonte[nome] = novos
                d.setdefault("fontes", {})[nome] = {"ok": True, "n": len(novos), "em": datetime.now().isoformat(timespec="seconds")}
            else:
                erros.append(f"{nome}: nenhuma data encontrada (a página mudou?)")
        except Exception as e:
            erros.append(f"{nome}: {str(e)[:120]}")
            d.setdefault("fontes", {})[nome] = {"ok": False, "msg": str(e)[:200]}
        time.sleep(1)
    limite = (date.today() - timedelta(days=7)).isoformat()
    todos = [e for lista in eventos_por_fonte.values() for e in lista if e["data"] >= limite]
    d["eventos"] = sorted(todos, key=lambda e: (e["data"], e.get("hora") or "99:99"))
    d["erros"] = erros
    d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    _gravar(d)
    n = {k: len(v) for k, v in eventos_por_fonte.items()}
    return (not erros), ", ".join(f"{k} {v}" for k, v in n.items()) + " eventos." + (" Falhas: " + "; ".join(erros) if erros else "")


def proximos(dias=30, desde=None):
    desde = desde or date.today()
    fim = (desde + timedelta(days=dias)).isoformat()
    return [e for e in _ler().get("eventos", []) if desde.isoformat() <= e["data"] <= fim]


def painel():
    d = _ler()
    return {"atualizado_em": d.get("atualizado_em"), "fontes": d.get("fontes", {}), "eventos": proximos(45),
            "fonte": "BCE · Reserva Federal · U.S. Bureau of Labor Statistics"}


def texto_semana(segunda):
    """Linhas para o Briefing Semanal (semana que começa na segunda-feira indicada)."""
    sem = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    linhas = []
    for e in proximos(6, segunda):
        dt = date.fromisoformat(e["data"])
        icone = {"alta": "🔴", "media": "🟡"}.get(e["nivel"], "⚪")
        linhas.append(f"{icone} **{sem[dt.weekday()]} {dt.day:02d}/{dt.month:02d}{(' ' + e['hora']) if e.get('hora') else ''}** · {e['titulo']}")
    return "\n".join(linhas)


_ultima = {"t": 0}


def diario(agora):
    vazio = not _ler().get("eventos")
    if not vazio and agora.hour < 6:
        return
    if time.time() - _ultima["t"] < 3600 * (1 if vazio else 6):
        return
    _ultima["t"] = time.time()
    try:
        ok, msg = atualizar()
        if "Já atualizado" not in msg:
            print(f"[calendario] {msg}")
    except Exception as e:
        print(f"[calendario] falhou: {e}")


def testar():
    try:
        ok, msg = atualizar(forcar=True)
        r = {"ok": ok, "msg": msg}
        if not ok and _diag:
            r["diagnostico"] = " | ".join(f"{k}: {v}" for k, v in _diag.items())[:500]
        return r
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}


def estado():
    d = _ler()
    return {"atualizado_em": d.get("atualizado_em"), "fontes": d.get("fontes", {}), "proximo": (proximos(60) or [None])[0]}
