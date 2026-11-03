"""
posicoes_curtas.py — Posições curtas (vendas a descoberto) por cotada.

EUROPA (por detentor): pelo Regulamento (UE) 236/2012, cada regulador publica as posições curtas líquidas
iguais ou superiores a 0,5% do capital, com o nome do detentor. Lemos os ficheiros/páginas oficiais de:
    PT CMVM · ES CNMV · FR AMF · DE Bundesanzeiger (BaFin) · IT Consob · NL AFM
Os endereços ficam em posicoes_curtas_fontes.json e podem ser corrigidos na Área de Gestão sem mexer no
código. Se um regulador só disponibilizar o ficheiro manualmente, o Admin pode carregá-lo na Gestão.
O leitor é genérico: reconhece as colunas (detentor, emitente, ISIN, %, data) pelos nomes em PT/EN/FR/DE/IT/ES/NL.

EUA (total, sem nomes): a FINRA publica duas vezes por mês o «short interest» consolidado (ações vendidas a
descoberto e ainda não recompradas), com dias para cobrir.

Atualização: uma vez por dia (agendador). As pesquisas leem só a cópia local (posicoes_curtas.json).
"""

import csv
import io
import json
import os
import re
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta

import requests

ARQ_DADOS = "posicoes_curtas.json"
ARQ_FONTES = "posicoes_curtas_fontes.json"
PASTA_MANUAL = "posicoes_curtas_manual"
UA = {"User-Agent": "Mozilla/5.0 (PortalBolsa; dados educativos)", "Accept": "*/*"}
LIMIAR = 0.5
_lock = threading.Lock()

FONTES_INICIAIS = {
    "PT": {"nome": "CMVM (Portugal)", "url": "", "tipo": "cmvm",
           "pagina": "https://www.cmvm.pt/PInstitucional/Content?Input=EBFFB649F6E814A9FF14425A585ADD6EA3C5815FA2332671623D5BE5A91518E4", "ativa": True,
           "nota": "Lido diretamente do serviço de dados da página «Interesses a descoberto relevantes» da CMVM (não precisa de endereço)."},
    "ES": {"nome": "CNMV (Espanha)", "url": "https://www.cnmv.es/DocPortal/Posiciones-Cortas/NetShortPositions.xls",
           "pagina": "https://www.cnmv.es/portal/consultas/busqueda.aspx?id=29", "ativa": True, "lembrete_dias": 7,
           "instrucoes": ["Abre a página oficial da CNMV «Posiciones cortas» (botão abaixo).",
                          "Clica em «Fichero descargable con las posiciones cortas netas publicadas e históricas» (ficheiro NetShortPositions.xls).",
                          "Aqui, carrega em «Carregar» e escolhe esse ficheiro."]},
    "FR": {"nome": "AMF (França)", "url": "https://www.data.gouv.fr/fr/datasets/r/c2539d1c-8531-4937-9cba-3bd8e9786cc5",
           "pagina": "https://www.amf-france.org/fr/actualites-publications/dossiers-thematiques/ventes-decouvert", "ativa": True},
    "DE": {"nome": "Bundesanzeiger / BaFin (Alemanha)", "url": "https://www.bundesanzeiger.de/pub/de/nlp?0--top~csv~form~panel-form-csv~resource~link",
           "pagina": "https://www.bundesanzeiger.de/pub/de/nlp", "sessao": "https://www.bundesanzeiger.de/pub/de/nlp", "ativa": True},
    "IT": {"nome": "Consob (Itália)", "url": "https://www.consob.it/documents/11973/395154/PncPubbl.xlsx/fbefe0a2-795b-bad3-9369-beccbeb14f27",
           "pagina": "https://www.consob.it/web/area-pubblica/pnc", "lembrete_dias": 7, "ativa": True,
           "nota": "O site da Consob tem uma proteção anti-robô (captcha). O portal tenta o ficheiro direto; se for bloqueado, usa o último ficheiro que carregaste e lembra-te de o atualizar.",
           "instrucoes": ["Abre a página oficial da Consob (botão abaixo) e, se aparecer, resolve o captcha.",
                          "Na caixa «Elenco delle PNC», clica em «Scarica il file Excel delle PNC» (ficheiro PncPubbl.xlsx).",
                          "Aqui, carrega em «Carregar» e escolhe esse ficheiro. A Consob atualiza todos os dias; basta fazê-lo uma vez por semana."]},
    "NL": {"nome": "AFM (Países Baixos)", "url": "https://www.afm.nl/export.aspx?type=8a46a4ef-f196-4467-a7ab-1ae1cb58f0e7&format=csv",
           "pagina": "https://www.afm.nl/en/sector/registers/meldingenregisters/netto-shortposities-actueel", "ativa": True},
}

# Palavras que identificam cada coluna (comparadas sem acentos e em minúsculas)
COLUNAS = {
    "detentor": ["position holder", "holder", "detentor", "titular", "detenteur", "positionsinhaber", "inhaber", "detentore",
                 "tenedor", "houder", "positie houder", "nome do detentor", "nom du detenteur", "denominazione detentore", "short seller"],
    "emitente": ["name of the issuer", "issuer", "emitente", "emittente", "emetteur", "emittent", "emisor", "uitgevende",
                 "company", "societe", "sociedade", "nome do emitente", "nom de l'emetteur", "denominazione emittente", "aktie"],
    "isin": ["isin"],
    "pct": ["net short position", "posicao curta", "position courte", "netto-leerverkaufsposition", "posizione netta corta",
            "posizione", "posicion corta", "netto shortpositie", "% ", "(%)", "percentage", "percentagem", "pourcentage", "prozent",
            "ratio", "position", "liquida curta", "curta liquida", "posicao liquida", "short position", "netta corta", "posicion neta"],
    "data": ["position date", "data da posicao", "date de debut", "date de la position", "datum", "data della posizione",
             "fecha de la posicion", "positiedatum", "date", "data", "fecha"],
}


def _sem_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t)) if not unicodedata.combining(c)).lower().strip()


def normalizar_nome(t):
    """Nome de emitente comparável: sem acentos, pontuação e formas jurídicas."""
    t = _sem_acentos(t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    for forma in (" sgps", " s a", " sa", " nv", " n v", " ag", " se", " spa", " s p a", " plc", " inc", " ltd", " oyj",
                  " ab", " asa", " group", " holding", " holdings", " corporation", " corp", " co"):
        t = re.sub(rf"{forma}\b", " ", " " + t)
    return re.sub(r"\s+", " ", t).strip()


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


def fontes():
    f = _ler(ARQ_FONTES, None)
    if not f:
        f = json.loads(json.dumps(FONTES_INICIAIS))
        _gravar(ARQ_FONTES, f)
    for k, v in FONTES_INICIAIS.items():  # novas fontes acrescentadas em versões futuras
        f.setdefault(k, json.loads(json.dumps(v)))
    # Migrações: CMVM passa a usar o serviço de dados; Consob passa a modo manual com lembrete
    alterado = False
    if f["PT"].get("tipo") != "cmvm" and not f["PT"].get("tipo_definido_admin"):
        f["PT"].update({k: FONTES_INICIAIS["PT"][k] for k in ("url", "tipo", "nota")})
        alterado = True
    for pais in ("ES", "IT"):
        if f[pais].get("instrucoes") != FONTES_INICIAIS[pais]["instrucoes"]:
            f[pais].pop("procurar_xlsx", None)
            f[pais].pop("modo", None)
            f[pais].update({k: v for k, v in FONTES_INICIAIS[pais].items() if k not in ("ativa",)})
            alterado = True
    if alterado:
        _gravar(ARQ_FONTES, f)
    return f


def gravar_fonte(pais, url=None, ativa=None):
    f = fontes()
    if pais not in f:
        raise ValueError("País desconhecido.")
    if url is not None:
        if url and not url.startswith("https://"):
            raise ValueError("O endereço tem de começar por https://")
        f[pais]["url"] = url.strip()
    if ativa is not None:
        f[pais]["ativa"] = bool(ativa)
    _gravar(ARQ_FONTES, f)


# ---------------------------------------------------------------
# LEITURA GENÉRICA DE TABELAS
# ---------------------------------------------------------------
def _num(v):
    if v is None:
        return None
    t = str(v).strip().replace("%", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _data(v):
    if v is None or v == "":
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    t = str(v).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return "-".join(m.groups())
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", t)
    if m:
        d, mth, a = m.groups()
        return f"{a}-{int(mth):02d}-{int(d):02d}"
    m = re.search(r"(\d{1,2}) ([a-zA-Z]{3})[a-z]* (\d{4})", t)
    if m:
        meses = {"jan": 1, "feb": 2, "fev": 2, "fév": 2, "mar": 3, "mrt": 3, "apr": 4, "abr": 4, "avr": 4, "may": 5, "mai": 5, "mei": 5,
                 "jun": 6, "jul": 7, "aug": 8, "ago": 8, "aoû": 8, "sep": 9, "set": 9, "oct": 10, "out": 10, "okt": 10, "ott": 10,
                 "nov": 11, "dec": 12, "dez": 12, "déc": 12, "dic": 12}
        mm = meses.get(m.group(2).lower())
        if mm:
            return f"{m.group(3)}-{mm:02d}-{int(m.group(1)):02d}"
    return None


def _mapear_colunas(cabecalho):
    norm = [_sem_acentos(c) for c in cabecalho]
    norm = [c if c.strip() != "%" else "(%)" for c in norm]  # cabeçalho só com «%»
    mapa = {}
    for campo in ("isin", "detentor", "emitente", "pct", "data"):
        for i, c in enumerate(norm):
            if i in mapa.values():
                continue
            if any(p in c for p in COLUNAS[campo]):
                # "data" não pode ser apanhada pela palavra "date" de "position date" já usada… nem a % pela data
                if campo == "pct" and ("date" in c or "data" in c or "datum" in c or "fecha" in c):
                    continue
                mapa[campo] = i
                break
    return mapa if {"emitente", "pct"} <= set(mapa) or {"isin", "pct"} <= set(mapa) else None


def _linhas_para_posicoes(linhas, pais):
    """linhas = lista de listas (1.ª linha útil = cabeçalho). Procura o cabeçalho nas primeiras 15 linhas."""
    for i, cab in enumerate(linhas[:40]):
        mapa = _mapear_colunas([str(c or "") for c in cab])
        if not mapa:
            continue
        out = []
        for l in linhas[i + 1:]:
            get = lambda campo: (l[mapa[campo]] if campo in mapa and mapa[campo] < len(l) else None)
            pct = _num(get("pct"))
            emit = str(get("emitente") or "").strip()
            isin = str(get("isin") or "").strip().upper()
            if pct is None or not (emit or isin):
                continue
            out.append({"pais": pais, "detentor": str(get("detentor") or "").strip() or "—", "emitente": emit or isin,
                        "isin": isin if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin) else "", "pct": round(pct, 2),
                        "data": _data(get("data"))})
        if out:
            return out
    return []


_ultimo_diag = {}


def _amostra(linhas, n=4):
    out = []
    for l in linhas[:n]:
        celulas = [str(c).strip()[:40] for c in l if str(c).strip()]
        if celulas:
            out.append(" | ".join(celulas)[:240])
    return out


def _ler_conteudo(conteudo, tipo, pais):
    """Aceita CSV (, ; tab), XLSX/XLS e HTML com tabelas. Guarda uma amostra para diagnóstico."""
    _ultimo_diag[pais] = {"bytes": len(conteudo), "tipo": tipo, "inicio": conteudo[:160].decode("latin-1", "replace")}
    return _ler_conteudo_(conteudo, tipo, pais)


def _ler_conteudo_(conteudo, tipo, pais):
    cab = conteudo[:8]
    if cab.startswith(b"PK") or cab.startswith(b"\xd0\xcf\x11\xe0") or "spreadsheet" in tipo or "excel" in tipo:
        import pandas as pd
        motor = None
        if cab.startswith(b"\xd0\xcf\x11\xe0"):  # .xls antigo (ex.: CNMV): precisa do pacote xlrd
            try:
                import xlrd  # noqa: F401
            except ImportError:
                raise RuntimeError("Ficheiro .xls antigo: falta o pacote «xlrd» no servidor (acrescenta xlrd ao requirements.txt).")
            motor = "xlrd"
        # Vê primeiro os nomes das folhas e lê SÓ a das posições atuais (ex.: CNMV «Última - Current»).
        # Ler o livro inteiro (anos de histórico) gasta muita memória e pode derrubar o servidor.
        livro = pd.ExcelFile(io.BytesIO(conteudo), engine=motor)
        nomes = livro.sheet_names
        atuais = [n for n in nomes if re.search(r"current|actual|[uú]ltima|attual|aktuell|vigent", str(n), re.I)]
        escolhidas = atuais or nomes[:3]
        _ultimo_diag[pais]["folhas_no_livro"] = [str(n) for n in nomes]
        folhas = {n: livro.parse(n, header=None) for n in escolhidas}
        livro.close()
        out = []
        _ultimo_diag[pais]["folhas"] = {}
        for nome, df in folhas.items():
            linhas = df.fillna("").values.tolist()
            _ultimo_diag[pais]["folhas"][str(nome)] = _amostra(linhas)
            out.extend(_linhas_para_posicoes(linhas, pais))
        return out
    texto = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        return []
    if "<html" in texto[:600].lower() and "<table" not in texto.lower():
        # Página sem tabela: os dados devem ser carregados por JavaScript a partir de outro endereço.
        _ultimo_diag[pais]["pagina_sem_tabela"] = True
        _ultimo_diag[pais]["scripts"] = re.findall(r'<script[^>]+src="([^"]+)"', texto, re.I)[:10]
        _ultimo_diag[pais]["urls"] = list(dict.fromkeys(re.findall(r'["\'](/[A-Za-z0-9_./?=&%-]{6,}|https?://[^"\' ]{8,})["\']', texto)))[:25]
        _ultimo_diag[pais]["iframes"] = re.findall(r'<iframe[^>]+src="([^"]+)"', texto, re.I)[:5]
        visivel = re.sub(r"<script.*?</script>|<style.*?</style>", " ", texto, flags=re.S | re.I)
        _ultimo_diag[pais]["texto"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", visivel)).strip()[:500]
        return []
    if "<table" in texto.lower():
        out = []
        tabelas = _tabelas_html(texto)
        _ultimo_diag[pais]["tabelas_html"] = [_amostra(t, 3) for t in tabelas[:4]]
        _ultimo_diag[pais]["n_tabelas"] = len(tabelas)
        if not tabelas:
            # Página sem tabela: pode carregar os dados por JavaScript ou ter links para ficheiros
            _ultimo_diag[pais]["links"] = list(dict.fromkeys(re.findall(r'(?:href|src)="([^"]+(?:\.xlsx?|\.csv|export|download|shortselling|iframe)[^"]*)"', texto, re.I)))[:8]
        for tabela in tabelas:
            out.extend(_linhas_para_posicoes(tabela, pais))
        return out
    amostra = texto[:5000]
    sep = max([";", ",", "\t", "|"], key=lambda s: amostra.count(s))
    linhas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    _ultimo_diag[pais]["csv"] = _amostra(linhas)
    return _linhas_para_posicoes(linhas, pais)


def _tabelas_html(texto):
    """Extrai as tabelas de uma página HTML como listas de linhas (texto das células), sem dependências."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tabelas, self.linha, self.celula, self.na_celula = [], None, [], False

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.tabelas.append([])
            elif tag == "tr" and self.tabelas:
                self.linha = []
            elif tag in ("td", "th") and self.linha is not None:
                self.na_celula, self.celula = True, []
            elif tag == "br" and self.na_celula:
                self.celula.append(" ")

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.na_celula:
                self.linha.append(re.sub(r"\s+", " ", "".join(self.celula)).strip())
                self.na_celula = False
            elif tag == "tr" and self.linha is not None and self.tabelas:
                if self.linha:
                    self.tabelas[-1].append(self.linha)
                self.linha = None

        def handle_data(self, data):
            if self.na_celula:
                self.celula.append(data)

    p = P()
    p.feed(texto)
    return [t for t in p.tabelas if len(t) > 1]


def _descarregar(fonte):
    s = requests.Session()
    s.headers.update(UA)
    if fonte.get("sessao"):
        s.get(fonte["sessao"], timeout=30)  # alguns sites só servem o ficheiro depois de abrir a página
    url = fonte.get("url")
    if not url and fonte.get("procurar_xlsx") and fonte.get("pagina"):
        resp = s.get(fonte["pagina"], timeout=30)
        pag = resp.text
        m = re.search(r'href="([^"]+\.xlsx?[^"]*)"', pag, re.I)
        if not m:
            pais = next((k for k, v in fontes().items() if v.get("nome") == fonte.get("nome")), "?")
            _ultimo_diag[pais] = {"pagina": fonte["pagina"], "estado_http": resp.status_code, "url_final": resp.url, "bytes": len(pag),
                                  "inicio": re.sub(r"\s+", " ", pag[:300])}
            raise RuntimeError("Não encontrei o ficheiro Excel na página (pode estar protegida contra robôs).")
        url = requests.compat.urljoin(fonte["pagina"], m.group(1).replace("&amp;", "&"))
    if not url:
        raise RuntimeError("Sem endereço configurado.")
    r = s.get(url, timeout=60)
    r.raise_for_status()
    _url_usado[fonte.get("nome", "")] = url
    return r.content, r.headers.get("Content-Type", "").lower()


_url_usado = {}


# ---------------------------------------------------------------
# CMVM: a página é uma aplicação OutSystems que vai buscar os dados a um serviço interno (acesso anónimo)
# ---------------------------------------------------------------
CMVM_BASE = "https://www.cmvm.pt/PInstitucional"
CMVM_LISTA = ("CMVM_SDI_Emitentes_CW/InteressesDescobertoRelevantes/InteressesDescobertoRelevantes/DataActionDataAction1",
              "CMVM_SDI_Emitentes_CW.InteressesDescobertoRelevantes.InteressesDescobertoRelevantes.mvc.js", "HfYr7Hu4MGXtIpklugdcAg")
CMVM_DETALHE = ("CMVM_SDI_Emitentes_CW/InteressesDescobertoRelevantes/InteressesDescobertoRelevantesDet/DataActionGetDescobertoRelevante",
                "CMVM_SDI_Emitentes_CW.InteressesDescobertoRelevantes.InteressesDescobertoRelevantesDet.mvc.js", "2hBXLnSku+pnpvjltT8Sew")
CMVM_CSRF_ANONIMO = "T6C+9iB49TLra4jEsMeSckDMNhQ="  # token público que o OutSystems usa para visitantes sem sessão


def _cmvm_api_version(s, acao):
    """Lê a versão atual da ação no script da página (muda quando a CMVM publica uma nova versão do site)."""
    caminho, script, omissao = acao
    nome = caminho.rsplit("/", 1)[1]
    try:
        js = s.get(f"{CMVM_BASE}/scripts/{script}", timeout=30).text
        m = re.search(r'callDataAction\("' + re.escape(nome) + r'",\s*"[^"]*",\s*"([^"]+)"', js)
        if m:
            return m.group(1)
    except Exception:
        pass
    return omissao


def _descarregar_cmvm():
    s = requests.Session()
    s.headers.update({**UA, "Content-Type": "application/json; charset=UTF-8", "Accept": "application/json",
                      "X-CSRFToken": CMVM_CSRF_ANONIMO, "OutSystems-locale": "pt-PT"})
    mv = s.get(f"{CMVM_BASE}/moduleservices/moduleversioninfo?{int(time.time() * 1000)}", timeout=30).json()["versionToken"]
    v_lista, v_det = _cmvm_api_version(s, CMVM_LISTA), _cmvm_api_version(s, CMVM_DETALHE)

    def chamar(acao, versao, variaveis):
        r = s.post(f"{CMVM_BASE}/screenservices/{acao[0]}", timeout=30, data=json.dumps({
            "versionInfo": {"moduleVersion": mv, "apiVersion": versao}, "viewName": "ContentSplit.ContentSDI",
            "screenData": {"variables": variaveis}}))
        r.raise_for_status()
        return r.json()["data"]

    emitentes = chamar(CMVM_LISTA, v_lista, {"MaxRecords": 500, "StartIndex": 0})["InteressesDescobertoRelevantesLst2"]["List"]
    if not emitentes:
        raise RuntimeError("O serviço da CMVM devolveu a lista de emitentes vazia.")
    posicoes = []
    for e in emitentes:
        d = chamar(CMVM_DETALHE, v_det, {"MaxRecords": 100, "StartIndex": 0, "Step": 0, "isin_cod": "", "datapos": "", "datacom": "",
                                          "num_tit": 0, "Titular": "", "Num_Ent": e["emi_id"], "_num_EntInDataFetchStatus": 1,
                                          "Nome": e["nom_ent"], "_nomeInDataFetchStatus": 1})
        isin = (d.get("Detail") or {}).get("isin_cod") or ""
        for p in (d.get("DetailList") or {}).get("List") or []:
            pct = _num(p.get("percent"))
            if pct is None:
                continue
            posicoes.append({"pais": "PT", "detentor": (p.get("Titular") or "—").strip(), "emitente": e["nom_ent"],
                             "isin": (p.get("isin_code") or isin or "").strip().upper(), "pct": round(pct, 2), "data": _data(p.get("data_pos"))})
        time.sleep(0.4)  # 42 emitentes ≈ 20 s: devagar, para não sobrecarregar o site da CMVM
    return posicoes, len(emitentes)


def _consolidar(posicoes):
    """Fica com a última posição de cada (detentor, emitente). É «atual» se for ≥ 0,5%."""
    ultimo = {}
    for p in posicoes:
        chave = (normalizar_nome(p["detentor"]), p["isin"] or normalizar_nome(p["emitente"]))
        if chave not in ultimo or (p["data"] or "") >= (ultimo[chave]["data"] or ""):
            ultimo[chave] = p
    return [p for p in ultimo.values() if p["pct"] >= LIMIAR]


def atualizar(paises=None, forcar=False):
    """Descarrega as fontes ativas. Uma fonte que falhe mantém os dados anteriores. Devolve o relatório."""
    with _lock:
        f = fontes()
        dados = _ler(ARQ_DADOS, {"posicoes": [], "fontes": {}})
        relatorio = {}
        por_pais = {}
        for p in dados.get("posicoes", []):
            por_pais.setdefault(p["pais"], []).append(p)
        for pais, fonte in f.items():
            if paises and pais not in paises:
                continue
            if not fonte.get("ativa"):
                relatorio[pais] = {"ok": None, "msg": "Desativada"}
                continue
            try:
                if fonte.get("modo") == "manual":
                    manual = _ficheiro_manual(pais)
                    if not manual:
                        relatorio[pais] = {"ok": None, "msg": "Modo manual: ainda não carregaste o ficheiro (vê as instruções)."}
                        continue
                    with open(manual, "rb") as fh:
                        posicoes = _consolidar(_ler_conteudo(fh.read(), "", pais))
                    dias = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(manual))).days
                    por_pais[pais] = posicoes
                    relatorio[pais] = {"ok": True, "n": len(posicoes), "dias_ficheiro": dias,
                                       "msg": f"{len(posicoes)} posições do ficheiro carregado há {dias} dia(s)."}
                    continue
                if fonte.get("tipo") == "cmvm":
                    brutas, n_emit = _descarregar_cmvm()
                    posicoes = _consolidar(brutas)
                    por_pais[pais] = posicoes
                    relatorio[pais] = {"ok": True, "n": len(posicoes), "msg": f"{len(posicoes)} posições atuais em {n_emit} emitentes (serviço da CMVM)."}
                    continue
                manual = _ficheiro_manual(pais)
                if manual and (not fonte.get("url") and not fonte.get("procurar_xlsx")):
                    with open(manual, "rb") as fh:
                        conteudo, tipo = fh.read(), ""
                    origem = "ficheiro carregado na Gestão"
                else:
                    conteudo, tipo = _descarregar(fonte)
                    origem = "download automático"
                posicoes = _consolidar(_ler_conteudo(conteudo, tipo, pais))
                if not posicoes:
                    raise RuntimeError("O ficheiro foi lido mas não reconheci posições (o formato mudou?).")
                _ultimo_diag.pop(pais, None)
                por_pais[pais] = posicoes
                relatorio[pais] = {"ok": True, "msg": f"{len(posicoes)} posições atuais ({origem}).", "n": len(posicoes)}
                time.sleep(2)
            except Exception as e:
                # Recurso: se o Admin carregou um ficheiro desta fonte, usa-o (e diz que o download falhou)
                manual = _ficheiro_manual(pais)
                try:
                    if not manual:
                        raise e
                    with open(manual, "rb") as fh:
                        posicoes = _consolidar(_ler_conteudo(fh.read(), "", pais))
                    por_pais[pais] = posicoes
                    relatorio[pais] = {"ok": True, "n": len(posicoes),
                                       "msg": f"{len(posicoes)} posições do ficheiro carregado na Gestão (download automático falhou: {str(e)[:120]})."}
                except Exception:
                    relatorio[pais] = {"ok": False, "msg": str(e)[:300]}
                    diag = dict(_ultimo_diag.get(pais) or {})
                    diag["url"] = _url_usado.get(fonte.get("nome", ""), fonte.get("url"))
                    relatorio[pais]["diagnostico"] = json.dumps(diag, ensure_ascii=False)[:1800]
        dados["posicoes"] = [p for lista in por_pais.values() for p in lista]
        dados["fontes"] = {**dados.get("fontes", {}), **{k: {**v, "em": datetime.now().isoformat(timespec="seconds")}
                                                          for k, v in relatorio.items()}}
        dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _gravar(ARQ_DADOS, dados)
        return relatorio


def _ficheiro_manual(pais):
    if not os.path.isdir(PASTA_MANUAL):
        return None
    cands = sorted(f for f in os.listdir(PASTA_MANUAL) if f.startswith(pais + "_"))
    return os.path.join(PASTA_MANUAL, cands[-1]) if cands else None


def carregar_manual(pais, nome, conteudo):
    """O Admin carrega o ficheiro oficial à mão (para reguladores sem download automático)."""
    if pais not in fontes():
        raise ValueError("País desconhecido.")
    posicoes = _consolidar(_ler_conteudo(conteudo, "", pais))
    if not posicoes:
        diag = json.dumps(_ultimo_diag.get(pais) or {}, ensure_ascii=False)[:700]
        raise ValueError("Não reconheci posições neste ficheiro. Confirma que é a lista oficial de posições curtas. "
                         f"Diagnóstico (envia-o se precisares de ajuda): {diag}")
    os.makedirs(PASTA_MANUAL, exist_ok=True)
    ext = os.path.splitext(nome)[1].lower()[:6] or ".csv"
    with open(os.path.join(PASTA_MANUAL, f"{pais}_{datetime.now():%Y%m%d%H%M%S}{ext}"), "wb") as fh:
        fh.write(conteudo)
    with _lock:
        dados = _ler(ARQ_DADOS, {"posicoes": [], "fontes": {}})
        dados["posicoes"] = [p for p in dados["posicoes"] if p["pais"] != pais] + posicoes
        dados.setdefault("fontes", {})[pais] = {"ok": True, "msg": f"{len(posicoes)} posições (ficheiro carregado na Gestão).",
                                                "n": len(posicoes), "em": datetime.now().isoformat(timespec="seconds")}
        _gravar(ARQ_DADOS, dados)
    return len(posicoes)


# ---------------------------------------------------------------
# PESQUISA
# ---------------------------------------------------------------
def pesquisar(texto, nomes_extra=()):
    """Procura por ISIN, nome do emitente ou nomes alternativos (ex.: o nome da empresa vindo do Yahoo)."""
    dados = _ler(ARQ_DADOS, {"posicoes": []})
    q = (texto or "").strip()
    if not q:
        return []
    alvos = {normalizar_nome(x) for x in (q, *nomes_extra) if x and len(normalizar_nome(x)) >= 3}
    isin = q.upper() if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", q.upper()) else None
    res = []
    for p in dados.get("posicoes", []):
        n = normalizar_nome(p["emitente"])
        # Correspondência por palavras inteiras (evita que «nos» apanhe «eurofins»)
        if (isin and p["isin"] == isin) or any(a and ((" " + a + " ") in (" " + n + " ") or (" " + a) in (" " + n + " ")[:len(a) + 2]
                                                      or (len(n) >= 4 and (" " + n + " ") in (" " + a + " "))) for a in alvos):
            res.append(p)
    return _agrupar(res)


def _agrupar(posicoes):
    grupos = {}
    for p in posicoes:
        k = p["isin"] or normalizar_nome(p["emitente"])
        g = grupos.setdefault(k, {"emitente": p["emitente"], "isin": p["isin"], "pais": p["pais"], "posicoes": [], "total": 0.0})
        g["posicoes"].append(p)
        g["total"] = round(g["total"] + p["pct"], 2)
    for g in grupos.values():
        g["posicoes"].sort(key=lambda p: -p["pct"])
        g["ultima_data"] = max((p["data"] or "" for p in g["posicoes"]), default=None)
    return sorted(grupos.values(), key=lambda g: -g["total"])


def ranking(pais=None, limite=15):
    dados = _ler(ARQ_DADOS, {"posicoes": []})
    pos = [p for p in dados.get("posicoes", []) if not pais or p["pais"] == pais]
    return _agrupar(pos)[:limite]


def estado():
    d = _ler(ARQ_DADOS, {"fontes": {}})
    f = fontes()
    return {"atualizado_em": d.get("atualizado_em"), "total": len(d.get("posicoes", [])),
            "fontes": {k: {**v, **(d.get("fontes", {}).get(k) or {}), "manual": bool(_ficheiro_manual(k)),
                           "idade_manual": idade_manual(k)} for k, v in f.items()}}


# ---------------------------------------------------------------
# EUA: SHORT INTEREST (FINRA)
# ---------------------------------------------------------------
FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
_cache_finra = {}


def _campo(d, *nomes):
    for n in nomes:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def short_interest_eua(ticker):
    """Últimas 6 datas de liquidação do short interest consolidado da FINRA (cache de 12 h)."""
    t = ticker.upper().strip()
    if t in _cache_finra and time.time() - _cache_finra[t][0] < 43200:
        return _cache_finra[t][1]
    filtro = [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": t}]
    hoje = date.today()
    # Tenta do pedido mais completo para o mais simples (a FINRA recusa com 400 combinações que não suporta)
    tentativas = [
        {"compareFilters": filtro, "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": (hoje - timedelta(days=120)).isoformat(),
                                                          "endDate": hoje.isoformat()}], "limit": 20},
        {"compareFilters": filtro, "limit": 200},
    ]
    r, erro = None, None
    for corpo in tentativas:
        r = requests.post(FINRA_URL, json=corpo, headers={**UA, "Accept": "application/json", "Content-Type": "application/json"}, timeout=30)
        if r.status_code in (200, 204):
            break
        erro = f"FINRA respondeu {r.status_code}: {r.text[:150]}"
    else:
        raise RuntimeError(erro)
    try:
        linhas = r.json() if r.status_code == 200 and r.content else []
    except ValueError:
        linhas = []  # a FINRA responde 204 sem corpo quando não há dados para o símbolo
    linhas = sorted(linhas, key=lambda d: str(d.get("settlementDate") or ""), reverse=True)[:6]
    out = []
    for d in linhas:
        out.append({
            "data": _campo(d, "settlementDate"),
            "nome": _campo(d, "issueName", "issuerName"),
            "acoes": _campo(d, "currentShortPositionQuantity", "currentShortShareNumber"),
            "anterior": _campo(d, "previousShortPositionQuantity", "previousShortShareNumber"),
            "variacao_pct": _campo(d, "changePercent", "percentChange"),
            "volume_medio": _campo(d, "averageDailyVolumeQuantity", "averageShortShareNumber"),
            "dias_cobrir": _campo(d, "daysToCoverQuantity", "daysToCover"),
        })
    res = {"ticker": t, "fonte": "FINRA (short interest consolidado)", "datas": out}
    _cache_finra[t] = (time.time(), res)
    return res


# ---------------------------------------------------------------
# LEMBRETES DAS FONTES MANUAIS (ex.: Consob)
# ---------------------------------------------------------------
def idade_manual(pais):
    m = _ficheiro_manual(pais)
    return None if not m else (datetime.now() - datetime.fromtimestamp(os.path.getmtime(m))).days


def _lembretes_manuais(agora):
    """Uma vez por semana, se o ficheiro de uma fonte manual tiver mais dias do que o limite, avisa o Admin."""
    import alertas_admin as aa
    semana = agora.strftime("%G-S%V")
    estado_fontes = _ler(ARQ_DADOS, {}).get("fontes", {})
    for pais, f in fontes().items():
        if not f.get("ativa") or not (f.get("modo") == "manual" or f.get("lembrete_dias")):
            continue
        ultimo = estado_fontes.get(pais) or {}
        automatico_ok = ultimo.get("ok") is True and "ficheiro carregado" not in (ultimo.get("msg") or "")
        if f.get("modo") != "manual" and automatico_ok:
            continue  # o download automático está a funcionar: não é preciso nada
        dias = idade_manual(pais)
        limite = int(f.get("lembrete_dias") or 7)
        if dias is None or dias > limite:
            estado = "Ainda não carregaste nenhum ficheiro." if dias is None else f"O último ficheiro tem {dias} dias."
            passos = "\n".join(f"{i}. {p}" for i, p in enumerate(f.get("instrucoes") or [], 1))
            aa.avisar(f"lembrete-{pais}:{semana}", f"Posições curtas: atualizar a lista da {f['nome']}",
                      f"{estado} O download automático não está a funcionar para esta fonte.\n\n{passos}\n\n"
                      f"Página oficial: {f.get('pagina', '')}\nÁrea de Gestão → Fontes oficiais → «Carregar» na linha da {f['nome']}.", "info")


# ---------------------------------------------------------------
# AGENDADOR
# ---------------------------------------------------------------
_ultima = {"t": 0}


def diario(agora):
    """Uma vez por dia, a partir das 19:00 (os reguladores publicam ao fim da tarde)."""
    d = _ler(ARQ_DADOS, {})
    vazio = not d.get("posicoes")
    if (d.get("atualizado_em") or "")[:10] == agora.date().isoformat() and not vazio:
        return
    if agora.hour < 19 and not vazio:
        return
    if time.time() - _ultima["t"] < 3600:
        return
    _ultima["t"] = time.time()
    rel = atualizar()
    _lembretes_manuais(agora)
    falhas = {k: v["msg"] for k, v in rel.items() if v.get("ok") is False}
    print(f"[curtas] {sum(1 for v in rel.values() if v.get('ok'))} fontes OK, {len(falhas)} com falha.")
    if falhas:
        import alertas_admin as aa
        aa.avisar(f"curtas:{agora.date()}", "Posições curtas: algumas fontes falharam",
                  "\n".join(f"• {k}: {v}" for k, v in falhas.items()) +
                  "\n\nOs dados anteriores dessas fontes mantêm-se. Podes corrigir o endereço ou carregar o ficheiro na Gestão.", "aviso")
