"""
sec_dados.py — Dados oficiais da SEC (EUA): compras e vendas de administradores (Form 4) e fundamentos
tirados diretamente dos relatórios anuais (XBRL «companyfacts»).

Regras de acesso da SEC (fair access):
    - É obrigatório identificar o cliente com um User-Agent que inclua um contacto.
      Define SEC_USER_AGENT nas Variáveis da Discloud, ex.: «Portal Bolsa contacto@teudominio.pt».
      Sem esta variável o módulo não faz pedidos.
    - No máximo 10 pedidos por segundo: aqui usamos no máximo ~4 por segundo.
    - A SEC bloqueia com frequência servidores de centros de dados; o botão «Testar fontes» da Gestão diz-te
      se o teu servidor está autorizado.

Cache em disco (pasta sec_cache/): lista de tickers 7 dias, filings e fundamentos 24 h, cada Form 4 para sempre.
"""

import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

PASTA = "sec_cache"
_lock = threading.Lock()
_ultimo_pedido = {"t": 0.0}

CODIGOS = {
    "P": ("Compra em bolsa", "compra"), "S": ("Venda em bolsa", "venda"),
    "A": ("Atribuição (prémio/ações)", "outro"), "M": ("Exercício de opções", "outro"), "F": ("Retenção para impostos", "outro"),
    "G": ("Doação", "outro"), "D": ("Devolução ao emitente", "outro"), "C": ("Conversão", "outro"), "X": ("Exercício de opções", "outro"),
}


class SemUserAgent(Exception):
    pass


def _ua():
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua or "@" not in ua:
        raise SemUserAgent("Falta SEC_USER_AGENT (nome e e-mail de contacto) nas Variáveis da Discloud.")
    return ua


def _get(url, accept="application/json"):
    with _lock:
        espera = 0.25 - (time.time() - _ultimo_pedido["t"])
        if espera > 0:
            time.sleep(espera)
        _ultimo_pedido["t"] = time.time()
    r = requests.get(url, headers={"User-Agent": _ua(), "Accept": accept, "Accept-Encoding": "gzip, deflate"}, timeout=30)
    if r.status_code == 403:
        raise RuntimeError("A SEC recusou o pedido (403). O servidor pode estar bloqueado ou o SEC_USER_AGENT não tem contacto válido.")
    r.raise_for_status()
    return r


def _cache(nome, validade_seg, produzir):
    os.makedirs(PASTA, exist_ok=True)
    caminho = os.path.join(PASTA, nome)
    if os.path.exists(caminho) and (validade_seg is None or time.time() - os.path.getmtime(caminho) < validade_seg):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    dados = produzir()
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f)
    os.replace(tmp, caminho)
    return dados


def cik(ticker):
    t = ticker.upper().strip().replace(".", "-")
    mapa = _cache("tickers.json", 7 * 86400, lambda: {v["ticker"].upper(): [str(v["cik_str"]).zfill(10), v.get("title")]
                                                       for v in _get("https://www.sec.gov/files/company_tickers.json").json().values()})
    return mapa.get(t)


# ---------------------------------------------------------------
# FORM 4: COMPRAS E VENDAS DE ADMINISTRADORES
# ---------------------------------------------------------------
def _txt(no, caminho):
    el = no.find(caminho)
    return el.text.strip() if el is not None and el.text else None


def _ler_form4(xml):
    raiz = ET.fromstring(xml)
    donos = []
    for o in raiz.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        cargos = []
        if rel is not None:
            if _txt(rel, "isDirector") in ("1", "true"):
                cargos.append("Administrador")
            if _txt(rel, "isOfficer") in ("1", "true"):
                cargos.append(_txt(rel, "officerTitle") or "Diretor")
            if _txt(rel, "isTenPercentOwner") in ("1", "true"):
                cargos.append("Acionista 10%+")
        donos.append({"nome": _txt(o, "reportingOwnerId/rptOwnerName"), "cargo": ", ".join(cargos) or "—"})
    notas = " ".join((n.text or "") for n in raiz.iter("footnote"))
    plano = _txt(raiz, "aff10b5One") in ("1", "true") or "10b5-1" in notas
    trans = []
    for t in raiz.findall("nonDerivativeTable/nonDerivativeTransaction"):
        codigo = _txt(t, "transactionCoding/transactionCode")
        acoes = _txt(t, "transactionAmounts/transactionShares/value")
        preco = _txt(t, "transactionAmounts/transactionPricePerShare/value")
        trans.append({
            "data": _txt(t, "transactionDate/value"),
            "codigo": codigo, "tipo": CODIGOS.get(codigo, (codigo or "?", "outro"))[0], "classe": CODIGOS.get(codigo, ("", "outro"))[1],
            "acoes": float(acoes) if acoes else None, "preco": float(preco) if preco else None,
            "valor": round(float(acoes) * float(preco), 2) if acoes and preco else None,
            "detidas_depois": float(_txt(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value") or 0) or None,
            "plano_10b5_1": plano,  # venda/compra pré-programada: sinal menos informativo
        })
    return {"donos": donos, "transacoes": trans}


def insiders(ticker, maximo=20):
    """Últimos Form 4 (máx. 20) com as transações, por ordem do mais recente."""
    c = cik(ticker)
    if not c:
        return {"erro": f"{ticker.upper()} não encontrado na lista da SEC (só empresas cotadas nos EUA)."}
    num, nome = c
    sub = _cache(f"sub_{num}.json", 86400, lambda: _get(f"https://data.sec.gov/submissions/CIK{num}.json").json())
    rec = sub.get("filings", {}).get("recent", {})
    out = []
    for i, forma in enumerate(rec.get("form", [])):
        if forma not in ("4", "4/A"):
            continue
        acc = rec["accessionNumber"][i]
        doc = re.sub(r"^xslF345X\d+/", "", rec["primaryDocument"][i])  # o XML original, sem a folha de estilo
        url = f"https://www.sec.gov/Archives/edgar/data/{int(num)}/{acc.replace('-', '')}/{doc}"
        try:
            f4 = _cache(f"f4_{acc}.json", None, lambda: _ler_form4(_get(url, "application/xml").content))
        except Exception as e:
            f4 = {"donos": [], "transacoes": [], "erro": str(e)[:120]}
        out.append({"data_entrega": rec["filingDate"][i], "url": f"https://www.sec.gov/Archives/edgar/data/{int(num)}/{acc.replace('-', '')}/{acc}-index.htm",
                    "emenda": forma == "4/A", **f4})
        if len(out) >= maximo:
            break
    compras = sum(t["valor"] or 0 for f in out for t in f["transacoes"] if t["codigo"] == "P")
    vendas = sum(t["valor"] or 0 for f in out for t in f["transacoes"] if t["codigo"] == "S")
    return {"ticker": ticker.upper(), "empresa": nome, "cik": num, "formularios": out,
            "resumo": {"compras_valor": round(compras, 2), "vendas_valor": round(vendas, 2),
                       "n_compras": sum(1 for f in out for t in f["transacoes"] if t["codigo"] == "P"),
                       "n_vendas": sum(1 for f in out for t in f["transacoes"] if t["codigo"] == "S")},
            "fonte": "SEC EDGAR (Form 4)"}


# ---------------------------------------------------------------
# FUNDAMENTOS OFICIAIS (XBRL)
# ---------------------------------------------------------------
CONCEITOS = {
    "receitas": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "resultado_operacional": ["OperatingIncomeLoss"],
    "lucro_liquido": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluido": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "fluxo_operacional": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "caixa": ["CashAndCashEquivalentsAtCarryingValue"],
    "divida_lp": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "capital_proprio": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "acoes": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"],
}


def _anuais(facts, nomes):
    """Valores anuais (10-K, período de 12 meses ou instantâneo no fecho do ano) do primeiro conceito disponível."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    resultado = {}
    for n in nomes:
        c = usgaap.get(n)
        if not c:
            continue
        unidades = c.get("units", {})
        lista = unidades.get("USD") or unidades.get("USD/shares") or unidades.get("shares") or next(iter(unidades.values()), [])
        por_ano = {}
        for v in lista:
            if v.get("form") not in ("10-K", "10-K/A") or v.get("fp") != "FY":
                continue
            ini, fim = v.get("start"), v.get("end")
            if ini and fim:
                dias = (date.fromisoformat(fim) - date.fromisoformat(ini)).days
                if not 350 <= dias <= 380:
                    continue  # ignora trimestres incluídos no 10-K
            ano = fim[:4] if fim else None
            if ano and (ano not in por_ano or (v.get("filed") or "") >= (por_ano[ano].get("filed") or "")):
                por_ano[ano] = v
        for a, v in por_ano.items():
            resultado.setdefault(a, v["val"])  # o 1.º conceito da lista tem prioridade; os outros preenchem anos em falta
    return dict(sorted(resultado.items()))


def fundamentos(ticker):
    c = cik(ticker)
    if not c:
        return {"erro": f"{ticker.upper()} não encontrado na lista da SEC (só empresas cotadas nos EUA)."}
    num, nome = c

    def produzir():
        facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{num}.json").json()
        series = {k: _anuais(facts, v) for k, v in CONCEITOS.items()}
        anos = sorted({a for s in series.values() for a in s})[-5:]
        linhas = []
        for a in anos:
            g = {k: series[k].get(a) for k in series}
            fcf = (g["fluxo_operacional"] - g["capex"]) if g["fluxo_operacional"] is not None and g["capex"] is not None else None
            margem = round(g["lucro_liquido"] / g["receitas"] * 100, 1) if g["lucro_liquido"] is not None and g["receitas"] else None
            roe = round(g["lucro_liquido"] / g["capital_proprio"] * 100, 1) if g["lucro_liquido"] is not None and g["capital_proprio"] else None
            linhas.append({"ano": a, **g, "fcf": fcf, "margem_liquida": margem, "roe": roe})
        return {"anos": linhas, "empresa": facts.get("entityName") or nome}

    dados = _cache(f"facts_{num}.json", 86400, produzir)
    return {"ticker": ticker.upper(), "cik": num, "fonte": "SEC EDGAR (relatórios anuais 10-K, XBRL)", **dados}


def testar():
    """Para a Gestão: confirma se o servidor consegue falar com a SEC."""
    try:
        c = cik("AAPL")
        return {"ok": bool(c), "msg": "SEC acessível." if c else "Lista de tickers vazia."}
    except SemUserAgent as e:
        return {"ok": False, "msg": str(e)}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}
