# -*- coding: utf-8 -*-
"""
Testes do aviso de versão nova. Usa um servidor de mentira só neste computador (não vai ao GitHub).

    python testes/teste_atualizacao.py
"""
import http.server
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import atualizacao as at  # noqa: E402


class Servidor:
    """Imita o GitHub: /releases/latest redireciona para /releases/tag/<tag>."""

    def __init__(self, tag="v2.13-build30", modo="normal"):
        servidor = self
        self.tag, self.modo = tag, modo

        class H(http.server.BaseHTTPRequestHandler):
            def _responder(self):
                if servidor.modo == "erro":
                    self.send_response(500)
                    self.end_headers()
                elif self.path == "/releases/latest":
                    self.send_response(302)
                    self.send_header("Location", "/releases/tag/" + servidor.tag if servidor.modo != "sem_tag" else "/outra/pagina")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            do_HEAD = do_GET = _responder

            def log_message(self, *a):
                pass

        self.http = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:{}/releases/latest".format(self.http.server_address[1])
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def __enter__(self):
        self._antes = at.URL_ULTIMA
        at.URL_ULTIMA = self.url
        return self

    def __exit__(self, *a):
        at.URL_ULTIMA = self._antes
        self.http.shutdown()
        self.http.server_close()


def teste_comparacao_de_versoes():
    assert at.mais_nova("2.13", "2.12")
    assert at.mais_nova("2.10", "2.9"), "2.10 é maior que 2.9 (não é comparação de texto)"
    assert at.mais_nova("3.0", "2.99")
    assert not at.mais_nova("2.12", "2.12")
    assert not at.mais_nova("2.11", "2.12")
    assert not at.mais_nova("2.12.0", "2.12")
    assert at.mais_nova("2.12.1", "2.12")
    assert not at.mais_nova(None, "2.12")
    assert not at.mais_nova("", "2.12")
    assert not at.mais_nova("abc", "2.12")
    assert not at.mais_nova("2.13", None)


def teste_le_a_versao_publicada():
    with Servidor("v2.13-build30"):
        assert at.versao_publicada() == "2.13"
    with Servidor("v2.10-build21"):
        assert at.versao_publicada() == "2.10"
    with Servidor("v3.0"):
        assert at.versao_publicada() == "3.0"


def teste_falhas_nao_viram_aviso():
    with Servidor(modo="erro"):
        assert at.versao_publicada() is None
    with Servidor(modo="sem_tag"):
        assert at.versao_publicada() is None
    antes = at.URL_ULTIMA
    at.URL_ULTIMA = "http://127.0.0.1:9/releases/latest"          # ninguém atende nessa porta (sem internet)
    try:
        assert at.versao_publicada(timeout=2) is None
    finally:
        at.URL_ULTIMA = antes


def _esperar(conferencia, tempo=10):
    t0 = time.time()
    while not conferencia.pronta and time.time() - t0 < tempo:
        time.sleep(0.05)
    return conferencia.pronta


def teste_conferencia_em_segundo_plano():
    with Servidor("v2.13-build30"):
        c = at.Conferencia("2.12")
        assert _esperar(c) and c.nova == "2.13"
        c = at.Conferencia("2.13")
        assert _esperar(c) and c.nova is None, "mesma versão: sem aviso"
        c = at.Conferencia("2.14")
        assert _esperar(c) and c.nova is None, "este programa é mais novo que o publicado: sem aviso"
    with Servidor(modo="erro"):
        c = at.Conferencia("2.12")
        assert _esperar(c) and c.nova is None


def teste_enderecos_apontam_para_o_repositorio_certo():
    assert at.URL_ULTIMA.startswith("https://github.com/janseysilva/gerador-de-declara-o/")
    assert at.URL_BAIXAR.startswith("https://github.com/janseysilva/gerador-de-declara-o/releases/")
    assert at.URL_BAIXAR.endswith("Instalador_DeclaracoesEscolares.exe")


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
