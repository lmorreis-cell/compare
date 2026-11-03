"""
fontes_bce.py — Dados oficiais do Banco Central Europeu (API SDMX pública, gratuita e sem chave).

    1. Câmbios de referência do BCE (os mesmos que o Banco de Portugal divulga) para o Cofre e os Dividendos.
       Uma cópia local (bce_cambios.json) é atualizada uma vez por dia; consultar um câmbio nunca vai à internet.
    2. Juros e Poupança: taxas diretoras do BCE, Euribor (médias mensais), curva de rendimentos AAA da
       área do euro e inflação (IHPC) de Portugal e da área do euro. Atualizado uma vez por dia (juros_bce.json).
    3. Certificados de Aforro: o IGCP não tem API, por isso a taxa base do mês é inserida pelo Admin
       (juros_manual.json).

Fonte a citar: «Banco Central Europeu (ECB Data Portal)». A Euribor diária é licenciada pela EMMI; aqui só
se usam as médias mensais publicadas pelo BCE.
"""

import csv
import io
import json
import os
import threading
import time
from datetime import date, datetime, timedelta

import requests

API = "https://data-api.ecb.europa.eu/service/data"
UA = {"User-Agent": "PortalBolsa/1.0 (dados educativos)", "Accept": "text/csv"}
ARQ_CAMBIOS = "bce_cambios.json"
ARQ_JUROS = "juros_bce.json"
ARQ_MANUAL = "juros_manual.json"
MOEDAS = ["USD", "GBP", "CHF", "CAD", "DKK", "SEK", "NOK", "BRL", "JPY", "HKD", "AUD", "PLN"]
INICIO_HISTORICO = "2015-01-01"
_lock = threading.Lock()


# ---------------------------------------------------------------
# ACESSO À API
# ---------------------------------------------------------------
def pedir_csv(fluxo, chave, **params):
    """Devolve as linhas (dicts) do CSV SDMX do BCE. Lança exceção se falhar."""
    params = {"format": "csvdata", "detail": "dataonly", **params}
    r = requests.get(f"{API}/{fluxo}/{chave}", params=params, headers=UA, timeout=30)
    if r.status_code == 404:
        return []  # sem dados para o período pedido (não é erro)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


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


# ---------------------------------------------------------------
# 1. CÂMBIOS
# ---------------------------------------------------------------
def atualizar_cambios(forcar=False):
    """Descarrega só o que falta (na 1.ª vez, desde 2015). Devolve (ok, mensagem)."""
    with _lock:
        dados = _ler(ARQ_CAMBIOS, {"taxas": {}, "atualizado_em": None})
        hoje = date.today().isoformat()
        if not forcar and (dados.get("atualizado_em") or "")[:10] == hoje and dados.get("taxas"):
            return True, "Já atualizado hoje."
        ultimo = max((max(v) for v in dados["taxas"].values() if v), default=None)
        inicio = (date.fromisoformat(ultimo) - timedelta(days=7)).isoformat() if ultimo else INICIO_HISTORICO
        linhas = pedir_csv("EXR", f"D.{'+'.join(MOEDAS)}.EUR.SP00.A", startPeriod=inicio)
        n = 0
        for l in linhas:
            moeda, dia, valor = l.get("CURRENCY"), l.get("TIME_PERIOD"), l.get("OBS_VALUE")
            if moeda and dia and valor not in (None, "", "NaN"):
                dados["taxas"].setdefault(moeda, {})[dia] = float(valor)
                n += 1
        dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(ARQ_CAMBIOS, dados)
        return True, f"{n} câmbios recebidos desde {inicio}."


def cambio(moeda, dia):
    """Câmbio de referência do BCE (unidades da moeda por 1 €) no dia indicado ou, se nesse dia não
    houve fixação (fim de semana/feriado TARGET), no último dia útil anterior.
    Devolve (taxa, data_usada) ou (None, None)."""
    moeda = moeda.upper()
    if moeda == "EUR":
        return 1.0, dia
    serie = _ler(ARQ_CAMBIOS, {"taxas": {}})["taxas"].get(moeda) or {}
    if not serie:
        return None, None
    alvo = dia
    for _ in range(10):
        if alvo in serie:
            return serie[alvo], alvo
        alvo = (date.fromisoformat(alvo) - timedelta(days=1)).isoformat()
    return None, None


# ---------------------------------------------------------------
# 2. JUROS E POUPANÇA
# ---------------------------------------------------------------
SERIES = {
    # fluxo, chave, parâmetros
    "diretoras": ("FM", "D.U2.EUR.4F.KR.DFR+MRR_FR+MLFR.LEV", {"startPeriod": "2022-01-01"}),
    "euribor": ("FM", "M.U2.EUR.RT.MM.EURIBOR1MD_+EURIBOR3MD_+EURIBOR6MD_+EURIBOR1YD_.HSTA", {"startPeriod": "2021-01"}),
    "curva": ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M+SR_1Y+SR_2Y+SR_5Y+SR_10Y+SR_30Y", {"lastNObservations": "300"}),
    "inflacao": ("ICP", "M.PT+U2.N.000000.4.ANR", {"startPeriod": "2021-01"}),
}
NOMES = {
    "DFR": "Facilidade de depósito", "MRR_FR": "Operações principais de refinanciamento", "MLFR": "Facilidade de cedência marginal",
    "EURIBOR1MD_": "Euribor 1 mês", "EURIBOR3MD_": "Euribor 3 meses", "EURIBOR6MD_": "Euribor 6 meses", "EURIBOR1YD_": "Euribor 12 meses",
    "SR_3M": "3 meses", "SR_1Y": "1 ano", "SR_2Y": "2 anos", "SR_5Y": "5 anos", "SR_10Y": "10 anos", "SR_30Y": "30 anos",
    "PT": "Portugal", "U2": "Área do euro",
}


IDS = {
    "diretoras": ("DFR", "MRR_FR", "MLFR"),
    "euribor": ("EURIBOR1MD_", "EURIBOR3MD_", "EURIBOR6MD_", "EURIBOR1YD_"),
    "curva": ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y"),
    "inflacao": ("PT", "U2"),
}


def _id_serie(linha, grupo):
    """Identifica a série pela parte da chave que a distingue dentro do grupo (ex.: DFR, SR_10Y, PT)."""
    partes = linha.get("KEY", "").split(".")
    for i in IDS[grupo]:
        if i in partes:
            return i
    return linha.get("KEY", "")


def atualizar_juros(forcar=False):
    with _lock:
        dados = _ler(ARQ_JUROS, {})
        if not forcar and (dados.get("atualizado_em") or "")[:10] == date.today().isoformat():
            return True, "Já atualizado hoje."
        novo, erros = {"series": {}}, []
        for grupo, (fluxo, chave, params) in SERIES.items():
            try:
                linhas = pedir_csv(fluxo, chave, **params)
                for l in linhas:
                    v = l.get("OBS_VALUE")
                    if v in (None, "", "NaN"):
                        continue
                    sid = _id_serie(l, grupo)
                    novo["series"].setdefault(grupo, {}).setdefault(sid, []).append([l["TIME_PERIOD"], float(v)])
                time.sleep(1)
            except Exception as e:
                erros.append(f"{grupo}: {e}")
                if grupo in (dados.get("series") or {}):
                    novo["series"][grupo] = dados["series"][grupo]  # mantém o último bom
        for grupo in novo["series"].values():
            for s in grupo.values():
                s.sort()
        novo["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        novo["erros"] = erros
        _gravar(ARQ_JUROS, novo)
        return not erros, ("Juros atualizados." if not erros else "; ".join(erros))


def _ultimo(serie):
    return serie[-1] if serie else None


def _dia(periodo):
    """'2026-10' → '2026-10-01'; '2026-10-31' fica igual."""
    return periodo if len(periodo) > 7 else periodo + "-01"


def _ha_um_ano(serie):
    if not serie:
        return None
    alvo = (date.fromisoformat(_dia(serie[-1][0])) - timedelta(days=365)).isoformat()
    antes = [p for p in serie if _dia(p[0]) <= alvo]
    return antes[-1] if antes else None


def manual():
    return _ler(ARQ_MANUAL, {"certificados_aforro": []})


def gravar_ca(mes, taxa):
    d = manual()
    d["certificados_aforro"] = [x for x in d.get("certificados_aforro", []) if x["mes"] != mes] + [{"mes": mes, "taxa": taxa}]
    d["certificados_aforro"].sort(key=lambda x: x["mes"])
    _gravar(ARQ_MANUAL, d)


def painel():
    """Resumo pronto para o separador «Juros & Poupança»."""
    d = _ler(ARQ_JUROS, {})
    s = d.get("series") or {}
    out = {"atualizado_em": d.get("atualizado_em"), "erros": d.get("erros") or [], "fonte": "Banco Central Europeu (ECB Data Portal)"}

    dire = s.get("diretoras") or {}
    out["diretoras"] = [{"id": k, "nome": NOMES[k], "taxa": _ultimo(dire[k])[1], "desde": _desde_quando(dire[k])}
                        for k in ("DFR", "MRR_FR", "MLFR") if dire.get(k)]
    eur = s.get("euribor") or {}
    out["euribor"] = [{"id": k, "nome": NOMES[k], "mes": _ultimo(eur[k])[0], "taxa": _ultimo(eur[k])[1],
                       "ha_um_ano": (_ha_um_ano(eur[k]) or [None, None])[1], "serie": eur[k][-36:]}
                      for k in ("EURIBOR1MD_", "EURIBOR3MD_", "EURIBOR6MD_", "EURIBOR1YD_") if eur.get(k)]
    cur = s.get("curva") or {}
    out["curva"] = [{"prazo": NOMES[k], "id": k, "taxa": _ultimo(cur[k])[1], "dia": _ultimo(cur[k])[0],
                     "ha_um_ano": (_ha_um_ano(cur[k]) or [None, None])[1]}
                    for k in ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y") if cur.get(k)]
    inf = s.get("inflacao") or {}
    out["inflacao"] = [{"id": k, "nome": NOMES[k], "mes": _ultimo(inf[k])[0], "taxa": _ultimo(inf[k])[1], "serie": inf[k][-36:]}
                       for k in ("PT", "U2") if inf.get(k)]

    ca = manual().get("certificados_aforro") or []
    out["certificados_aforro"] = ca[-1] if ca else None
    out["certificados_aforro_hist"] = ca[-24:]

    # Comparador educativo: nominal → líquido de IRS (28%) → real (descontando a inflação de Portugal)
    infl_pt = next((x["taxa"] for x in out["inflacao"] if x["id"] == "PT"), None)
    linhas = []
    if out["certificados_aforro"]:
        linhas.append(("Certificados de Aforro (taxa base do mês)", out["certificados_aforro"]["taxa"], "IGCP (inserido pelo Admin)"))
    for e in out["euribor"]:
        if e["id"] == "EURIBOR3MD_":
            linhas.append(("Euribor 3 meses (média mensal)", e["taxa"], "BCE"))
    for c in out["curva"]:
        if c["id"] in ("SR_2Y", "SR_10Y"):
            linhas.append((f"Obrigações AAA da área do euro a {c['prazo']}", c["taxa"], "BCE"))
    out["comparador"] = [{
        "nome": n, "fonte": f, "bruta": round(t, 3), "liquida": round(t * 0.72, 3),
        "real": round(t * 0.72 - infl_pt, 3) if infl_pt is not None else None,
    } for n, t, f in linhas]
    out["inflacao_pt"] = infl_pt
    return out


def _desde_quando(serie):
    """Data da última alteração de uma taxa diretora."""
    if not serie:
        return None
    atual = serie[-1][1]
    desde = serie[-1][0]
    for dia, v in reversed(serie):
        if v != atual:
            break
        desde = dia
    return desde


# ---------------------------------------------------------------
# AGENDADOR: uma vez por dia, depois da fixação das 16:00 CET
# ---------------------------------------------------------------
_ultima_tentativa = {}


def diario(agora):
    """Depois das 17:00 atualiza uma vez por dia. Se ainda não houver dados nenhuns (instalação nova),
    tenta já, no máximo uma vez por hora."""
    for nome, f, arq in (("câmbios", atualizar_cambios, ARQ_CAMBIOS), ("juros", atualizar_juros, ARQ_JUROS)):
        existente = _ler(arq, {})
        vazio = not (existente.get("taxas") or existente.get("series"))
        if (existente.get("atualizado_em") or "")[:10] == agora.date().isoformat() and not vazio:
            continue
        if agora.hour < 17 and not vazio:
            continue
        if time.time() - _ultima_tentativa.get(nome, 0) < 3600:
            continue
        _ultima_tentativa[nome] = time.time()
        try:
            ok, msg = f()
            print(f"[bce] {nome}: {msg}")
        except Exception as e:
            print(f"[bce] {nome} falhou: {e}")
            import alertas_admin as aa
            aa.avisar(f"bce-{nome}:{agora.date()}", f"BCE: a atualização de {nome} falhou", str(e), "aviso")


def estado():
    c = _ler(ARQ_CAMBIOS, {"taxas": {}})
    j = _ler(ARQ_JUROS, {})
    return {
        "cambios_atualizado_em": c.get("atualizado_em"),
        "cambios_ultimo_dia": max((max(v) for v in c.get("taxas", {}).values() if v), default=None),
        "moedas": sorted(c.get("taxas", {}).keys()),
        "juros_atualizado_em": j.get("atualizado_em"),
        "juros_erros": j.get("erros") or [],
        "ca_ultimo": (manual().get("certificados_aforro") or [None])[-1],
    }
