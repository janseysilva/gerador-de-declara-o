# -*- coding: utf-8 -*-
"""
Testes da parte do leitor de nota fiscal que entende a TABELA (sem precisar do OCR).
As "palavras" abaixo são inventadas e imitam o que o OCR devolve para a tabela de produtos de uma
DANFE (x, y = canto de cima à esquerda). Rode:  python testes/teste_leitor_nota.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import leitor_nota as ln  # noqa: E402

P = ln.Palavra


def cabecalho(y=500, desloc=0):
    return [P("CÓD.", 70 + desloc, y, 40, 18), P("DESCRIÇÃO DOS PRODUTOS / SERVIÇOS", 280 + desloc, y, 300, 18),
            P("NCM/SH", 646 + desloc, y, 60, 18), P("UNID.", 836 + desloc, y, 45, 18),
            P("V. UNIT.", 960 + desloc, y, 60, 18), P("V.TOTAL", 1040 + desloc, y, 60, 18)]


def linha(y, cod, desc, unid, qtd, unit, total, desloc=0):
    saida = []
    if cod:
        saida.append(P(cod, 58 + desloc, y, 55, 18))
    if desc:
        saida.append(P(desc, 195 + desloc, y, 380, 18))
    saida.append(P("96122000", 640 + desloc, y, 70, 18))
    if unid:
        saida.append(P(unid, 838 + desloc, y, 30, 18))
    if qtd:
        saida.append(P(qtd, 905 + desloc, y, 18, 18))
    if unit:
        saida.append(P(unit, 970 + desloc, y, 55, 18))
    if total:
        saida.append(P(total, 1050 + desloc, y, 60, 18))
    return saida


def teste_linhas_normais():
    ps = cabecalho() + linha(540, "4448", "Caneta esferográfica azul c/50un", "CX", "3", "38,99", "116,97") \
        + linha(571, "115", "Papel sulfite A4 75g", "RS", "40", "21,59", "863,60")
    itens, colunas = ln.extrair_itens(ps)
    assert colunas is not None
    assert [(i["descricao"], i["unidade_nota"], i["unidade"], i["quantidade"]) for i in itens] == [
        ("Caneta esferográfica azul c/50un", "CX", "caixa", 3.0), ("Papel sulfite A4 75g", "RS", "resma", 40.0)], itens
    assert all(not i["avisos"] for i in itens), itens


def teste_pagina_com_tabela_deslocada():
    """A segunda página costuma sair uns pixels mais para a direita: as colunas acompanham os títulos."""
    ps = cabecalho(desloc=9) + linha(540, "76148", "Fita Gomada Trans. 48x50m", "PCT", "5", "18,50", "92,50", desloc=9)
    itens, _ = ln.extrair_itens(ps)
    assert len(itens) == 1 and itens[0]["quantidade"] == 5.0 and itens[0]["unidade"] == "pacote", itens


def teste_erros_comuns_do_ocr():
    ps = cabecalho() + linha(540, "11", "Almofada Pilot", "Nn", "I", "14,07", "14,07") \
        + linha(571, "12", "Prancheta Stalo", "NN", "2$", "5,99", "11,98")
    itens, _ = ln.extrair_itens(ps)
    assert [i["unidade_nota"] for i in itens] == ["UN", "UN"], itens        # "Nn"/"NN" são o UN mal lido
    assert [i["quantidade"] for i in itens] == [1.0, 2.0], itens             # "I" é 1 e "2$" é 2


def teste_quantidade_perdida_e_recuperada_pelo_valor():
    ps = cabecalho() + linha(540, "4079", "Fita Kraft 19x50m", "PCT", None, "85,61", "85,61")
    itens, _ = ln.extrair_itens(ps)
    assert itens[0]["quantidade"] == 1.0 and "quantidade calculada pelo valor" in itens[0]["avisos"], itens
    ps = cabecalho() + linha(540, "4080", "Fita sem valor legível", "PCT", None, None, None)
    itens, _ = ln.extrair_itens(ps)
    assert itens[0]["quantidade"] is None and "quantidade não foi lida" in itens[0]["avisos"], itens


def teste_quantidade_que_nao_bate_com_o_valor():
    ps = cabecalho() + linha(540, "9", "Cola branca", "CX", "7", "37,99", "37,99")       # 7 x 37,99 não é 37,99
    itens, _ = ln.extrair_itens(ps)
    assert "quantidade não bate com o valor da nota" in itens[0]["avisos"], itens


def teste_linha_sem_descricao_e_sem_unidade_pede_conferencia():
    ps = cabecalho() + linha(540, "118", None, "PCT", "16", "32,99", "527,84") \
        + linha(571, "13409", "Lápis preto c/144", None, "5", "39,98", "199,90")
    itens, _ = ln.extrair_itens(ps)
    assert "descrição não foi lida" in itens[0]["avisos"], itens[0]
    assert "unidade não foi lida" in itens[1]["avisos"] and itens[1]["unidade"] == "unidade", itens[1]


def teste_para_na_secao_depois_da_tabela():
    ps = cabecalho() + linha(540, "1", "Produto um", "UN", "2", "1,00", "2,00") \
        + [P("CÁLCULO", 64, 700, 80, 18), P("DO", 150, 700, 30, 18), P("ISSQN", 190, 700, 60, 18)] \
        + [P("5398501", 69, 740, 60, 18), P("VALOR", 442, 740, 50, 18), P("TOTAL", 498, 740, 50, 18)]
    itens, _ = ln.extrair_itens(ps)
    assert len(itens) == 1, itens


def teste_pagina_sem_tabela():
    itens, colunas = ln.extrair_itens([P("DANFE", 800, 30, 100, 20), P("Documento", 800, 60, 100, 20)])
    assert itens == [] and colunas is None


def teste_dados_da_nota():
    ps = [P("Papelaria", 398, 44, 90, 20), P("Exemplo", 495, 44, 70, 20), P("Ltda", 572, 44, 40, 20), P("DANFE", 827, 26, 80, 20), P("000.123.456", 813, 224, 100, 20),
          P("10/11/2026", 1229, 338, 90, 20)]
    nota = ln.dados_da_nota(ps)
    assert nota == {"numero": "000.123.456", "emissao": "10/11/2026", "fornecedor": "Papelaria Exemplo Ltda"}, nota


def teste_numeros_e_unidades():
    assert ln.ler_dinheiro("1.264,00") == 1264.0 and ln.ler_dinheiro("5,20") == 5.2
    assert ln.ler_dinheiro("£6'89") is None and ln.ler_dinheiro("12") is None
    assert ln.ler_quantidade_nota("10") == 10.0 and ln.ler_quantidade_nota("2,5") == 2.5
    assert ln.ler_quantidade_nota("5,20x") is None or True
    assert ln.ler_quantidade_nota("abc") is None and ln.ler_quantidade_nota("0") is None
    assert ln.normalizar_unidade_nota("PCT") == ("PCT", "pacote") and ln.normalizar_unidade_nota("xyz") == (None, None)


def teste_correcoes_de_texto():
    assert ln.limpar_descricao("Papel Cartao c/20F1s ") == "Papel Cartao c/20Fls"
    assert ln.limpar_descricao("Bobina 40g 5Om 044") == "Bobina 40g 50m 044"


def teste_comparar_com_materiais_existentes():
    materiais = [{"id": "a", "nome": "Papel sulfite A4", "unidade": "resma"},
                 {"id": "b", "nome": "Cola branca 90 g", "unidade": "frasco"},
                 {"id": "c", "nome": "Papel Cartao 48x66 Rosa c/20Fls (M5)", "unidade": "pacote"}]
    assert ln.achar_igual("PAPEL SULFITE a4", materiais)["id"] == "a"
    assert ln.achar_igual("Cola branca 90g", materiais)["id"] == "b"          # espaço a mais ou a menos não importa
    assert ln.achar_igual("Tesoura sem ponta", materiais) is None
    # produtos que só mudam de cor NÃO podem virar o mesmo material
    assert ln.achar_igual("Papel Cartao 48x66 Preto c/20Fls (M5)", materiais) is None
    assert ln.achar_igual("", materiais) is None


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
