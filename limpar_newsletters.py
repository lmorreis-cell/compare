"""
limpar_newsletters.py — Apaga as newsletters antigas, mantendo só as mais recentes de cada região.

Corre automaticamente no GitHub Actions logo depois de gerar as newsletters do dia
(ver .github/workflows/gerar_radar.yml). Na primeira execução limpa também todas as
newsletters acumuladas no repositório.

    python limpar_newsletters.py              # mantém as 5 mais recentes de cada região
    NEWSLETTERS_A_MANTER=3 python limpar_newsletters.py

Segurança:
  - A ordem é decidida pela data escrita no NOME do ficheiro (ex.: ..._27oct26.html),
    nunca pela data de modificação (que no GitHub é igual para todos os ficheiros).
  - Ficheiros cujo nome não tem uma data reconhecível nunca são apagados.
  - Nunca apaga a newsletter mais recente, mesmo que NEWSLETTERS_A_MANTER seja 0.
"""

import glob
import os
import re
import subprocess
from datetime import datetime

MANTER = max(1, int(os.environ.get("NEWSLETTERS_A_MANTER", 5)))
PADROES = {
    "Europa": "radar_europeu_escolhidos_*.html",
    "States": "radar_states_escolhidos_*.html",
}


def data_do_nome(caminho):
    """'radar_europeu_escolhidos_27oct26.html' -> datetime(2026, 10, 27). None se não reconhecer."""
    m = re.search(r"_(\d{2})([a-z]{3})(\d{2})\.html$", os.path.basename(caminho).lower())
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2).capitalize()}{m.group(3)}", "%d%b%y")
    except ValueError:
        return None


def apagar(caminho):
    # 'git rm' regista a remoção no commit; se o ficheiro não estiver no git, apaga só do disco
    r = subprocess.run(["git", "rm", "-q", "--", caminho], capture_output=True, text=True)
    if r.returncode != 0 and os.path.exists(caminho):
        os.remove(caminho)


def main():
    total = 0
    for regiao, padrao in PADROES.items():
        datados = [(data_do_nome(f), f) for f in glob.glob(padrao)]
        datados = sorted([(d, f) for d, f in datados if d is not None], reverse=True)
        a_apagar = [f for _, f in datados[MANTER:]]
        for f in a_apagar:
            apagar(f)
        total += len(a_apagar)
        mantidas = ", ".join(os.path.basename(f) for _, f in datados[:MANTER]) or "nenhuma"
        print(f"[{regiao}] mantidas: {mantidas} | apagadas: {len(a_apagar)}")
    print(f"Limpeza concluída: {total} newsletters antigas removidas.")


if __name__ == "__main__":
    main()
