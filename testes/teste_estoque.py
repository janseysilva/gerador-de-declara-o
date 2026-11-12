# -*- coding: utf-8 -*-
"""
Testes das regras do estoque (sem tela). Nomes inventados.

    python testes/teste_estoque.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import estoque as e  # noqa: E402


def erro_de(funcao, *args, **kw):
    try:
        funcao(*args, **kw)
    except e.ErroEstoque as erro:
        return str(erro)
    raise AssertionError("era para dar erro")


def novo(pc="pc1", pasta=None):
    return e.Livro(pasta or tempfile.mkdtemp(), pc)


def teste_numeros():
    assert e.ler_quantidade("3") == 3
    assert e.ler_quantidade("2,5") == 2.5
    assert e.ler_quantidade("2.5") == 2.5
    assert e.ler_quantidade("1.000") == 1000
    assert e.ler_quantidade("1.000,5") == 1000.5
    for ruim in ("", "abc", "0", "-2", "2000000"):
        erro_de(e.ler_quantidade, ruim)
    assert e.ler_minimo("") == 0 and e.ler_minimo("4") == 4
    erro_de(e.ler_minimo, "-1")
    assert e.texto_quantidade(3.0) == "3" and e.texto_quantidade(2.5) == "2,5" and e.texto_quantidade(0.125) == "0,125"


def teste_cadastro_e_busca():
    l = novo()
    a = l.cadastrar_material("  Papel   sulfite A4 ", "resma", 5)
    l.cadastrar_material("Lápis de cor", "caixa")
    l.cadastrar_material("Papel crepom", "folha")
    assert l.material(a)["nome"] == "Papel sulfite A4"            # espaços arrumados
    assert "já existe" in erro_de(l.cadastrar_material, "papel SULFITE a4").lower()
    assert "nome" in erro_de(l.cadastrar_material, "   ").lower()
    assert [m["nome"] for m in l.buscar_materiais("papel")] == ["Papel crepom", "Papel sulfite A4"]
    assert [m["nome"] for m in l.buscar_materiais("lapis")] == ["Lápis de cor"]        # sem acento
    assert [m["nome"] for m in l.buscar_materiais("sulf a4")] == ["Papel sulfite A4"]  # pedaços das palavras
    assert [m["nome"] for m in l.buscar_materiais("a4 pap")] == ["Papel sulfite A4"]   # ordem não importa
    assert [m["nome"] for m in l.buscar_materiais("sulfato")] == []
    assert l.buscar_materiais("   ") == []


def teste_entrada_saida_e_saldo():
    l = novo()
    papel = l.cadastrar_material("Papel sulfite A4", "resma", 5)
    cola = l.cadastrar_material("Cola branca", "frasco")
    prof = l.cadastrar_destinatario("Professora Exemplo", "Turma PE I-A")
    assert l.saldo(papel) == 0 and l.material(papel)["situacao"] == "zerado"

    l.registrar_entrada([{"material": papel, "quantidade": 10}, {"material": cola, "quantidade": 20}], "Fornecedor X")
    assert l.saldo(papel) == 10 and l.saldo(cola) == 20
    assert l.material(papel)["situacao"] == "ok"

    l.registrar_saida(prof, [{"material": papel, "quantidade": 6}, {"material": cola, "quantidade": 2.5}])
    assert l.saldo(papel) == 4 and l.saldo(cola) == 17.5
    assert l.material(papel)["situacao"] == "baixo"                # 4 <= mínimo 5

    msg = erro_de(l.registrar_saida, prof, [{"material": papel, "quantidade": 5}])
    assert "saldo" in msg.lower() and "Papel sulfite A4" in msg
    assert l.saldo(papel) == 4                                      # nada foi gravado
    # o mesmo material duas vezes na lista é somado antes de conferir o saldo
    erro_de(l.registrar_saida, prof, [{"material": papel, "quantidade": 3}, {"material": papel, "quantidade": 3}])
    erro_de(l.registrar_saida, "nao-existe", [{"material": papel, "quantidade": 1}])
    erro_de(l.registrar_entrada, [])
    erro_de(l.registrar_entrada, [{"material": "nao-existe", "quantidade": 1}])


def teste_historico_e_repetir():
    l = novo()
    papel = l.cadastrar_material("Papel sulfite A4", "resma")
    lapis = l.cadastrar_material("Lápis de cor", "caixa")
    prof = l.cadastrar_destinatario("Professora Exemplo", "Turma PE I-A")
    cozinha = l.cadastrar_destinatario("Cozinha")
    t0 = datetime(2026, 11, 9, 8, 0, 0)
    l.registrar_entrada([{"material": papel, "quantidade": 20}, {"material": lapis, "quantidade": 20}], quando=t0)
    l.registrar_saida(prof, [{"material": papel, "quantidade": 2}, {"material": lapis, "quantidade": 3}],
                      quando=t0 + timedelta(hours=1))
    l.registrar_saida(cozinha, [{"material": papel, "quantidade": 1}], quando=t0 + timedelta(hours=2))

    todos = l.movimentos()
    assert [m["tipo"] for m in todos] == ["saida", "saida", "entrada"]        # mais nova primeiro
    saidas = l.movimentos("saida")
    assert len(saidas) == 2 and saidas[1]["destinatario"]["nome"] == "Professora Exemplo"
    assert saidas[1]["quando"] == t0 + timedelta(hours=1)                    # dia e hora ficam salvos
    assert [i["quantidade"] for i in saidas[1]["itens"]] == [2, 3]
    assert len(l.movimentos(texto="professora")) == 1
    assert len(l.movimentos(texto="lapis")) == 2                              # entrada e a saída da professora
    # "repetir": os mesmos materiais viram uma saída nova, com outra data
    antiga = saidas[1]
    itens = [{"material": i["material"], "quantidade": i["quantidade"]} for i in antiga["itens"]]
    l.registrar_saida(prof, itens)
    assert l.saldo(papel) == 20 - 2 - 1 - 2 and l.saldo(lapis) == 20 - 3 - 3


def teste_estorno():
    l = novo()
    papel = l.cadastrar_material("Papel sulfite A4", "resma")
    prof = l.cadastrar_destinatario("Professora Exemplo")
    ent = l.registrar_entrada([{"material": papel, "quantidade": 10}])
    sai = l.registrar_saida(prof, [{"material": papel, "quantidade": 4}])
    assert l.saldo(papel) == 6
    # estornar a entrada agora deixaria o saldo negativo
    assert "já saiu" in erro_de(l.estornar, ent)
    l.estornar(sai, "lançado por engano")                            # a saída volta ao estoque
    assert l.saldo(papel) == 10
    assert l.movimento(sai)["estornado"] and l.movimento(sai)["motivo_estorno"] == "lançado por engano"
    assert "já foi estornado" in erro_de(l.estornar, sai)
    l.estornar(ent)                                                  # agora a entrada pode ser desfeita
    assert l.saldo(papel) == 0
    assert len(l.movimentos(incluir_estornados=False)) == 0 and len(l.movimentos()) == 2
    erro_de(l.estornar, "nao-existe")


def teste_dois_computadores():
    pasta = tempfile.mkdtemp()
    a, b = e.Livro(pasta, "pc-direcao"), e.Livro(pasta, "pc-secretaria")
    papel = a.cadastrar_material("Papel sulfite A4", "resma")
    prof = a.cadastrar_destinatario("Professora Exemplo")
    a.registrar_entrada([{"material": papel, "quantidade": 10}])
    b.recarregar()
    assert b.saldo(papel) == 10 and b.destinatario(prof)               # o outro PC enxerga
    b.registrar_saida(prof, [{"material": papel, "quantidade": 7}])
    assert a.saldo(papel) == 10                                       # ainda não leu
    a.recarregar()
    assert a.saldo(papel) == 3
    # a saída confere o saldo com o que o outro PC já registrou, mesmo sem clicar em atualizar
    assert "saldo" in erro_de(a.registrar_saida, prof, [{"material": papel, "quantidade": 5}]).lower()
    assert sorted(n for n in os.listdir(pasta)) == ["eventos-pc-direcao.jsonl", "eventos-pc-secretaria.jsonl"]
    # cópia repetida de um arquivo (conflito do OneDrive) não soma duas vezes
    with open(os.path.join(pasta, "eventos-pc-direcao.jsonl"), "rb") as f:
        dados = f.read()
    with open(os.path.join(pasta, "eventos-pc-direcao (cópia em conflito).jsonl"), "wb") as f:
        f.write(dados)
    a.recarregar()
    assert a.saldo(papel) == 3


def teste_arquivo_estragado():
    pasta = tempfile.mkdtemp()
    l = e.Livro(pasta, "pc1")
    papel = l.cadastrar_material("Papel sulfite A4")
    l.registrar_entrada([{"material": papel, "quantidade": 5}])
    with open(os.path.join(pasta, "eventos-pc1.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"id": "x", "quando": \n')                          # linha cortada (sincronização pela metade)
        f.write("lixo\n")
    l.recarregar()
    assert l.saldo(papel) == 5 and l.linhas_ruins == 2


def teste_ocultar_e_editar():
    l = novo()
    a = l.cadastrar_material("Detergente", "frasco", 3)
    b = l.cadastrar_material("Água sanitária", "litro")
    l.editar_material(a, nome="Detergente neutro", minimo=4)
    assert l.material(a)["nome"] == "Detergente neutro" and l.material(a)["minimo"] == 4
    erro_de(l.editar_material, a, nome="água SANITARIA")
    l.editar_material(b, ativo=False)
    assert [m["nome"] for m in l.materiais()] == ["Detergente neutro"]
    assert len(l.materiais(incluir_ocultos=True)) == 2
    assert l.buscar_materiais("agua") == []
    assert "oculto" in erro_de(l.cadastrar_material, "Água sanitária")
    erro_de(l.registrar_entrada, [{"material": b, "quantidade": 1}])
    l.editar_material(b, ativo=True)
    assert len(l.buscar_materiais("agua")) == 1


def teste_ordem_no_mesmo_segundo():
    """Criar e editar várias vezes em seguida: vale sempre a última edição (antes dava empate)."""
    pasta = tempfile.mkdtemp()
    l = e.Livro(pasta, "pc1")
    a = l.cadastrar_material("Papel A4", "resma", 1)
    for n in range(1, 31):
        l.editar_material(a, nome="Papel A4 v{}".format(n), minimo=n)
    assert l.material(a)["nome"] == "Papel A4 v30" and l.material(a)["minimo"] == 30
    outro = e.Livro(pasta, "pc1")                                    # lido do zero, pelo disco
    assert outro.material(a)["nome"] == "Papel A4 v30"
    outro.editar_material(a, nome="Depois de reabrir")               # o carimbo continua crescendo
    assert e.Livro(pasta, "pc1").material(a)["nome"] == "Depois de reabrir"


def teste_destinatarios():
    l = novo()
    l.cadastrar_destinatario("Professora Exemplo", "Turma PE I-A")
    l.cadastrar_destinatario("Professora Exemplo", "Turma PE II-B")       # mesmo nome, outro setor: pode
    erro_de(l.cadastrar_destinatario, "professora  exemplo", "turma pe i-a")
    erro_de(l.cadastrar_destinatario, "")
    assert len(l.buscar_destinatarios("exemplo")) == 2


def teste_resumo():
    l = novo()
    a = l.cadastrar_material("Papel sulfite A4", "resma", 5)
    b = l.cadastrar_material("Cola branca", "frasco", 2)
    l.cadastrar_material("Tinta guache", "frasco")
    l.registrar_entrada([{"material": a, "quantidade": 4}, {"material": b, "quantidade": 10}])
    assert l.resumo() == {"materiais": 3, "baixo": 1, "zerado": 1}


def teste_filtro_do_historico():
    from datetime import date
    hoje = date(2026, 11, 12)
    # datas digitadas
    assert e.ler_data("12/11/2026", hoje) == date(2026, 11, 12) and e.ler_data("5/3/26", hoje) == date(2026, 3, 5)
    assert e.ler_data("05-11", hoje) == date(2026, 11, 5)                          # sem ano: o de hoje
    assert e.ler_data("hoje", hoje) == hoje and e.ler_data(" Ontem ", hoje) == date(2026, 11, 11)
    assert e.ler_data("", hoje) is None and e.ler_data("   ", hoje) is None
    for ruim in ("31/02/2026", "13/13/2026", "abc", "12/1/", "2026/11/12", "12/11/20266"):
        erro_de(e.ler_data, ruim, hoje)
    # os dois campos de dia: só o 1º = aquele dia; os dois = de/até; só o 2º = até aquele dia
    d = lambda a, b: e.intervalo_de_dias(a, b, hoje)                                 # noqa: E731
    assert d("12/11", "") == (date(2026, 11, 12), date(2026, 11, 12))
    assert d("10/11", "12/11") == (date(2026, 11, 10), date(2026, 11, 12))
    assert d("", "12/11") == (None, date(2026, 11, 12)) and d("", "") == (None, None)
    assert "antes" in erro_de(d, "12/11", "10/11")

    # um livro com saídas em dias e pessoas diferentes
    l = novo()
    papel = l.cadastrar_material("Papel sulfite A4", "resma")
    ana = l.cadastrar_destinatario("Professora Ana Exemplo", "Turma A")
    beto = l.cadastrar_destinatario("Professor Beto Exemplo", "Turma B")
    t = lambda dia, h, m=0: datetime(2026, 11, dia, h, m)                            # noqa: E731
    l.registrar_entrada([{"material": papel, "quantidade": 100}], quando=t(9, 7, 50))
    l.registrar_saida(ana, [{"material": papel, "quantidade": 1}], quando=t(9, 8, 0))
    l.registrar_saida(beto, [{"material": papel, "quantidade": 1}], quando=t(9, 14, 30))
    l.registrar_saida(ana, [{"material": papel, "quantidade": 1}], quando=t(10, 8, 45))
    l.registrar_saida(beto, [{"material": papel, "quantidade": 1}], quando=t(12, 9, 0))
    quando = lambda **kw: sorted(m["quando"].strftime("%d %H:%M") for m in l.movimentos(**kw))   # noqa: E731
    assert len(l.movimentos()) == 5
    # por pessoa: só as saídas dela (a entrada não tem pessoa)
    assert quando(destinatario_id=ana) == ["09 08:00", "10 08:45"]
    assert quando(destinatario_id=beto) == ["09 14:30", "12 09:00"]
    # por dia
    assert quando(dia_de=date(2026, 11, 9), dia_ate=date(2026, 11, 9)) == ["09 07:50", "09 08:00", "09 14:30"]
    assert quando(dia_de=date(2026, 11, 10), dia_ate=date(2026, 11, 12)) == ["10 08:45", "12 09:00"]
    assert quando(dia_de=date(2026, 11, 11)) == ["12 09:00"]                           # de 11 em diante
    assert quando(dia_ate=date(2026, 11, 9)) == ["09 07:50", "09 08:00", "09 14:30"]  # até 9
    # pessoa + dia juntos, e junto com o tipo e a pesquisa de texto
    assert quando(destinatario_id=ana, dia_de=date(2026, 11, 10), dia_ate=date(2026, 11, 10)) == ["10 08:45"]
    assert quando(destinatario_id=ana, dia_de=date(2026, 11, 11)) == []
    assert quando(tipo="entrada", dia_de=date(2026, 11, 9), dia_ate=date(2026, 11, 9)) == ["09 07:50"]
    assert quando(texto="beto", dia_de=date(2026, 11, 10)) == ["12 09:00"]
    assert quando(texto="beto", dia_ate=date(2026, 11, 9)) == ["09 14:30"]
    # estornada continua na lista (marcada) e pode ser escondida como antes
    saida = l.movimentos(destinatario_id=beto)[0]
    l.estornar(saida["id"], "teste")
    assert len(l.movimentos(destinatario_id=beto)) == 2 and len(l.movimentos(destinatario_id=beto, incluir_estornados=False)) == 1


def teste_relatorio_por_quantidade():
    # a quantidade digitada: zero vale (só os zerados); vazio, letra e negativo não
    assert e.ler_limite_relatorio("0") == 0 and e.ler_limite_relatorio("10") == 10 and e.ler_limite_relatorio("2,5") == 2.5
    for ruim in ("", "   ", "abc", "-1", "2000000"):
        erro_de(e.ler_limite_relatorio, ruim)
    l = novo()
    a = l.cadastrar_material("Papel sulfite A4", "resma")
    b = l.cadastrar_material("Cola branca", "frasco")
    c = l.cadastrar_material("Tinta guache", "frasco")
    d = l.cadastrar_material("Lápis de cor", "caixa")
    l.registrar_entrada([{"material": a, "quantidade": 10}, {"material": b, "quantidade": 3},
                         {"material": c, "quantidade": 11}])
    todos = l.materiais()
    nomes = lambda lista: [m["nome"] for m in lista]                         # noqa: E731
    assert nomes(e.filtrar_por_quantidade(todos)) == nomes(todos)             # "Todos": a lista inteira, mesma ordem
    assert nomes(e.filtrar_por_quantidade(todos, 10)) == ["Cola branca", "Lápis de cor", "Papel sulfite A4"]   # 10 entra (igual)
    assert nomes(e.filtrar_por_quantidade(todos, 3)) == ["Cola branca", "Lápis de cor"]
    assert nomes(e.filtrar_por_quantidade(todos, 0)) == ["Lápis de cor"]      # zero = só os zerados
    assert e.filtrar_por_quantidade(todos, 2.9) == [m for m in todos if m["nome"] == "Lápis de cor"]
    assert nomes(e.filtrar_por_quantidade(todos, 11)) == nomes(todos)
    # "Só os que tenho em estoque": tira os zerados (aqui o Lápis de cor, que nunca teve entrada)
    assert nomes(e.filtrar_em_estoque(todos)) == ["Cola branca", "Papel sulfite A4", "Tinta guache"]
    assert nomes(e.selecionar_para_relatorio(todos, "todos")) == nomes(todos)
    assert nomes(e.selecionar_para_relatorio(todos, "tenho")) == ["Cola branca", "Papel sulfite A4", "Tinta guache"]
    assert nomes(e.selecionar_para_relatorio(todos, "ate", 3)) == ["Cola branca", "Lápis de cor"]
    # um material que teve entrada e depois ficou zerado por saídas: "Todos" mostra com 0, "tenho" não mostra
    prof = l.cadastrar_destinatario("Professora Exemplo", "Turma")
    l.registrar_saida(prof, [{"material": b, "quantidade": 3}])
    depois = l.materiais()
    assert [m["saldo"] for m in depois if m["id"] == b] == [0]
    assert "Cola branca" in nomes(e.selecionar_para_relatorio(depois, "todos"))
    assert "Cola branca" not in nomes(e.selecionar_para_relatorio(depois, "tenho"))
    assert "Cola branca" in nomes(e.selecionar_para_relatorio(depois, "ate", 0))
    # material oculto não aparece no relatório (a lista base já o tira)
    l.editar_material(d, ativo=False)
    assert nomes(e.filtrar_por_quantidade(l.materiais(), 0)) == ["Cola branca"]


if __name__ == "__main__":
    testes =[(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
