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

import html
import io
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


# ---------------------------------------------------------------
# 13F: CARTEIRAS DOS GRANDES INVESTIDORES (trimestral, 45 dias de atraso)
# ---------------------------------------------------------------
# CIK confirmado pela SEC: o nome mostrado vem sempre da própria SEC (se um CIK estiver errado, vê-se logo).
GESTORES_13F = [
    ("0001067983", "Berkshire Hathaway", "Warren Buffett"),
    ("0001336528", "Pershing Square", "Bill Ackman"),
    ("0001061768", "Baupost Group", "Seth Klarman"),
    ("0001536411", "Duquesne Family Office", "Stanley Druckenmiller"),
    ("0001656456", "Appaloosa", "David Tepper"),
    ("0001709323", "Himalaya Capital", "Li Lu"),
    ("0001040273", "Third Point", "Dan Loeb"),
    ("0001079114", "Greenlight Capital", "David Einhorn"),
    ("0001350694", "Bridgewater Associates", "Ray Dalio (fundador)"),
    ("0001167483", "Tiger Global", "Chase Coleman"),
    ("0001061165", "Lone Pine Capital", "Stephen Mandel (fundador)"),
    ("0001697748", "ARK Investment Management", "Cathie Wood"),
    ("0001112520", "Akre Capital", "Chuck Akre (fundador)"),
]


def _local(tag):
    return tag.split("}")[-1]


def _filho(no, nome):
    for c in no.iter():
        if _local(c.tag) == nome:
            return c.text.strip() if c.text else None
    return None


def _ler_info_table(xml):
    """Lê a «information table» do 13F (independente dos namespaces) e junta linhas do mesmo título."""
    raiz = ET.fromstring(xml)
    por_chave = {}
    for it in raiz.iter():
        if _local(it.tag) != "infoTable":
            continue
        cusip = (_filho(it, "cusip") or "").upper()
        put_call = (_filho(it, "putCall") or "").strip().capitalize()
        chave = (cusip, put_call)
        valor = float(_filho(it, "value") or 0)
        acoes = float(_filho(it, "sshPrnamt") or 0)
        p = por_chave.setdefault(chave, {"emitente": _filho(it, "nameOfIssuer"), "classe": _filho(it, "titleOfClass"),
                                         "cusip": cusip, "opcao": put_call or None, "valor": 0.0, "acoes": 0.0})
        p["valor"] += valor
        p["acoes"] += acoes
    return list(por_chave.values())


def _13f_entregas(num):
    sub = _cache(f"sub_{num}.json", 86400, lambda: _get(f"https://data.sec.gov/submissions/CIK{num}.json").json())
    rec = sub.get("filings", {}).get("recent", {})
    por_periodo = {}
    for i, forma in enumerate(rec.get("form", [])):
        if forma != "13F-HR":
            continue
        periodo = (rec.get("reportDate") or [None] * (i + 1))[i]
        if periodo and periodo not in por_periodo:  # a lista vem do mais recente para o mais antigo
            por_periodo[periodo] = {"periodo": periodo, "entregue": rec["filingDate"][i], "acc": rec["accessionNumber"][i]}
    return sub.get("name"), sorted(por_periodo.values(), key=lambda x: x["periodo"], reverse=True)


def _13f_posicoes(num, acc):
    def produzir():
        pasta = f"https://www.sec.gov/Archives/edgar/data/{int(num)}/{acc.replace('-', '')}"
        itens = _get(pasta + "/index.json").json().get("directory", {}).get("item", [])
        xmls = [x for x in itens if x.get("name", "").lower().endswith(".xml") and x["name"].lower() != "primary_doc.xml"]
        if not xmls:
            raise RuntimeError("Tabela de posições não encontrada na entrega.")
        maior = max(xmls, key=lambda x: int(x.get("size") or 0) if str(x.get("size") or "").isdigit() else 0)
        return _ler_info_table(_get(f"{pasta}/{maior['name']}", "application/xml").content)
    return _cache(f"13f_{acc}.json", None, produzir)  # uma entrega nunca muda: cache permanente


def carteira_13f(cik_gestor):
    """Posições do último 13F-HR comparadas com o trimestre anterior."""
    num = re.sub(r"\D", "", str(cik_gestor)).zfill(10)
    nome_sec, entregas = _13f_entregas(num)
    if not entregas:
        return {"erro": "Este CIK não tem entregas 13F-HR na SEC."}
    atual = entregas[0]
    pos = _13f_posicoes(num, atual["acc"])
    ant = _13f_posicoes(num, entregas[1]["acc"]) if len(entregas) > 1 else None
    total = sum(p["valor"] for p in pos if not p["opcao"]) or 1
    mapa_ant = {(p["cusip"], p["opcao"]): p for p in (ant or [])}
    linhas = []
    for p in sorted(pos, key=lambda x: -x["valor"]):
        a = mapa_ant.get((p["cusip"], p["opcao"]))
        if ant is None:
            mov, var = None, None
        elif not a:
            mov, var = "nova", None
        else:
            var = round((p["acoes"] - a["acoes"]) / a["acoes"] * 100, 1) if a["acoes"] else None
            mov = "reforco" if var is not None and var >= 1 else ("reducao" if var is not None and var <= -1 else "igual")
        linhas.append({**p, "peso": round(p["valor"] / total * 100, 2) if not p["opcao"] else None, "movimento": mov, "variacao_acoes": var})
    vendidas = []
    if ant is not None:
        atuais = {(p["cusip"], p["opcao"]) for p in pos}
        vendidas = sorted([p for p in ant if (p["cusip"], p["opcao"]) not in atuais], key=lambda x: -x["valor"])
    return {"cik": num, "gestor": nome_sec, "periodo": atual["periodo"], "entregue": atual["entregue"],
            "periodo_anterior": entregas[1]["periodo"] if len(entregas) > 1 else None,
            "valor_total": round(sum(p["valor"] for p in pos if not p["opcao"])), "n_posicoes": len(pos),
            "posicoes": linhas, "vendidas": vendidas[:30],
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={num}&type=13F-HR",
            "fonte": "SEC EDGAR (formulário 13F-HR)"}


def _norm_nome(n):
    n = re.sub(r"[^A-Z0-9 ]", " ", (n or "").upper().replace("&", " "))
    n = re.sub(r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS?|HLDGS?|GROUP|GRP|SA|NV|AG|THE|CL|CLASS|COM|NEW|DEL|OF|AND|A|B|C)\b", " ", n)
    return n.split()


def _mesmo_emitente(nome_13f, nome_sec):
    """Os 13F usam nomes abreviados («BANK AMER CORP», «OCCIDENTAL PETE CORP»): a 1.ª palavra tem de coincidir e
    cada palavra seguinte tem de partilhar as 3 primeiras letras com uma palavra do nome oficial."""
    a, b = _norm_nome(nome_13f), _norm_nome(nome_sec)
    if not a or not b or a[0] != b[0]:
        return False
    return all(any(x[:3] == y[:3] for y in b[1:]) for x in a[1:]) and abs(len(a) - len(b)) <= 1


def quem_detem(ticker):
    """Quais dos gestores acompanhados têm esta ação no último 13F. Usa só gestores já em cache (rápido)."""
    c = cik(ticker)
    if not c:
        return {"erro": f"{ticker.upper()} não encontrado na lista da SEC."}
    out = []
    for g_cik, g_nome, g_pessoa in GESTORES_13F:
        if not os.path.exists(os.path.join(PASTA, f"sub_{g_cik}.json")):
            continue
        try:
            d = carteira_13f(g_cik)
        except Exception:
            continue
        for p in d.get("posicoes", []):
            if not p["opcao"] and _mesmo_emitente(p["emitente"], c[1]):
                out.append({"gestor": g_nome, "pessoa": g_pessoa, "cik": g_cik, "peso": p["peso"], "valor": p["valor"], "classe": p["classe"],
                            "acoes": p["acoes"], "movimento": p["movimento"], "variacao_acoes": p["variacao_acoes"], "periodo": d["periodo"]})
    return {"ticker": ticker.upper(), "empresa": c[1], "detentores": sorted(out, key=lambda x: -(x["peso"] or 0)),
            "nota": "Correspondência pelo nome do emitente (os 13F não indicam o ticker)."}


def lista_gestores():
    """Lista para o separador, com o resumo de cada um (só a partir da cache; nunca bloqueia)."""
    out = []
    for g_cik, g_nome, g_pessoa in GESTORES_13F:
        item = {"cik": g_cik, "nome": g_nome, "pessoa": g_pessoa}
        caminho = os.path.join(PASTA, f"sub_{g_cik}.json")
        if os.path.exists(caminho):
            try:
                nome_sec, entregas = _13f_entregas(g_cik)
                if entregas:
                    item.update({"periodo": entregas[0]["periodo"], "entregue": entregas[0]["entregue"]})
            except Exception:
                pass
        out.append(item)
    return out


def atualizar_13f():
    """Descarrega (com calma) os 13F de todos os gestores acompanhados. Corre de madrugada."""
    ok, erros = 0, []
    for g_cik, g_nome, _ in GESTORES_13F:
        try:
            d = carteira_13f(g_cik)
            if d.get("erro"):
                erros.append(f"{g_nome}: {d['erro']}")
            else:
                ok += 1
        except SemUserAgent:
            raise
        except Exception as e:
            erros.append(f"{g_nome}: {str(e)[:80]}")
    return ok, erros


# ---------------------------------------------------------------
# 8-K: COMUNICADOS DE EVENTOS RELEVANTES
# ---------------------------------------------------------------
ITENS_8K = {
    "1.01": ("Acordo relevante celebrado", "media"), "1.02": ("Fim de um acordo relevante", "media"),
    "1.03": ("Falência ou insolvência", "alta"), "1.05": ("Incidente de cibersegurança relevante", "alta"),
    "2.01": ("Aquisição ou venda de ativos concluída", "media"), "2.02": ("Resultados divulgados", "baixa"),
    "2.03": ("Nova dívida ou obrigação financeira relevante", "media"), "2.04": ("Evento que antecipa o vencimento de dívida", "alta"),
    "2.05": ("Custos de reestruturação ou saída de uma atividade", "media"), "2.06": ("Imparidades (perdas de valor) relevantes", "alta"),
    "3.01": ("Aviso de exclusão da bolsa ou incumprimento das regras de cotação", "alta"),
    "3.02": ("Venda de ações não registada (diluição)", "media"), "3.03": ("Alteração dos direitos dos acionistas", "media"),
    "4.01": ("Mudança de auditor", "alta"), "4.02": ("Contas anteriores deixam de ser fiáveis (reexpressão)", "alta"),
    "5.01": ("Mudança de controlo da empresa", "alta"), "5.02": ("Saída ou entrada de administradores/diretores", "media"),
    "5.03": ("Alteração dos estatutos ou do ano fiscal", "baixa"), "5.07": ("Resultados de votações da assembleia", "baixa"),
    "7.01": ("Divulgação ao mercado (Reg FD), p. ex. apresentações", "baixa"), "8.01": ("Outros eventos", "baixa"),
    "9.01": ("Demonstrações financeiras e anexos", "baixa"),
}
_PESO = {"alta": 3, "media": 2, "baixa": 1}


def eventos(ticker, dias=90, sub_validade=3600):
    """8-K recentes (com os itens traduzidos e a importância). Usa o JSON de submissões (1 pedido, cache 1 h)."""
    c = cik(ticker)
    if not c:
        return {"erro": f"{ticker.upper()} não encontrado na lista da SEC (só empresas cotadas nos EUA)."}
    num, nome = c
    sub = _cache(f"sub_{num}.json", sub_validade, lambda: _get(f"https://data.sec.gov/submissions/CIK{num}.json").json())
    rec = sub.get("filings", {}).get("recent", {})
    limite = (date.today() - timedelta(days=dias)).isoformat()
    out = []
    for i, forma in enumerate(rec.get("form", [])):
        if forma not in ("8-K", "8-K/A"):
            continue
        dia = rec["filingDate"][i]
        if dia < limite:
            break
        cods = [x.strip() for x in (rec.get("items") or [""] * (i + 1))[i].split(",") if x.strip()]
        itens = [{"codigo": k, "nome": ITENS_8K.get(k, ("Item " + k, "baixa"))[0], "nivel": ITENS_8K.get(k, ("", "baixa"))[1]}
                 for k in cods if k != "9.01"]
        nivel = max((x["nivel"] for x in itens), key=lambda n: _PESO[n], default="baixa")
        acc = rec["accessionNumber"][i]
        out.append({"data": dia, "hora": (rec.get("acceptanceDateTime") or [""] * (i + 1))[i][11:16] or None,
                    "forma": forma, "itens": itens, "nivel": nivel,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(num)}/{acc.replace('-', '')}/{rec['primaryDocument'][i]}",
                    "acc": acc})
    return {"ticker": ticker.upper(), "empresa": nome, "eventos": out, "fonte": "SEC EDGAR (formulário 8-K)"}


def eventos_lote(tickers, dias=3):
    """Para os alertas locais do browser: só recebe tickers, não guarda nada. Inclui compras de administradores."""
    res = []
    for t in tickers[:25]:
        try:
            ev = eventos(t, dias=dias)
        except SemUserAgent:
            raise
        except Exception:
            continue
        for e in ev.get("eventos", []):
            if e["nivel"] in ("alta", "media") or any(i["codigo"] == "2.02" for i in e["itens"]):
                res.append({"ticker": ev["ticker"], "empresa": ev["empresa"], **e})
        # Compras em bolsa de administradores (Form 4, código P) nos últimos 10 dias
        try:
            ins = insiders(t, maximo=10)
            lim = (date.today() - timedelta(days=10)).isoformat()
            compras = [x for f in ins.get("formularios", []) if f["data_entrega"] >= lim
                       for x in f["transacoes"] if x["codigo"] == "P" and not x.get("plano_10b5_1")]
            if compras:
                res.append({"ticker": ev.get("ticker", t.upper()), "empresa": ins.get("empresa"), "tipo": "insider",
                            "data": max(x["data"] or "" for x in compras), "n": len(compras),
                            "valor": round(sum(x["valor"] or 0 for x in compras))})
        except Exception:
            pass
    return res


# ---------------------------------------------------------------
# VIGILÂNCIA PARA O DISCORD (lista definida pelo Admin + ações americanas da Liga)
# ---------------------------------------------------------------
ARQ_VIGIA = "sec_vigia.json"


def _ler_json(caminho, omissao):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return omissao


def _gravar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def vigia_config():
    d = _ler_json(ARQ_VIGIA, {})
    return {"tickers": d.get("tickers", []), "incluir_liga": d.get("incluir_liga", True), "nivel_minimo": d.get("nivel_minimo", "media"),
            "vistos": d.get("vistos", []), "ultima": d.get("ultima"), "enviados": d.get("enviados", 0)}


def gravar_vigia(tickers=None, incluir_liga=None, nivel_minimo=None):
    d = _ler_json(ARQ_VIGIA, {})
    if tickers is not None:
        d["tickers"] = sorted({t.strip().upper() for t in tickers if re.fullmatch(r"[A-Z]{1,5}([.\-][A-Z])?", t.strip().upper())})[:60]
    if incluir_liga is not None:
        d["incluir_liga"] = bool(incluir_liga)
    if nivel_minimo in ("alta", "media", "baixa"):
        d["nivel_minimo"] = nivel_minimo
    _gravar_json(ARQ_VIGIA, d)
    return vigia_config()


def _tickers_liga():
    """Ações americanas (sem sufixo de bolsa) nas carteiras da Liga."""
    d = _ler_json("liga_carteiras.json", {})
    achados = set()

    def andar(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() in ("ticker", "ativo", "simbolo") and isinstance(v, str):
                    achados.add(v.strip().upper())
                else:
                    andar(v)
        elif isinstance(x, list):
            for v in x:
                andar(v)
    meses = sorted(k for k in d if re.fullmatch(r"\d{4}-\d{2}", str(k)))[-2:]  # só a edição atual e a anterior
    andar([d[m] for m in meses] if meses else d)
    return sorted(t for t in achados if re.fullmatch(r"[A-Z]{1,5}([.\-][A-Z])?", t))


def _webhook_eventos():
    for v in ("WEBHOOK_EVENTOS", "WEBHOOK_RELATORIO", "WEBHOOK_SNIPER"):
        u = (os.environ.get(v) or "").strip()
        if u:
            return u
    return None


def vigiar(agora):
    """De 30 em 30 min (dias úteis, 11:00–23:59 de Lisboa) procura 8-K novos dos tickers vigiados e publica no Discord."""
    if agora.weekday() >= 5 or agora.hour < 11:
        return
    cfg = vigia_config()
    if cfg["ultima"] and time.time() - cfg["ultima"] < 1800:
        return
    tickers = list(cfg["tickers"]) + (_tickers_liga() if cfg["incluir_liga"] else [])
    tickers = sorted(set(tickers))[:60]
    d = _ler_json(ARQ_VIGIA, {})
    d["ultima"] = time.time()
    _gravar_json(ARQ_VIGIA, d)
    if not tickers or not (os.environ.get("SEC_USER_AGENT") or "").strip():
        return
    vistos = set(d.get("vistos", []))
    primeira_vez = not d.get("semeado")  # 1.ª execução: memoriza o que já existe sem publicar
    minimo = _PESO[cfg["nivel_minimo"]]
    novos = []
    for t in tickers:
        try:
            ev = eventos(t, dias=4, sub_validade=1500)
        except Exception:
            continue
        for e in ev.get("eventos", []):
            if e["acc"] in vistos:
                continue
            vistos.add(e["acc"])
            if not primeira_vez and _PESO[e["nivel"]] >= minimo:
                novos.append({"ticker": ev["ticker"], "empresa": ev["empresa"], **e})
    d = _ler_json(ARQ_VIGIA, {})
    d["vistos"] = sorted(vistos)[-3000:]
    d["semeado"] = True
    url = _webhook_eventos()
    if novos and url:
        icone = {"alta": "🔴", "media": "🟡", "baixa": "⚪"}
        campos = [{"name": f"{icone[e['nivel']]} {e['ticker']} · {e['empresa']}"[:256],
                   "value": ("\n".join(f"• {i['nome']}" for i in e["itens"]) or "• Comunicado 8-K") + f"\n[Ler na SEC]({e['url']})", "inline": False}
                  for e in novos[:10]]
        try:
            requests.post(url, json={"embeds": [{"title": "📰 Comunicados relevantes à SEC (8-K)", "color": 15105570, "fields": campos,
                                                 "footer": {"text": "Fonte: SEC EDGAR · Informação educativa, não é recomendação de investimento"}}]}, timeout=15)
            d["enviados"] = d.get("enviados", 0) + len(novos[:10])
        except Exception as e:
            print(f"[sec] Discord 8-K falhou: {e}")
    _gravar_json(ARQ_VIGIA, d)


_ultima_13f = {"dia": None}


def diario(agora):
    """Às 04:00 atualiza os 13F (só traz entregas novas; as antigas ficam em cache) e corre a vigilância de 8-K."""
    try:
        vigiar(agora)
    except Exception as e:
        print(f"[sec] vigilância 8-K: {e}")
    if agora.hour == 5 and _ultima_13f.get("ftd") != agora.date() and (os.environ.get("SEC_USER_AGENT") or "").strip():
        _ultima_13f["ftd"] = agora.date()
        try:
            ok, msg = atualizar_ftd()
            print(f"[sec] fails-to-deliver: {msg}")
        except Exception as e:
            print(f"[sec] fails-to-deliver falhou: {e}")
    if agora.hour == 4 and _ultima_13f["dia"] != agora.date() and (os.environ.get("SEC_USER_AGENT") or "").strip():
        _ultima_13f["dia"] = agora.date()
        try:
            ok, erros = atualizar_13f()
            print(f"[sec] 13F: {ok} gestores atualizados" + (f"; erros: {'; '.join(erros)}" if erros else ""))
        except Exception as e:
            print(f"[sec] 13F falhou: {e}")


# ---------------------------------------------------------------
# 13D / 13G: QUEM TEM MAIS DE 5% (E OS ACIONISTAS ATIVISTAS)
# ---------------------------------------------------------------
def _ler_13dg(xml):
    """Formato XML da SEC (desde dezembro de 2024): nomes, % do capital, data do evento e, no 13D, o objetivo."""
    t = xml.decode("utf-8", "replace") if isinstance(xml, bytes) else xml
    g = lambda n: [html.unescape(x.strip()) for x in re.findall(rf"<{n}>([^<]*)</{n}>", t)]
    nomes = list(dict.fromkeys(g("reportingPersonName") or g("filingPersonName")))
    pcts = [float(x) for x in (g("percentOfClass") or g("classPercent")) if re.fullmatch(r"[0-9.]+", x or "")]
    evento = (g("dateOfEvent") or g("eventDateRequiresFilingThisStatement") or [None])[0]
    if evento and re.fullmatch(r"\d{2}/\d{2}/\d{4}", evento):
        evento = f"{evento[6:]}-{evento[:2]}-{evento[3:5]}"
    objetivo = re.sub(r"\s+", " ", (g("transactionPurpose") or [""])[0])[:600] or None
    return {"detentores": nomes[:4], "pct": max(pcts) if pcts else None, "evento": evento, "objetivo": objetivo}


def grandes_acionistas(ticker, meses=24, maximo=25):
    """Últimos formulários 13D/13G (e alterações) sobre a empresa: quem passou os 5% e com que intenção."""
    c = cik(ticker)
    if not c:
        return {"erro": f"{ticker.upper()} não encontrado na lista da SEC (só empresas cotadas nos EUA)."}
    num, nome = c
    sub = _cache(f"sub_{num}.json", 86400, lambda: _get(f"https://data.sec.gov/submissions/CIK{num}.json").json())
    rec = sub.get("filings", {}).get("recent", {})
    limite = (date.today() - timedelta(days=meses * 31)).isoformat()
    out = []
    for i, forma in enumerate(rec.get("form", [])):
        if not re.match(r"^(SC 13[DG]|SCHEDULE 13[DG])(/A)?$", forma):
            continue
        dia = rec["filingDate"][i]
        if dia < limite:
            break
        acc = rec["accessionNumber"][i]
        pasta = f"https://www.sec.gov/Archives/edgar/data/{int(num)}/{acc.replace('-', '')}"
        doc = re.sub(r"^xsl[^/]+/", "", rec["primaryDocument"][i])
        item = {"data": dia, "forma": forma, "ativista": "13D" in forma, "alteracao": forma.endswith("/A"),
                "url": f"{pasta}/{rec['primaryDocument'][i]}", "detentores": [], "pct": None, "evento": None, "objetivo": None}
        if doc.lower().endswith(".xml"):
            try:
                item.update(_cache(f"13dg_{acc}.json", None, lambda: _ler_13dg(_get(f"{pasta}/{doc}", "application/xml").content)))
            except Exception:
                pass
        out.append(item)
        if len(out) >= maximo:
            break
    return {"ticker": ticker.upper(), "empresa": nome, "filings": out, "fonte": "SEC EDGAR (Schedule 13D/13G)"}


# ---------------------------------------------------------------
# FAILS-TO-DELIVER (ações vendidas que não foram entregues na data de liquidação)
# ---------------------------------------------------------------
ARQ_FTD = "sec_ftd.json"
PAGINA_FTD = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
_ftd_mem = {"t": 0, "d": None}


def atualizar_ftd(forcar=False):
    """Descarrega os 2 ficheiros mais recentes (cada um cobre meio mês; saem com ~2 semanas de atraso)."""
    import zipfile
    d = _ler_json(ARQ_FTD, {})
    pag = _get(PAGINA_FTD, "text/html").text
    links = re.findall(r'href="([^"]*cnsfails(\d{6}[ab])\.zip)"', pag)
    if not links:
        raise RuntimeError("Não encontrei ficheiros na página da SEC (mudou o formato?).")
    links = sorted({(p, u) for u, p in links}, reverse=True)[:2]
    periodos = [p for p, _ in links]
    if not forcar and d.get("periodos") == periodos:
        return True, f"Já tinha os períodos {', '.join(periodos)}."
    dados = {}
    for periodo, url in links:
        url = url if url.startswith("http") else "https://www.sec.gov" + url
        z = zipfile.ZipFile(io.BytesIO(_get(url, "application/zip").content))
        texto = z.read(z.namelist()[0]).decode("latin-1")
        linhas = texto.splitlines()
        cab = [c.strip().upper() for c in linhas[0].split("|")]
        col = lambda chave: next(i for i, c in enumerate(cab) if chave in c)
        i_d, i_s, i_q, i_p, i_n = col("SETTLEMENT"), col("SYMBOL"), col("QUANTITY"), col("PRICE"), col("DESCRIPTION")
        for l in linhas[1:]:
            p = l.split("|")
            if len(p) <= max(i_d, i_s, i_q, i_p):
                continue
            try:
                q = int(p[i_q])
                preco = float(p[i_p]) if p[i_p].strip() not in ("", ".") else None
            except ValueError:
                continue
            dia = p[i_d].strip()
            dados.setdefault(p[i_s].strip().upper(), {"nome": p[i_n].strip(), "dias": []})["dias"].append(
                [f"{dia[:4]}-{dia[4:6]}-{dia[6:8]}", q, preco])
    for v in dados.values():
        v["dias"] = sorted({d[0]: d for d in v["dias"]}.values())  # um registo por dia (ficheiros podem sobrepor-se)
    # Ranking pelo valor máximo num só dia (quantidade × preço)
    ranking = sorted(((sym, max((q * (pr or 0) for _, q, pr in v["dias"]), default=0), v["nome"]) for sym, v in dados.items()),
                     key=lambda x: -x[1])[:25]
    novo = {"periodos": periodos, "dados": dados, "ranking": [{"ticker": t, "valor_max": round(val), "nome": n} for t, val, n in ranking],
            "atualizado_em": datetime.now().isoformat(timespec="seconds")}
    _gravar_json(ARQ_FTD, novo)
    _ftd_mem.update({"t": 0, "d": None})
    return True, f"{len(dados)} títulos nos períodos {', '.join(periodos)}."


def _ftd_dados():
    if _ftd_mem["d"] is None or time.time() - _ftd_mem["t"] > 3600:
        _ftd_mem.update({"t": time.time(), "d": _ler_json(ARQ_FTD, {})})
    return _ftd_mem["d"]


def ftd(ticker):
    d = _ftd_dados()
    t = ticker.upper().replace("-", ".")
    v = (d.get("dados") or {}).get(t) or (d.get("dados") or {}).get(ticker.upper())
    base = {"ticker": ticker.upper(), "periodos": d.get("periodos") or [], "fonte": "SEC (Fails-to-Deliver)"}
    if not v:
        return {**base, "dias": []}
    dias = [{"data": dt, "acoes": q, "preco": pr, "valor": round(q * pr) if pr else None} for dt, q, pr in v["dias"]]
    return {**base, "nome": v["nome"], "dias": dias, "max": max(dias, key=lambda x: x["acoes"])}


def ranking_ftd():
    d = _ftd_dados()
    return {"periodos": d.get("periodos") or [], "ranking": d.get("ranking") or [], "atualizado_em": d.get("atualizado_em")}


def testar():
    """Para a Gestão: confirma se o servidor consegue falar com a SEC."""
    try:
        c = cik("AAPL")
        return {"ok": bool(c), "msg": "SEC acessível." if c else "Lista de tickers vazia."}
    except SemUserAgent as e:
        return {"ok": False, "msg": str(e)}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}
