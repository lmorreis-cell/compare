"""
relatorio_psi.py — Briefing PSI (Euronext Lisboa) automático para o Discord.

Lê o universo "psi" do Snapshot diário (mesmas regras do Screener: indicadores, sinais,
fundamentos e track record) e envia para o webhook WEBHOOK_RELATORIO_PSI — uma sala do
Discord diferente da do Briefing Matinal.

Se a fotografia do PSI ainda não existir ou estiver desatualizada (ex.: primeiro dia após
a instalação), calcula-a na hora com um ÚNICO pedido ao Yahoo e grava-a.

Uso:
    import relatorio_psi as rel_psi
    rel_psi.construir_relatorio()     # devolve (payload, erro) para pré-visualizar
    rel_psi.enviar_relatorio()        # envia (no máximo 1 vez por dia, salvo forcar=True)
    rel_psi.iniciar()                 # relógio interno: dias úteis às 08:10 (Lisboa)

Variáveis de ambiente:
    WEBHOOK_RELATORIO_PSI   (obrigatória) webhook da sala do Discord para o PSI
    PSI_HORA_ENVIO          (opcional)    "HH:MM", hora de Lisboa. Por omissão "08:10"
    PSI_TICKERS             (opcional)    lista separada por vírgulas para substituir a composição
"""

import json
import os
import threading
import time
from datetime import datetime

import requests

import snapshot_diario as snap
import yahoo_guard as yg
from relatorio_matinal import _linha_track, DIAS_SEMANA, MESES

try:
    from zoneinfo import ZoneInfo
    TZ_LISBOA = ZoneInfo("Europe/Lisbon")
except Exception:  # pragma: no cover
    TZ_LISBOA = None

ARQUIVO_ESTADO = os.path.join(snap.PASTA, "estado_relatorio_psi.json")


# ------------------------------------------------------------------ utilitários
def _webhook():
    return os.environ.get("WEBHOOK_RELATORIO_PSI")


def agora_lisboa():
    return datetime.now(TZ_LISBOA) if TZ_LISBOA else datetime.now()


def _ler_estado():
    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _gravar_estado(est):
    os.makedirs(snap.PASTA, exist_ok=True)
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False)


def estado():
    est = _ler_estado()
    est["webhook_configurado"] = bool(_webhook())
    est["hora_envio"] = os.environ.get("PSI_HORA_ENVIO", "08:10")
    est["cotadas"] = len(snap.composicao_psi())
    return est


def _pct(v):
    if v is None:
        return "N/A"
    seta = "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")
    return f"{seta} {v:+.2f}%"


def _eur(v):
    if v is None:
        return "N/A"
    casas = 4 if v < 1 else (3 if v < 10 else 2)
    return f"{v:.{casas}f} €".replace(".", ",")


def _curto(t):
    return t.replace(".LS", "")


def _data_curta(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m")
    except Exception:
        return iso or "?"


def _psi_atual():
    """Devolve (dados_psi, origem). Usa o snapshot; se não houver um fresco, calcula na hora."""
    psi = snap.carregar("psi")
    if snap.esta_fresco(psi):
        return psi, "snapshot"
    if yg.esta_bloqueado():
        raise RuntimeError("Sem fotografia recente do PSI e o Yahoo está em pausa de proteção.")
    return snap.processar_psi(gravar=True), "ao vivo"


# ------------------------------------------------------------------ relatório
def _linhas_setup(sinais, ativos, maximo=5):
    if not sinais:
        return "Nenhuma cotada cumpre os critérios hoje."
    linhas = []
    for s in sinais[:maximo]:
        a = ativos.get(s["ticker"], {}) or {}
        selo = "⚠️" if s.get("is_toxic") else "✅"
        rsi = f" · RSI {a['rsi']:.0f}" if a.get("rsi") is not None else ""
        linhas.append(f"{selo} **{_curto(s['ticker'])}** {_eur(s['preco'])}{rsi}")
    if len(sinais) > maximo:
        linhas.append(f"*+{len(sinais) - maximo} no Screener do Terminal*")
    return "\n".join(linhas)


def construir_relatorio():
    """Monta o payload do Discord. Devolve (payload, erro)."""
    try:
        psi, origem = _psi_atual()
    except Exception as e:
        return None, f"Não foi possível obter a fotografia do PSI: {e}"

    ativos = psi.get("ativos", {})
    if not ativos:
        return None, "A fotografia do PSI não tem cotadas válidas."
    nomes = snap.composicao_psi()

    hoje = agora_lisboa()
    titulo = f"🇵🇹 Briefing PSI — {DIAS_SEMANA[hoje.weekday()]}, {hoje.day} de {MESES[hoje.month - 1]}"

    # 1. Índice + quadro completo das cotadas, ordenado pela sessão
    cab = f"**Fecho de {_data_curta(psi.get('data_mercado'))}**\n"
    idx = psi.get("indice")
    if idx:
        pts = f"{idx['preco']:,.2f}".replace(",", " ")
        extra = []
        if idx.get("perf_5d") is not None:
            extra.append(f"5 sessões {idx['perf_5d']:+.2f}%")
        if idx.get("perf_ytd") is not None:
            extra.append(f"no ano {idx['perf_ytd']:+.2f}%")
        cab += f"**PSI** `{pts}` {_pct(idx.get('var_1d'))}" + ("  ·  " + "  ·  ".join(extra) if extra else "") + "\n"
    linhas = []
    for t, a in sorted(ativos.items(), key=lambda kv: -(kv[1].get("var_1d") or -999)):
        nome = a.get("nome") or nomes.get(t, _curto(t))
        linhas.append(f"`{_curto(t):<5}` {nome} — {_eur(a.get('preco'))} {_pct(a.get('var_1d'))}")
    descricao = cab + "\n" + "\n".join(linhas)

    # 2. Saúde interna do índice
    total = len(ativos)
    n50 = sum(1 for a in ativos.values() if a.get("acima_ema50"))
    n200 = sum(1 for a in ativos.values() if a.get("acima_sma200"))
    sobem = sum(1 for a in ativos.values() if (a.get("var_1d") or 0) > 0)
    racio = n50 / total
    if racio >= 0.7:
        txt, cor = "Participação **ampla**: a maioria das cotadas acompanha a tendência.", 6076508
    elif racio >= 0.4:
        txt, cor = "Regime **misto**: subida concentrada em poucos nomes, exige seletividade.", 15773006
    else:
        txt, cor = "**Fraqueza generalizada**: prioridade à preservação de capital.", 14242639
    campos = [{
        "name": "🧭 Saúde do PSI",
        "value": (f"**{n50}/{total}** acima da EMA 50 · **{n200}/{total}** acima da SMA 200 · "
                  f"**{sobem}/{total}** subiram na sessão.\n{txt}"),
        "inline": False,
    }]

    # 3. Setups (exatamente os do Screener, com histórico calculado sobre o PSI)
    tr = psi.get("track_record") or {}
    nomes_est = {"pullback": "📉 Pullback Tático (EMA 20)", "squeeze": "🗜️ Bollinger Squeeze", "oversold": "🩸 Capitulação (RSI < 30)"}
    for est in snap.ESTRATEGIAS:
        valor = _linhas_setup(psi.get("sinais", {}).get(est, []), ativos) + _linha_track(tr.get(est), est)
        campos.append({"name": nomes_est[est], "value": valor[:1024], "inline": True})

    # 4. Força relativa (Mansfield vs PSI) e máximos
    rk = psi.get("rankings", {})
    partes = []
    por_mansfield = sorted([(t, a["mansfield"]) for t, a in ativos.items() if a.get("mansfield") is not None], key=lambda x: -x[1])
    if len(por_mansfield) >= 2:
        n = min(3, len(por_mansfield) // 2)
        partes.append("🏅 **Maior força relativa vs PSI:** " + ", ".join(f"{_curto(t)} ({m:+.0f})" for t, m in por_mansfield[:n]))
        partes.append("🐢 **Mais fracas:** " + ", ".join(f"{_curto(t)} ({m:+.0f})" for t, m in por_mansfield[::-1][:n]))
    maximos = rk.get("novos_max52", [])
    perto = [_curto(t) for t, a in ativos.items() if (a.get("dist_max52") or -99) >= -3 and t not in maximos]
    if maximos:
        partes.append(f"🚀 **Novos máximos de 52 semanas:** {', '.join(_curto(t) for t in maximos)}")
    if perto:
        partes.append(f"📈 **A menos de 3% do máximo:** {', '.join(perto)}")
    if partes:
        campos.append({"name": "💪 Força Relativa", "value": "\n".join(partes)[:1024], "inline": False})

    rodape = "Portal Bolsa · Briefing PSI automático · ✅ fundamentos limpos ⚠️ alertas fundamentais · Informação educativa, não é recomendação de investimento"
    payload = {
        "embeds": [{
            "title": titulo,
            "color": cor,
            "description": descricao[:4000],
            "fields": campos[:25],
            "footer": {"text": rodape + (" · calculado ao vivo" if origem == "ao vivo" else "")},
        }],
    }
    return payload, None


def enviar_relatorio(forcar=False):
    """Envia o briefing PSI. Devolve (sucesso, mensagem)."""
    url = _webhook()
    if not url:
        return False, "Webhook não configurado. Define WEBHOOK_RELATORIO_PSI nas Variáveis da Discloud."

    est = _ler_estado()
    hoje = agora_lisboa().strftime("%Y-%m-%d")
    if not forcar and est.get("dia_envio") == hoje:
        return False, "O briefing PSI de hoje já foi enviado."

    payload, erro = construir_relatorio()
    if erro:
        est["ultimo_erro"] = f"{agora_lisboa().isoformat(timespec='seconds')}: {erro}"
        _gravar_estado(est)
        return False, erro

    data_mercado = (snap.carregar("psi") or {}).get("data_mercado")
    if not forcar and data_mercado and est.get("data_mercado_enviada") == data_mercado:
        # Feriado em Lisboa (ex.: 25 de abril, 1 de dezembro): não repete o briefing de ontem
        est["dia_envio"] = hoje
        _gravar_estado(est)
        return False, "Sem sessão nova em Lisboa desde o último briefing (feriado?). Envio ignorado."

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        est["ultimo_erro"] = f"{agora_lisboa().isoformat(timespec='seconds')}: {e}"
        _gravar_estado(est)
        return False, f"Falha ao enviar para o Discord: {e}"

    est.update({
        "dia_envio": hoje,
        "ultimo_envio": agora_lisboa().isoformat(timespec="seconds"),
        "data_mercado_enviada": data_mercado,
        "ultimo_erro": None,
    })
    _gravar_estado(est)
    return True, "Briefing PSI enviado para o Discord."


# ------------------------------------------------------------------ relógio interno
_arrancado = False


def _ciclo():
    hora_txt = os.environ.get("PSI_HORA_ENVIO", "08:10")
    try:
        h, m = (int(x) for x in hora_txt.split(":"))
    except Exception:
        h, m = 8, 10
    tentativas = {}
    while True:
        try:
            agora = agora_lisboa()
            dia = agora.strftime("%Y-%m-%d")
            janela_aberta = agora.weekday() < 5 and (h, m) <= (agora.hour, agora.minute) < (h + 2, m)
            if janela_aberta and _ler_estado().get("dia_envio") != dia and tentativas.get(dia, 0) < 3:
                # Trinco por ficheiro: evita envios duplicados se houver vários workers
                os.makedirs(snap.PASTA, exist_ok=True)
                trinco = os.path.join(snap.PASTA, f".psi_{dia}.lock")
                try:
                    fd = os.open(trinco, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                except FileExistsError:
                    if time.time() - os.path.getmtime(trinco) < 600:
                        time.sleep(60)
                        continue
                    os.utime(trinco)
                tentativas[dia] = tentativas.get(dia, 0) + 1
                ok, msg = enviar_relatorio()
                print(f"[Briefing PSI] {agora:%H:%M} {msg}", flush=True)
                if not ok and "já foi enviado" not in msg and "Envio ignorado" not in msg:
                    try:
                        os.remove(trinco)  # permite nova tentativa daqui a 10 minutos
                    except OSError:
                        pass
                    time.sleep(540)
        except Exception as e:
            print(f"[Briefing PSI] erro no relógio: {e}", flush=True)
        time.sleep(60)


def iniciar():
    """Arranca o relógio do briefing PSI (uma vez por processo)."""
    global _arrancado
    if _arrancado:
        return
    _arrancado = True
    threading.Thread(target=_ciclo, daemon=True, name="briefing_psi").start()
