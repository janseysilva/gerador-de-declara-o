"""Testes dos pareceres do Gier contra o Gier de mentira (nomes INVENTADOS).

Uso: python testes/teste_pareceres.py
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
import pareceres_gier as pg  # noqa: E402
from avaliacao_falsa import ESTADO  # noqa: E402


def _sessao():
    s = gier_online.SessaoGier()
    assert s.entrar("usuario", "x")["ok"]
    return s


def teste_turmas_e_semestres_do_ano_atual():
    pagina = pg.carregar_avaliacao(_sessao())
    assert pagina.ano == "2026"
    assert [t["descricao"] for t in pagina.turmas] == ["PE I-TURMA-A", "PE II -TURMA-B", "PE II -TURMA-C (com erro)"]
    assert [s["descricao"] for s in pagina.semestres] == ["1º Semestre", "2º Semestre"]   # sem bimestres e sem repetir


def teste_lista_de_alunos_com_situacao():
    s = _sessao()
    pagina = pg.carregar_avaliacao(s)
    lista = pg.abrir_turma(s, pagina.turmas[0], pagina.semestres[1])
    assert [(a["ordem"], a["nome"], a["situacao"]) for a in lista.alunos] == [
        (1, "ALICE EXEMPLO ROCHA", "Lançamento Completo"), (2, "BENTO EXEMPLO DIAS", "Sem lançamentos"),
        (3, "CAIO EXEMPLO NUNES", "Lançamento Parcial")]
    assert [pg.sem_lancamentos(a) for a in lista.alunos] == [False, True, False]


def teste_baixa_varios_alunos_em_sequencia():
    s = _sessao()
    pagina = pg.carregar_avaliacao(s)
    lista = pg.abrir_turma(s, pagina.turmas[1], pagina.semestres[0])
    for aluno in lista.alunos:                 # o __VIEWSTATE novo precisa ir no pedido seguinte
        pdf = pg.baixar_parecer(s, lista, aluno)
        assert pdf[:4] == b"%PDF" and pg.nome_no_pdf(aluno["nome"], pdf)
    assert not pg.nome_no_pdf("ALICE EXEMPLO ROCHA", pdf)


def teste_sem_relatorio_vira_erro_claro():
    s = _sessao()
    pagina = pg.carregar_avaliacao(s)
    lista = pg.abrir_turma(s, pagina.turmas[2], pagina.semestres[0])
    assert pg.baixar_parecer(s, lista, lista.alunos[0])[:4] == b"%PDF"
    try:
        pg.baixar_parecer(s, lista, lista.alunos[1])
    except gier_online.ErroGier as erro:
        assert erro.codigo == "sem_relatorio" and "não gerou" in pg.texto_do_erro(erro)
    else:
        raise AssertionError("devia falhar")


def teste_sem_login_pede_para_entrar_de_novo():
    try:
        pg.carregar_avaliacao(gier_online.SessaoGier())
    except gier_online.ErroGier as erro:
        assert erro.codigo == "sessao_expirada"
    else:
        raise AssertionError("devia falhar")


def teste_conexao_que_cai_e_tentada_de_novo():
    chamadas, esperas = [], []

    def cai_duas_vezes(sessao, x):
        chamadas.append(x)
        if len(chamadas) < 3:
            raise gier_online.ErroGier("conexao", "IncompleteRead")
        return "pdf"
    assert pg.com_tentativas(None, cai_duas_vezes, 7, esperar=esperas.append) == "pdf"
    assert chamadas == [7, 7, 7] and esperas == [3, 8]
    chamadas.clear()
    try:
        pg.com_tentativas(None, lambda s, x: (chamadas.append(x), cai_duas_vezes.__call__)[0] or
                          (_ for _ in ()).throw(gier_online.ErroGier("conexao")), 1, esperar=lambda s: None)
    except gier_online.ErroGier as erro:
        assert erro.codigo == "conexao" and len(chamadas) == 3     # desiste depois de 3
    else:
        raise AssertionError("devia falhar")
    chamadas.clear()
    try:                                                          # outros erros não repetem
        pg.com_tentativas(None, lambda s: (chamadas.append(1), (_ for _ in ()).throw(
            gier_online.ErroGier("outro_aluno")))[1], esperar=lambda s: None)
    except gier_online.ErroGier as erro:
        assert erro.codigo == "outro_aluno" and chamadas == [1]


def teste_leitura_da_resposta_assincrona():
    blocos = pg.ler_delta("3|hiddenField|__VIEWSTATE|abc|5|scriptStartupBlock|x|a|b|c|")
    assert blocos == [("hiddenField", "__VIEWSTATE", "abc"), ("scriptStartupBlock", "x", "a|b|c")]


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
    print("pedidos ao Gier de mentira:", len(ESTADO["pedidos"]))
    sys.exit(1 if falhas else 0)
