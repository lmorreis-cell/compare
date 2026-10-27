"""
agendador.py — Relógio interno do portal (dispensa configurar crons externos).

Dias úteis (segunda a sexta, hora de Lisboa):
    22:30 → tira o Snapshot diário (depois do fecho de Wall Street, às 21:00 em Lisboa)
    08:00 → envia o Briefing Matinal para o Discord (com o snapshot da noite anterior)

Travões de segurança (para nunca repetir o erro do loop):
  - O snapshot só corre uma vez por dia; se falhar, tenta no máximo 3 vezes, com 45 min de intervalo.
  - O snapshot só corre na janela 22:30–23:59: um reinício do servidor a meio do dia não o dispara.
  - O briefing só é enviado uma vez por dia, na janela 08:00–10:59.
  - Se o Yahoo estiver em pausa de proteção, o snapshot espera pela tentativa seguinte.

Variáveis de ambiente opcionais (Discloud → Variáveis):
    AGENDADOR_ATIVO=0        desliga o agendador
    HORA_SNAPSHOT=22:30      muda a hora do snapshot
    HORA_RELATORIO=08:00     muda a hora do briefing
    RELATORIO_ATIVO=0        mantém o snapshot mas não envia o briefing
"""

import os
import threading
import time
from datetime import datetime, timedelta

import yahoo_guard as yg
import snapshot_diario as snap
import relatorio_matinal as rel

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("Europe/Lisbon")
except Exception:  # sem base de fusos horários no servidor: usa a hora do sistema
    FUSO = None

MAX_TENTATIVAS_DIA = 3
INTERVALO_TENTATIVAS_MIN = 45
_iniciado = False
_lock_inicio = threading.Lock()


def agora_lisboa():
    if FUSO is not None:
        return datetime.now(FUSO).replace(tzinfo=None)
    return datetime.now()


def _hora(var, padrao):
    try:
        h, m = os.environ.get(var, padrao).split(":")
        return int(h), int(m)
    except Exception:
        h, m = padrao.split(":")
        return int(h), int(m)


def _deve_tirar_snapshot(agora):
    if agora.weekday() > 4:
        return False
    h, m = _hora("HORA_SNAPSHOT", "22:30")
    inicio = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (inicio <= agora <= agora.replace(hour=23, minute=59, second=59)):
        return False
    est = snap.estado()
    hoje = agora.strftime('%Y-%m-%d')
    if est.get("a_correr") or est.get("dia_sucesso") == hoje:
        return False
    if est.get("dia_tentativas") == hoje:
        if est.get("tentativas_hoje", 0) >= MAX_TENTATIVAS_DIA:
            return False
        try:
            ultima = datetime.fromisoformat(est.get("ultima_tentativa"))
            if datetime.now() - ultima < timedelta(minutes=INTERVALO_TENTATIVAS_MIN):
                return False
        except Exception:
            pass
    return not yg.esta_bloqueado()


def _deve_enviar_relatorio(agora):
    if os.environ.get("RELATORIO_ATIVO", "1") == "0" or agora.weekday() > 4:
        return False
    h, m = _hora("HORA_RELATORIO", "08:00")
    inicio = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (inicio <= agora < inicio + timedelta(hours=3)):
        return False
    return rel.estado().get("dia_envio") != agora.strftime('%Y-%m-%d')


def _ciclo():
    print("[agendador] Ativo: snapshot às %02d:%02d e briefing às %02d:%02d (dias úteis, Lisboa)."
          % (_hora("HORA_SNAPSHOT", "22:30") + _hora("HORA_RELATORIO", "08:00")))
    time.sleep(30)  # deixa o servidor arrancar primeiro
    while True:
        try:
            agora = agora_lisboa()
            if _deve_tirar_snapshot(agora):
                snap.executar_snapshot()
            elif _deve_enviar_relatorio(agora):
                ok, msg = rel.enviar_relatorio()
                print(f"[agendador] Briefing Matinal: {msg}")
        except Exception as e:
            print(f"[agendador] Erro no ciclo: {e}")
        time.sleep(60)


def iniciar():
    """Arranca o agendador uma única vez por processo."""
    global _iniciado
    if os.environ.get("AGENDADOR_ATIVO", "1") == "0":
        print("[agendador] Desligado (AGENDADOR_ATIVO=0).")
        return
    with _lock_inicio:
        if _iniciado:
            return
        _iniciado = True
    threading.Thread(target=_ciclo, name="agendador-portal", daemon=True).start()
