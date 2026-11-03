"""
alertas_admin.py — Avisos PRIVADOS ao Admin (sala do Discord só tua) quando alguma peça do portal falha.

Webhook: WEBHOOK_ADMIN (obrigatório para os avisos saírem; sem ele tudo fica só no registo da Gestão).

O que vigia (chamado pelo agendador.py a cada minuto, função vigiar):
    07:00–07:45  dias úteis  → a fotografia diária da noite anterior não correu / teve erros
    10:00–10:30  dias úteis  → o Briefing PSI ou o Briefing EUA não saiu hoje
    13:15–13:45  sábados     → o Briefing Semanal não saiu
    a qualquer hora          → o Yahoo entrou em pausa de proteção (1 aviso por dia)
    a qualquer hora          → um aviso automático da Liga falhou (1 aviso por erro)
Os módulos também podem chamar avisar(...) diretamente (ex.: cópias de segurança).

Cada aviso tem uma chave e só é enviado UMA vez (registo em alertas_admin.json, últimos 200).
"""

import json
import os
import threading
from datetime import datetime, timedelta

import requests

ARQ = "alertas_admin.json"
_lock = threading.Lock()
NIVEIS = {"erro": (14242639, "🔴"), "aviso": (15773006, "🟡"), "info": (5793266, "🔵"), "ok": (6076508, "🟢")}


def _webhook():
    return os.environ.get("WEBHOOK_ADMIN")


def _ler():
    try:
        with open(ARQ, "r", encoding="utf-8") as f:
            d = json.load(f)
            d.setdefault("enviados", {})
            d.setdefault("registo", [])
            return d
    except Exception:
        return {"enviados": {}, "registo": []}


def _gravar(d):
    # Mantém o ficheiro pequeno: últimas 200 chaves e últimos 50 registos
    if len(d["enviados"]) > 200:
        d["enviados"] = dict(sorted(d["enviados"].items(), key=lambda kv: kv[1])[-200:])
    d["registo"] = d["registo"][-50:]
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQ)


def avisar(chave, titulo, texto, nivel="erro", ficheiro=None, nome_ficheiro=None, repetir=False):
    """Envia um aviso privado. Com a mesma chave só sai uma vez (salvo repetir=True).
    ficheiro: caminho opcional para anexar (ex.: cópia de segurança). Devolve (ok, info)."""
    with _lock:
        d = _ler()
        if not repetir and chave in d["enviados"]:
            return False, "já enviado"
        agora = datetime.now().isoformat(timespec="seconds")
        reg = {"em": agora, "chave": chave, "titulo": titulo, "texto": texto[:500], "nivel": nivel}
        url = _webhook()
        if not url:
            reg["estado"] = "sem WEBHOOK_ADMIN"
            d["registo"].append(reg)
            d["enviados"][chave] = agora
            _gravar(d)
            return False, "sem WEBHOOK_ADMIN"
        cor, icone = NIVEIS.get(nivel, NIVEIS["erro"])
        embed = {"title": f"{icone} {titulo}"[:256], "description": texto[:3900], "color": cor,
                 "footer": {"text": "Portal Bolsa · aviso privado do Admin · " + datetime.now().strftime("%d/%m %H:%M")}}
        try:
            if ficheiro and os.path.exists(ficheiro):
                with open(ficheiro, "rb") as fh:
                    r = requests.post(url, data={"payload_json": json.dumps({"username": "Portal · Admin", "embeds": [embed]})},
                                      files={"files[0]": (nome_ficheiro or os.path.basename(ficheiro), fh)}, timeout=60)
            else:
                r = requests.post(url, json={"username": "Portal · Admin", "embeds": [embed]}, timeout=15)
            ok = r.status_code < 300
            reg["estado"] = "enviado" if ok else f"HTTP {r.status_code}"
        except Exception as e:
            ok, reg["estado"] = False, f"falhou: {e}"
        d["registo"].append(reg)
        if ok:
            d["enviados"][chave] = agora
        _gravar(d)
        return ok, reg["estado"]


def estado():
    d = _ler()
    return {"webhook": bool(_webhook()), "registo": list(reversed(d["registo"][-15:]))}


# ---------------------------------------------------------------
# VIGIA (agendador)
# ---------------------------------------------------------------
_ultimo_bloqueio = {"dia": None}


def _dia_util_anterior(d):
    d -= timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def vigiar(agora):
    """agora = hora de Lisboa (naive). Nunca lança exceções para o agendador."""
    try:
        _vigiar(agora)
    except Exception as e:
        print(f"[alertas-admin] Erro na vigia: {e}")


def _vigiar(agora):
    hoje = agora.date()
    hm = (agora.hour, agora.minute)

    # 1) Fotografia diária (de manhã, sobre a noite anterior)
    if agora.weekday() <= 4 and (7, 0) <= hm < (7, 45):
        import snapshot_diario as snap
        est = snap.estado()
        ontem = _dia_util_anterior(hoje).isoformat()
        if est.get("a_correr"):
            pass
        elif est.get("dia_sucesso") != ontem and est.get("dia_sucesso", "") < ontem:
            erros = est.get("erros") or []
            avisar(f"snapshot:{ontem}", "A fotografia diária de ontem falhou",
                   f"Último sucesso: {est.get('ultimo_sucesso') or 'nunca'} · tentativas: {est.get('tentativas_hoje', 0)}.\n"
                   + ("Erros:\n• " + "\n• ".join(erros[:6]) if erros else "Sem registo de erros (o servidor esteve desligado?).")
                   + "\n\nSem fotografia fresca o Screener e o Briefing EUA usam dados antigos. "
                     "Podes lançá-la na Gestão (demora 10–15 min).", "erro")
        elif est.get("dia_sucesso") == ontem and est.get("erros"):
            erros = est["erros"]
            avisar(f"snapshot-avisos:{ontem}", f"Fotografia de ontem concluída com {len(erros)} aviso(s)",
                   "• " + "\n• ".join(erros[:8]), "aviso")

    # 2) Briefings (depois da janela de envio)
    if agora.weekday() <= 4 and (10, 0) <= hm < (10, 30):
        import relatorio_psi as rel_psi
        import relatorio_matinal as rel
        for nome, est, var in (("Briefing PSI", rel_psi.estado(), "WEBHOOK_RELATORIO_PSI"),
                               ("Briefing EUA", rel.estado(), "WEBHOOK_RELATORIO")):
            dia = hoje.isoformat()
            if not est.get("webhook_configurado"):
                avisar(f"briefing-webhook:{nome}:{dia}", f"{nome}: falta o webhook", f"Define {var} nas Variáveis da Discloud.", "erro")
            elif est.get("dia_envio") != dia:
                avisar(f"briefing:{nome}:{dia}", f"{nome} não saiu hoje",
                       f"Último envio: {est.get('ultimo_envio') or 'nunca'}.\nÚltimo erro: {est.get('ultimo_erro') or '—'}\n\n"
                       "Podes enviá-lo na Gestão com «Enviar agora».", "erro")
            elif not str(est.get("ultimo_envio") or "").startswith(dia):
                avisar(f"briefing-ignorado:{nome}:{dia}", f"{nome} ignorado hoje",
                       "Não havia sessão nova desde o último envio (feriado?). Se não for feriado, envia-o na Gestão.", "info")

    # 2b) Briefing Semanal (sábado, depois da janela de envio)
    if agora.weekday() == 5 and (13, 15) <= hm < (13, 45):
        import relatorio_semanal as rel_sem
        est = rel_sem.estado()
        semana = rel_sem._semana_id(hoje)
        if est.get("semana_envio") != semana:
            avisar(f"semanal:{semana}", "O Briefing Semanal não saiu hoje",
                   f"Último erro: {est.get('ultimo_erro') or '—'}" + ("" if est.get("webhook_configurado") else
                   "\nFalta o webhook: define WEBHOOK_SEMANAL (ou WEBHOOK_RELATORIO).")
                   + "\n\nPodes enviá-lo na Gestão com «Enviar agora».", "erro")

    # 3) Yahoo em pausa de proteção (1 aviso por dia)
    try:
        import yahoo_guard as yg
        if yg.esta_bloqueado():
            avisar(f"yahoo:{hoje.isoformat()}", "O Yahoo entrou em pausa de proteção",
                   "O portal deixou de pedir dados ao Yahoo durante a pausa (levanta-se sozinha). "
                   "O Screener continua a funcionar com a fotografia diária.", "aviso")
    except Exception:
        pass

    # 4) Avisos automáticos da Liga
    try:
        import liga_avisos
        e = (liga_avisos._carregar_estado() or {}).get("ultimo_erro")
        if e:
            avisar(f"liga-aviso:{e.get('chave')}:{e.get('em', '')[:13]}", "Um aviso da Liga não saiu",
                   f"Aviso: {e.get('chave')} · erro: {e.get('erro')}. Volta a tentar no minuto seguinte.", "aviso")
    except Exception:
        pass
