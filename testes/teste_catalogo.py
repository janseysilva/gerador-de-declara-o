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


def teste_sem_catalogo_de_fabrica_funciona():
    c = cat.Catalogo(tempfile.mkdtemp(), "PC1", arquivo_base=os.path.join(tempfile.mkdtemp(), "nao_existe.json"))
    assert c.entradas == {} and c.aplicar([item("Qualquer coisa")])[0]["descricao"] == "Qualquer coisa"


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
