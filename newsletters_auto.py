"""
newsletters_auto.py — Gera as newsletters Radar States e Radar Europa no próprio servidor (Discloud),
à hora marcada pelo agendador ou a pedido na Área de Gestão. Substitui o GitHub Actions.

Como funciona:
    - Cada newsletter é o seu script (Newsletter_Escolhidos_States.py / Newsletter_Escolhidos.py), na pasta
      do portal, ao lado da lista de ações (tickers_escolhidos_states.txt / tickers_escolhidos_europe.txt).
    - O script corre num PROCESSO À PARTE, com prioridade baixa, para o portal continuar rápido. Só corre uma
      newsletter de cada vez. O ficheiro HTML gerado fica na pasta do portal e o /ver/... mostra-o logo.
    - Fica registado o resultado, a duração e as últimas linhas do registo (newsletters_estado.json).
    - Se falhar, sai um aviso na sala privada do Admin (WEBHOOK_ADMIN).

Configuração (Área de Gestão → cartão «Newsletters»; guardada em newsletters_config.json):
    ligada / desligada, hora e dias da semana de cada newsletter.
    Por omissão estão DESLIGADAS: liga-as na Gestão depois de desligares o workflow do GitHub Actions,
    para não haver duas newsletters no mesmo dia.
"""

import glob
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(BASE, "newsletters_config.json")
ARQ_ESTADO = os.path.join(BASE, "newsletters_estado.json")
TEMPO_MAX_SEG = 60 * 60          # um script que demore mais de 1 hora é interrompido
LINHAS_REGISTO = 80
DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

NEWSLETTERS = {
    "states": {"nome": "Radar States", "script": "Newsletter_Escolhidos_States.py",
               "tickers": "tickers_escolhidos_states.txt", "padrao": "radar_states_escolhidos_*.html",
               "hora": "02:30", "dias": [1, 2, 3, 4, 5]},   # ter–sáb: depois de cada sessão americana
    "europa": {"nome": "Radar Europa", "script": "Newsletter_Escolhidos.py",
               "tickers": "tickers_escolhidos_europe.txt", "padrao": "radar_europeu_escolhidos_*.html",
               "hora": "01:30", "dias": [1, 2, 3, 4, 5]},
}

_lock = threading.Lock()
_a_correr = {"chave": None, "inicio": None}


def _ler(caminho, omissao):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return omissao


def _gravar(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def config():
    c = _ler(ARQ_CONFIG, {})
    out = {}
    for k, n in NEWSLETTERS.items():
        x = c.get(k, {})
        out[k] = {"ativa": bool(x.get("ativa", False)), "hora": x.get("hora", n["hora"]),
                  "dias": x.get("dias", n["dias"])}
    return out


def gravar_config(chave, ativa=None, hora=None, dias=None):
    if chave not in NEWSLETTERS:
        raise ValueError("Newsletter desconhecida.")
    c = _ler(ARQ_CONFIG, {})
    x = c.get(chave, {})
    if ativa is not None:
        x["ativa"] = bool(ativa)
    if hora is not None:
        h, m = str(hora).split(":")
        h, m = int(h), int(m)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hora inválida.")
        x["hora"] = f"{h:02d}:{m:02d}"
    if dias is not None:
        d = sorted({int(v) for v in dias if 0 <= int(v) <= 6})
        if not d:
            raise ValueError("Escolhe pelo menos um dia.")
        x["dias"] = d
    c[chave] = x
    _gravar(ARQ_CONFIG, c)


def _ficheiro_mais_recente(padrao):
    lista = glob.glob(os.path.join(BASE, padrao))
    if not lista:
        return None
    f = max(lista, key=os.path.getmtime)
    return {"nome": os.path.basename(f), "em": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(timespec="seconds")}


MODULOS = ("plotly", "pytz", "matplotlib", "jinja2", "yfinance", "pandas", "numpy")


def _faltam(n):
    """Ficheiros e módulos Python que faltam (os módulos acrescentam-se ao requirements.txt)."""
    import importlib.util
    falta = [f for f in (n["script"], n["tickers"], "yahoo_guard.py") if not os.path.exists(os.path.join(BASE, f))]
    falta += [f"módulo {m} (requirements.txt)" for m in MODULOS if importlib.util.find_spec(m) is None]
    return falta


def a_correr():
    return dict(_a_correr) if _a_correr["chave"] else None


# ---------------------------------------------------------------
# EXECUTAR UMA NEWSLETTER
# ---------------------------------------------------------------
def _executar(chave, origem):
    n = NEWSLETTERS[chave]
    inicio = time.time()
    est = _ler(ARQ_ESTADO, {})
    reg = {"inicio": datetime.now().isoformat(timespec="seconds"), "origem": origem}
    antes = _ficheiro_mais_recente(n["padrao"])
    try:
        env = dict(os.environ, YG_MODO="lote", PYTHONUNBUFFERED="1", MPLBACKEND="Agg")
        pre = (lambda: os.nice(10)) if hasattr(os, "nice") else None
        r = subprocess.run([sys.executable, n["script"]], cwd=BASE, env=env, capture_output=True, text=True,
                           timeout=TEMPO_MAX_SEG, preexec_fn=pre)
        saida = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        depois = _ficheiro_mais_recente(n["padrao"])
        gerou = depois and (not antes or depois["em"] != antes["em"] or depois["nome"] != antes["nome"])
        reg.update({"ok": r.returncode == 0 and bool(gerou), "codigo": r.returncode,
                    "ficheiro": depois["nome"] if gerou else None})
        if r.returncode == 0 and not gerou:
            reg["erro"] = "O script terminou mas não gravou nenhuma newsletter nova."
        elif r.returncode != 0:
            ult = [l for l in saida.strip().splitlines() if l.strip()]
            reg["erro"] = ult[-1][:300] if ult else f"O script terminou com o código {r.returncode}."
    except subprocess.TimeoutExpired as e:
        saida = (e.stdout or "") if isinstance(e.stdout, str) else ""
        reg.update({"ok": False, "erro": f"Interrompido ao fim de {TEMPO_MAX_SEG // 60} minutos."})
    except Exception as e:
        saida = ""
        reg.update({"ok": False, "erro": str(e)[:300]})
    reg["duracao_seg"] = int(time.time() - inicio)
    reg["registo"] = "\n".join(saida.strip().splitlines()[-LINHAS_REGISTO:])
    est[chave] = reg
    if reg["ok"]:
        est.setdefault("dias_feitos", {})[chave] = datetime.now().date().isoformat()
    _gravar(ARQ_ESTADO, est)
    print(f"[newsletters] {n['nome']}: {'OK' if reg['ok'] else 'FALHOU'} em {reg['duracao_seg']}s"
          + (f" · {reg.get('erro')}" if not reg["ok"] else f" · {reg.get('ficheiro')}"))
    if not reg["ok"]:
        try:
            import alertas_admin
            alertas_admin.avisar(f"newsletter-{chave}-{datetime.now():%Y-%m-%d-%H%M}",
                                 f"{n['nome']} não foi gerada",
                                 f"{reg.get('erro', '')}\n\nVê o registo na Área de Gestão → Newsletters.", nivel="erro")
        except Exception as e:
            print(f"[newsletters] aviso ao Admin falhou: {e}")
    return reg


def lancar(chave, origem="manual"):
    """Arranca a newsletter num fio à parte. Devolve (ok, mensagem)."""
    if chave not in NEWSLETTERS:
        return False, "Newsletter desconhecida."
    falta = _faltam(NEWSLETTERS[chave])
    if falta:
        return False, "Faltam ficheiros na pasta do portal: " + ", ".join(falta)
    with _lock:
        if _a_correr["chave"]:
            return False, f"Já está a ser gerada: {NEWSLETTERS[_a_correr['chave']]['nome']}. Espera que termine."
        _a_correr.update(chave=chave, inicio=datetime.now().isoformat(timespec="seconds"))

    def corre():
        try:
            _executar(chave, origem)
        finally:
            _a_correr.update(chave=None, inicio=None)

    threading.Thread(target=corre, daemon=True, name=f"newsletter-{chave}").start()
    return True, f"{NEWSLETTERS[chave]['nome']} a ser gerada. Demora alguns minutos."


# ---------------------------------------------------------------
# AGENDADOR (chamado a cada minuto, hora de Lisboa)
# ---------------------------------------------------------------
def diario(agora):
    if _a_correr["chave"]:
        return
    cfg = config()
    est = _ler(ARQ_ESTADO, {})
    feitos = est.get("dias_feitos", {})
    tentativas = est.get("tentativas", {})
    hoje = agora.date().isoformat()
    for chave, c in cfg.items():
        if not c["ativa"] or agora.weekday() not in c["dias"] or feitos.get(chave) == hoje:
            continue
        h, m = map(int, c["hora"].split(":"))
        inicio = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        if not (inicio <= agora and (agora - inicio).total_seconds() < 4 * 3600):
            continue  # janela de 4 horas depois da hora marcada (ex.: servidor reiniciado)
        t = tentativas.get(chave, {})
        if t.get("dia") == hoje and (t.get("n", 0) >= 2 or time.time() - t.get("ts", 0) < 30 * 60):
            continue  # no máximo 2 tentativas por dia, com 30 min de intervalo
        tentativas[chave] = {"dia": hoje, "n": (t.get("n", 0) + 1) if t.get("dia") == hoje else 1, "ts": time.time()}
        est["tentativas"] = tentativas
        _gravar(ARQ_ESTADO, est)
        lancar(chave, origem="agendador")
        return  # uma de cada vez: a outra entra no minuto seguinte a esta terminar


# ---------------------------------------------------------------
# ÁREA DE GESTÃO
# ---------------------------------------------------------------
def painel():
    cfg = config()
    est = _ler(ARQ_ESTADO, {})
    out = {"a_correr": a_correr(), "newsletters": {}}
    for k, n in NEWSLETTERS.items():
        ult = est.get(k) or {}
        out["newsletters"][k] = {
            "nome": n["nome"], **cfg[k], "faltam": _faltam(n), "mais_recente": _ficheiro_mais_recente(n["padrao"]),
            "ultima": {x: ult.get(x) for x in ("inicio", "origem", "ok", "erro", "duracao_seg", "ficheiro")} if ult else None,
        }
    return out


def registo(chave):
    return (_ler(ARQ_ESTADO, {}).get(chave) or {}).get("registo", "")


def registar(app, e_admin):
    from flask import jsonify, request

    def negado():
        if not e_admin():
            return jsonify({"erro": "Acesso negado. Apenas Admin."}), 403
        if request.method != "GET":
            origem = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if origem and request.host not in origem:
                return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        return None

    @app.route("/api/admin/newsletters", methods=["GET", "POST"])
    def newsletters_admin():
        n = negado()
        if n:
            return n
        if request.method == "POST":
            b = request.get_json(silent=True) or {}
            try:
                gravar_config(b.get("chave"), b.get("ativa"), b.get("hora"), b.get("dias"))
            except Exception as e:
                return jsonify({"erro": str(e)}), 400
        return jsonify(painel())

    @app.route("/api/admin/newsletters/<chave>/gerar", methods=["POST"])
    def newsletters_gerar(chave):
        n = negado()
        if n:
            return n
        ok, msg = lancar(chave)
        return jsonify({"sucesso": ok, "mensagem": msg}), (200 if ok else 409)

    @app.route("/api/admin/newsletters/<chave>/registo")
    def newsletters_registo(chave):
        n = negado()
        if n:
            return n
        return jsonify({"registo": registo(chave)})
