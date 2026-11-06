"""
macro_vespera.py — Aviso no Discord na VÉSPERA dos grandes eventos macro (chamado pelo agendador a cada minuto).

Todos os dias à hora definida (por omissão 19:00, Lisboa), se amanhã houver eventos importantes na agenda macro
(decisões do BCE e da Fed, emprego e inflação dos EUA…), sai uma mensagem curta no Discord com a hora (de Lisboa)
e o que está em jogo. Ao domingo avisa os eventos de segunda. Se amanhã não houver nada importante, não envia nada.

A agenda vem de calendario_macro.py (páginas oficiais do BCE, da Fed e do BLS), que já é atualizada todos os dias.

Configuração (Discloud → Variáveis), tudo opcional:
    WEBHOOK_MACRO          sala do Discord (se não existir, usa WEBHOOK_RELATORIO, a sala do Briefing EUA)
    MACRO_VESPERA_HORA     hora do aviso, HH:MM (por omissão 19:00)
    MACRO_VESPERA_NIVEL    «alta» (só os mais importantes, por omissão) ou «media» (inclui também os médios)
    MACRO_VESPERA_ATIVO=0  desliga o aviso
"""

import json
import os
from datetime import date, datetime, timedelta

import requests

import calendario_macro as cm

ARQ = "macro_vespera_estado.json"
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
HORA_FIM = 22


def _webhook():
    return os.environ.get("WEBHOOK_MACRO") or os.environ.get("WEBHOOK_RELATORIO")


def _hora():
    try:
        h, m = os.environ.get("MACRO_VESPERA_HORA", "19:00").split(":")
        return int(h), int(m)
    except Exception:
        return 19, 0


def _niveis():
    return ("alta", "media") if os.environ.get("MACRO_VESPERA_NIVEL", "alta").lower().startswith("m") else ("alta",)


def _ler():
    try:
        with open(ARQ, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _gravar(d):
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQ)


def eventos_de(dia):
    return [e for e in cm.proximos(0, dia) if e["data"] == dia.isoformat() and e.get("nivel") in _niveis()]


def mensagem(dia, eventos):
    linhas = []
    for e in eventos:
        icone = "🔴" if e.get("nivel") == "alta" else "🟡"
        linhas.append(f"{icone} **{e.get('hora') or 'hora a confirmar'}** · {e['titulo']}")
        if e.get("explica"):
            linhas.append(f"> {e['explica'].strip()[:300]}")
    linhas.append("\nÉ habitual o mercado mexer mais nestas horas: atenção a stops apertados e a ordens ao mercado. "
                  "Agenda completa no terminal → Juros & dados oficiais.")
    return {"username": "Agenda macro · Portal Bolsa",
            "embeds": [{"title": f"📅 Amanhã ({DIAS[dia.weekday()]}, {dia.day:02d}/{dia.month:02d}) na agenda macro",
                        "description": "\n".join(linhas)[:4000], "color": 0xE3B341,
                        "footer": {"text": "Horas de Lisboa · Fontes: BCE, Reserva Federal, U.S. Bureau of Labor Statistics · conteúdo educativo"}}]}


def enviar(agora, forcar=False):
    """Envia o aviso de amanhã, se houver eventos. Devolve (ok, mensagem)."""
    amanha = agora.date() + timedelta(days=1)
    est = _ler()
    if not forcar and est.get("dia") == agora.date().isoformat():
        return True, "Já foi tratado hoje."
    evs = eventos_de(amanha)
    if evs:
        url = _webhook()
        if not url:
            return False, "Falta WEBHOOK_MACRO (ou WEBHOOK_RELATORIO)."
        r = requests.post(url, json=mensagem(amanha, evs), timeout=15)
        if r.status_code >= 300:
            return False, f"Discord respondeu {r.status_code}: {r.text[:150]}"
    est.update({"dia": agora.date().isoformat(), "em": datetime.now().isoformat(timespec="seconds"),
                "enviados": len(evs), "titulos": [e["titulo"] for e in evs]})
    est.pop("erro", None)
    _gravar(est)
    return True, (f"Aviso enviado: {len(evs)} evento(s) amanhã." if evs else "Amanhã não há eventos importantes: nada a enviar.")


def diario(agora):
    if os.environ.get("MACRO_VESPERA_ATIVO", "1") == "0":
        return
    h, m = _hora()
    if not (agora.replace(hour=h, minute=m, second=0, microsecond=0) <= agora < agora.replace(hour=HORA_FIM, minute=0, second=0, microsecond=0)):
        return
    est = _ler()
    hoje = agora.date().isoformat()
    if est.get("dia") == hoje:
        return
    if est.get("dia_tentativa") == hoje and est.get("tentativas", 0) >= 3:
        return
    if est.get("dia_tentativa") == hoje and (datetime.now() - datetime.fromisoformat(est["ultima_tentativa"])).total_seconds() < 1800:
        return
    est["tentativas"] = (est.get("tentativas", 0) + 1) if est.get("dia_tentativa") == hoje else 1
    est.update({"dia_tentativa": hoje, "ultima_tentativa": datetime.now().isoformat(timespec="seconds")})
    _gravar(est)
    try:
        ok, msg = enviar(agora)
    except Exception as e:
        ok, msg = False, str(e)[:200]
    if not ok:
        est = _ler()
        est["erro"] = f"{datetime.now():%d/%m %H:%M} · {msg}"
        _gravar(est)
    if not ok or "enviado" in msg:
        print(f"[macro-véspera] {msg}")


def estado():
    est = _ler()
    h, m = _hora()
    return {"ativo": os.environ.get("MACRO_VESPERA_ATIVO", "1") != "0", "hora": f"{h:02d}:{m:02d}",
            "niveis": list(_niveis()), "webhook": bool(_webhook()),
            "sala": "WEBHOOK_MACRO" if os.environ.get("WEBHOOK_MACRO") else ("WEBHOOK_RELATORIO" if os.environ.get("WEBHOOK_RELATORIO") else None),
            "ultimo": est.get("em"), "ultimo_n": est.get("enviados"), "ultimo_titulos": est.get("titulos"),
            "erro": est.get("erro")}


def registar(app, e_admin):
    from flask import jsonify, request

    def _agora():
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("Europe/Lisbon")).replace(tzinfo=None)
        except Exception:
            return datetime.now()

    @app.route("/api/admin/macro_vespera", methods=["GET", "POST"])
    def macro_vespera_admin():
        if not e_admin():
            return jsonify({"erro": "Acesso negado. Apenas Admin."}), 403
        if request.method == "POST":
            origem = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if origem and request.host not in origem:
                return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
            try:
                ok, msg = enviar(_agora(), forcar=True)
            except Exception as e:
                ok, msg = False, str(e)[:200]
            return jsonify({"sucesso": ok, "mensagem": msg}), (200 if ok else 502)
        amanha = _agora().date() + timedelta(days=1)
        return jsonify({**estado(), "amanha": amanha.isoformat(),
                        "eventos_amanha": [{k: e.get(k) for k in ("hora", "titulo", "nivel", "fonte")} for e in eventos_de(amanha)]})
