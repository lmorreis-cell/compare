"""
agendador.py — Relógio interno do portal (dispensa configurar crons externos).

Dias úteis (segunda a sexta, hora de Lisboa):
    22:30 → tira o Snapshot diário (depois do fecho de Wall Street, às 21:00 em Lisboa)
    07:50 → envia o Briefing PSI para o Discord (sala WEBHOOK_RELATORIO_PSI; ver relatorio_psi.py)
    08:00 → envia o Briefing Matinal para o Discord (com o snapshot da noite anterior)

Sábados (hora de Lisboa):
    10:00 → envia o Briefing Semanal (relatorio_semanal.py; HORA_SEMANAL muda a hora)

Todos os dias (hora de Lisboa):
    03:00 → cópia de segurança dos dados (backups.py), enviada também para a sala privada do Admin
    17:00 → câmbios de referência e juros do BCE (fontes_bce.py)
    19:00 → posições curtas publicadas pelos reguladores europeus (posicoes_curtas.py)
    22:00 → curva de juros dos EUA e Commitments of Traders da CFTC; 12:00 → indicadores avançados da OCDE (fontes_mundo.py)
    de 30 em 30 min (dias úteis, 11:00–24:00) → comunicados 8-K dos tickers vigiados para o Discord; 04:00 → carteiras 13F (sec_dados.py)
    de hora a hora (dias úteis, 08:00–22:00) → comunicados da CMVM: dirigentes, participações qualificadas, ações próprias (cmvm_comunicados.py)
    12:00 → juros dos bancos em Portugal (Banco de Portugal) e inflação, desemprego e habitação (Eurostat/INE) (fontes_portugal.py)
    06:00 → agenda macro: reuniões do BCE e da Fed, publicações do BLS (calendario_macro.py); 05:00 → fails-to-deliver da SEC
    12:30 (dias úteis; sábado só a resposta) → pergunta do dia da Escola no Discord (escola_discord.py; WEBHOOK_ESCOLA)
    sempre → vigia: avisa o Admin em privado se a fotografia, um briefing ou um aviso falhar (alertas_admin.py)

Todos os dias (10:00–21:59, hora de Lisboa):
    Liga Mensal → avisos automáticos no Discord (inscrições abertas, último dia, nevoeiro levantou,
    resumo da edição). Cada aviso sai uma única vez; ver liga_avisos.py. LIGA_AVISOS_ATIVO=0 desliga.

Travões de segurança (para nunca repetir o erro do loop):
  - O snapshot só corre uma vez por dia; se falhar, tenta no máximo 3 vezes, com 45 min de intervalo.
  - O snapshot só corre na janela 22:30–23:59: um reinício do servidor a meio do dia não o dispara.
  - O briefing só é enviado uma vez por dia, na janela 08:00–10:59.
  - Se o Yahoo estiver em pausa de proteção, o snapshot espera pela tentativa seguinte.

Variáveis de ambiente opcionais (Discloud → Variáveis):
    AGENDADOR_ATIVO=0        desliga o agendador
    HORA_SNAPSHOT=22:30      muda a hora do snapshot
    HORA_RELATORIO=08:00     muda a hora do briefing
    HORA_RELATORIO_PSI=07:50 muda a hora do Briefing PSI
    RELATORIO_ATIVO=0        mantém o snapshot mas não envia o briefing
"""

import os
import threading
import time
from datetime import datetime, timedelta

import yahoo_guard as yg
import snapshot_diario as snap
import relatorio_matinal as rel
import relatorio_psi as rel_psi
import relatorio_semanal as rel_sem
import liga_avisos
import backups
import alertas_admin
import fontes_bce
import posicoes_curtas
import fontes_mundo
import sec_dados
import cmvm_comunicados
import fontes_portugal
import calendario_macro
import escola_discord

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
    print("[agendador] Ativo: snapshot às %02d:%02d, briefing PSI às %02d:%02d e briefing EUA às %02d:%02d (dias úteis, Lisboa)."
          % (_hora("HORA_SNAPSHOT", "22:30") + rel_psi.hora_envio() + _hora("HORA_RELATORIO", "08:00")))
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
        try:
            rel_psi.envio_agendado(agora_lisboa())  # Briefing PSI (independente do snapshot e do briefing EUA)
        except Exception as e:
            print(f"[agendador] Erro no Briefing PSI: {e}")
        for tarefa, nome in ((rel_sem.envio_agendado, "Briefing Semanal"), (backups.diario, "cópia de segurança"),
                             (alertas_admin.vigiar, "vigia"), (fontes_bce.diario, "atualização do BCE"),
                             (posicoes_curtas.diario, "atualização das posições curtas"),
                             (fontes_mundo.diario, "atualização dos dados macro (Tesouro/OCDE/CFTC)"),
                             (sec_dados.diario, "vigilância da SEC (8-K e 13F)"),
                             (cmvm_comunicados.diario, "leitura dos comunicados da CMVM"),
                             (fontes_portugal.diario, "atualização do Banco de Portugal e do Eurostat"),
                             (calendario_macro.diario, "atualização da agenda macro"),
                             (escola_discord.diario, "pergunta do dia da Escola")):
            try:
                tarefa(agora_lisboa())
            except Exception as e:
                print(f"[agendador] Erro na {nome}: {e}")
        try:
            liga_avisos.verificar(agora_lisboa())  # avisos da Liga (independentes do snapshot e do briefing)
        except Exception as e:
            print(f"[agendador] Erro nos avisos da Liga: {e}")
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
