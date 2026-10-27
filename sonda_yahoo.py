"""
sonda_yahoo.py — Verifica se o bloqueio do Yahoo Finance já acabou, com UM ÚNICO pedido.

Uso (no servidor, ou no teu PC para comparar):
    python sonda_yahoo.py            # no máximo 1 sonda por hora (o script recusa correr antes)
    python sonda_yahoo.py --forcar   # ignora o travão (usa com moderação!)

Resultados possíveis:
    LIVRE      -> o Yahoo respondeu com dados: podes reativar o portal e o cron.
    BLOQUEADO  -> 429 Too Many Requests: espera e volta a tentar mais tarde (não insistas).
    OUTRO      -> erro diferente (rede, DNS, 403...): lê a mensagem.

Cada sonda fica registada em sonda_yahoo.log para veres a evolução.
"""

import sys
import time
from datetime import datetime

INTERVALO_MIN_SEG = 60 * 60  # 1 sonda por hora, no máximo
ARQUIVO_ULTIMA = "sonda_yahoo_ultima.txt"
ARQUIVO_LOG = "sonda_yahoo.log"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d"


def registar(linha):
    print(linha)
    try:
        with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def main():
    forcar = "--forcar" in sys.argv

    try:
        with open(ARQUIVO_ULTIMA) as f:
            decorrido = time.time() - float(f.read().strip())
    except Exception:
        decorrido = float("inf")

    if decorrido < INTERVALO_MIN_SEG and not forcar:
        faltam = int((INTERVALO_MIN_SEG - decorrido) // 60) + 1
        print(f"Sonda recusada: a última foi há {int(decorrido // 60)} min. "
              f"Espera mais {faltam} min (cada pedido durante o bloqueio pode prolongá-lo).")
        return

    with open(ARQUIVO_ULTIMA, "w") as f:
        f.write(str(time.time()))

    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        try:
            from curl_cffi import requests as http
            r = http.get(URL, impersonate="chrome", timeout=10)
            motor = "curl_cffi"
        except ImportError:
            import requests as http
            r = http.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            motor = "requests"

        if r.status_code == 200:
            preco = r.json()["chart"]["result"][0]["meta"].get("regularMarketPrice")
            registar(f"[{agora}] LIVRE ({motor}) — AAPL = {preco}. Podes reativar o portal e o cron.")
        elif r.status_code == 429:
            registar(f"[{agora}] BLOQUEADO ({motor}) — 429 Too Many Requests. Volta a tentar daqui a 1-2 horas.")
        else:
            registar(f"[{agora}] OUTRO ({motor}) — HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        registar(f"[{agora}] OUTRO — erro de ligação: {e}")


if __name__ == "__main__":
    main()
