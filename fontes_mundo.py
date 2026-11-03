"""
fontes_mundo.py — Dados macro oficiais, gratuitos e sem chave (nenhum vem do Yahoo Finance).

    1. Curva de juros dos EUA (U.S. Department of the Treasury, «Daily Treasury Par Yield Curve Rates»),
       com o sinal clássico de recessão: 10 anos − 3 meses e 10 anos − 2 anos.            → tesouro_eua.json
    2. Indicadores avançados da OCDE (Composite Leading Indicators, API SDMX da OCDE): em que fase do
       ciclo está cada economia (expansão, abrandamento, contração, recuperação).          → ocde_cli.json
    3. Posicionamento dos grandes especuladores nos futuros (CFTC «Commitments of Traders», relatório
       Legacy, só futuros), com o «índice COT» de 3 anos para detetar extremos.            → cftc_cot.json

Cada fonte é atualizada no máximo uma vez por dia (a OCDE e a CFTC só mudam uma vez por mês/semana) e
consultar o painel nunca vai à internet. Se uma atualização falhar, mantém-se a última cópia boa.

Fontes a citar: «U.S. Department of the Treasury», «OCDE (OECD Data Explorer)», «CFTC Commitments of Traders».
"""

import csv
import io
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

UA = {"User-Agent": "PortalBolsa/1.0 (dados educativos)"}
ARQ_TESOURO = "tesouro_eua.json"
ARQ_CLI = "ocde_cli.json"
ARQ_COT = "cftc_cot.json"
_lock = threading.Lock()
_diag = {}  # último erro/diagnóstico por fonte (aparece no «Testar fontes» da Gestão)


def _ler(caminho, omissao):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return omissao


def _gravar(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def _pedir(url, params=None, tentativas=3, timeout=60, accept="*/*"):
    ultimo = None
    for n in range(tentativas):
        try:
            r = requests.get(url, params=params, headers={**UA, "Accept": accept}, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"respondeu {r.status_code}")
            r.raise_for_status()
            return r
        except Exception as e:
            ultimo = e
            time.sleep(5 * (n + 1))
    raise RuntimeError(str(ultimo)[:200])


def _num(v):
    try:
        if v in (None, "", "NaN", "N/A"):
            return None
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


# ===============================================================
# 1. CURVA DE JUROS DOS EUA (Tesouro)
# ===============================================================
URL_TESOURO = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
# Elementos do XML: d:BC_1MONTH, d:BC_1_5MONTH, d:BC_3MONTH, d:BC_1YEAR, d:BC_10YEAR, ... (d:BC_30YEARDISPLAY ignora-se)
_RE_PRAZO = re.compile(r"^BC_(\d+)(?:_(\d+))?(MONTH|YEAR)$")
PRAZOS_MOSTRAR = ["1M", "3M", "6M", "1A", "2A", "5A", "10A", "30A"]


def _prazo(tag):
    m = _RE_PRAZO.match(tag)
    if not m:
        return None
    n = m.group(1) + ("," + m.group(2) if m.group(2) else "")
    return n + ("M" if m.group(3) == "MONTH" else "A")


def _anos(prazo):
    v = float(prazo[:-1].replace(",", "."))
    return v / 12 if prazo.endswith("M") else v


def _ler_xml_tesouro(conteudo):
    """Devolve {dia: {prazo: taxa}}. Lê pelo nome local das etiquetas (independente dos namespaces)."""
    raiz = ET.fromstring(conteudo)
    dias = {}
    for el in raiz.iter():
        if not el.tag.endswith("properties"):
            continue
        dia, taxas = None, {}
        for c in el:
            nome = c.tag.split("}")[-1]
            if nome == "NEW_DATE":
                dia = (c.text or "")[:10]
            else:
                p = _prazo(nome)
                v = _num(c.text)
                if p and v is not None:
                    taxas[p] = v
        if dia and taxas:
            dias[dia] = taxas
    return dias


def atualizar_tesouro(forcar=False):
    with _lock:
        dados = _ler(ARQ_TESOURO, {"dias": {}})
        hoje = date.today()
        if not forcar and (dados.get("atualizado_em") or "")[:10] == hoje.isoformat() and dados.get("dias"):
            return True, "Já atualizado hoje."
        pedidos = []
        if len(dados["dias"]) < 200:  # 1.ª vez: 3 anos de histórico (um pedido por ano)
            pedidos = [{"field_tdr_date_value": str(a)} for a in (hoje.year - 2, hoje.year - 1, hoje.year)]
        else:
            pedidos = [{"field_tdr_date_value_month": hoje.strftime("%Y%m")}]
            if hoje.day <= 5:
                anterior = hoje.replace(day=1) - timedelta(days=1)
                pedidos.insert(0, {"field_tdr_date_value_month": anterior.strftime("%Y%m")})
        n = 0
        for p in pedidos:
            r = _pedir(URL_TESOURO, {"data": "daily_treasury_yield_curve", **p}, accept="application/xml")
            try:
                novos = _ler_xml_tesouro(r.content)
            except ET.ParseError as e:
                _diag["tesouro"] = r.text[:300]
                raise RuntimeError(f"XML do Tesouro ilegível ({e})")
            dados["dias"].update(novos)
            n += len(novos)
            time.sleep(1)
        limite = (hoje - timedelta(days=3 * 366)).isoformat()
        dados["dias"] = {k: v for k, v in dados["dias"].items() if k >= limite}
        dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(ARQ_TESOURO, dados)
        if not dados["dias"]:
            return False, "O Tesouro não devolveu dados."
        return True, f"{n} dias recebidos · último: {max(dados['dias'])}."


def _no_dia_ou_antes(dias, alvo):
    antes = [k for k in dias if k <= alvo]
    return max(antes) if antes else None


def painel_tesouro():
    d = _ler(ARQ_TESOURO, {"dias": {}})
    dias = d.get("dias") or {}
    out = {"fonte": "U.S. Department of the Treasury (Daily Treasury Par Yield Curve Rates)", "atualizado_em": d.get("atualizado_em")}
    if not dias:
        return {**out, "curva": [], "spreads": {}}
    ult = max(dias)
    hoje = date.fromisoformat(ult)
    d_mes = _no_dia_ou_antes(dias, (hoje - timedelta(days=30)).isoformat())
    d_ano = _no_dia_ou_antes(dias, (hoje - timedelta(days=365)).isoformat())
    curva = []
    for p in sorted(dias[ult], key=_anos):
        if p not in PRAZOS_MOSTRAR:
            continue
        curva.append({"prazo": p.replace("A", " anos").replace("M", " meses").replace("1 anos", "1 ano").replace("1 meses", "1 mês"),
                      "id": p, "taxa": dias[ult][p],
                      "ha_um_mes": (dias.get(d_mes) or {}).get(p) if d_mes else None,
                      "ha_um_ano": (dias.get(d_ano) or {}).get(p) if d_ano else None})
    out.update({"dia": ult, "curva": curva, "dia_mes": d_mes, "dia_ano": d_ano})

    # Spreads e sinal de recessão
    spreads = {}
    for nome, curto in (("10A-3M", "3M"), ("10A-2A", "2A")):
        serie = [(k, round(v["10A"] - v[curto], 3)) for k, v in sorted(dias.items()) if "10A" in v and curto in v]
        if not serie:
            continue
        atual = serie[-1][1]
        # Desde quando está no estado atual (invertida ou positiva)?
        desde = serie[-1][0]
        for k, v in reversed(serie):
            if (v < 0) != (atual < 0):
                break
            desde = k
        um_ano = [v for k, v in serie if k >= (hoje - timedelta(days=365)).isoformat()]
        dias_inv = sum(1 for v in um_ano if v < 0)
        # Última vez que saiu de uma inversão (a «desinversão» costuma surgir perto do início das recessões)
        desinversao = None
        for i in range(1, len(serie)):
            if serie[i - 1][1] < 0 <= serie[i][1]:
                desinversao = serie[i][0]
        semanal = serie[::5] if len(serie) > 5 else serie
        if semanal[-1] != serie[-1]:
            semanal = semanal + [serie[-1]]
        spreads[nome] = {"atual": atual, "invertida": atual < 0, "desde": desde, "dias_invertida_12m": dias_inv,
                         "uteis_12m": len(um_ano), "minimo_3a": min(v for _, v in serie), "desinversao": desinversao,
                         "serie": [[k, v] for k, v in semanal]}
    out["spreads"] = spreads
    s = spreads.get("10A-3M")
    if s:
        if s["invertida"]:
            sinal = ("vermelho", f"Curva invertida desde {s['desde']}: os juros a 3 meses rendem mais do que a 10 anos. "
                                 "Historicamente, inversões prolongadas antecederam as recessões nos EUA (com 6 a 24 meses de atraso), embora não digam quando.")
        elif s["desinversao"] and s["desinversao"] >= (hoje - timedelta(days=540)).isoformat():
            sinal = ("amarelo", f"A curva voltou a ficar positiva em {s['desinversao']}, depois de ter estado invertida. "
                                "No passado, a «desinversão» aconteceu muitas vezes perto do início das recessões: é uma fase de atenção, não uma certeza.")
        elif s["atual"] < 0.5:
            sinal = ("amarelo", "Curva quase plana: o mercado vê pouca diferença entre juros curtos e longos.")
        else:
            sinal = ("verde", "Curva positiva: os prazos longos rendem mais do que os curtos, a configuração normal de uma economia em crescimento.")
        out["sinal"] = {"cor": sinal[0], "texto": sinal[1]}
    return out


# ===============================================================
# 2. INDICADORES AVANÇADOS DA OCDE (CLI)
# ===============================================================
URL_CLI = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI/.M.LI...AA...H"
AREAS = {  # sem bandeiras: no Windows os emojis de bandeiras aparecem como letras («US», «DE»)
    "USA": "EUA", "EA20": "Área do euro", "DEU": "Alemanha", "FRA": "França", "ESP": "Espanha",
    "ITA": "Itália", "PRT": "Portugal", "GBR": "Reino Unido", "JPN": "Japão", "CHN": "China",
    "IND": "Índia", "BRA": "Brasil", "G7": "G7", "G20": "G20", "OECD": "OCDE",
}
ORDEM_AREAS = list(AREAS)


def atualizar_cli(forcar=False):
    with _lock:
        dados = _ler(ARQ_CLI, {"series": {}})
        if not forcar and dados.get("series") and (dados.get("atualizado_em") or "") >= (datetime.now() - timedelta(days=3)).isoformat():
            return True, "Atualizado nos últimos 3 dias (a OCDE publica uma vez por mês)."
        inicio = (date.today().replace(day=1) - timedelta(days=4 * 366)).strftime("%Y-%m")
        r = _pedir(URL_CLI, {"startPeriod": inicio, "dimensionAtObservation": "AllDimensions", "format": "csvfile"},
                   accept="application/vnd.sdmx.data+csv, text/csv, */*", timeout=90)
        linhas = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", errors="replace"))))
        if not linhas:
            _diag["ocde"] = r.text[:300]
            return False, "A OCDE não devolveu linhas."
        series = {}
        for l in linhas:
            area, mes, v = l.get("REF_AREA"), (l.get("TIME_PERIOD") or "")[:7], _num(l.get("OBS_VALUE"))
            if area and mes and v is not None:
                series.setdefault(area, {})[mes] = v
        if not series:
            _diag["ocde"] = "Colunas recebidas: " + ", ".join(list(linhas[0].keys())[:20])
            return False, "Formato da OCDE inesperado (ver diagnóstico)."
        dados = {"series": {a: sorted(s.items()) for a, s in series.items()},
                 "atualizado_em": datetime.now().isoformat(timespec="seconds")}
        _gravar(ARQ_CLI, dados)
        return True, f"{len(series)} economias · último mês: {max(max(s) for s in series.values())}."


def _fase(nivel, variacao):
    """As quatro fases do ciclo segundo a OCDE (nível face à média de longo prazo = 100 e direção)."""
    if nivel >= 100:
        return ("expansao", "Expansão", "🟢") if variacao >= 0 else ("abrandamento", "Abrandamento", "🟡")
    return ("recuperacao", "Recuperação", "🔵") if variacao >= 0 else ("contracao", "Contração", "🔴")


def painel_cli():
    d = _ler(ARQ_CLI, {"series": {}})
    s = d.get("series") or {}
    out = {"fonte": "OCDE — Composite Leading Indicators (OECD Data Explorer)", "atualizado_em": d.get("atualizado_em"), "areas": []}
    for a in sorted(s, key=lambda x: ORDEM_AREAS.index(x) if x in ORDEM_AREAS else 99):
        if a not in AREAS or len(s[a]) < 4:
            continue
        serie = s[a]
        nivel = serie[-1][1]
        var1 = nivel - serie[-2][1]
        var3 = nivel - serie[-4][1]
        fid, fnome, ic = _fase(nivel, var3)
        out["areas"].append({"id": a, "nome": AREAS[a], "mes": serie[-1][0], "nivel": round(nivel, 2),
                             "var_1m": round(var1, 2), "var_3m": round(var3, 2), "fase": fid, "fase_nome": fnome,
                             "icone": ic, "serie": serie[-36:]})
    return out


# ===============================================================
# 3. COMMITMENTS OF TRADERS (CFTC)
# ===============================================================
URL_COT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"  # Legacy, só futuros
MERCADOS_COT = [
    ("13874A", "S&P 500 (E-mini)", "indices"), ("209742", "Nasdaq-100 (E-mini)", "indices"),
    ("043602", "Obrigações EUA 10 anos", "juros"), ("099741", "Euro / Dólar", "moedas"),
    ("097741", "Iene japonês", "moedas"), ("096742", "Libra esterlina", "moedas"),
    ("088691", "Ouro", "materias"), ("084691", "Prata", "materias"), ("085692", "Cobre", "materias"),
    ("067651", "Petróleo WTI", "materias"), ("023651", "Gás natural", "materias"), ("133741", "Bitcoin (CME)", "cripto"),
]
_CAMPOS = {
    "dia": ("report_date_as_yyyy_mm_dd", "as_of_date_in_form_yyyy_mm_dd"),
    "codigo": ("cftc_contract_market_code",),
    "oi": ("open_interest_all",),
    "esp_long": ("noncomm_positions_long_all",), "esp_short": ("noncomm_positions_short_all",),
    "com_long": ("comm_positions_long_all",), "com_short": ("comm_positions_short_all",),
    "peq_long": ("nonrept_positions_long_all",), "peq_short": ("nonrept_positions_short_all",),
}


def _c(linha, chave):
    baixo = {k.lower(): v for k, v in linha.items()}
    for nome in _CAMPOS[chave]:
        if nome in baixo:
            return baixo[nome]
    return None


def atualizar_cot(forcar=False):
    with _lock:
        dados = _ler(ARQ_COT, {"mercados": {}})
        if not forcar and dados.get("mercados") and (dados.get("atualizado_em") or "")[:10] == date.today().isoformat():
            return True, "Já atualizado hoje."
        inicio = (date.today() - timedelta(days=3 * 366 + 14)).isoformat()
        codigos = ",".join(f"'{c}'" for c, _, _ in MERCADOS_COT)
        params = {"$where": f"cftc_contract_market_code in({codigos}) AND report_date_as_yyyy_mm_dd >= '{inicio}T00:00:00'",
                  "$order": "report_date_as_yyyy_mm_dd", "$limit": "10000"}
        r = _pedir(URL_COT, params, accept="application/json", timeout=90)
        try:
            linhas = r.json()
        except ValueError:
            _diag["cftc"] = r.text[:300]
            raise RuntimeError("Resposta da CFTC não é JSON.")
        if isinstance(linhas, dict):  # erro da API Socrata
            _diag["cftc"] = json.dumps(linhas)[:300]
            raise RuntimeError(linhas.get("message") or "Erro da API da CFTC.")
        mercados = {}
        for l in linhas:
            cod, dia = _c(l, "codigo"), (_c(l, "dia") or "")[:10]
            if not cod or not dia:
                continue
            v = {k: _num(_c(l, k)) for k in ("oi", "esp_long", "esp_short", "com_long", "com_short", "peq_long", "peq_short")}
            if v["esp_long"] is None or v["esp_short"] is None:
                continue
            mercados.setdefault(cod.strip(), {})[dia] = v
        if not mercados:
            _diag["cftc"] = ("Campos recebidos: " + ", ".join(list(linhas[0].keys())[:25])) if linhas else "Lista vazia."
            return False, "A CFTC não devolveu dados para os mercados escolhidos (ver diagnóstico)."
        dados = {"mercados": {c: sorted(s.items()) for c, s in mercados.items()},
                 "atualizado_em": datetime.now().isoformat(timespec="seconds")}
        _gravar(ARQ_COT, dados)
        ult = max(max(k for k, _ in s) for s in dados["mercados"].values())
        return True, f"{len(mercados)} mercados · relatório de {ult}."


def painel_cot():
    d = _ler(ARQ_COT, {"mercados": {}})
    m = d.get("mercados") or {}
    out = {"fonte": "CFTC — Commitments of Traders (Legacy, futuros)", "atualizado_em": d.get("atualizado_em"), "mercados": []}
    for cod, nome, grupo in MERCADOS_COT:
        serie = m.get(cod)
        if not serie or len(serie) < 10:
            continue
        liquidos = [(dia, v["esp_long"] - v["esp_short"]) for dia, v in serie]
        dia, ult = serie[-1]
        liq = liquidos[-1][1]
        valores = [x for _, x in liquidos]
        lo, hi = min(valores), max(valores)
        indice = round((liq - lo) / (hi - lo) * 100) if hi > lo else 50
        ant = liquidos[-2][1] if len(liquidos) > 1 else liq
        oi = ult.get("oi") or 0
        com_liq = (ult.get("com_long") or 0) - (ult.get("com_short") or 0)
        if indice >= 90:
            leitura = "Extremo comprador: os especuladores raramente estiveram tão apostados na subida. Historicamente, extremos destes são muitas vezes sinal contrário (quem tinha de comprar já comprou)."
        elif indice <= 10:
            leitura = "Extremo vendedor: os especuladores raramente estiveram tão apostados na descida. Quando mudam de ideias, as recompras podem acelerar uma subida."
        elif indice >= 70:
            leitura = "Especuladores claramente compradores."
        elif indice <= 30:
            leitura = "Especuladores claramente vendedores."
        else:
            leitura = "Posicionamento na zona média dos últimos 3 anos."
        if cod == "043602":
            leitura += (" Atenção: nos futuros de obrigações, grande parte da posição vendedora dos «especuladores» é o chamado"
                        " basis trade (fundos vendem o futuro e compram a obrigação para ganhar a diferença), não uma aposta na descida.")
        out["mercados"].append({
            "codigo": cod, "nome": nome, "grupo": grupo, "dia": dia,
            "liquido": liq, "variacao": liq - ant, "pct_oi": round(liq / oi * 100, 1) if oi else None,
            "comerciais": com_liq, "indice": indice, "leitura": leitura,
            "extremo": indice >= 90 or indice <= 10,
            "serie": [[k, v] for k, v in liquidos[-104:]],
        })
    return out


# ===============================================================
# PAINEL CONJUNTO, AGENDADOR E ESTADO
# ===============================================================
def painel():
    return {"tesouro": painel_tesouro(), "ocde": painel_cli(), "cot": painel_cot()}


FONTES = (
    # nome, função, ficheiro, hora mínima (Lisboa), chave com dados
    ("Tesouro dos EUA · curva de juros", atualizar_tesouro, ARQ_TESOURO, 22, "dias"),
    ("OCDE · indicadores avançados", atualizar_cli, ARQ_CLI, 12, "series"),
    ("CFTC · Commitments of Traders", atualizar_cot, ARQ_COT, 22, "mercados"),
)
_ultima_tentativa = {}


def diario(agora):
    """Tesouro: depois das 22:00 (a curva sai ~20:30 de Lisboa). CFTC: relatório à sexta ~20:30, verificado
    todos os dias depois das 22:00. OCDE: depois das 12:00, de 3 em 3 dias. Instalação nova: tenta logo."""
    for nome, f, arq, hora, chave in FONTES:
        existente = _ler(arq, {})
        vazio = not existente.get(chave)
        if not vazio and agora.hour < hora:
            continue
        if time.time() - _ultima_tentativa.get(nome, 0) < 3600:
            continue
        _ultima_tentativa[nome] = time.time()
        try:
            ok, msg = f()
            if "Já atualizado" not in msg and "últimos 3 dias" not in msg:
                print(f"[mundo] {nome}: {msg}")
        except Exception as e:
            print(f"[mundo] {nome} falhou: {e}")
            if not vazio and agora.weekday() < 5:
                import alertas_admin as aa
                aa.avisar(f"mundo-{arq}:{agora.date()}", f"{nome}: a atualização falhou", str(e)[:300], "aviso")


def testar():
    """Usado pelo botão «Testar fontes» da Gestão."""
    r = {}
    for nome, f, _, _, _ in FONTES:
        try:
            ok, msg = f(forcar=True)
        except Exception as e:
            ok, msg = False, str(e)[:300]
        chave = {"Tesouro": "tesouro", "OCDE": "ocde", "CFTC": "cftc"}[nome.split(" ")[0]]
        item = {"ok": ok, "msg": msg}
        if not ok and _diag.get(chave):
            item["diagnostico"] = _diag[chave]
        r[nome] = item
    return r


def estado():
    t, c, k = _ler(ARQ_TESOURO, {}), _ler(ARQ_CLI, {}), _ler(ARQ_COT, {})
    return {
        "tesouro_atualizado_em": t.get("atualizado_em"), "tesouro_ultimo_dia": max(t.get("dias") or {"": 0}) or None,
        "ocde_atualizado_em": c.get("atualizado_em"),
        "ocde_ultimo_mes": max((s[-1][0] for s in (c.get("series") or {}).values() if s), default=None),
        "cot_atualizado_em": k.get("atualizado_em"),
        "cot_ultimo_relatorio": max((s[-1][0] for s in (k.get("mercados") or {}).values() if s), default=None),
    }
