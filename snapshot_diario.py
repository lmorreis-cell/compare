"""
snapshot_diario.py — Fotografia diária do mercado, tirada UMA vez por dia após o fecho americano.

Porquê: em vez de cada membro disparar centenas de pedidos ao Yahoo quando usa o Screener,
o portal descarrega o universo inteiro uma única vez por dia (devagar, em lotes espaçados)
e guarda tudo em disco. O Screener, o Briefing Matinal e futuras funcionalidades leem daqui.
Resultado: o mesmo número de pedidos ao Yahoo com 10 membros ou com 500.

Ficheiros gerados (pasta snapshot/):
    macro.json   -> índices, VIX, Breadth (11 setores), Rotação Setorial (RRG 21D)
    ndx.json     -> Nasdaq 100: sinais do screener + fundamentos + track record + rankings
    sp500.json   -> S&P 500: idem
    cripto.json  -> Top cripto: idem (sem fundamentos)
    estado.json  -> quando correu, quanto demorou, erros

Uso:
    import snapshot_diario as snap
    snap.executar_snapshot()            # corre já (respeita o travão de execução única)
    snap.carregar("sp500")              # lê o último snapshot de um universo
    snap.estado()                       # diagnóstico
"""

import json
import os
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd

import yahoo_guard as yg

# ---------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------
PASTA = "snapshot"
TAMANHO_LOTE = 20               # tickers por download
PAUSA_ENTRE_LOTES_SEG = 15      # respiro entre lotes (o universo inteiro demora ~10-15 min)
VALIDADE_DIAS = 4               # snapshot mais antigo do que isto é considerado obsoleto

UNIVERSOS = {
    "ndx": "ndx.txt",
    "sp500": "sp500.txt",
    "cripto": None,
}
CRIPTO = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'AVAX-USD', 'DOGE-USD', 'DOT-USD', 'LINK-USD']

INDICES = {
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^GDAXI": "DAX 40", "^STOXX50E": "Euro Stoxx 50",
    "PSI20.LS": "PSI 20", "^VIX": "VIX", "BTC-USD": "Bitcoin", "GC=F": "Ouro", "CL=F": "Petróleo",
}
SETORES_USA = {
    'XLK': 'Tecnologia', 'XLV': 'Saúde', 'XLF': 'Finanças', 'XLE': 'Energia', 'XLY': 'Consumo Disc.',
    'XLP': 'Bens Básicos', 'XLI': 'Indústria', 'XLB': 'Materiais', 'XLRE': 'Imobiliário',
    'XLU': 'Utilities', 'XLC': 'Comunicações',
}
ESTRATEGIAS = ("pullback", "squeeze", "oversold")

_lock = threading.Lock()


# ---------------------------------------------------------------
# UTILITÁRIOS DE DISCO
# ---------------------------------------------------------------
def _caminho(nome):
    return os.path.join(PASTA, f"{nome}.json")


def _gravar(nome, dados):
    os.makedirs(PASTA, exist_ok=True)
    tmp = _caminho(nome) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, default=_json_default)
    os.replace(tmp, _caminho(nome))  # escrita atómica: nunca deixa um ficheiro meio escrito


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


_cache_leitura = {}


def carregar(nome):
    """Lê um snapshot do disco (com cache em memória invalidada pela data do ficheiro)."""
    caminho = _caminho(nome)
    if not os.path.exists(caminho):
        return None
    mtime = os.path.getmtime(caminho)
    em_cache = _cache_leitura.get(nome)
    if em_cache and em_cache[0] == mtime:
        return em_cache[1]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        _cache_leitura[nome] = (mtime, dados)
        return dados
    except Exception:
        return None


def esta_fresco(dados):
    """True se o snapshot existe e tem menos de VALIDADE_DIAS dias."""
    if not dados or "gerado_em" not in dados:
        return False
    try:
        idade = datetime.now() - datetime.fromisoformat(dados["gerado_em"])
        return idade.total_seconds() < VALIDADE_DIAS * 86400
    except Exception:
        return False


def estado():
    est = carregar("estado") or {}
    est["a_correr"] = _lock.locked()
    return est


def _r(v, casas=2):
    try:
        v = float(v)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, casas)
    except Exception:
        return None


# ---------------------------------------------------------------
# INDICADORES (exatamente os mesmos do Screener ao vivo)
# ---------------------------------------------------------------
def _indicadores(df):
    df = df.copy()
    df['SMA200'] = df['Close'].rolling(200).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()

    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    df['BB_Mid'] = df['Close'].rolling(20).mean()
    df['BB_Std'] = df['Close'].rolling(20).std()
    df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']

    df['PrevClose'] = df['Close'].shift(1)
    df['TR'] = df[['High', 'PrevClose']].max(axis=1) - df[['Low', 'PrevClose']].min(axis=1)
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    return df


def _sinais_hoje(df):
    """Réplica fiel da lógica do Screener ao vivo (mesmos limiares e mesmas legendas)."""
    sinais = {}
    fecho = float(df['Close'].iloc[-1])
    ultimo = df.iloc[-1]

    if fecho > ultimo['SMA200'] and fecho > ultimo['EMA50']:
        if abs(fecho - ultimo['EMA20']) / fecho < 0.015:
            sinais['pullback'] = f"RSI: {ultimo['RSI']:.1f} | Base de Suporte (EMA 20)"

    # O screener ao vivo usava 1 ano de histórico para o quantil — mantemos a mesma janela
    if ultimo['BB_Width'] < df['BB_Width'].tail(252).quantile(0.10):
        sinais['squeeze'] = f"Risco de Explosão | Largura BB: {ultimo['BB_Width'] * 100:.1f}%"

    if ultimo['RSI'] < 30 and fecho < ultimo['BB_Lower']:
        sinais['oversold'] = f"Capitulação | RSI Extremo: {ultimo['RSI']:.1f}"

    return sinais


def _series_sinais_historicos(df):
    """Sinais dia a dia (vetorizado) para medir o histórico de cada setup. Conta apenas o
    1.º dia de cada sequência, para um setup que dura 5 dias não contar como 5 sinais."""
    c = df['Close']
    brutos = {
        'pullback': (c > df['SMA200']) & (c > df['EMA50']) & ((c - df['EMA20']).abs() / c < 0.015),
        # Aproximação sem olhar para o futuro: quantil móvel de 6 meses
        'squeeze': df['BB_Width'] < df['BB_Width'].rolling(126, min_periods=60).quantile(0.10),
        'oversold': (df['RSI'] < 30) & (c < df['BB_Lower']),
    }
    return {k: (v.fillna(False) & ~v.shift(1, fill_value=False).fillna(False)) for k, v in brutos.items()}


def _eventos_historicos(ticker, df, janela=250):
    """Lista de sinais passados com o retorno 5 e 20 sessões depois."""
    c = df['Close']
    r5 = (c.shift(-5) / c - 1) * 100
    r20 = (c.shift(-20) / c - 1) * 100
    desde = (c.iloc[-1] / c - 1) * 100
    inicio = max(0, len(df) - janela)
    eventos = {}
    for est, serie in _series_sinais_historicos(df).items():
        idx = np.flatnonzero(serie.values)
        idx = idx[idx >= inicio]
        eventos[est] = [{
            "ticker": ticker,
            "data": df.index[i].strftime('%Y-%m-%d'),
            "pos": int(len(df) - 1 - i),  # sessões desde o sinal
            "preco": _r(c.iloc[i]),
            "r5": _r(r5.iloc[i]),
            "r20": _r(r20.iloc[i]),
            "desde": _r(desde.iloc[i]),
        } for i in idx]
    return eventos


def _agregar_track_record(eventos, estrategia):
    """Resumo estatístico dos sinais passados de um setup num universo."""
    def stats(chave):
        vals = [e[chave] for e in eventos if e[chave] is not None]
        if not vals:
            return None
        arr = np.array(vals)
        if estrategia == 'squeeze':  # o squeeze não prevê direção: medimos a amplitude do movimento
            return {"n": len(arr), "media_abs": _r(np.abs(arr).mean()), "mediana_abs": _r(np.median(np.abs(arr)))}
        return {"n": len(arr), "media": _r(arr.mean()), "taxa_acerto": _r((arr > 0).mean() * 100, 1)}

    recentes = sorted([e for e in eventos if e['pos'] <= 10], key=lambda e: e['pos'])[:15]
    return {"s5": stats('r5'), "s20": stats('r20'), "recentes": recentes}


def _fundamentos(ticker):
    """Auditoria fundamental (mesmos alertas e textos do Screener ao vivo)."""
    alertas = []
    try:
        info = yg.info(ticker)
        eps = info.get('trailingEps', 0)
        fcf = info.get('freeCashflow', 0)
        peg = info.get('pegRatio', 0)

        if eps is None or eps < 0:
            val_eps = f"${eps:.2f}" if eps is not None else "N/A"
            alertas.append({"tipo": "EPS Negativo",
                            "desc": f"A empresa destrói valor operacional. O Lucro por Ação (EPS) atual é de {val_eps}."})
        if fcf is None or fcf < 0:
            def formata_caixa(v):
                if v is None: return "N/A"
                if abs(v) >= 1e9: return f"${v/1e9:.2f}B"
                if abs(v) >= 1e6: return f"${v/1e6:.2f}M"
                return f"${v:.2f}"
            alertas.append({"tipo": "Cash Flow Destrutivo",
                            "desc": f"Queima de caixa ativa. O Free Cash Flow está negativo em {formata_caixa(fcf)}. A sobrevivência pode exigir diluição de capital."})
        if peg is None or peg > 2 or peg < 0:
            val_peg = f"{peg:.2f}" if peg is not None else "N/A"
            alertas.append({"tipo": "PEG Especulativo",
                            "desc": f"Múltiplo de crescimento (PEG) em {val_peg}. Valores > 2.0 indicam que a cotação está inflacionada face ao crescimento real estimado."})
    except yg.YahooIndisponivel:
        raise
    except Exception:
        alertas.append({"tipo": "Dados Ocultos",
                        "desc": "O algoritmo não conseguiu extrair a métrica financeira (N/A). Avaliação fundamental no escuro."})
    return alertas


def _resumo_ativo(ticker, df, spx_close=None):
    c = df['Close']
    ultimo = df.iloc[-1]
    fecho = float(c.iloc[-1])

    def perf(n):
        return _r((fecho / float(c.iloc[-1 - n]) - 1) * 100) if len(c) > n else None

    max_52 = float(df['High'].tail(252).max())
    mansfield = None
    if spx_close is not None:
        alinhados = pd.concat([c, spx_close], axis=1, join='inner').dropna()
        if len(alinhados) >= 252:
            rs = alinhados.iloc[:, 0] / alinhados.iloc[:, 1]
            mansfield = _r(((rs / rs.rolling(252).mean()) - 1).iloc[-1] * 100)

    return {
        "preco": _r(fecho, 4),
        "var_1d": perf(1),
        "perf_1m": perf(21),
        "perf_3m": perf(63),
        "rsi": _r(ultimo['RSI'], 1),
        "dist_sma200": _r((fecho / ultimo['SMA200'] - 1) * 100) if pd.notna(ultimo['SMA200']) else None,
        "dist_max52": _r((fecho / max_52 - 1) * 100),
        "novo_max52": bool(fecho >= max_52 * 0.999),
        "vol_ratio": _r(ultimo['Volume'] / ultimo['Vol_SMA20']) if ultimo['Vol_SMA20'] else None,
        "atr_pct": _r(ultimo['ATR'] / fecho * 100) if pd.notna(ultimo['ATR']) else None,
        "mansfield": mansfield,
    }


# ---------------------------------------------------------------
# MACRO: ÍNDICES, BREADTH E RRG
# ---------------------------------------------------------------
def _processar_macro():
    tickers = list(INDICES) + list(SETORES_USA)
    dados = yg.download(tickers, period="2y", interval="1d", group_by="ticker", usar_cache=False)
    if dados is None or dados.empty:
        raise RuntimeError("Sem dados macro.")

    fechos = {}
    for t in tickers:
        f = yg.fatia(dados, t)
        if not f.empty and 'Close' in f.columns:
            serie = f['Close'].dropna()
            if len(serie) >= 2:
                fechos[t] = serie

    indices = []
    for t, nome in INDICES.items():
        if t in fechos:
            s = fechos[t]
            indices.append({"ticker": t, "nome": nome, "preco": _r(s.iloc[-1]), "var": _r((s.iloc[-1] / s.iloc[-2] - 1) * 100)})

    # Breadth: setores acima da EMA 50 (mesma regra do painel Market Breadth)
    acima = [t for t in SETORES_USA if t in fechos and fechos[t].iloc[-1] > fechos[t].ewm(span=50, adjust=False).mean().iloc[-1]]

    # RRG 21D (mesma fórmula da Rotação Setorial do Radar Global)
    rrg = []
    if "^GSPC" in fechos:
        bench = fechos["^GSPC"]
        janela = 21
        for t, nome in SETORES_USA.items():
            if t not in fechos:
                continue
            al = pd.concat([fechos[t], bench], axis=1, join='inner').ffill().dropna()
            rs = al.iloc[:, 0] / al.iloc[:, 1]
            ratio = 100 + ((rs - rs.rolling(janela).mean()) / rs.rolling(janela).std()) * 3
            mom = 100 + ((ratio - ratio.rolling(janela).mean()) / ratio.rolling(janela).std()) * 3
            x, y = ratio.iloc[-1], mom.iloc[-1]
            if pd.isna(x) or pd.isna(y):
                continue
            quadrante = ("Líderes" if y >= 100 else "A Enfraquecer") if x >= 100 else ("A Melhorar" if y >= 100 else "Atrasados")
            rrg.append({"setor": nome, "ticker": t, "x": _r(x), "y": _r(y), "quadrante": quadrante})

    vix = next((i for i in indices if i["ticker"] == "^VIX"), None)
    data_mercado = fechos["^GSPC"].index[-1].strftime('%Y-%m-%d') if "^GSPC" in fechos else None
    return {
        "indices": indices,
        "breadth": {"acima_ema50": len(acima), "total": len(SETORES_USA), "setores_acima": [SETORES_USA[t] for t in acima]},
        "vix": vix,
        "rrg": rrg,
        "data_mercado": data_mercado,
    }, fechos.get("^GSPC")


# ---------------------------------------------------------------
# UNIVERSOS
# ---------------------------------------------------------------
def _ler_universo(nome):
    if nome == "cripto":
        return list(CRIPTO)
    caminho = UNIVERSOS[nome]
    try:
        with open(caminho, 'r') as f:
            return [linha.strip().upper() for linha in f if linha.strip()]
    except FileNotFoundError:
        print(f"[snapshot] Ficheiro {caminho} não encontrado — universo '{nome}' ignorado.")
        return []


def _processar_tickers(tickers, spx_close, registo_erros):
    """Descarrega e processa uma lista de tickers em lotes espaçados. Devolve {ticker: resultado}."""
    resultados = {}
    lotes = [tickers[i:i + TAMANHO_LOTE] for i in range(0, len(tickers), TAMANHO_LOTE)]
    for n, lote in enumerate(lotes, 1):
        if n > 1:
            time.sleep(PAUSA_ENTRE_LOTES_SEG)
        try:
            dados = yg.download(lote, period="2y", interval="1d", group_by="ticker", usar_cache=False)
        except yg.YahooIndisponivel:
            raise
        except Exception as e:
            registo_erros.append(f"Lote {n}: {e}")
            continue
        for t in lote:
            try:
                df = yg.fatia(dados, t).dropna()
                if df.empty or len(df) < 200:
                    continue
                df = _indicadores(df)
                resultados[t] = {
                    "resumo": _resumo_ativo(t, df, spx_close),
                    "sinais": _sinais_hoje(df),
                    "eventos": _eventos_historicos(t, df),
                }
            except Exception as e:
                registo_erros.append(f"{t}: {e}")
        print(f"[snapshot] Lote {n}/{len(lotes)} processado ({len(resultados)} ativos válidos).")
    return resultados


def _montar_universo(nome, tickers, processados, data_mercado):
    sinais = {est: [] for est in ESTRATEGIAS}
    eventos = {est: [] for est in ESTRATEGIAS}
    ativos = {}

    for t in tickers:
        r = processados.get(t)
        if not r:
            continue
        ativos[t] = r["resumo"]
        for est in ESTRATEGIAS:
            eventos[est].extend(r["eventos"].get(est, []))
            if est in r["sinais"]:
                sinais[est].append({"ticker": t, "preco": r["resumo"]["preco"], "metricas": r["sinais"][est]})

    # Fundamentos só para quem passou no filtro técnico (como no Screener ao vivo)
    if nome != "cripto":
        auditados = {}
        for est in ESTRATEGIAS:
            for s in sinais[est]:
                if s["ticker"] not in auditados:
                    auditados[s["ticker"]] = _fundamentos(s["ticker"])
                s["fundamentos"] = auditados[s["ticker"]]
                s["is_toxic"] = len(s["fundamentos"]) > 0
    else:
        for est in ESTRATEGIAS:
            for s in sinais[est]:
                s["fundamentos"], s["is_toxic"] = [], False

    # Ordenação útil: fundamentos limpos primeiro, depois por força relativa
    for est in ESTRATEGIAS:
        sinais[est].sort(key=lambda s: (s["is_toxic"], -(ativos[s["ticker"]].get("mansfield") or -999)))

    lista = list(ativos.items())
    rankings = {
        "novos_max52": sorted([t for t, a in lista if a.get("novo_max52")]),
        "top_mansfield": [t for t, a in sorted(lista, key=lambda kv: -(kv[1].get("mansfield") or -999))[:10] if a.get("mansfield") is not None],
        "maiores_subidas": [t for t, a in sorted(lista, key=lambda kv: -(kv[1].get("var_1d") or -999))[:5]],
        "maiores_quedas": [t for t, a in sorted(lista, key=lambda kv: (kv[1].get("var_1d") or 999))[:5]],
    }

    return {
        "universo": nome,
        "gerado_em": datetime.now().isoformat(timespec='seconds'),
        "data_mercado": data_mercado,
        "total_universo": len(tickers),
        "total_processado": len(ativos),
        "sinais": sinais,
        "track_record": {est: _agregar_track_record(eventos[est], est) for est in ESTRATEGIAS},
        "rankings": rankings,
        "ativos": ativos,
    }


# ---------------------------------------------------------------
# EXECUÇÃO
# ---------------------------------------------------------------
def executar_snapshot():
    """Tira a fotografia completa. Só corre uma de cada vez; nunca apaga o snapshot anterior
    se falhar a meio (os ficheiros só são substituídos no fim de cada universo)."""
    if not _lock.acquire(blocking=False):
        print("[snapshot] Já está a correr. Pedido ignorado.")
        return False

    inicio = time.time()
    est = carregar("estado") or {}
    est.update({"ultima_tentativa": datetime.now().isoformat(timespec='seconds'), "erros": []})
    est["tentativas_hoje"] = (est.get("tentativas_hoje", 0) + 1) if est.get("dia_tentativas") == datetime.now().strftime('%Y-%m-%d') else 1
    est["dia_tentativas"] = datetime.now().strftime('%Y-%m-%d')
    _gravar("estado", est)

    try:
        print(f"[snapshot] A iniciar fotografia diária do mercado ({datetime.now()})...")
        macro, spx_close = _processar_macro()
        macro["gerado_em"] = datetime.now().isoformat(timespec='seconds')
        _gravar("macro", macro)

        # Descarrega a UNIÃO dos universos uma única vez (o Nasdaq 100 está quase todo no S&P 500)
        universos = {nome: _ler_universo(nome) for nome in UNIVERSOS}
        todos = sorted(set(t for lista in universos.values() for t in lista))
        print(f"[snapshot] {len(todos)} ativos únicos a processar em lotes de {TAMANHO_LOTE}.")
        processados = _processar_tickers(todos, spx_close, est["erros"])

        for nome, tickers in universos.items():
            if tickers:
                _gravar(nome, _montar_universo(nome, tickers, processados, macro.get("data_mercado")))

        est.update({
            "ultimo_sucesso": datetime.now().isoformat(timespec='seconds'),
            "dia_sucesso": datetime.now().strftime('%Y-%m-%d'),
            "data_mercado": macro.get("data_mercado"),
            "duracao_seg": int(time.time() - inicio),
            "ativos_processados": len(processados),
            "erros": est["erros"][:30],
        })
        print(f"[snapshot] Concluído em {est['duracao_seg']}s: {len(processados)} ativos.")
        return True
    except yg.YahooIndisponivel as e:
        est["erros"].append(f"Yahoo em pausa de proteção: {e}")
        print(f"[snapshot] Abortado: {e}")
        return False
    except Exception as e:
        est["erros"].append(f"Erro inesperado: {e}")
        print(f"[snapshot] Erro inesperado: {e}")
        return False
    finally:
        est["erros"] = est.get("erros", [])[:30]
        _gravar("estado", est)
        _lock.release()
