"""
pwa.py — A «app no telemóvel» (PWA) foi DESLIGADA: o portal continua a usar-se só no browser, como sempre.

Este ficheiro ficou apenas com duas coisas pequenas:
    /favicon.ico   o ícone PB que aparece no separador do browser (pasta pwa/ ao lado do main.py).
                   Todas as páginas recebem também <link rel="icon" …?v=N>: os browsers guardam durante muito tempo
                   a «falta de ícone» de um site, e o ?v=N obriga-os a ir buscá-lo de novo.
    /sw.js         limpeza: se alguém chegou a abrir a versão com a app, o browser dessa pessoa apaga sozinho
                   o service worker antigo e as caches na visita seguinte. Pode ser retirado daqui a umas semanas.

Não há manifest, aviso «Instalar», página offline nem sessão prolongada.

Integração no main.py (depois de criar a app):
    import pwa
    pwa.registar(app)
"""

import os

from flask import Response, send_from_directory

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pwa")
VERSAO_ICONE = "2"
LINK_ICONE = f'<link rel="icon" type="image/png" sizes="32x32" href="/favicon.png?v={VERSAO_ICONE}">\n'


SW_LIMPEZA = """// A app do Portal foi desligada: remove este service worker e limpa as caches
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k))))
    .then(() => self.registration.unregister()));
});
"""


def registar(app):
    @app.route("/sw.js")
    def pwa_sw_limpeza():
        r = Response(SW_LIMPEZA, mimetype="application/javascript")
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.route("/favicon.ico")
    @app.route("/favicon.png")
    def pwa_favicon():
        return send_from_directory(PASTA, "favicon-32.png", mimetype="image/png", max_age=7 * 24 * 3600)

    @app.after_request
    def _icone_nas_paginas(resp):
        try:
            if resp.direct_passthrough or resp.status_code != 200 or resp.mimetype != "text/html":
                return resp
            html = resp.get_data(as_text=True)
            fim = html.find("</head>")
            if fim == -1 or 'rel="icon"' in html[:fim]:
                return resp
            resp.set_data(html[:fim] + LINK_ICONE + html[fim:])
        except Exception as e:  # nunca estraga uma página por causa do ícone
            print(f"[favicon] {e}")
        return resp
