"""
fontes_bce.py — Dados oficiais do Banco Central Europeu (API SDMX pública, gratuita e sem chave).

    1. Câmbios de referência do BCE (os mesmos que o Banco de Portugal divulga) para o Cofre e os Dividendos.
       Uma cópia local (bce_cambios.json) é atualizada uma vez por dia; consultar um câmbio nunca vai à internet.
    2. Juros e Poupança: taxas diretoras do BCE, Euribor (médias mensais), curva de rendimentos AAA da
       área do euro, inflação (IHPC) de Portugal e da área do euro, juro da dívida pública a 10 anos de PT/DE/ES/IT/FR/GR
       e o termómetro de stress financeiro (CISS). Atualizado uma vez por dia (juros_bce.json).
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
def pedir_csv(fluxo, chave, tentativas=3, **params):
    """Devolve as linhas (dicts) do CSV SDMX do BCE. O BCE responde por vezes com 504/timeout quando está
    carregado: tenta até 3 vezes, com pausas crescentes. Lança exceção se todas falharem."""
    params = {"format": "csvdata", "detail": "dataonly", **params}
    ultimo_erro = None
    for n in range(tentativas):
        try:
            r = requests.get(f"{API}/{fluxo}/{chave}", params=params, headers=UA, timeout=60)
            if r.status_code == 404:
                return []  # sem dados para o período pedido (não é erro)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"BCE respondeu {r.status_code}")
            r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        except Exception as e:
            ultimo_erro = e
            time.sleep(5 * (n + 1))
    raise RuntimeError(f"{fluxo}/{chave}: {str(ultimo_erro)[:160]}")


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
# Uma série por pedido (pedidos pequenos: o BCE responde melhor) — grupo: [(fluxo, chave, parâmetros)]
SERIES = {
    "diretoras": [("FM", f"B.U2.EUR.4F.KR.{k}.LEV", {"lastNObservations": "12"}) for k in ("DFR", "MRR_FR", "MLFR")],
    "euribor": [("FM", f"M.U2.EUR.RT.MM.{k}.HSTA", {"lastNObservations": "40"}) for k in ("EURIBOR1MD_", "EURIBOR3MD_", "EURIBOR6MD_", "EURIBOR1YD_")],
    "curva": [("YC", f"B.U2.EUR.4F.G_N_A.SV_C_YM.{k}", {"lastNObservations": "270"}) for k in ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y")],
    "inflacao": [("ICP", f"M.{k}.N.000000.4.ANR", {"lastNObservations": "40"}) for k in ("PT", "U2")],
    # Juro da dívida pública a 10 anos (taxa de longo prazo para efeitos de convergência, média mensal)
    "divida": [("IRS", f"M.{k}.L.L40.CI.0000.EUR.N.Z", {"lastNObservations": "62"}) for k in ("PT", "DE", "ES", "IT", "FR", "GR")],
    # Termómetro de stress financeiro do BCE (CISS diário, entre 0 e 1)
    "stress": [("CISS", f"D.{k}.Z0Z.4F.EC.SS_CIN.IDX", {"lastNObservations": "1600"}) for k in ("U2", "PT", "US")],
}
# Se uma série não existir (404/vazia), tenta esta alternativa (ex.: CISS original da área do euro)
ALTERNATIVAS = {("stress", "U2"): ("CISS", "D.U2.Z0Z.4F.EC.SS_CI.IDX", {"lastNObservations": "1600"})}
NOMES = {
    "DFR": "Facilidade de depósito", "MRR_FR": "Operações principais de refinanciamento", "MLFR": "Facilidade de cedência marginal",
    "EURIBOR1MD_": "Euribor 1 mês", "EURIBOR3MD_": "Euribor 3 meses", "EURIBOR6MD_": "Euribor 6 meses", "EURIBOR1YD_": "Euribor 12 meses",
    "SR_3M": "3 meses", "SR_1Y": "1 ano", "SR_2Y": "2 anos", "SR_5Y": "5 anos", "SR_10Y": "10 anos", "SR_30Y": "30 anos",
    "PT": "Portugal", "U2": "Área do euro", "DE": "Alemanha", "ES": "Espanha", "IT": "Itália", "FR": "França", "GR": "Grécia", "US": "EUA",
}


IDS = {
    "diretoras": ("DFR", "MRR_FR", "MLFR"),
    "euribor": ("EURIBOR1MD_", "EURIBOR3MD_", "EURIBOR6MD_", "EURIBOR1YD_"),
    "curva": ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y"),
    "inflacao": ("PT", "U2"),
    "divida": ("PT", "DE", "ES", "IT", "FR", "GR"),
    "stress": ("U2", "PT", "US"),
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
        antigos = dados.get("series") or {}
        for grupo, pedidos in SERIES.items():
            for fluxo, chave, params in pedidos:
                sid_pedida = next(i for i in IDS[grupo] if i in chave.split("."))
                try:
                    linhas = pedir_csv(fluxo, chave, **params)
                    if not linhas and (grupo, sid_pedida) in ALTERNATIVAS:
                        f2, c2, p2 = ALTERNATIVAS[(grupo, sid_pedida)]
                        linhas = pedir_csv(f2, c2, **p2)
                    if not linhas:
                        erros.append(f"{grupo}/{sid_pedida}: o BCE não devolveu dados ({fluxo}.{chave})")
                    for l in linhas:
                        v = l.get("OBS_VALUE")
                        if v in (None, "", "NaN"):
                            continue
                        novo["series"].setdefault(grupo, {}).setdefault(sid_pedida, []).append([l["TIME_PERIOD"], float(v)])
                except Exception as e:
                    erros.append(f"{grupo}/{sid_pedida}: {str(e)[:120]}")
                    if sid_pedida in (antigos.get(grupo) or {}):  # mantém o último valor bom desta série
                        novo["series"].setdefault(grupo, {})[sid_pedida] = antigos[grupo][sid_pedida]
                time.sleep(1)
        for grupo in novo["series"].values():
            for s in grupo.values():
                s.sort()
        total = sum(len(p) for p in SERIES.values())
        if len(erros) >= total:
            # O BCE não respondeu a nada (ex.: manutenção, erro 503): não mexe nos dados guardados e tenta mais tarde
            dados["ultima_falha"] = datetime.now().isoformat(timespec="seconds")
            dados["erros"] = [_resumo_erros(erros)]
            _gravar(ARQ_JUROS, dados)
            raise RuntimeError(f"BCE indisponível: {_resumo_erros(erros)}. Mantêm-se os dados de {(dados.get('atualizado_em') or '—')[:10]}.")
        novo["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        novo["erros"] = erros
        _gravar(ARQ_JUROS, novo)
        return not erros, ("Juros atualizados." if not erros else _resumo_erros(erros))


def _resumo_erros(erros):
    """«23 séries: BCE respondeu 503» em vez de uma lista enorme."""
    import re as _re
    grupos = {}
    for e in erros:
        motivo = (_re.search(r"BCE respondeu \d+|não devolveu dados|timed? ?out|Read timed out|Max retries", e) or [None])[0] or e.split(": ", 1)[-1][:60]
        grupos.setdefault(motivo, []).append(e.split(":", 1)[0])
    return "; ".join(f"{len(v)} série{'s' if len(v) > 1 else ''} ({', '.join(v[:4])}{'…' if len(v) > 4 else ''}): {k}" for k, v in grupos.items())


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

    # Dívida pública a 10 anos e prémio de risco face à Alemanha (pontos percentuais)
    div = s.get("divida") or {}
    de = div.get("DE") or []
    de_por_mes = dict(de)
    out["divida"] = []
    for k in ("PT", "ES", "IT", "FR", "GR", "DE"):
        serie = div.get(k)
        if not serie:
            continue
        mes, taxa = serie[-1]
        um_ano = _ha_um_ano(serie)
        spread = round(taxa - de_por_mes[mes], 3) if mes in de_por_mes and k != "DE" else None
        spreads = [[m, round(v - de_por_mes[m], 3)] for m, v in serie if m in de_por_mes] if k != "DE" else []
        out["divida"].append({"id": k, "nome": NOMES[k], "mes": mes, "taxa": taxa, "ha_um_ano": um_ano[1] if um_ano else None,
                              "spread_de": spread, "spread_max_5a": max((x[1] for x in spreads), default=None),
                              "serie": serie[-60:], "serie_spread": spreads[-60:]})
    # Stress financeiro (CISS): valor atual, posição face aos últimos anos e nível
    st = s.get("stress") or {}
    out["stress"] = []
    for k in ("U2", "PT", "US"):
        serie = st.get(k)
        if not serie or len(serie) < 20:
            continue
        dia, v = serie[-1]
        valores = [x for _, x in serie]
        percentil = round(sum(1 for x in valores if x <= v) / len(valores) * 100)
        nivel = ("calmo", "🟢") if v < 0.15 else ("tensão moderada", "🟡") if v < 0.3 else ("stress elevado", "🟠") if v < 0.5 else ("crise", "🔴")
        semanal = serie[::5] + ([serie[-1]] if (len(serie) - 1) % 5 else [])
        out["stress"].append({"id": k, "nome": NOMES[k], "dia": dia, "valor": round(v, 4), "percentil": percentil,
                              "nivel": nivel[0], "icone": nivel[1], "max_periodo": round(max(valores), 3), "desde": serie[0][0],
                              "ha_um_mes": round(serie[-22][1], 4) if len(serie) > 22 else None, "serie": semanal[-160:]})

    ca = manual().get("certificados_aforro") or []
    out["certificados_aforro"] = ca[-1] if ca else None
    out["certificados_aforro_hist"] = ca[-24:]

    # Comparador educativo: nominal → líquido de IRS (28%) → real (descontando a inflação de Portugal)
    infl_pt = next((x["taxa"] for x in out["inflacao"] if x["id"] == "PT"), None)
    linhas = []
    if out["certificados_aforro"]:
        linhas.append(("Certificados de Aforro (taxa base do mês)", out["certificados_aforro"]["taxa"], "IGCP (inserido pelo Admin)"))
    try:  # juro médio que os bancos portugueses pagam nos novos depósitos a prazo (Banco de Portugal)
        import fontes_portugal
        dep = fontes_portugal.painel()["bancos"].get("dep_pt")
        if dep:
            linhas.append((f"Depósito a prazo (média dos bancos em PT, {dep['mes']})", dep["taxa"], "Banco de Portugal"))
    except Exception:
        pass
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
        feito_hoje = (existente.get("atualizado_em") or "")[:10] == agora.date().isoformat()
        incompleto = bool(existente.get("erros")) and agora.hour < 23  # algumas séries falharam: volta a tentar
        if feito_hoje and not vazio and not incompleto:
            continue
        if agora.hour < 17 and not vazio:
            continue
        if time.time() - _ultima_tentativa.get(nome, 0) < 3600:
            continue
        _ultima_tentativa[nome] = time.time()
        try:
            ok, msg = f(forcar=incompleto)
            print(f"[bce] {nome}: {msg}")
        except Exception as e:
            print(f"[bce] {nome} falhou: {e}")
            # Falhas do BCE costumam ser passageiras (manutenção, sobrecarga): só avisa o Admin se ainda falhar à noite
            if agora.hour >= 21 or vazio:
                import alertas_admin as aa
                aa.avisar(f"bce-{nome}:{agora.date()}", f"BCE: os {nome} não foram atualizados hoje",
                          f"O BCE não respondeu em nenhuma das tentativas de hoje (desde as 17:00, de hora a hora). "
                          f"O Portal continua a usar os últimos dados bons; amanhã tenta de novo.\n\nÚltimo erro: {str(e)[:300]}", "aviso")


def estado():
    c = _ler(ARQ_CAMBIOS, {"taxas": {}})
    j = _ler(ARQ_JUROS, {})
    return {
        "cambios_atualizado_em": c.get("atualizado_em"),
        "cambios_ultimo_dia": max((max(v) for v in c.get("taxas", {}).values() if v), default=None),
        "moedas": sorted(c.get("taxas", {}).keys()),
        "juros_atualizado_em": j.get("atualizado_em"),
        "juros_erros": ([_resumo_erros(j["erros"])] if j.get("erros") and len(j["erros"]) > 1 else (j.get("erros") or [])),
        "juros_ultima_falha": j.get("ultima_falha"),
        "ca_ultimo": (manual().get("certificados_aforro") or [None])[-1],
    }
