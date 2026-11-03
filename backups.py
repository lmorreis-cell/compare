"""
backups.py — Cópias de segurança diárias dos dados do portal (os que NÃO estão no GitHub).

O código está no GitHub, mas os dados vivem só no servidor: carteiras e histórico da Liga,
janelas, progresso e lições da Escola, watchlist, acessos, estados dos briefings. Um ficheiro
corrompido ou apagado num deploy fazia perder meses de trabalho.

    - Todos os dias às 03:00 (Lisboa) cria backups/backup_AAAA-MM-DD_HHMM.zip (mantém os últimos 30).
    - Se WEBHOOK_ADMIN existir, envia também o .zip para a tua sala privada do Discord
      (cópia FORA do servidor). Acima de 8 MB envia uma versão sem imagens da Escola.
    - Na Área de Gestão: criar agora, descarregar e repor. Antes de repor, é criada
      automaticamente uma cópia do estado atual ("antes_de_repor"), para poderes voltar atrás.

Nunca entram: código (.py/.html), a fotografia diária do mercado (refaz-se sozinha), caches,
gráficos da Escola (regeneráveis) e as próprias cópias de segurança.
"""

import fnmatch
import json
import os
import threading
import zipfile
from datetime import datetime

PASTA = "backups"
MANTER = 30
LIMITE_DISCORD = 8 * 1024 * 1024

# O que entra (relativo à raiz do projeto)
INCLUIR = [
    "*.json",                      # liga_*, watchlist, acessos, contador, alertas, ...
    "escola/*.json",               # lições, progresso, alunos
    "escola/imagens/*",            # imagens das lições (únicas: não se refazem)
    "snapshot/estado*.json",       # estado da fotografia e dos briefings (pequenos)
]
EXCLUIR = ["*.tmp", "setores_cache.json", "macro_calendar.json", "escola/backups/*", "escola/graficos/*", f"{PASTA}/*"]

_lock = threading.Lock()


def _ficheiros():
    encontrados = []
    for raiz, pastas, nomes in os.walk("."):
        raiz_rel = os.path.relpath(raiz, ".")
        if raiz_rel.startswith((".git", PASTA, "__pycache__", "static", "templates", "node_modules")):
            pastas[:] = []
            continue
        for n in nomes:
            rel = os.path.normpath(os.path.join(raiz_rel, n)).replace("\\", "/")
            if rel.startswith("./"):
                rel = rel[2:]
            if any(fnmatch.fnmatch(rel, p) for p in INCLUIR) and not any(fnmatch.fnmatch(rel, p) for p in EXCLUIR):
                # *.json na raiz: só a raiz (não apanha subpastas por engano)
                if fnmatch.fnmatch(rel, "*.json") and "/" in rel and not any(fnmatch.fnmatch(rel, p) for p in INCLUIR[1:]):
                    continue
                encontrados.append(rel)
    return sorted(encontrados)


def criar(motivo="diario", sem_imagens=False, agora=None):
    """Cria o .zip. Devolve (nome, tamanho_bytes, n_ficheiros)."""
    with _lock:
        os.makedirs(PASTA, exist_ok=True)
        carimbo = (agora or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
        nome = f"backup_{carimbo}_{motivo}.zip"
        caminho = os.path.join(PASTA, nome)
        ficheiros = [f for f in _ficheiros() if not (sem_imagens and f.startswith("escola/imagens/"))]
        with zipfile.ZipFile(caminho + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
            for f in ficheiros:
                try:
                    z.write(f, f)
                except OSError:
                    pass
            z.writestr("_info.json", json.dumps({"criado_em": datetime.now().isoformat(timespec="seconds"),
                                                 "motivo": motivo, "ficheiros": ficheiros}, ensure_ascii=False, indent=1))
        os.replace(caminho + ".tmp", caminho)
        _limpar()
        return nome, os.path.getsize(caminho), len(ficheiros)


def _limpar():
    zips = sorted(f for f in os.listdir(PASTA) if f.startswith("backup_") and f.endswith(".zip"))
    for velho in zips[:-MANTER]:
        try:
            os.remove(os.path.join(PASTA, velho))
        except OSError:
            pass


def listar():
    if not os.path.isdir(PASTA):
        return []
    out = []
    for f in sorted(os.listdir(PASTA), reverse=True):
        if f.startswith("backup_") and f.endswith(".zip"):
            p = os.path.join(PASTA, f)
            try:
                with zipfile.ZipFile(p) as z:
                    info = json.loads(z.read("_info.json"))
                n = len(info.get("ficheiros", []))
                motivo = info.get("motivo", "")
                criado = info.get("criado_em")
            except Exception:
                n, motivo, criado = None, "?", None
            out.append({"nome": f, "tamanho": os.path.getsize(p), "ficheiros": n, "motivo": motivo, "criado_em": criado})
    return out


def caminho_valido(nome):
    """Só aceita nomes de cópias existentes (nada de ../)."""
    if not nome or "/" in nome or "\\" in nome or not (nome.startswith("backup_") and nome.endswith(".zip")):
        return None
    p = os.path.join(PASTA, nome)
    return p if os.path.isfile(p) else None


def conteudo(nome):
    p = caminho_valido(nome)
    if not p:
        return None
    with zipfile.ZipFile(p) as z:
        return [i.filename for i in z.infolist() if i.filename != "_info.json"]


def repor(nome, so=None):
    """Repõe os ficheiros de uma cópia (todos, ou só os da lista 'so').
    Primeiro guarda o estado atual numa cópia 'antes_de_repor'. Devolve (n_repostos, nome_copia_previa)."""
    p = caminho_valido(nome)
    if not p:
        raise ValueError("Cópia de segurança não encontrada.")
    previa, _t, _n = criar("antes_de_repor")
    n = 0
    with _lock, zipfile.ZipFile(p) as z:
        for info in z.infolist():
            f = info.filename
            if f == "_info.json" or f.endswith("/"):
                continue
            if so and f not in so:
                continue
            # Segurança: só repõe caminhos que o backup pode conter
            destino = os.path.normpath(f)
            if destino.startswith("..") or os.path.isabs(destino):
                continue
            if not any(fnmatch.fnmatch(f, pat) for pat in INCLUIR):
                continue
            os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
            with z.open(info) as origem, open(destino + ".tmp", "wb") as out:
                out.write(origem.read())
            os.replace(destino + ".tmp", destino)
            n += 1
    return n, previa


# ---------------------------------------------------------------
# AGENDADOR: 1 cópia por dia às 03:00, enviada também para a sala privada
# ---------------------------------------------------------------
def _ja_fez_hoje(hoje):
    return any(f["nome"].startswith(f"backup_{hoje}") and f["motivo"] == "diario" for f in listar())


def diario(agora):
    if not (3 <= agora.hour < 6):
        return
    hoje = agora.strftime("%Y-%m-%d")
    if _ja_fez_hoje(hoje):
        return
    import alertas_admin as aa
    try:
        nome, tamanho, n = criar("diario", agora=agora)
    except Exception as e:
        aa.avisar(f"backup-falhou:{hoje}", "A cópia de segurança de hoje falhou", str(e), "erro")
        return
    print(f"[backups] {nome}: {n} ficheiros, {tamanho / 1024:.0f} KB.")
    caminho = os.path.join(PASTA, nome)
    texto = f"{n} ficheiros · {tamanho / 1024:.0f} KB. Guarda-a fora do servidor (esta mensagem já é uma cópia)."
    if tamanho > LIMITE_DISCORD:
        leve, t2, n2 = criar("discord_sem_imagens", sem_imagens=True)
        caminho, texto = os.path.join(PASTA, leve), (texto + f"\nAnexo sem as imagens da Escola ({t2 / 1024:.0f} KB): "
                                                     "a cópia completa está no servidor (Gestão → Cópias de segurança).")
    aa.avisar(f"backup:{hoje}", f"Cópia de segurança de {datetime.now().strftime('%d/%m')}", texto, "ok",
              ficheiro=caminho, nome_ficheiro=os.path.basename(caminho))
    if "discord_sem_imagens" in caminho:
        try:
            os.remove(caminho)  # só servia para o anexo; a cópia completa fica no servidor
        except OSError:
            pass
