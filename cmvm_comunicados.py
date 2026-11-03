"""
cmvm_comunicados.py — Comunicados oficiais das cotadas portuguesas no Sistema de Difusão de Informação da CMVM:

    TRAN → Transações de dirigentes (administradores e pessoas próximas que compram/vendem ações da empresa)
    PQ   → Participações qualificadas, posições longas e acordos parassociais (quem passa os 5%, 10%, 20%...)
    ACPR → Transações de ações próprias (a empresa a comprar as suas ações: programas de recompra)

A página da CMVM é uma aplicação OutSystems; o serviço que alimenta a lista aceita visitantes anónimos (o mesmo
mecanismo já usado para as posições curtas). Só se guardam a data, o emitente, a descrição e a ligação para o PDF
oficial: os montantes e preços estão dentro do PDF e não são copiados.

Atualização: dias úteis, de hora a hora entre as 08:00 e as 22:00 (pedido pequeno: só os mais recentes). Na 1.ª vez
descarrega os últimos 300 de cada tipo (cerca de ano e meio). Ficheiro: cmvm_comunicados.json.
"""

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests

import posicoes_curtas as pc  # reaproveita a sessão anónima da CMVM, o token e a normalização de nomes

ARQ = "cmvm_comunicados.json"
ACAO = ("CMVM_SDI_Emitentes_CW/Relatorios/Relatorio_NewFileLink/DataActionGetReports",
        "CMVM_SDI_Emitentes_CW.Relatorios.Relatorio_NewFileLink.mvc.js", "XaBV1wKS0jvMjPx600o31A")
TIPOS = {
    "TRAN": "Transações de dirigentes",
    "PQ": "Participações qualificadas",
    "ACPR": "Ações próprias",
}
PAGINA = "https://www.cmvm.pt/PInstitucional/ContentSDI?Input=FD05DCC30588AE3CDF55203FDCBD0083C8CDE10F359812BF0AFBE7CC680C5DFA"
_lock = threading.Lock()
_diag = {}


def _ler(omissao=None):
    try:
        with open(ARQ, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return omissao if omissao is not None else {"tipos": {}, "atualizado_em": None}


def _gravar(d):
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, ARQ)


def _sessao():
    s = requests.Session()
    s.headers.update({**pc.UA, "Content-Type": "application/json; charset=UTF-8", "Accept": "application/json",
                      "X-CSRFToken": pc.CMVM_CSRF_ANONIMO, "OutSystems-locale": "pt-PT"})
    mv = s.get(f"{pc.CMVM_BASE}/moduleservices/moduleversioninfo?{int(time.time() * 1000)}", timeout=30).json()["versionToken"]
    return s, mv, pc._cmvm_api_version(s, ACAO)


def _pedir(s, mv, versao, tipo, n):
    corpo = {"versionInfo": {"moduleVersion": mv, "apiVersion": versao}, "viewName": "ContentSplit.ContentSDI",
             "screenData": {"variables": {
                 "StartIndex": 0, "MaxRecords": n,
                 "Reports_List": {"List": [], "EmptyListItem": {"ID": 0, "Time": "", "DATA_FACT": "1900-01-01", "DSC_FACT": "",
                                                                "PDF_FACT": "", "IsZip": False, "IsEN": False, "EncryptedURL": ""}},
                 "IsLoading": True, "LanguageId": "1", "_languageIdInDataFetchStatus": 1,
                 "Tipo_de_Facto": tipo, "_tipo_de_FactoInDataFetchStatus": 1,
                 "EntitiesList": "", "_entitiesListInDataFetchStatus": 1,
                 "StartDate": "1900-01-01", "_startDateInDataFetchStatus": 1, "EndDate": "1900-01-01", "_endDateInDataFetchStatus": 1,
                 "GetLanguage": {"Language": {"PortugueseId": 0, "EnglishId": 2}, "DataFetchStatus": 1}}}}
    r = s.post(f"{pc.CMVM_BASE}/screenservices/{ACAO[0]}", data=json.dumps(corpo), timeout=90)
    if r.status_code != 200:
        _diag["cmvm"] = f"HTTP {r.status_code}: {r.text[:300]}"
        raise RuntimeError(f"CMVM respondeu {r.status_code}")
    try:
        return r.json()["data"]["ReportsList"]["List"]
    except Exception:
        _diag["cmvm"] = r.text[:300]
        raise RuntimeError("Resposta da CMVM em formato inesperado (ver diagnóstico).")


_RE_EMITENTE = re.compile(r"^(.*?)\s+(informa|informs|comunica|divulga|anuncia)\b", re.I)


def _sentido(tipo, texto):
    t = pc._sem_acentos(texto)
    if tipo == "PQ":
        if re.search(r"reduc|diminui|abaixo|inferior|alienac|venda", t):
            return "desce"
        if re.search(r"aument|ultrapass|superior|aquisic|adquir|compra", t):
            return "sobe"
        return None
    if re.search(r"\bvend|alienac|aliena", t):
        return "venda"
    if re.search(r"\bcompr|aquisic|adquir|subscric", t):
        return "compra"
    return None


def _item(tipo, x):
    desc = (x.get("DSC_FACT") or "").strip()
    m = _RE_EMITENTE.match(desc)
    emitente = m.group(1).strip(" ,-") if m else desc.split(" ")[0]
    resto = desc[m.end():].strip() if m else desc
    return {"id": x.get("ID"), "tipo": tipo, "data": (x.get("DATA_FACT") or "")[:10], "hora": x.get("Time") or None,
            "emitente": emitente, "descricao": desc, "resumo": re.sub(r"^(sobre|que|a)\s+", "", resto, flags=re.I),
            "sentido": _sentido(tipo, desc), "url": x.get("EncryptedURL") or None}


def atualizar(forcar=False, completo=None):
    """Junta os comunicados novos aos guardados (por ID). Devolve (ok, mensagem)."""
    with _lock:
        d = _ler()
        if completo is None:
            completo = forcar or not d.get("tipos")
        s, mv, versao = _sessao()
        novos, contagem = 0, {}
        for tipo in TIPOS:
            lista = _pedir(s, mv, versao, tipo, 300 if completo else 40)
            existentes = {i["id"]: i for i in d["tipos"].get(tipo, [])}
            for x in lista:
                if x.get("IsEN"):
                    continue  # versão inglesa do mesmo comunicado
                it = _item(tipo, x)
                if it["id"] not in existentes:
                    novos += 1
                    it["visto_em"] = datetime.now().isoformat(timespec="seconds")
                existentes.setdefault(it["id"], it)
            limite = (date.today() - timedelta(days=730)).isoformat()
            d["tipos"][tipo] = sorted([i for i in existentes.values() if i["data"] >= limite],
                                      key=lambda i: (i["data"], i.get("hora") or "", i["id"] or 0), reverse=True)
            contagem[tipo] = len(d["tipos"][tipo])
            time.sleep(1)
        d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(d)
        return True, f"{novos} novos · guardados: " + ", ".join(f"{TIPOS[k].lower()} {v}" for k, v in contagem.items()) + "."


def _corresponde(emitente, alvos):
    n = pc.normalizar_nome(emitente)
    return any(a and ((" " + a + " ") in (" " + n + " ") or (len(n) >= 4 and (" " + n + " ") in (" " + a + " "))) for a in alvos)


# Tickers da Euronext Lisboa → nome usado nos comunicados (a pesquisa também aceita o nome diretamente)
ALIASES = {
    "BCP": "Banco Comercial Português", "EDP": "EDP - Energias de Portugal", "EDPR": "EDP Renováveis", "GALP": "Galp Energia",
    "JMT": "Jerónimo Martins", "NOS": "NOS", "SON": "Sonae", "CTT": "CTT - Correios de Portugal", "NVG": "Navigator",
    "ALTR": "Altri", "SEM": "Semapa", "RENE": "REN - Redes Energéticas Nacionais", "EGL": "Mota-Engil", "COR": "Corticeira Amorim",
    "IBS": "Ibersol", "PHR": "Pharol", "RAM": "Ramada", "VAF": "Vista Alegre Atlantis", "GVOLT": "Greenvolt", "SNC": "Sonaecom",
    "TDSA": "Teixeira Duarte", "ESON": "Estoril-Sol", "GPA": "Grão-Pará", "SCP": "Sporting", "SLBEN": "Benfica", "FCP": "Futebol Clube do Porto",
    "NBA": "Novabase", "MAR": "Martifer", "LIG": "Lisgráfica", "INA": "Inapa", "CFN": "Cofina", "IPR": "Impresa", "MRL": "Media Capital",
}


def painel(q="", nomes_extra=(), tipo=None, dias=60):
    d = _ler()
    t_q = re.sub(r"\.LS$", "", (q or "").strip().upper())
    if t_q in ALIASES:
        nomes_extra = (*nomes_extra, ALIASES[t_q])
    out = {"atualizado_em": d.get("atualizado_em"), "fonte": "CMVM — Sistema de Difusão de Informação", "pagina": PAGINA,
           "tipos": TIPOS, "itens": []}
    alvos = {pc.normalizar_nome(x) for x in (q, *nomes_extra) if x and len(pc.normalizar_nome(x)) >= 3}
    limite = (date.today() - timedelta(days=dias if not alvos else 730)).isoformat()
    for t, lista in (d.get("tipos") or {}).items():
        if tipo and t != tipo:
            continue
        for i in lista:
            if i["data"] < limite:
                continue
            if alvos and not _corresponde(i["emitente"], alvos):
                continue
            out["itens"].append(i)
    out["itens"].sort(key=lambda i: (i["data"], i.get("hora") or ""), reverse=True)
    out["itens"] = out["itens"][:150]
    # Quem mais comunicou nos últimos 90 dias (sem pesquisa)
    if not alvos:
        lim90 = (date.today() - timedelta(days=90)).isoformat()
        cont = {}
        for t, lista in (d.get("tipos") or {}).items():
            for i in lista:
                if i["data"] >= lim90:
                    c = cont.setdefault(i["emitente"], {"emitente": i["emitente"], "TRAN": 0, "PQ": 0, "ACPR": 0})
                    c[t] = c.get(t, 0) + 1
        out["mais_ativos"] = sorted(cont.values(), key=lambda c: -(c["TRAN"] * 2 + c["PQ"] * 2 + c["ACPR"]))[:10]
    return out


def novos_desde(iso):
    """Comunicados vistos pela 1.ª vez depois de um instante (para o Briefing PSI e o Discord)."""
    d = _ler()
    return [i for lista in (d.get("tipos") or {}).values() for i in lista if (i.get("visto_em") or "") > iso]


# ---------------------------------------------------------------
# AGENDADOR E DISCORD
# ---------------------------------------------------------------
_ultima = {"t": 0}


def _webhook():
    for v in ("WEBHOOK_CMVM", "WEBHOOK_RELATORIO_PSI"):
        u = (os.environ.get(v) or "").strip()
        if u:
            return u
    return None


def diario(agora):
    vazio = not _ler().get("tipos")
    if not vazio and (agora.weekday() >= 5 or not 8 <= agora.hour <= 22):
        return
    if time.time() - _ultima["t"] < 3600:
        return
    _ultima["t"] = time.time()
    antes = datetime.now().isoformat(timespec="seconds")
    try:
        ok, msg = atualizar()
        if not msg.startswith("0 novos"):
            print(f"[cmvm] {msg}")
    except Exception as e:
        print(f"[cmvm] comunicados falharam: {e}")
        if not vazio and agora.hour >= 12:
            import alertas_admin as aa
            aa.avisar(f"cmvm-comunicados:{agora.date()}", "CMVM: a leitura dos comunicados falhou", str(e)[:300], "aviso")
        return
    if vazio:
        return  # 1.ª carga: não publica o histórico no Discord
    novos = [i for i in novos_desde(antes) if i["tipo"] in ("TRAN", "PQ") and i["data"] >= (agora.date() - timedelta(days=3)).isoformat()]
    url = _webhook()
    if not novos or not url:
        return
    icone = {"TRAN": "👔", "PQ": "🏛️"}
    seta = {"compra": "🟢 ", "venda": "🔴 ", "sobe": "⬆️ ", "desce": "⬇️ "}
    campos = [{"name": f"{icone[i['tipo']]} {i['emitente']}"[:256],
               "value": f"{seta.get(i['sentido'], '')}{i['descricao']}"[:900] + (f"\n[Abrir o comunicado]({i['url']})" if i.get("url") else ""),
               "inline": False} for i in novos[:10]]
    try:
        requests.post(url, json={"embeds": [{"title": "🇵🇹 Novos comunicados na CMVM: dirigentes e participações qualificadas",
                                             "color": 3447003, "fields": campos,
                                             "footer": {"text": "Fonte: CMVM · Informação educativa, não é recomendação de investimento"}}]}, timeout=15)
    except Exception as e:
        print(f"[cmvm] Discord falhou: {e}")


def testar():
    try:
        ok, msg = atualizar(forcar=True)
        return {"ok": ok, "msg": msg}
    except Exception as e:
        r = {"ok": False, "msg": str(e)[:300]}
        if _diag.get("cmvm"):
            r["diagnostico"] = _diag["cmvm"]
        return r


def estado():
    d = _ler()
    return {"atualizado_em": d.get("atualizado_em"), "n": {k: len(v) for k, v in (d.get("tipos") or {}).items()},
            "ultimo": max((v[0]["data"] for v in (d.get("tipos") or {}).values() if v), default=None)}
