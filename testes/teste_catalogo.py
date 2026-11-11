# -*- coding: utf-8 -*-
"""
Testes do catálogo de materiais (catalogo.py) e das perguntas por tamanho de embalagem.
Só dados inventados; usam uma pasta temporária. Rode:  python testes/teste_catalogo.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import catalogo as cat  # noqa: E402
import leitor_nota as ln  # noqa: E402


def novo(pc="PC1", pasta=None):
    return cat.Catalogo(pasta or tempfile.mkdtemp(), pc)


def item(descricao, embalagem="", codigo="", unidade="unidade", quantidade=1.0):
    return {"descricao": descricao, "embalagem": embalagem, "codigo": codigo, "unidade": unidade,
            "quantidade": quantidade, "avisos": []}


def teste_catalogo_de_fabrica():
    c = novo()
    nomes = {e["nome"] for e in c.entradas.values()}
    assert len(c.entradas) >= 29 and {"Sabão em pó", "Água sanitária", "Detergente líquido", "Pano de chão"} <= nomes, nomes
    assert all(e["tipo"] == "limpeza" for e in c.entradas.values())


def teste_reconhece_pelo_nome_e_pelos_apelidos():
    c = novo()
    for lido, esperado in [("SABÃO EM PÓ", "Sabão em pó"), ("Agua sanitária", "Água sanitária"),
                           ("Detergente", "Detergente líquido"), ("DETERGENTE LIQUIDO", "Detergente líquido"),
                           ("Pano para limpeza do chão", "Pano de chão"), ("Cêra liquida incolor", "Cera líquida incolor"),
                           ("LIMPADOR MULTIUSO (TIPO VEJA SIMILAR)", "Limpador multiuso"),
                           ("Pasta saponaceo (sapolio)", "Pasta saponácea (sapólio)")]:
        i = c.aplicar([item(lido)])[0]
        assert i["descricao"] == esperado and i["reconhecido"] == "nome" and i["catalogo"], (lido, i)
        assert i["descricao_lida"] == lido
    assert c.aplicar([item("Papel Cartão Rosa")])[0]["descricao"] == "Papel Cartão Rosa"      # desconhecido: fica como está


def teste_mesmo_nome_com_tamanho_diferente_nao_junta_sozinho():
    c = novo()
    ok = c.aplicar([item("Sabão em pó", "pacote 500g")])[0]
    assert ok["reconhecido"] == "nome", ok                                          # 500 g = 500 g
    sem_tamanho = c.aplicar([item("Sabão em pó", "Unid c/ 500")])[0]                  # "c/ 500" não diz a unidade
    assert sem_tamanho["reconhecido"] == "nome", sem_tamanho
    outro = c.aplicar([item("Sabão em pó", "250 g")])[0]
    assert outro["reconhecido"] is None if "reconhecido" in outro else True
    assert "catalogo" not in outro and outro["tamanho_diferente_de"]["nome"] == "Sabão em pó", outro


def teste_pergunta_por_tamanho_e_respostas():
    c = novo()
    i = c.aplicar([item("Sabão em pó", "250 g", quantidade=12)])[0]
    d = ln.achar_duvidas([i], [], c)
    assert len(d) == 1 and d[0]["motivo"] == "tamanho" and d[0]["tamanho_item"] == "250 g" and d[0]["tamanho_outro"] == "500 g", d
    # "Não juntar": vira outro material, com o tamanho no nome
    import tela_estoque as te  # noqa: F401  (usa a mesma regra da tela)
    te_resposta = _resposta_da_tela(d[0], juntar=False)
    assert te_resposta["descricao"] == "Sabão em pó - 250 g" and te_resposta["variante"] and not te_resposta.get("catalogo")
    assert ln.achar_duvidas([te_resposta], [], c) == []
    # "Juntar": passa a ser o produto do catálogo
    j = c.aplicar([item("Sabão em pó", "250 g", quantidade=12)])[0]
    d = ln.achar_duvidas([j], [], c)
    r = _resposta_da_tela(d[0], juntar=True)
    assert r["descricao"] == "Sabão em pó" and r["catalogo"] == "base-sabao-em-po" and r["tamanho_resolvido"], r


def _resposta_da_tela(duvida, juntar):
    """A mesma regra que a janela de conferência usa (tela_estoque.DialogoNotaLida._aplicar_resposta)."""
    import tela_estoque as te
    te.DialogoNotaLida._aplicar_resposta(duvida, juntar)
    return duvida["item"]


def teste_tamanho_dentro_de_uma_lista():
    """Duas linhas da mesma lista com o mesmo nome e tamanhos diferentes: pergunta."""
    itens = [item("Detergente", "500 ml"), item("Detergente", "5 litros"), item("Detergente", "500 ml")]
    d = ln.achar_duvidas(itens, [])
    assert len(d) == 1 and d[0]["motivo"] == "tamanho" and d[0]["indice"] == 1 and d[0]["origem"] is itens[0], d
    assert d[0]["tamanho_item"] == "5 L" and d[0]["tamanho_outro"] == "500 ml"
    assert ln.planejar_destinos(itens, []) == [("novo",), ("novo",), ("junta", 0, "Detergente")]


def teste_codigo_do_fornecedor():
    pasta = tempfile.mkdtemp()
    c = novo("PC1", pasta)
    # 1ª nota: nada é conhecido; a pessoa confirma e o catálogo aprende nome, apelido e código
    i1 = c.aplicar([item("Borracha Leo&Leo Branca c/24 (48x24) REF 4584", codigo="7104", unidade="caixa")], "11222333000181")[0]
    assert "catalogo" not in i1
    e = c.aprender(i1, "Borracha Leo&Leo Branca c/24", "caixa", "pedagogico", "11222333000181")
    assert e["codigos"] == {"11222333000181": ["7104"]} and e["tipo"] == "pedagogico"
    # 2ª nota, outro computador lendo a mesma pasta: o fornecedor escreveu o nome de outro jeito, mas o código é o mesmo
    c2 = novo("PC2", pasta)
    i2 = c2.aplicar([item("BORRACHA LEO LEO BCA 48X24 M48", codigo="7104")], "11222333000181")[0]
    assert i2["reconhecido"] == "código" and i2["descricao"] == "Borracha Leo&Leo Branca c/24", i2
    # o mesmo código de OUTRO fornecedor não confunde
    i3 = c2.aplicar([item("Caderno qualquer", codigo="7104")], "99999999000100")[0]
    assert "catalogo" not in i3


def teste_aprende_apelidos_e_respostas():
    pasta = tempfile.mkdtemp()
    c = novo("PC1", pasta)
    # juntou "Desinfetante" ao "Desinfetante floral": vira apelido e a pergunta não volta
    i = c.aplicar([item("Desinfetante", "Litro")])[0]
    antes = len(c.entradas)
    e = c.aprender(i, "Desinfetante floral", "unidade", "limpeza")
    assert len(c.entradas) == antes and e["id"] == "base-desinfetante-floral" and e["apelidos"] == ["Desinfetante"],         "tem de acrescentar o apelido ao produto que já existe, sem criar outro igual"
    c2 = novo("PC2", pasta)
    j = c2.aplicar([item("DESINFETANTE")])[0]
    assert j["reconhecido"] == "nome" and j["descricao"] == "Desinfetante floral", j
    # "Não juntar": os dois nomes deixam de ser perguntados
    c2.marcar_diferentes("Detergente neutro", "Detergente")
    c2.marcar_diferentes("Detergente neutro", "Detergente")                          # repetir não duplica
    c3 = novo("PC1", pasta)
    assert c3.sao_diferentes("detergente", "DETERGENTE NEUTRO")
    mats = [{"id": "m2", "nome": "Detergente", "unidade": "unidade", "ativo": True}]
    pergunta = ln.achar_duvidas([item("Detergente neutro")], mats)
    assert len(pergunta) == 1 and pergunta[0]["motivo"] == "nome"                    # sem catálogo: pergunta
    assert ln.achar_duvidas([item("Detergente neutro")], mats, c3) == []              # com a resposta guardada: não
    assert ln.planejar_destinos([item("Detergente neutro")], mats, c3) == [("novo",)]


def teste_variante_nao_vira_apelido():
    c = novo()
    i = item("Sabão em pó", "250 g")
    i.update(descricao="Sabão em pó - 250 g", descricao_lida="Sabão em pó", variante=True)
    e = c.aprender(i, "Sabão em pó - 250 g", "unidade", "limpeza")
    assert e["nome"] == "Sabão em pó - 250 g" and e["apelidos"] == [] and e["embalagem"] == "250 g", e
    # agora existem "Sabão em pó" (500 g) e "Sabão em pó - 250 g" (250 g)
    assert c.aplicar([item("Sabão em pó", "250 g")])[0]["descricao"] == "Sabão em pó - 250 g"
    assert c.aplicar([item("Sabão em pó - 250 g")])[0]["descricao"] == "Sabão em pó - 250 g"
    assert c.aplicar([item("Sabão em pó", "pacote 500g")])[0]["descricao"] == "Sabão em pó"


def teste_dois_computadores_na_mesma_pasta():
    pasta = tempfile.mkdtemp()
    a, b = novo("PC1", pasta), novo("PC2", pasta)
    ia = a.aplicar([item("Fita crepe 18mm", codigo="55")], "F1")[0]
    a.aprender(ia, "Fita crepe 18mm", "unidade", "pedagogico", "F1")
    ib = b.aplicar([item("Fita crepe 18mm", codigo="55")], "F1")[0]      # b ainda não recarregou
    assert "catalogo" not in ib
    b.recarregar()
    assert b.aplicar([item("X", codigo="55")], "F1")[0]["descricao"] == "Fita crepe 18mm"
    arquivos = sorted(f for f in os.listdir(pasta) if f.endswith(".jsonl"))
    assert arquivos == ["eventos-PC1.jsonl"], arquivos                      # cada computador grava no seu arquivo


def teste_arquivo_estragado_nao_derruba():
    pasta = tempfile.mkdtemp()
    with open(os.path.join(pasta, "eventos-PC9.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"gravado": "2026-11-10T10:00:00.000001", "tipo": "entrada", "dados": {"id": "u-1", "nome": "Giz de cera"}}\n')
        f.write("{linha cortada pela queda de luz\n")
    c = novo("PC1", pasta)
    assert c.aplicar([item("GIZ DE CERA")])[0]["descricao"] == "Giz de cera"


def teste_catalogo_federal_tem_o_basico_de_escola():
    f = cat.CatalogoFederal()
    assert len(f) >= 400, len(f)
    nomes = {e["nome"] for e in f.entradas}
    for esperado in ("Tesoura", "Cola", "Giz de cera", "Massa de modelar", "Papel crepom", "Folha de EVA", "Tinta guache",
                     "Detergente", "Sabão em pó", "Água sanitária", "Papel higiênico", "Vassoura", "Rodo", "Papel toalha"):
        assert esperado in nomes, esperado
    assert all(e["tipo"] in ("limpeza", "pedagogico", "ambos") for e in f.entradas)
    assert len({e["nome"].lower() for e in f.entradas}) == len(f), "nomes repetidos no catálogo federal"


def teste_federal_acha_pelo_jeito_de_falar():
    f = cat.CatalogoFederal()
    nomes = lambda q, t: [x["nome"] for x in f.buscar(q, t)]                # noqa: E731
    assert "Papel A4 branco 75 g" in nomes("sulfite", "pedagogico")
    assert "Saco de lixo 50 L" in nomes("saco de lixo", "limpeza")
    assert nomes("massa de modelar", "pedagogico")[0] == "Massa de modelar"
    assert "Desinfetante" in nomes("desinfetante", "limpeza")
    assert "Folha de EVA" in nomes("eva", "pedagogico")
    assert nomes("giz de cera", "pedagogico")[0] == "Giz de cera"
    assert nomes("LAPIS DE COR", "pedagogico")[0] == "Lápis de cor"          # maiúscula e acento não atrapalham
    assert nomes("papel toalha", "limpeza")[0] == "Papel toalha"             # o que começa igual vem primeiro


def teste_federal_respeita_o_tipo_de_estoque():
    f = cat.CatalogoFederal()
    assert f.buscar("sulfite", "limpeza") == []                              # papel não aparece no estoque de limpeza
    assert f.buscar("vassoura", "pedagogico") == []
    assert any(x["nome"] == "Copo descartável" for x in f.buscar("copo", "pedagogico"))   # "ambos" aparece nos dois
    assert any(x["nome"] == "Copo descartável" for x in f.buscar("copo", "limpeza"))
    assert f.buscar("", "limpeza") == [] and f.buscar("   ", None) == []


def teste_federal_nao_repete_o_que_ja_esta_cadastrado():
    f = cat.CatalogoFederal()
    todos = f.buscar("detergente", "limpeza")
    assert any(x["nome"] == "Detergente" for x in todos)
    sem = f.buscar("detergente", "limpeza", ja_cadastrados={"detergente"})
    assert all(x["nome"] != "Detergente" for x in sem) and len(sem) == len(todos) - 1
    s = todos[0]
    assert s["do_catalogo"] is True and s["id"] is None and s["unidade"] and s["saldo"] == 0.0


def teste_federal_tem_cada_cor_como_opcao():
    f = cat.CatalogoFederal()
    nomes = lambda q, t: [x["nome"] for x in f.buscar(q, t)]                # noqa: E731
    cartolina = nomes("cartolina", "pedagogico")
    assert cartolina[0] == "Cartolina", cartolina                           # o produto vem antes das cores
    assert cartolina[1:4] == ["Cartolina branca", "Cartolina azul", "Cartolina amarela"], cartolina   # as mais comuns primeiro
    tnt = nomes("tnt", "pedagogico")
    assert tnt[:4] == ["TNT", "TNT branco", "TNT azul", "TNT amarelo"] and "TNT preto" in tnt, tnt   # TNT é masculino
    assert "Folha de EVA branca" in nomes("eva", "pedagogico") and "Folha de EVA dourada" in nomes("eva", "pedagogico")
    assert nomes("cartolina azul", "pedagogico")[0] == "Cartolina azul"
    assert "Luva descartável M" in nomes("luva", "limpeza") and "Desinfetante lavanda" in nomes("desinfetante", "limpeza")
    assert "Copo descartável 200 ml" in nomes("copo", "limpeza")
    cor = f.buscar("cartolina azul", "pedagogico")[0]
    assert cor["unidade"] == "folha" and cor["do_catalogo"] is True


def teste_federal_tem_os_modelos_do_material_escolar():
    f = cat.CatalogoFederal()
    por = lambda q: {x["nome"]: x for x in f.buscar(q, "pedagogico", limite=100)}          # noqa: E731
    lapis = f.buscar("lapis de cor", "pedagogico")
    assert [x["nome"] for x in lapis][:3] == ["Lápis de cor", "Lápis de cor 6 a 12 cores", "Lápis de cor 24 cores"], lapis
    assert all(x["unidade"] == "caixa" for x in lapis)                                  # lápis de cor se compra em caixa
    nomes = por("lapis de cor")
    assert {"Lápis de cor 36 cores", "Lápis de cor 48 cores", "Lápis de cor 72 cores", "Lápis de cor jumbo 6 a 12 cores"} <= set(nomes)
    assert "Giz de cera 6 a 12 cores" in por("giz de cera") and "Caneta hidrográfica 24 cores" in por("hidrografica")
    assert "Tinta guache kit 12 cores" in por("tinta guache") and por("tinta guache")["Tinta guache kit 6 cores"]["unidade"] == "caixa"
    assert por("tinta guache")["Tinta guache azul"]["unidade"] == "unidade"              # o pote avulso continua unidade
    assert "Cola branca 90 g" in por("cola branca") and "Cola em bastão 20 g" in por("cola bastao")
    assert "Tesoura escolar sem ponta" in por("tesoura") and "Caderno brochura 96 folhas" in por("caderno")
    assert "Papel A4 branco 90 g" in por("sulfite")


def teste_federal_tem_os_tamanhos_do_material_de_limpeza():
    f = cat.CatalogoFederal()
    por = lambda q: {x["nome"]: x for x in f.buscar(q, "limpeza", limite=100)}          # noqa: E731
    sabao = [x["nome"] for x in f.buscar("sabao em po", "limpeza")]
    assert sabao[:4] == ["Sabão em pó", "Sabão em pó 500 g", "Sabão em pó 1 kg", "Sabão em pó 250 g"], sabao
    assert por("sabao em po")["Sabão em pó 250 g"]["unidade"] == "pacote"
    assert "Sabão líquido 2 L" in por("sabao liquido 2 litros")                            # "2 litros" acha "2 L"
    assert por("agua sanitaria")["Água sanitária 2 L"]["unidade"] == "frasco"             # líquido com tamanho: conta frascos
    desinf = [x["nome"] for x in f.buscar("desinfetante", "limpeza")]
    assert desinf[:3] == ["Desinfetante", "Desinfetante 2 L", "Desinfetante 1 L"], desinf    # tamanho antes do cheiro
    assert "Desinfetante lavanda" in desinf
    assert "Limpa-vidros 500 ml" in por("limpa vidro")                                     # o hífen separa as palavras
    assert "Balde 20 L" in por("balde") and "Vassoura de piaçava" in por("vassoura")
    assert not f.buscar("sabao", "pedagogico")                                             # limpeza não aparece no pedagógico


def teste_federal_busca_pelo_comeco_da_palavra():
    f = cat.CatalogoFederal()
    achou = [x["nome"] for x in f.buscar("cola", "pedagogico", limite=100)]
    assert "Cola" in achou and "Sacola" not in achou and "Transferidor escolar" not in achou, achou
    assert [x["nome"] for x in f.buscar("cart az", "pedagogico")][:2] == ["Cartolina azul", "Cartolina azul claro"]
    assert f.buscar("olina", "pedagogico") == []                            # pedaço do meio da palavra não vale


def teste_federal_sem_arquivo_nao_derruba():
    f = cat.CatalogoFederal(os.path.join(tempfile.mkdtemp(), "nao_existe.json"))
    assert len(f) == 0 and f.buscar("papel", "pedagogico") == []


def teste_sem_catalogo_de_fabrica_funciona():
    c = cat.Catalogo(tempfile.mkdtemp(), "PC1", arquivo_base=os.path.join(tempfile.mkdtemp(), "nao_existe.json"))
    assert c.entradas == {} and c.aplicar([item("Qualquer coisa")])[0]["descricao"] == "Qualquer coisa"


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
