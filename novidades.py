"""
novidades.py — Página «O que há de novo» (/novidades) e a etiqueta «novo» na página inicial.

As novidades ficam em novidades.json (dados do servidor, entram na cópia de segurança diária) e geram-se
na Área de Gestão → cartão «O que há de novo»: acrescentar, editar e apagar. Na primeira vez o ficheiro
é criado com as novidades mais recentes do portal.

A etiqueta «novo» funciona no browser de cada membro: o portal guarda (localStorage) a data da última
novidade que esse membro já viu. Nada disto vai para o servidor.

Cada novidade: id, data (AAAA-MM-DD), icone, titulo, texto, link (opcional), nivel (1 = todos, 2 = só Patrocinadores).
"""

import json
import os
import threading
import uuid
from datetime import date

from flask import jsonify, render_template_string, request, session

BASE = os.path.dirname(os.path.abspath(__file__))
ARQ = os.path.join(BASE, "novidades.json")
_lock = threading.Lock()

INICIAIS = [
    {"data": "2026-11-06", "icone": "📖", "titulo": "Glossário", "nivel": 1, "link": "/glossario",
     "texto": "80 termos do portal explicados de forma simples, com pesquisa e um link direto para cada termo. Ideal para quem está a começar."},
    {"data": "2026-11-06", "icone": "📈", "titulo": "Gráficos do TradingView no terminal", "nivel": 2, "link": "/interativo#tab-acoes",
     "texto": "Gráfico interativo no Sniper, no Duelo e no Laboratório de cripto, com indicadores e desenho de linhas. Na Pulsação da sessão americana há um mapa de calor do S&P 500 e do Nasdaq 100."},
    {"data": "2026-11-06", "icone": "📰", "titulo": "Newsletters verificadas antes de sair", "nivel": 1, "link": "/ver/states",
     "texto": "As variações do dia nas newsletters Radar são confirmadas com os fechos oficiais antes de a newsletter ser publicada."},
    {"data": "2026-11-05", "icone": "❓", "titulo": "Pergunta do dia no Discord", "nivel": 1, "link": "/escola",
     "texto": "Nos dias úteis às 12:30 sai uma pergunta da lição da Escola em sondagem; a resposta chega no dia seguinte, escondida em spoiler."},
    {"data": "2026-11-05", "icone": "🌱", "titulo": "Simulador de poupança", "nivel": 2, "link": "/interativo#tab-oficial",
     "texto": "Compara depósitos, Certificados de Aforro e um ETF de ações ao longo dos anos, com IRS e inflação. As contas são feitas só no teu browser."},
    {"data": "2026-11-05", "icone": "🧭", "titulo": "Confiança na economia", "nivel": 2, "link": "/interativo#tab-oficial",
     "texto": "Sentimento económico e confiança de consumidores, indústria e serviços em Portugal e na área do euro (Comissão Europeia)."},
    {"data": "2026-11-03", "icone": "🌍", "titulo": "Novos dados oficiais", "nivel": 2, "link": "/interativo#tab-oficial",
     "texto": "Probabilidade de recessão da Fed de Nova Iorque, stress financeiro do BCE, juros da dívida europeia, juros dos bancos portugueses, inflação, desemprego e preços das casas."},
    {"data": "2026-11-01", "icone": "🏛️", "titulo": "Cofre fiscal com mais moedas", "nivel": 2, "link": "/interativo#tab-cofre",
     "texto": "O Cofre aceita agora coroas dinamarquesas e outras moedas, e reconhece tickers como BRK-B."},
]


def _ler():
    try:
        with open(ARQ, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        lista = [dict(x, id=uuid.uuid4().hex[:8]) for x in INICIAIS]
        _gravar(lista)
        return lista
    except Exception:
        return []


def _gravar(lista):
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQ)


def lista():
    """Todas as novidades, da mais recente para a mais antiga (as de Patrocinador aparecem a todos, com etiqueta)."""
    return sorted(_ler(), key=lambda x: (x.get("data", ""), x.get("id", "")), reverse=True)


def ultima_data():
    l = lista()
    return l[0]["data"] if l else ""


def _validar(b):
    titulo = str(b.get("titulo", "")).strip()[:120]
    texto = str(b.get("texto", "")).strip()[:600]
    if not titulo or not texto:
        raise ValueError("Falta o título ou o texto.")
    d = str(b.get("data") or date.today().isoformat())[:10]
    date.fromisoformat(d)
    link = str(b.get("link", "")).strip()[:200]
    if link and not (link.startswith("/") or link.startswith("https://")):
        raise ValueError("O link tem de começar por / (página do portal) ou https://")
    return {"data": d, "titulo": titulo, "texto": texto, "link": link,
            "icone": (str(b.get("icone", "")).strip() or "✨")[:4], "nivel": 2 if int(b.get("nivel", 1) or 1) >= 2 else 1}


PAGINA = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>O que há de novo · Portal Bolsa</title>
<style>
  :root { --fundo:#0b0e14; --painel:#11161f; --linha:#232b38; --texto:#e6edf3; --suave:#9aa6b8; --mudo:#6e7a8c; --laranja:#f28b24; --azul:#4da6ff; --verde:#3fbf8f; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fundo); color:var(--texto); font-family:Inter, "Segoe UI", Arial, sans-serif; font-size:15px; line-height:1.55; }
  header { border-bottom:1px solid var(--linha); }
  .topo { max-width:820px; margin:0 auto; padding:14px 18px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .topo h1 { font-size:18px; margin:0; flex:1; }
  .topo a { color:var(--suave); text-decoration:none; font-size:13px; border:1px solid var(--linha); border-radius:999px; padding:6px 12px; }
  main { max-width:820px; margin:0 auto; padding:18px; }
  .dia { font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:var(--mudo); margin:22px 0 8px; }
  .nov { background:var(--painel); border:1px solid var(--linha); border-radius:10px; padding:14px 16px; margin-bottom:10px; display:flex; gap:12px; }
  .nov.e-nova { border-color:rgba(242,139,36,.6); }
  .ic { font-size:24px; line-height:1; }
  .nov h3 { margin:0 0 4px; font-size:16px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .nov p { margin:0; color:#cdd6e0; }
  .tag { font-size:10.5px; font-weight:800; text-transform:uppercase; letter-spacing:.4px; border-radius:999px; padding:2px 8px; }
  .tag-novo { background:rgba(242,139,36,.15); color:var(--laranja); }
  .tag-pat { background:rgba(77,166,255,.12); color:var(--azul); }
  .nov a.abrir { display:inline-block; margin-top:8px; font-size:13px; color:var(--azul); text-decoration:none; }
  .vazio { color:var(--mudo); text-align:center; padding:40px 0; }
</style>
</head>
<body>
<header><div class="topo"><h1>🆕 O que há de novo</h1><a href="/">Página inicial</a><a href="/glossario">📖 Glossário</a></div></header>
<main>
  <div id="lista"></div>
</main>
<script>
const NOV = {{ novidades|tojson }};
const NIVEL = {{ nivel }};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let visto = ""; try { visto = localStorage.getItem("novidadesVisto") || ""; } catch (e) {}
const MESES = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"];
const dataPt = d => { const [a, m, dd] = d.split("-").map(Number); return `${dd} de ${MESES[m - 1]} de ${a}`; };
let h = "", ultimoDia = "";
for (const n of NOV) {
  if (n.data !== ultimoDia) { h += `<div class="dia">${dataPt(n.data)}</div>`; ultimoDia = n.data; }
  const nova = !visto || n.data > visto;
  const bloqueado = n.nivel >= 2 && NIVEL < 2;
  h += `<div class="nov${nova && visto ? " e-nova" : ""}"><div class="ic">${esc(n.icone)}</div><div>
    <h3>${esc(n.titulo)} ${nova && visto ? '<span class="tag tag-novo">novo</span>' : ""} ${n.nivel >= 2 ? '<span class="tag tag-pat">Patrocinador</span>' : ""}</h3>
    <p>${esc(n.texto)}</p>
    ${n.link && !bloqueado ? `<a class="abrir" href="${esc(n.link)}">Experimentar →</a>` : ""}
  </div></div>`;
}
document.getElementById("lista").innerHTML = h || '<div class="vazio">Ainda não há novidades.</div>';
try { if (NOV.length) localStorage.setItem("novidadesVisto", NOV[0].data); } catch (e) {}
</script>
</body>
</html>"""


def registar(app, requer_cargo, e_admin):
    @app.context_processor
    def _novidades_ultima():
        # Disponível em todos os templates (a página inicial usa-o para a etiqueta «novo»)
        try:
            return {"novidades_ultima": ultima_data()}
        except Exception:
            return {"novidades_ultima": ""}

    @app.route("/novidades")
    @requer_cargo(nivel_minimo=1)
    def novidades_pagina():
        nivel = int(session.get("nivel_acesso", 0) or 0)
        return render_template_string(PAGINA, novidades=lista(), nivel=nivel)

    def negado():
        if not e_admin():
            return jsonify({"erro": "Acesso negado. Apenas Admin."}), 403
        if request.method != "GET":
            origem = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if origem and request.host not in origem:
                return jsonify({"erro": "Pedido recusado (origem inválida)."}), 403
        return None

    @app.route("/api/admin/novidades", methods=["GET", "POST"])
    def novidades_admin():
        n = negado()
        if n:
            return n
        if request.method == "POST":
            b = request.get_json(silent=True) or {}
            try:
                with _lock:
                    todas = _ler()
                    if b.get("apagar"):
                        todas = [x for x in todas if x.get("id") != b["apagar"]]
                    else:
                        nova = _validar(b)
                        if b.get("id"):
                            for i, x in enumerate(todas):
                                if x.get("id") == b["id"]:
                                    todas[i] = dict(nova, id=x["id"])
                                    break
                            else:
                                raise ValueError("Novidade não encontrada.")
                        else:
                            todas.append(dict(nova, id=uuid.uuid4().hex[:8]))
                    _gravar(todas)
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400
        return jsonify({"novidades": lista()})
