"""
yahoo_guard.py — Camada única de acesso ao Yahoo Finance para o Portal Bolsa.

Objetivo: nunca mais um ciclo descontrolado conseguir "queimar" o IP do servidor.

O que faz:
  1. Usa uma sessão curl_cffi que imita o Chrome (exigida pelas versões recentes do yfinance).
  2. Serializa todos os pedidos e impõe um intervalo mínimo entre eles (rate limiter global).
  3. Disjuntor (circuit breaker): ao primeiro 429 / bloqueio, PÁRA todos os pedidos durante
     15 minutos em vez de continuar a martelar o Yahoo (é isto que transforma um bloqueio
     de minutos num bloqueio de dias).
  4. Cache em memória (5 min) para históricos e downloads: vários utilizadores a pedir o
     mesmo ticker no mesmo intervalo geram 1 único pedido.
  5. Cache em disco para .info (dados fundamentais mudam pouco — 24h chega). Se o Yahoo
     falhar, devolve a versão antiga em vez de erro.

Uso:
    import yahoo_guard as yg

    df    = yg.historico("AAPL", period="1y", interval="1d")    # em vez de yf.Ticker(t).history(...)
    info  = yg.info("AAPL")                                      # em vez de yf.Ticker(t).info
    dados = yg.download(["AAPL", "MSFT"], period="6mo")          # em vez de yf.download(...)
    preco = yg.ultimo_preco("AAPL")                              # em vez de fast_info['lastPrice']
    js    = yg.get_json("https://query1.finance.yahoo.com/...")  # em vez de requests.get(...) ao Yahoo
    tk    = yg.ticker("AAPL")                                    # para income_stmt, news, etc.
    news  = yg.chamar(lambda: tk.news)                           # cada propriedade passa pelo limitador
"""

import inspect
import json
import os
import threading
import time

import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    SESSAO = cffi_requests.Session(impersonate="chrome")
except Exception:  # se o curl_cffi não estiver instalado, o yfinance gere a sua própria sessão
    cffi_requests = None
    SESSAO = None

try:
    from yfinance.exceptions import YFRateLimitError
except ImportError:  # versões muito antigas
    class YFRateLimitError(Exception):
        pass


# ---------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------
INTERVALO_MIN_SEG = 0.6            # espaço mínimo entre dois pedidos ao Yahoo
PAUSA_APOS_BLOQUEIO_SEG = 15 * 60  # pausa após o 1.º bloqueio
PAUSA_MAXIMA_SEG = 2 * 3600        # a pausa duplica a cada bloqueio seguido (15 → 30 → 60 → 120 min)
FALHAS_VAZIAS_PARA_DISPARAR = 3    # downloads em lote vazios seguidos que contam como bloqueio
CACHE_MEMORIA_SEG = 300            # validade da cache de históricos/downloads
CACHE_MEMORIA_MAX_ENTRADAS = 400
CACHE_INFO_FICHEIRO = "cache_info_yahoo.json"
CACHE_INFO_VALIDADE_SEG = 24 * 3600


class YahooIndisponivel(Exception):
    """Lançada quando o disjuntor está aberto ou o Yahoo devolve rate limit."""


def _aceita_session(fn):
    try:
        return "session" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


_DOWNLOAD_ACEITA_SESSION = _aceita_session(yf.download)


def _kw_sessao():
    return {"session": SESSAO} if SESSAO is not None else {}


# ---------------------------------------------------------------
# RATE LIMITER + DISJUNTOR
# ---------------------------------------------------------------
_lock = threading.Lock()
_ultimo_pedido = 0.0
_bloqueado_ate = 0.0
_falhas_vazias = 0
_total_pedidos = 0
_bloqueios_seguidos = 0  # volta a 0 assim que um pedido tem sucesso


def estado():
    """Diagnóstico (usado pela rota /api/admin/yahoo)."""
    restante = max(0, int(_bloqueado_ate - time.time()))
    return {
        "bloqueado": restante > 0,
        "segundos_restantes": restante,
        "bloqueios_seguidos": _bloqueios_seguidos,
        "falhas_vazias": _falhas_vazias,
        "pedidos_desde_arranque": _total_pedidos,
        "entradas_cache_memoria": len(_cache_mem),
        "entradas_cache_info": len(_cache_info),
        "curl_cffi_ativo": SESSAO is not None,
    }


def esta_bloqueado():
    return time.time() < _bloqueado_ate


def _verificar_disjuntor():
    restante = _bloqueado_ate - time.time()
    if restante > 0:
        raise YahooIndisponivel(
            f"Fonte de dados em pausa de proteção ({int(restante // 60) + 1} min restantes). Tenta mais tarde."
        )


def _esperar_vez():
    global _ultimo_pedido, _total_pedidos
    _verificar_disjuntor()
    with _lock:
        espera = INTERVALO_MIN_SEG - (time.time() - _ultimo_pedido)
        if espera > 0:
            time.sleep(espera)
        _ultimo_pedido = time.time()
        _total_pedidos += 1
    # Verifica de novo: o disjuntor pode ter aberto enquanto esperávamos na fila
    _verificar_disjuntor()


def _abrir_disjuntor(motivo):
    global _bloqueado_ate, _falhas_vazias, _bloqueios_seguidos
    # Recuo exponencial: se o Yahoo continua bloqueado após a pausa, a pausa seguinte é o dobro.
    # Assim, enquanto o bloqueio durar, o portal só "espreita" o Yahoo umas poucas vezes por dia.
    pausa = min(PAUSA_APOS_BLOQUEIO_SEG * (2 ** _bloqueios_seguidos), PAUSA_MAXIMA_SEG)
    _bloqueios_seguidos += 1
    _bloqueado_ate = time.time() + pausa
    _falhas_vazias = 0
    print(f"[yahoo_guard] DISJUNTOR ABERTO ({motivo}). Bloqueio n.º {_bloqueios_seguidos}, pausa de {pausa // 60} min.")
    raise YahooIndisponivel(f"O Yahoo Finance limitou os pedidos. Pausa automática de proteção ativada ({pausa // 60} min).")


def _parece_bloqueio(erro):
    txt = str(erro).lower()
    return (
        isinstance(erro, YFRateLimitError)
        or "too many requests" in txt
        or "rate limit" in txt
        or " 429" in txt
        or "429 " in txt
    )


def _chamar(fn):
    global _bloqueios_seguidos
    _esperar_vez()
    try:
        resultado = fn()
        _bloqueios_seguidos = 0  # o Yahoo respondeu: o bloqueio acabou
        return resultado
    except YahooIndisponivel:
        raise
    except Exception as e:
        if _parece_bloqueio(e):
            _abrir_disjuntor(type(e).__name__)
        raise


def chamar(fn):
    """Passa qualquer acesso avulso ao yfinance (news, income_stmt, ...) pelo limitador/disjuntor."""
    return _chamar(fn)


# ---------------------------------------------------------------
# CACHE EM MEMÓRIA (históricos e downloads)
# ---------------------------------------------------------------
_cache_mem = {}
_cache_mem_lock = threading.Lock()


def _chave(*partes, **kwargs):
    return repr(partes) + repr(sorted(kwargs.items()))


def _cache_get(chave):
    with _cache_mem_lock:
        entrada = _cache_mem.get(chave)
        if entrada and time.time() - entrada[0] < CACHE_MEMORIA_SEG:
            return entrada[1]
    return None


def _cache_set(chave, valor):
    with _cache_mem_lock:
        if len(_cache_mem) >= CACHE_MEMORIA_MAX_ENTRADAS:
            # descarta as entradas mais antigas
            for k, _ in sorted(_cache_mem.items(), key=lambda kv: kv[1][0])[: CACHE_MEMORIA_MAX_ENTRADAS // 4]:
                _cache_mem.pop(k, None)
        _cache_mem[chave] = (time.time(), valor)


def _copia(df):
    # Os motores escrevem colunas novas nos DataFrames: devolvemos sempre uma cópia
    return df.copy() if df is not None else df


# ---------------------------------------------------------------
# API PÚBLICA
# ---------------------------------------------------------------
def ticker(simbolo):
    """
    Objeto Ticker com a sessão segura. Cada propriedade (income_stmt, news,
    insider_transactions, get_earnings_dates...) faz o seu próprio pedido HTTP —
    envolve cada acesso em yg.chamar(lambda: tk.news).
    """
    _verificar_disjuntor()
    return yf.Ticker(simbolo, **_kw_sessao())


def historico(simbolo, **kwargs):
    chave = _chave("hist", simbolo.upper(), **kwargs)
    em_cache = _cache_get(chave)
    if em_cache is not None:
        return _copia(em_cache)

    df = _chamar(lambda: yf.Ticker(simbolo, **_kw_sessao()).history(**kwargs))
    if df is not None and not df.empty:
        _cache_set(chave, df)
    return _copia(df)


def download(tickers, **kwargs):
    lista = tickers.split() if isinstance(tickers, str) else list(tickers)
    kwargs.setdefault("progress", False)
    kwargs["threads"] = False  # threads=True dispara dezenas de pedidos em paralelo — proibido
    kwargs.setdefault("auto_adjust", True)

    chave = _chave("dl", tuple(sorted(t.upper() for t in lista)), **kwargs)
    em_cache = _cache_get(chave)
    if em_cache is not None:
        return _copia(em_cache)

    kw = dict(kwargs)
    if _DOWNLOAD_ACEITA_SESSION and SESSAO is not None:
        kw["session"] = SESSAO
    alvo = lista[0] if len(lista) == 1 else lista
    df = _chamar(lambda: yf.download(alvo, **kw))

    global _falhas_vazias
    if df is None or df.empty:
        # Só lotes com vários tickers contam: um ticker mal escrito não deve disparar o disjuntor
        if len(lista) > 1:
            _falhas_vazias += 1
            if _falhas_vazias >= FALHAS_VAZIAS_PARA_DISPARAR:
                _abrir_disjuntor("downloads em lote vazios consecutivos")
    else:
        _falhas_vazias = 0
        _cache_set(chave, df)
    return _copia(df)


def ultimo_preco(simbolo):
    """Substitui fast_info['lastPrice'] (que faz vários pedidos) por 1 único pedido (e com cache)."""
    df = historico(simbolo, period="5d", interval="1d")
    if df is None or df.empty:
        return None
    serie = df["Close"].dropna()
    return float(serie.iloc[-1]) if not serie.empty else None


def get_json(url, timeout=5, headers=None):
    """Para os endpoints diretos do Yahoo (screener predefinido, pesquisa)."""
    def _pedido():
        if SESSAO is not None:
            r = SESSAO.get(url, timeout=timeout, headers=headers)
        else:
            import requests
            r = requests.get(url, timeout=timeout, headers=headers or {"User-Agent": "Mozilla/5.0"})
        if r.status_code == 429:
            raise YFRateLimitError("Too Many Requests")
        r.raise_for_status()
        return r.json()

    chave = _chave("json", url)
    em_cache = _cache_get(chave)
    if em_cache is not None:
        return em_cache
    dados = _chamar(_pedido)
    _cache_set(chave, dados)
    return dados


# --- .info com cache em disco -------------------------------------------
_cache_info_lock = threading.Lock()
_cache_info = {}
if os.path.exists(CACHE_INFO_FICHEIRO):
    try:
        with open(CACHE_INFO_FICHEIRO, "r") as f:
            _cache_info = json.load(f)
    except Exception:
        _cache_info = {}


def info(simbolo, max_idade_seg=CACHE_INFO_VALIDADE_SEG):
    simbolo = simbolo.upper()
    agora = time.time()
    entrada = _cache_info.get(simbolo)
    if entrada and agora - entrada["ts"] < max_idade_seg:
        return entrada["dados"]

    try:
        dados = _chamar(lambda: yf.Ticker(simbolo, **_kw_sessao()).info) or {}
    except YahooIndisponivel:
        if entrada:  # melhor dados antigos do que nada
            return entrada["dados"]
        raise
    except Exception:
        if entrada:
            return entrada["dados"]
        raise

    with _cache_info_lock:
        _cache_info[simbolo] = {"ts": agora, "dados": dados}
        try:
            tmp = CACHE_INFO_FICHEIRO + ".tmp"
            with open(tmp, "w") as f:
                json.dump(_cache_info, f, default=str)
            os.replace(tmp, CACHE_INFO_FICHEIRO)
        except Exception:
            pass
    return dados


def dividend_yield_pct(dados_info):
    """
    O Yahoo mudou o formato de 'dividendYield' (antes fração 0.025, agora percentagem 2.5).
    Esta função devolve sempre a percentagem, seja qual for a versão do yfinance.
    """
    try:
        trailing = dados_info.get("trailingAnnualDividendYield")
        if trailing and float(trailing) > 0:
            return float(trailing) * 100
        dy = dados_info.get("dividendYield")
        if dy is None:
            return 0.0
        dy = float(dy)
        return dy if dy > 0.2 else dy * 100
    except Exception:
        return 0.0


def fatia(dados, simbolo):
    """
    Extrai o DataFrame OHLCV de um ticker de um yf.download, funcione o download com
    group_by="ticker" ou não, e com 1 ou vários tickers (as versões recentes do yfinance
    devolvem colunas MultiIndex mesmo para 1 ticker).
    """
    import pandas as pd
    if dados is None or dados.empty:
        return pd.DataFrame()
    cols = dados.columns
    if isinstance(cols, pd.MultiIndex):
        if simbolo in cols.get_level_values(0):
            return dados[simbolo]
        if simbolo in cols.get_level_values(1):
            return dados.xs(simbolo, axis=1, level=1)
        return pd.DataFrame()
    return dados


def serie(dados, simbolo):
    """Extrai uma Series (ex.: fechos) de um DataFrame que pode vir como coluna única ou MultiIndex."""
    import pandas as pd
    if isinstance(dados, pd.Series):
        return dados
    if dados is None or dados.empty:
        return pd.Series(dtype=float)
    if simbolo in dados.columns:
        return dados[simbolo]
    if dados.shape[1] == 1:
        return dados.iloc[:, 0]
    return pd.Series(dtype=float)
