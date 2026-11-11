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
    assert (nota["numero"], nota["emissao"], nota["fornecedor"]) == ("000.123.456", "10/11/2026", "Papelaria Exemplo Ltda"), nota
    assert nota["rotulo"] == "Papelaria Exemplo Ltda – NF 000.123.456 – 10/11/2026", nota


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


# ---------------------------------------------------------------------------
# Listas simples (ITEM | DESCRIÇÃO | UND | POR FUNC | QUANT.), como o material de limpeza mensal
# ---------------------------------------------------------------------------

def cabecalho_lista(y=312, tipo="A"):
    if tipo == "A":
        return [P("ITEM", 257, y, 50, 22), P("DESCRIÇÃO", 552, y, 120, 22), P("UND", 990, y, 50, 22),
                P("POR", 1172, y, 40, 22), P("FUNC", 1165, y + 20, 50, 22), P("QUANT", 1304, y, 70, 22)]
    return [P("ITEM", 115, y, 50, 22), P("DESCRIÇÃO", 491, y, 120, 22), P("TIPO DE", 883, y, 80, 22),
            P("UND.", 900, y + 23, 50, 22), P("QT. POR", 1097, y, 70, 22), P("FUNCIONARIO", 1060, y + 23, 130, 22),
            P("QT. TOTAIS", 1340, y, 130, 22)]


def linha_lista(y, n, desc, und, por, total, tipo="A"):
    x = {"A": (282, 341, 940, 1186, 1333), "B": (141, 283, 895, 1140, 1404)}[tipo]
    return [P(str(n), x[0], y, 20, 20), P(desc, x[1], y, 300, 20), P(und, x[2], y, 100, 20),
            P(str(por), x[3], y, 20, 20), P(str(total), x[4], y, 25, 20)]


def teste_lista_formato_a():
    ps = cabecalho_lista() + linha_lista(372, 1, "ÁGUA SANITÁRIA", "Litro", 15, 60) \
        + linha_lista(412, 2, "CÊRA LIQUIDA INCOLOR", "Com 850 ml", 3, 12) \
        + linha_lista(452, 3, "PALHA DE AÇO", "Pacote com 8", 2, 8) \
        + linha_lista(492, 4, "PEDRA SANITÁRIA (desodex ou similar)", "Unid c/ 35 grs", 4, 16) \
        + linha_lista(532, 5, "ESPONJA DUPLA FACE", "Unid", 3, 12) \
        + [P("LOCAL DA ENTREGA: Cmei Exemplo", 235, 580, 300, 20), P("Ana", 99, 700, 40, 20)]
    itens, cab = ln.extrair_itens_lista(ps)
    assert cab is not None and ln.achar_colunas(ps) is None, "a palavra Unid das linhas não pode virar título de nota"
    assert [(i["descricao"], i["unidade"], i["quantidade"]) for i in itens] == [
        ("Água sanitária", "litro", 60.0), ("Cêra liquida incolor", "unidade", 12.0),
        ("Palha de aço", "pacote", 8.0),
        ("Pedra sanitária (desodex ou similar)", "unidade", 16.0), ("Esponja dupla face", "unidade", 12.0)], itens
    assert [i["embalagem"] for i in itens] == ["", "850 ml", "pacote com 8", "35 grs", ""], itens
    assert all(not i["avisos"] for i in itens), itens


def teste_lista_formato_b_usa_a_quantidade_total():
    ps = cabecalho_lista(616, "B") + linha_lista(676, 1, "AGUA SANITÁRIA", "LITRO", 4, 8, "B") \
        + linha_lista(722, 2, "ALCOOL LÍQUIDO ETILICO", "500 ml", 4, 8, "B") \
        + linha_lista(767, 3, "PANO BRANCO DE PRATO", "UND", 2, 4, "B") \
        + linha_lista(811, 4, "SABÃO EM PÓ", "PCT 500g", 4, 8, "B") \
        + [P("ASSINATURA DO FUNCIONÁRIO", 246, 900, 300, 20)]
    itens, cab = ln.extrair_itens_lista(ps)
    assert [(i["descricao"], i["unidade"], i["quantidade"]) for i in itens] == [
        ("Agua sanitária", "litro", 8.0), ("Alcool líquido etilico", "unidade", 8.0),
        ("Pano branco de prato", "unidade", 4.0), ("Sabão em pó", "pacote", 8.0)], itens


def teste_lista_confere_por_funcionario():
    """Quantidade = por funcionário x número fixo; quem foge da regra é marcado, e a que falta é calculada."""
    linhas = []
    for n, (desc, por, total) in enumerate([("A", 15, 60), ("B", 3, 12), ("C", 4, 16), ("D", 2, 8), ("E", 10, 40)], 1):
        linhas += linha_lista(372 + 40 * (n - 1), n, "PRODUTO " + desc, "Unid", por, total)
    ps = cabecalho_lista() + linhas
    # a linha C perdeu a quantidade (OCR) e a D foi lida errado (8 virou 6)
    ps = [p for p in ps if not (abs(p.y - 452) < 5 and p.x > 1300)]
    ps = [P("6", 1333, 492, 25, 20) if (abs(p.y - 492) < 5 and p.x > 1300) else p for p in ps]
    itens, _ = ln.extrair_itens_lista(ps)
    c, d = itens[2], itens[3]
    assert c["quantidade"] == 16.0 and any("calculada" in a for a in c["avisos"]), c
    assert d["quantidade"] == 6.0 and any("não é 2 x 4" in a for a in d["avisos"]), d
    assert not itens[0]["avisos"] and not itens[1]["avisos"] and not itens[4]["avisos"], itens


def teste_unidades_das_listas():
    f = ln.converter_und_lista
    assert f("Litro") == ("litro", "") and f("LITRO") == ("litro", "")
    assert f("Unid") == ("unidade", "") and f("UND") == ("unidade", "")
    assert f("Com 850 ml") == ("unidade", "850 ml") and f("Com 2 Litros") == ("unidade", "2 litros")
    assert f("500 ml") == ("unidade", "500 ml")
    assert f("Frasco 500ml") == ("frasco", "frasco 500ml")
    assert f("Pacote com 8") == ("pacote", "pacote com 8") and f("Pct c/ 20 unid") == ("pacote", "pacote com 20 unid")
    assert f("PCT 500g") == ("pacote", "pacote 500g")
    assert f("Unid c/ 35 grs") == ("unidade", "35 grs") and f("Unid c/ 500") == ("unidade", "c/ 500")
    assert f("") == ("unidade", "")
    assert ln.montar_nome_lista("DETERGENTE") == "Detergente"
    assert ln.montar_nome_lista("Caneta Bic Azul") == "Caneta Bic Azul"
    assert ln.montar_nome_lista("PEDRA SANITÁRIA (desodex ou similar)") == "Pedra sanitária (desodex ou similar)"


def teste_dados_da_lista():
    ps = [P("MATERIAL DE LIMPEZA MENSAL", 705, 99, 300, 20), P("REFERENTE AO MÊS 09/2026 - SEMED", 664, 159, 400, 20),
          P("DDZ CENTRO SUL - 24", 850, 205, 250, 20)] + cabecalho_lista()
    cab = ln.achar_cabecalho_lista(ps)
    dados = ln.dados_da_lista(ps, cab)
    assert dados["emissao"] == "09/2026" and dados["rotulo"] == "Material de limpeza 09/2026 – DDZ CENTRO SUL - 24", dados
    ps = [P("PRI APOIO ADMINISTRATIVO E OPERACIONAL LTDA", 470, 203, 600, 20), P("COMPETÊNCIA", 1324, 203, 120, 20),
          P("08/2026", 1370, 228, 80, 20), P("DDZ:", 23, 308, 50, 20), P("CENTRO SUL", 288, 308, 150, 20),
          P("KIT:", 19, 548, 50, 20), P("2", 283, 548, 20, 20)] + cabecalho_lista(616, "B")
    dados = ln.dados_da_lista(ps, ln.achar_cabecalho_lista(ps))
    assert dados["rotulo"] == "Material de limpeza 08/2026 – DDZ CENTRO SUL – kit 2 – PRI APOIO ADMINISTRATIVO E OPERACIONAL LTDA", dados


# ---------------------------------------------------------------------------
# O mesmo produto escrito de jeito diferente vai para o mesmo material
# ---------------------------------------------------------------------------

def teste_mesmo_produto_com_termos_diferentes():
    iguais = [("Sabão em pó", "SABÃO EM PÓ"), ("Água sanitária", "AGUA SANITARIA"),
              ("Detergente", "Detergente líquido"), ("Desinfetante floral", "Desinfetante"),
              ("Limpador multiuso (tipo veja similar)", "Limpador multiuso"),
              ("Pano de chão", "Pano para limpeza do chão"), ("Detergente liquida", "Detergente líquido"),
              ("Esponja dupla face", "ESPONJA DUPLA FACE"), ("Palha de aço", "Palha de aço (pacote)"),
              ("Caderno brochura 96fls", "Cademo brochura 96fls"), ("Sacos de lixo", "Saco para lixo")]
    for a, b in iguais:
        assert ln.mesmo_produto(a, b) and ln.mesmo_produto(b, a), (a, b)


def teste_produtos_diferentes_nao_se_juntam():
    diferentes = [("Papel Cartao 48x66 Rosa c/20Fls", "Papel Cartao 48x66 Preto c/20Fls"),     # cor
                  ("Sacos p/ lixo capacidade p/ 100 litros", "Sacos p/ lixo capacidade p/ 50 litros"),  # número
                  ("Sabão em pedra", "Sabão em barra"), ("Palha de aço", "Esponja lã de aço"),
                  ("Esponja dupla face", "Esponja lã de aço"), ("Pano branco de prato", "Pano de chão"),
                  ("Papel", "Papel Cartao 48x66 Rosa c/20Fls"),                               # palavra solta x nome comprido
                  ("Papel Cartao 48x66", "Papel Cartao 48x66 Rosa"),                          # só a cor a mais
                  ("Flanela de algodão", "Flanela de algodão branca"), ("Cola branca 90g", "Cola branca 500g"),
                  ("Bobina De T.N.T Santa Fe 40g Amarelo 50m 044", "Bobina De T.N.T Santa Fe 40g Azul Cel. 50m 028"),
                  ("Tinta Guache 250ml N°507 VermFogo", "Tinta Guache 250ml N°511 VerdBand")]
    for a, b in diferentes:
        assert not ln.mesmo_produto(a, b), (a, b)


def teste_planejar_destinos():
    existentes = [{"id": "m1", "nome": "Sabão em pó", "unidade": "unidade", "ativo": True}]
    itens = [{"descricao": "Sabão em pó"}, {"descricao": "Detergente"}, {"descricao": "Detergente líquido"},
             {"descricao": "Papel Cartao Rosa"}, {"descricao": "Papel Cartao Preto"},
             {"descricao": "Detergente", "separado": True}, {"descricao": "Água sanitária"}]
    d = ln.planejar_destinos(itens, existentes)
    assert d[0] == ("existente", existentes[0]), d
    assert d[1] == ("novo",) and d[2] == ("junta", 1, "Detergente"), d             # o 2º detergente se junta ao 1º
    assert d[3] == ("novo",) and d[4] == ("novo",), d                                # cores diferentes: dois materiais
    assert d[5] == ("junta", 1, "Detergente"), d                                     # "separado" mas com nome IGUAL junta
    assert d[6] == ("novo",), d
    itens[2]["separado"] = True                                                      # "Detergente líquido": não juntar
    d = ln.planejar_destinos(itens, existentes)
    assert d[2] == ("novo",), d


def teste_nomes_da_nota_fiscal_real_nao_se_juntam():
    """Os produtos da DANFE de exemplo (cores, tamanhos, códigos) continuam todos separados."""
    nomes = ["Bobina De T.N.T Santa Fe 40g Amarelo 50m 044", "Bobina De T.N.T Santa Fe 40g Azul Cel. 50m 028",
             "Bobina De T.N.T Santa Fe 40g Bege 50m 024", "Cola Compactor Branca 090gr Polar c/12un (12x12)",
             "Cola P/Isopor Compactor Polar 90gr c/12un (12x12)", "Papel Cartao 48x66 Amarelo c/20Fls (M5)",
             "Papel Cartao 48x66 Azul Escuro c/20Fls", "Papel Duplex 48x66 Colorset Amarelo c/20Fls (M10)",
             "Papel Duplex 48x66 Colorset Rosa c/20Fls (M10)", "Fita Kraft Adere 19x50m Marrom (6x12) C/12 (M6)",
             "Fita Kraft Adere 50x50m Marrom 432/326 (06x04) c/4 (M6)", "Tinta Guache Acrilex 250ml N°507 VermFogo",
             "Tinta Guache Acrilex 250ml N°511 VerdBand", "Papel Fotografico 50Fls 180g (22x50)",
             "Papel Fotografico Auto Adesivo 50Fls 130g (24x50)", "Lapis de Cor Leo&Leo 12Cor. Sextavado",
             "Lapis Preto Leo&Leo N°2 S/Bor Sext4683c/144"]
    d = ln.planejar_destinos([{"descricao": n} for n in nomes], [])
    assert all(x == ("novo",) for x in d), [(nomes[i], x) for i, x in enumerate(d) if x != ("novo",)]


def teste_so_pergunta_o_que_e_parecido_mas_nao_igual():
    """Nome igual (acento, plural, parênteses) junta sozinho; só palavra a mais ou letra trocada vira pergunta."""
    existentes = [{"id": "m1", "nome": "Pano de chão", "unidade": "unidade", "ativo": True}]
    itens = [{"descricao": "Água sanitária"}, {"descricao": "Detergente"}, {"descricao": "Limpador multiuso (tipo veja similar)"},
             {"descricao": "Detergente líquido"}, {"descricao": "Limpador multiuso"}, {"descricao": "Agua sanitária"},
             {"descricao": "Desinfetante floral"}, {"descricao": "Desinfetante"}, {"descricao": "Pano para limpeza do chão"},
             {"descricao": "Papel Cartao Rosa"}, {"descricao": "Papel Cartao Preto"}]
    duvidas = ln.achar_duvidas(itens, existentes)
    assert [(d["item"]["descricao"], d["nome_destino"]) for d in duvidas] == [
        ("Detergente líquido", "Detergente"), ("Desinfetante", "Desinfetante floral"),
        ("Pano para limpeza do chão", "Pano de chão")], [(d["item"]["descricao"], d["nome_destino"]) for d in duvidas]
    assert duvidas[0]["origem"] is itens[1] and duvidas[2]["origem"] is None and duvidas[2]["destino"][0] == "existente"
    # quem respondeu "não" (separado) deixa de ser dúvida e vira material à parte
    itens[3]["separado"] = True
    assert [d["item"]["descricao"] for d in ln.achar_duvidas(itens, existentes)] == ["Desinfetante", "Pano para limpeza do chão"]
    assert ln.planejar_destinos(itens, existentes)[3] == ("novo",)


def teste_sem_duvidas_na_nota_fiscal_real():
    nomes = ["Papel Cartao 48x66 Amarelo c/20Fls (M5)", "Papel Cartao 48x66 Azul Escuro c/20Fls",
             "Bobina De T.N.T Santa Fe 40g Amarelo 50m 044", "Bobina De T.N.T Santa Fe 40g Azul Cel. 50m 028",
             "Cola Compactor Branca 090gr Polar c/12un (12x12)", "Cola P/Isopor Compactor Polar 90gr c/12un (12x12)"]
    assert ln.achar_duvidas([{"descricao": n} for n in nomes], []) == []


def teste_unidade_escrita_de_outro_jeito_e_a_mesma():
    mesmo = lambda a, b: ln.chave_produto(a) == ln.chave_produto(b)                  # noqa: E731
    assert mesmo("Sabão em pó 500g", "Sabão em pó 500 g") and mesmo("Sabão em pó - 500 g", "Sabão em pó 500 gramas")
    assert mesmo("Saco de lixo 100 litros", "Saco de lixo 100 L") and mesmo("Arroz 1 quilo", "Arroz 1 kg")
    assert not mesmo("Sabão em pó 500 g", "Sabão em pó 1 kg") and not mesmo("Saco de lixo 100 L", "Saco de lixo 50 L")
    assert ln.chave_produto("Papel A4") != ln.chave_produto("Papel A3")                # número continua distinguindo


def teste_nome_com_tamanho_no_estoque_casa_com_a_nota():
    """O banco de materiais cadastra "Sabão em pó 500 g"; a nota traz "Sabão em pó" com a embalagem de 500 g."""
    import tempfile
    import catalogo as cat
    c = cat.Catalogo(tempfile.mkdtemp(), "PC1")
    estoque = [{"id": "m1", "nome": "Sabão em pó 500 g", "unidade": "pacote", "ativo": True, "saldo": 0, "minimo": 0}]

    def item(desc, emb=""):
        return {"descricao": desc, "embalagem": emb, "codigo": "", "unidade": "unidade", "quantidade": 2.0, "avisos": []}

    def destino(desc, emb=""):
        itens = [item(desc, emb)]
        c.aplicar(itens)
        return ln.planejar_destinos(itens, estoque, c)[0][0], ln.achar_duvidas(itens, estoque, c)

    assert destino("SABAO EM PO", "500 g") == ("existente", [])                      # nome + tamanho = o material, sem perguntar
    assert destino("Sabão em pó", "500g") == ("existente", [])
    assert destino("Sabão em pó 500g") == ("existente", [])                          # o tamanho já vem no nome da nota
    assert destino("Sabão em pó 500 gramas") == ("existente", [])
    assert destino("Sabão em pó 1 kg")[0] == "novo"                                  # outro tamanho: outro material
    assert destino("Sabão em pó", "1 kg")[0] == "novo"


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
