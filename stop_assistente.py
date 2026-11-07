"""
stop_assistente.py — Dados técnicos para o «🛡️ Assistente de Stop» do terminal (só Patrocinadores).

GET /api/stop/<ticker>  →  indicadores do último ano e meio, calculados aqui a partir dos fechos diários:
    preço e data, ATR 14 (amplitude média diária), RSI 14, EMA 10/20/50, média de 200 dias,
    mínimo da sessão anterior, suportes (mínimos relevantes abaixo do preço), sequência de dias a subir,
    queda prévia e ressalto, a deteção de «ativo esticado», a próxima data de resultados, a moeda,
    e as velas diárias recentes (para as comparações históricas dos níveis 2 e 3, feitas no browser).

O preço de entrada, o capital e as quantidades NUNCA vêm ao servidor: as contas são feitas no browser.
"""

import math
from datetime import date, datetime

import pandas as pd
from flask import jsonify

import yahoo_guard as yg
from yahoo_guard import YahooIndisponivel

VELAS_ENVIADAS = 380


def _r(x, casas=4):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else round(x, casas)
    except Exception:
        return None


def calcular(df):
    df = df.dropna(subset=["Close", "High", "Low"]).copy()
    if len(df) < 60:
        raise ValueError("Histórico insuficiente (menos de 60 sessões).")
    c, h, l = df["Close"], df["High"], df["Low"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    delta = c.diff()
    ganho = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    perda = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + ganho / perda.replace(0, 1e-12))
    ema = {n: c.ewm(span=n, adjust=False).mean() for n in (10, 20, 50)}
    m200 = c.rolling(200).mean()

    preco, atr_v, rsi_v = float(c.iloc[-1]), float(atr.iloc[-1]), float(rsi.iloc[-1])

    # Suportes: mínimos locais (o mais baixo de 3 sessões para cada lado) abaixo do preço, nos últimos 6 meses
    suportes = []
    lows = l.values
    inicio = max(3, len(df) - 126)
    for i in range(inicio, len(df) - 3):
        if lows[i] == min(lows[i - 3:i + 4]) and lows[i] < preco:
            suportes.append({"preco": _r(lows[i]), "data": df.index[i].strftime("%Y-%m-%d")})
    # os mais próximos do preço primeiro, sem repetir níveis quase iguais (menos de 0,5 ATR)
    suportes.sort(key=lambda s: -s["preco"])
    unicos = []
    for s in suportes:
        if all(abs(s["preco"] - u["preco"]) > 0.5 * atr_v for u in unicos):
            unicos.append(s)
    suportes = unicos[:4]

    # Sequência de subidas, ressalto e queda prévia
    dias_subida = 0
    for i in range(len(c) - 1, 0, -1):
        if c.iloc[i] > c.iloc[i - 1]:
            dias_subida += 1
        else:
            break
    janela = l.iloc[-20:]
    i_min = janela.idxmin()
    minimo20 = float(janela.min())
    subida_desde_min = preco / minimo20 - 1 if minimo20 > 0 else 0
    antes = h.loc[:i_min].iloc[-120:]
    maximo_antes = float(antes.max()) if len(antes) else preco
    queda_previa = minimo20 / maximo_antes - 1 if maximo_antes > 0 else 0
    dist_ema20_atr = (preco - float(ema[20].iloc[-1])) / atr_v if atr_v > 0 else 0

    # Ativo esticado: RSI alto E pelo menos um sinal de subida exagerada
    sinais = []
    if dias_subida >= 4:
        sinais.append(f"{dias_subida} sessões seguidas a subir")
    if dist_ema20_atr >= 2:
        sinais.append(f"preço {dist_ema20_atr:.1f}× o ATR acima da EMA 20".replace(".", ","))
    if subida_desde_min >= 0.25:
        sinais.append(f"+{subida_desde_min * 100:.0f}% desde o mínimo das últimas 4 semanas")
    esticado = rsi_v >= 70 and bool(sinais)
    muito = esticado and rsi_v >= 75 and dist_ema20_atr >= 3
    ressalto = esticado and queda_previa <= -0.25 and subida_desde_min >= 0.15

    min_anterior = float(l.iloc[-2])
    velas = df.iloc[-VELAS_ENVIADAS:]
    return {
        "preco": _r(preco), "data": df.index[-1].strftime("%Y-%m-%d"),
        "atr": _r(atr_v), "atr_pct": _r(atr_v / preco * 100, 2),
        "rsi": _r(rsi_v, 1),
        "ema10": _r(ema[10].iloc[-1]), "ema20": _r(ema[20].iloc[-1]), "ema50": _r(ema[50].iloc[-1]),
        "m200": _r(m200.iloc[-1]),
        "min_anterior": _r(min_anterior), "max_anterior": _r(h.iloc[-2]),
        "suportes": suportes,
        "dias_subida": dias_subida,
        "subida_desde_min_pct": _r(subida_desde_min * 100, 1), "minimo20": _r(minimo20),
        "minimo20_data": i_min.strftime("%Y-%m-%d"),
        "queda_previa_pct": _r(queda_previa * 100, 1),
        "dist_ema20_atr": _r(dist_ema20_atr, 2),
        "esticado": {"ativo": esticado, "forte": muito, "ressalto_pos_queda": ressalto, "sinais": sinais},
        "velas": {"d": [x.strftime("%Y-%m-%d") for x in velas.index],
                  "h": [_r(x) for x in velas["High"]], "l": [_r(x) for x in velas["Low"]],
                  "c": [_r(x) for x in velas["Close"]], "o": [_r(x) for x in velas["Open"]] if "Open" in velas else None},
    }


def _resultados_e_moeda(ticker):
    out = {"moeda": None, "nome": None, "resultados": None}
    if "-" in ticker and ticker.endswith(("-USD", "-EUR", "-USDT")):
        out["moeda"] = ticker.rsplit("-", 1)[1].replace("USDT", "USD")
        return out
    try:
        info = yg.info(ticker)
    except Exception:
        return out
    out["moeda"] = info.get("currency")
    out["nome"] = info.get("shortName") or info.get("longName")
    hoje = date.today()
    datas = []
    for chave in ("earningsTimestampStart", "earningsTimestamp", "earningsTimestampEnd"):
        ts = info.get(chave)
        if isinstance(ts, (int, float)) and ts > 0:
            d = datetime.fromtimestamp(ts).date()
            if d >= hoje:
                datas.append(d)
    if datas:
        out["resultados"] = min(datas).isoformat()
    return out


def registar(app, requer_cargo, cache=None):
    def vista(ticker):
        t = str(ticker or "").strip().upper()
        if not t or len(t) > 20:
            return jsonify({"erro": "Ticker inválido."}), 400
        try:
            df = yg.historico(t, period="2y", interval="1d", auto_adjust=True)
        except YahooIndisponivel as e:
            return jsonify({"erro": str(e)}), 503
        except Exception as e:
            return jsonify({"erro": f"Não foi possível obter o histórico de {t}."}), 502
        if df is None or df.empty:
            return jsonify({"erro": f"Sem dados para {t}. Confirma o ticker (ex.: AAPL, EDP.LS, ASML.AS, BTC-USD)."}), 404
        try:
            dados = calcular(df)
        except ValueError as e:
            return jsonify({"erro": str(e)}), 422
        dados.update(_resultados_e_moeda(t))
        dados["ticker"] = t
        return jsonify(dados)

    if cache is not None:  # a cache fica POR DENTRO da verificação do cargo (nunca serve dados a quem não é Patrocinador)
        vista = cache.cached(timeout=300, response_filter=lambda r: getattr(r, "status_code", 0) == 200)(vista)
    vista = requer_cargo(nivel_minimo=2)(vista)
    app.add_url_rule("/api/stop/<ticker>", "api_stop_assistente", vista)
