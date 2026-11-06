"""
fontes_portugal.py — Portugal em números, de fontes oficiais, gratuitas e sem chave:

    1. Banco de Portugal (API BPstat): juros médios dos NOVOS depósitos a prazo e dos NOVOS créditos à habitação e
       ao consumo em Portugal, comparados com a média dos bancos da área do euro.             → portugal_bdp.json
    2. Eurostat (que publica os dados do INE harmonizados): estimativa rápida da inflação, taxa de desemprego mensal
       e preços da habitação, de Portugal e da área do euro.                                     → portugal_eurostat.json
    3. Comissão Europeia (via Eurostat): inquéritos de confiança — sentimento económico, consumidores, indústria e
       serviços, de Portugal e da área do euro.                                                  → portugal_eurostat.json

Porque Eurostat e não diretamente o INE: o serviço de dados do INE limita os pedidos automáticos de forma muito
agressiva (responde 429 e bloqueia temporariamente o endereço). Os números são os mesmos: o Eurostat recebe-os do INE.

Atualização: uma vez por dia, depois das 12:00 (o BdP publica às ~10:30 e o Eurostat às 11:00). Se falhar, mantém a
última cópia boa. Consultar o painel nunca vai à internet.
"""

import json
import os
import threading
import time
from datetime import date, datetime, timedelta

import requests

UA = {"User-Agent": "PortalBolsa/1.0 (dados educativos)", "Accept": "application/json"}
ARQ_BDP = "portugal_bdp.json"
ARQ_EUROSTAT = "portugal_eurostat.json"
BPSTAT = "https://bpstat.bportugal.pt/data/v1"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_lock = threading.Lock()
_diag = {}

# Séries do BPstat (identificador → nome). Taxas anualizadas acordadas (TAA), média mensal das novas operações.
SERIES_BDP = {
    "dep_pt": (12519807, "Novos depósitos a prazo de particulares · Portugal"),
    "dep_ae": (12759837, "Novos depósitos a prazo de particulares · bancos da área do euro"),
    "hab_pt": (12533735, "Novos empréstimos à habitação (TAA) · Portugal"),
    "hab_ae": (12559870, "Novos empréstimos à habitação (TAA) · bancos da área do euro"),
    "hab_taeg": (12533714, "TAEG dos novos contratos de crédito à habitação · Portugal"),
    "cons_pt": (12533733, "Novos empréstimos ao consumo (TAA) · Portugal"),
}

# Eurostat: (conjunto, filtros fixos, unidade a ler)
SERIES_EUROSTAT = {
    "inflacao": ("teicp000", {"unit": "PCH_M12"}, 26),         # estimativa rápida incluída (mês mais recente)
    "desemprego": ("une_rt_m", {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}, 36),
    "habitacao": ("prc_hpi_q", {"purchase": "TOTAL", "unit": "RCH_A"}, 12),
    # Inquéritos de conjuntura da Comissão Europeia (publicados pelo Eurostat no fim de cada mês, sobre esse mês).
    # As tabelas «teibs» só trazem os últimos 12 meses: o histórico vai-se acumulando no ficheiro, mês a mês.
    "sentimento": ("teibs010", {"indic": "BS-ESI-I", "s_adj": "SA"}, 12),          # índice: média de longo prazo = 100
    "conf_consumidores": ("teibs020", {"indic": "BS-CSMCI-BAL", "s_adj": "SA"}, 12),  # saldo de respostas (%)
    "conf_industria": ("teibs020", {"indic": "BS-ICI-BAL", "s_adj": "SA"}, 12),
    "conf_servicos": ("teibs020", {"indic": "BS-SCI-BAL", "s_adj": "SA"}, 12),
}
SERIES_ACUMULADAS = {"sentimento", "conf_consumidores", "conf_industria", "conf_servicos"}
MAX_ACUMULADO = 60  # meses guardados
AREAS_EURO = ("EA21", "EA20", "EA")  # a área do euro muda de código quando entra um país novo


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


def _get(url, params=None, tentativas=3):
    ultimo = None
    for n in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"respondeu {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            ultimo = e
            time.sleep(4 * (n + 1))
    raise RuntimeError(str(ultimo)[:200])


# ---------------------------------------------------------------
# BANCO DE PORTUGAL
# ---------------------------------------------------------------
def atualizar_bdp(forcar=False):
    with _lock:
        d = _ler(ARQ_BDP, {"series": {}, "meta": {}})
        if not forcar and d.get("series") and (d.get("atualizado_em") or "")[:10] == date.today().isoformat():
            return True, "Já atualizado hoje."
        ids = [v[0] for v in SERIES_BDP.values()]
        meta = d.get("meta") or {}
        if any(str(i) not in meta for i in ids):
            lista = _get(f"{BPSTAT}/series/", {"lang": "PT", "series_ids": ",".join(map(str, ids))})
            for x in lista:
                meta[str(x["id"])] = {"dominio": (x.get("domain_ids") or [None])[0], "dataset": x.get("dataset_id"), "nome": x.get("label")}
        erros, n = [], 0
        for chave, (sid, _) in SERIES_BDP.items():
            m = meta.get(str(sid))
            if not m or not m.get("dominio"):
                erros.append(f"{chave}: série {sid} sem metadados")
                continue
            try:
                j = _get(f"{BPSTAT}/domains/{m['dominio']}/datasets/{m['dataset']}/",
                         {"lang": "PT", "series_ids": sid, "obs_last_n": 60})
                datas = list(j["dimension"]["reference_date"]["category"]["index"])
                valores = j.get("value") or []
                if isinstance(valores, dict):  # JSON-stat também pode vir em formato «esparso»
                    valores = [valores.get(str(i)) for i in range(len(datas))]
                serie = [[dt[:7], v] for dt, v in zip(datas, valores) if v is not None]
                if serie:
                    d["series"][chave] = serie
                    n += 1
                else:
                    erros.append(f"{chave}: sem valores")
            except Exception as e:
                erros.append(f"{chave}: {str(e)[:100]}")
                _diag["bdp"] = str(e)[:300]
            time.sleep(0.5)
        d["meta"] = meta
        d["erros"] = erros
        d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(ARQ_BDP, d)
        ult = max((s[-1][0] for s in d["series"].values() if s), default="—")
        return (n > 0 and not erros), (f"{n} séries · último mês: {ult}." + (" Falhas: " + "; ".join(erros) if erros else ""))


# ---------------------------------------------------------------
# EUROSTAT (dados do INE harmonizados)
# ---------------------------------------------------------------
def _jsonstat_series(j, filtros, geo):
    """Extrai {período: valor} de um JSON-stat do Eurostat para um país, com os filtros indicados."""
    ids, tamanhos = j["id"], j["size"]
    dims = j["dimension"]
    if geo not in dims["geo"]["category"]["index"]:
        return {}
    passo = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        passo[i] = passo[i + 1] * tamanhos[i + 1]
    base = 0
    for i, dim in enumerate(ids):
        if dim == "time":
            continue
        idx = dims[dim]["category"]["index"]
        if dim == "geo":
            pos = idx[geo]
        elif dim in filtros:
            if filtros[dim] not in idx:
                return {}
            pos = idx[filtros[dim]]
        else:
            pos = 0  # dimensão com um só valor (ex.: freq)
        base += pos * passo[i]
    t_i = ids.index("time")
    valores = j.get("value") or {}
    out = {}
    for periodo, pos in dims["time"]["category"]["index"].items():
        v = valores.get(str(base + pos * passo[t_i])) if isinstance(valores, dict) else valores[base + pos * passo[t_i]]
        if v is not None:
            out[periodo] = v
    return out


def atualizar_eurostat(forcar=False):
    with _lock:
        d = _ler(ARQ_EUROSTAT, {"series": {}})
        completo = all(k in (d.get("series") or {}) for k in SERIES_EUROSTAT)
        if not forcar and completo and (d.get("atualizado_em") or "")[:10] == date.today().isoformat():
            return True, "Já atualizado hoje."
        erros, n = [], 0
        for chave, (conjunto, filtros, ultimos) in SERIES_EUROSTAT.items():
            params = [("geo", "PT")] + [("geo", a) for a in AREAS_EURO] + list(filtros.items()) + [("lastTimePeriod", ultimos)]
            try:
                j = _get(f"{EUROSTAT}/{conjunto}", params)
                pt = _jsonstat_series(j, filtros, "PT")
                ae, area = {}, None
                for a in AREAS_EURO:
                    ae = _jsonstat_series(j, filtros, a)
                    if ae:
                        area = a
                        break
                if pt:
                    if chave in SERIES_ACUMULADAS:  # junta ao que já estava guardado (os valores novos prevalecem)
                        antigo = d["series"].get(chave) or {}
                        pt = {**dict(antigo.get("PT") or []), **pt}
                        if area and area == antigo.get("area"):
                            ae = {**dict(antigo.get("AE") or []), **ae}
                        pt = dict(sorted(pt.items())[-MAX_ACUMULADO:])
                        ae = dict(sorted(ae.items())[-MAX_ACUMULADO:])
                    d["series"][chave] = {"PT": sorted(pt.items()), "AE": sorted(ae.items()), "area": area,
                                          "atualizado_fonte": j.get("updated")}
                    n += 1
                else:
                    erros.append(f"{chave}: sem dados de Portugal")
                    _diag["eurostat"] = json.dumps({k: j.get(k) for k in ("id", "size", "error")})[:300]
            except Exception as e:
                erros.append(f"{chave}: {str(e)[:100]}")
            time.sleep(0.5)
        d["erros"] = erros
        d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(ARQ_EUROSTAT, d)
        return (n > 0 and not erros), (f"{n} indicadores." + (" Falhas: " + "; ".join(erros) if erros else ""))


# ---------------------------------------------------------------
# PAINEL
# ---------------------------------------------------------------
def _ultimo_e_ano(serie, passos_ano):
    if not serie:
        return None, None, None
    p, v = serie[-1]
    antes = serie[-1 - passos_ano][1] if len(serie) > passos_ano else None
    return p, v, antes


def painel():
    b = _ler(ARQ_BDP, {"series": {}})
    e = _ler(ARQ_EUROSTAT, {"series": {}})
    s = b.get("series") or {}
    out = {"fonte_bdp": "Banco de Portugal (BPstat)", "fonte_eurostat": "Eurostat (dados do INE harmonizados)",
           "bdp_atualizado_em": b.get("atualizado_em"), "eurostat_atualizado_em": e.get("atualizado_em"),
           "bancos": {}, "economia": {}}
    for chave, (_, nome) in SERIES_BDP.items():
        mes, v, ano = _ultimo_e_ano(s.get(chave), 12)
        if mes:
            out["bancos"][chave] = {"nome": nome, "mes": mes, "taxa": v, "ha_um_ano": ano, "serie": s[chave][-36:]}
    passos = {"inflacao": 12, "desemprego": 12, "habitacao": 4}
    out["confianca"] = {}
    for chave, x in (e.get("series") or {}).items():
        mes, v, ano = _ultimo_e_ano(x.get("PT"), passos.get(chave, 12))
        mes_ae, v_ae, _ = _ultimo_e_ano(x.get("AE"), passos.get(chave, 12))
        if not mes:
            continue
        item = {"periodo": mes, "pt": v, "pt_ha_um_ano": ano, "ae": v_ae, "periodo_ae": mes_ae,
                "area": x.get("area"), "serie": [list(p) for p in x["PT"][-36:]]}
        if chave in SERIES_ACUMULADAS:
            pt = x.get("PT") or []
            item["mes_anterior"] = pt[-2][1] if len(pt) > 1 else None
            item["serie_ae"] = [list(p) for p in (x.get("AE") or [])[-36:]]
            out["confianca"][chave] = item
        else:
            out["economia"][chave] = item
    return out


# ---------------------------------------------------------------
# AGENDADOR, TESTE E ESTADO
# ---------------------------------------------------------------
_ultima_tentativa = {}


def diario(agora):
    for nome, f, arq in (("Banco de Portugal", atualizar_bdp, ARQ_BDP), ("Eurostat", atualizar_eurostat, ARQ_EUROSTAT)):
        existente = _ler(arq, {})
        # «vazio» também quando falta um indicador novo (ex.: a confiança, acrescentada depois): vai buscá-lo já
        esperadas = SERIES_EUROSTAT if arq == ARQ_EUROSTAT else SERIES_BDP
        vazio = not existente.get("series") or any(k not in existente["series"] for k in esperadas)
        if (existente.get("atualizado_em") or "")[:10] == agora.date().isoformat() and not vazio:
            continue
        if not vazio and agora.hour < 12:
            continue
        if time.time() - _ultima_tentativa.get(nome, 0) < 3600:
            continue
        _ultima_tentativa[nome] = time.time()
        try:
            ok, msg = f()
            print(f"[portugal] {nome}: {msg}")
        except Exception as e:
            print(f"[portugal] {nome} falhou: {e}")


def testar():
    r = {}
    for nome, f, chave in (("Banco de Portugal · juros de depósitos e crédito", atualizar_bdp, "bdp"),
                           ("Eurostat/INE · inflação, desemprego, habitação e confiança", atualizar_eurostat, "eurostat")):
        try:
            ok, msg = f(forcar=True)
        except Exception as e:
            ok, msg = False, str(e)[:300]
        r[nome] = {"ok": ok, "msg": msg}
        if not ok and _diag.get(chave):
            r[nome]["diagnostico"] = _diag[chave]
    return r


def estado():
    b, e = _ler(ARQ_BDP, {}), _ler(ARQ_EUROSTAT, {})
    return {"bdp_atualizado_em": b.get("atualizado_em"), "bdp_n": len(b.get("series") or {}),
            "eurostat_atualizado_em": e.get("atualizado_em"), "eurostat_n": len(e.get("series") or {})}
