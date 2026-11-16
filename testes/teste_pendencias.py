"""Testes das pendências de lançamento do Gier contra o Gier de mentira (nomes INVENTADOS).

Uso: python testes/teste_pendencias.py
"""
import os
import sys
import threading
from http.server import ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

import gier_falso  # noqa: E402

servidor = ThreadingHTTPServer(("127.0.0.1", 0), gier_falso.H)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
os.environ["GIER_BASE"] = "http://127.0.0.1:{}".format(servidor.server_address[1])

import gier_online  # noqa: E402
import pendencias_gier as pd  # noqa: E402
from frequencia_falsa import FREQ  # noqa: E402


def _sessao():
    s = gier_online.SessaoGier()
    assert s.entrar("usuario", "x")["ok"]
    return s


def teste_turmas_do_ano_uma_por_turma():
    pagina = pd.carregar_frequencia(_sessao())
    assert pagina.ano == "2026"
    # a PE II-F tem duas professoras, mas aparece uma vez só
    assert [t["descricao"] for t in pagina.turmas] == ["PE I-TURMA-A", "PE II -TURMA-F", "PE II -TURMA-L (com erro)"]
    assert pagina.turmas[1]["professor"] == "9002"


def teste_baixa_o_pdf_da_turma_certa():
    s = _sessao()
    pagina = pd.carregar_frequencia(s)
    for turma in pagina.turmas[:2]:
        pdf = pd.baixar_pendencias(s, turma)
        assert pdf[:4] == b"%PDF" and pd.turma_no_pdf(turma["descricao"], pdf)
    assert not pd.turma_no_pdf("PE I-TURMA-A", pdf)
    assert FREQ["relatorios"][-2:] == ["PE I-TURMA-A", "PE II -TURMA-F"]


def teste_sem_relatorio_vira_erro_claro():
    s = _sessao()
    turma = pd.carregar_frequencia(s).turmas[2]
    try:
        pd.baixar_pendencias(s, turma)
    except gier_online.ErroGier as erro:
        assert erro.codigo == "sem_relatorio_pendencias" and "não gerou" in pd.texto_do_erro(erro)
    else:
        raise AssertionError("devia falhar")


def teste_sem_login_pede_para_entrar_de_novo():
    try:
        pd.carregar_frequencia(gier_online.SessaoGier())
    except gier_online.ErroGier as erro:
        assert erro.codigo == "sessao_expirada"
    else:
        raise AssertionError("devia falhar")


def teste_codigo_do_relatorio_pelo_nome():
    html = ("<select><option value='0'>Imprimir Relatórios</option><option value=\"777\">"
            "Relação de Pendências de Lançamento de Aula</option></select>")
    assert pd.id_do_relatorio(html) == "777"
    assert pd.id_do_relatorio("<html></html>") == "524"


if __name__ == "__main__":
    falhas = 0
    for nome, f in sorted(globals().items()):
        if nome.startswith("teste_") and callable(f):
            try:
                f()
                print("ok  ", nome)
            except Exception as erro:
                falhas += 1
                print("FALHOU", nome, type(erro).__name__, erro)
    sys.exit(1 if falhas else 0)
