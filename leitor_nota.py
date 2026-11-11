# -*- coding: utf-8 -*-
"""
Leitor de nota fiscal (DANFE) em PDF para a ENTRADA do estoque.

O PDF da nota costuma ser ESCANEADO (só imagem). Então o arquivo é aberto página por página,
a imagem é endireitada e lida por um OCR (reconhecimento de texto, o RapidOCR, que roda no
próprio computador, sem internet). Depois o texto é arrumado em linhas da tabela de produtos:
descrição, unidade (UN, CX, PCT...) e quantidade.

O que está aqui:
  - a parte que entende a tabela (`extrair_itens`, `ler_dinheiro`...): só Python puro, testada
    sem precisar do OCR (`testes/teste_leitor_nota.py`);
  - a parte que usa o OCR (`LeitorNota`): abre o PDF, endireita a imagem, chama o OCR.

O OCR erra (letras e números), então o programa NUNCA registra sozinho: ele mostra a lista lida,
com a imagem de cada linha da nota ao lado, para a pessoa conferir antes de entrar no estoque.
"""

import math
import os
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

# Unidades que aparecem na nota -> como ficam no estoque (ver estoque.UNIDADES).
UNIDADES_NOTA = {
    "UN": "unidade", "UND": "unidade", "UNID": "unidade", "U": "unidade", "PC": "unidade", "PÇ": "unidade",
    "CX": "caixa", "CXA": "caixa", "PCT": "pacote", "PT": "pacote", "PCTE": "pacote",
    "RS": "resma", "RESMA": "resma", "RL": "rolo", "ROL": "rolo", "PAR": "par", "PR": "par",
    "KG": "kg", "LT": "litro", "L": "litro", "DZ": "dúzia", "FD": "fardo", "MT": "metro", "M": "metro",
    "FL": "folha", "FLS": "folha", "GL": "galão", "BD": "balde", "JG": "jogo", "KIT": "kit",
    "FR": "frasco", "TB": "tubo", "SC": "saco", "BL": "bloco", "CT": "cartela", "ET": "caixa",
}
# Leituras erradas comuns do OCR para as unidades (o "UN" quase sempre vira "NN" ou "Nn").
CORRECOES_UNIDADE = {"NN": "UN", "N": "UN", "UM": "UN", "LN": "UN", "IN": "UN", "VN": "UN", "UH": "UN",
                     "CK": "CX", "CXX": "CX", "OX": "CX", "PCI": "PCT", "PGT": "PCT", "PC1": "PCT", "P0T": "PCT"}


# ---------------------------------------------------------------------------
# Pedacinhos de texto
# ---------------------------------------------------------------------------

class Palavra:
    """Um trecho de texto lido pelo OCR, com a posição na página (x, y = canto de cima à esquerda)."""

    __slots__ = ("t", "x", "y", "w", "h")

    def __init__(self, t, x, y, w, h):
        self.t, self.x, self.y, self.w, self.h = t, float(x), float(y), float(w), float(h)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def __repr__(self):
        return "Palavra({!r}, x={:.0f}, y={:.0f})".format(self.t, self.x, self.y)


def sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c))


def _chave(texto):
    """Só letras e números em maiúsculas, para comparar títulos de coluna lidos pelo OCR."""
    return re.sub(r"[^A-Z0-9]", "", sem_acento(texto).upper())


def ler_dinheiro(texto):
    """'1.264,00' -> 1264.0 ; devolve None se não parece um valor (o OCR às vezes embaralha)."""
    t = (texto or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", t):
        return None
    return float(t.replace(".", "").replace(",", "."))


def ler_quantidade_nota(texto):
    """
    Quantidade da coluna QUANT.: '10' -> 10.0, '2,5' -> 2.5. Aceita as trocas comuns do OCR em um
    token curto (I/l/| no lugar do 1, O no lugar do 0, símbolo sobrando depois do número).
    """
    t = (texto or "").strip()
    if not t or len(t) > 7:
        return None
    if t in ("I", "l", "|", "!", "i"):
        return 1.0
    t = t.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"}))
    m = re.fullmatch(r"(\d{1,5})(?:,(\d{1,3}))?\D{0,2}", t)
    if not m:
        return None
    numero = float(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
    return numero if numero > 0 else None


def normalizar_unidade_nota(texto):
    """'Nn' -> ('UN', 'unidade'); devolve (None, None) se não reconhece."""
    t = re.sub(r"[^A-Za-zÇç]", "", texto or "").upper()
    t = CORRECOES_UNIDADE.get(t, t)
    if t in UNIDADES_NOTA:
        return t, UNIDADES_NOTA[t]
    return None, None


# ---------------------------------------------------------------------------
# Da lista de palavras da página para as linhas da tabela
# ---------------------------------------------------------------------------

class ColunasTabela:
    """Onde ficam as colunas da tabela de produtos desta página (a partir dos títulos)."""

    def __init__(self, esq_codigo, esq_unid, esq_valor_unit, esq_total, dir_total, fim_descricao, topo):
        self.esq_codigo, self.esq_unid, self.esq_valor_unit = esq_codigo, esq_unid, esq_valor_unit
        self.esq_total, self.dir_total, self.fim_descricao, self.topo = esq_total, dir_total, fim_descricao, topo

    @property
    def inicio_descricao(self):
        return self.esq_codigo + 95

    @property
    def inicio_qtd(self):
        return self.esq_unid + 40

    @property
    def fim_qtd(self):
        return self.esq_valor_unit - 20


def achar_colunas(palavras):
    """
    Procura os títulos "UNID." / "V. UNIT." / "V. TOTAL" / "NCM" / "CÓD." e devolve as colunas,
    ou None se a página não tem a tabela de produtos.
    """
    unid = [p for p in palavras if _chave(p.t).startswith("UNID")
            and any(m in _chave(q.t) for q in palavras if abs(q.cy - p.cy) < 14 and q is not p
                    for m in ("NCM", "UNIT", "VTOTAL"))]
    if not unid:
        return None
    u = min(unid, key=lambda p: p.y)
    mesma = [p for p in palavras if abs(p.cy - u.cy) < 14]
    esq_codigo = next((p.x for p in mesma if _chave(p.t).startswith("COD")), None)
    if esq_codigo is None:
        esq_codigo = min([p.x for p in mesma] or [u.x - 760])
    ncm = next((p for p in mesma if _chave(p.t).startswith("NCM")), None)
    unit = next((p for p in mesma if "UNIT" in _chave(p.t)), None)
    total = next((p for p in mesma if _chave(p.t).endswith("TOTAL")), None)
    esq_unit = unit.x if unit else u.x + 125
    esq_total = total.x if total else esq_unit + 80
    return ColunasTabela(
        esq_codigo=esq_codigo, esq_unid=u.x, esq_valor_unit=esq_unit,
        esq_total=esq_total, dir_total=esq_total + 70,
        fim_descricao=(ncm.x - 15) if ncm else u.x - 215, topo=u.y + u.h + 6)


# Se a linha tem um destes trechos, a tabela de produtos já acabou (o OCR pode lê-los em pedaços ou juntos).
FIM_TABELA = ("CALCULODOISSQN", "ISSQN", "DADOSADICIONAIS", "INFORMACOESCOMPLEMENTARES", "RESERVADOAOFISCO")


def agrupar_linhas(palavras, tolerancia=13):
    """Junta as palavras que estão na mesma altura (mesma linha da tabela)."""
    grupos = []
    for p in sorted(palavras, key=lambda p: p.cy):
        if grupos and abs(p.cy - grupos[-1]["cy"]) <= max(tolerancia, p.h * 0.55):
            g = grupos[-1]
            g["palavras"].append(p)
            g["cy"] = sum(q.cy for q in g["palavras"]) / len(g["palavras"])
        else:
            grupos.append({"cy": p.cy, "palavras": [p]})
    for g in grupos:
        g["palavras"].sort(key=lambda p: p.x)
    return grupos


def _juntar(palavras):
    return " ".join(p.t.strip() for p in palavras if p.t.strip()).strip()


def limpar_descricao(texto):
    t = re.sub(r"\s+", " ", texto or "").strip(" |.,;:-")
    t = re.sub(r"(?<=\d)F[1l]s\b|\bF1s\b", "Fls", t)            # 'c/20F1s' -> 'c/20Fls'
    t = re.sub(r"(?<=\d)O(?=[mMgGlL]\b)", "0", t)               # '5Om' -> '50m'
    return t


def extrair_itens(palavras, colunas=None):
    """
    Linhas de produto de UMA página. Cada item: dict com descricao, unidade_nota ('UN'),
    unidade (estoque), quantidade (ou None), valor_unitario, valor_total, codigo, y (altura da
    linha na página) e avisos (o que precisa de conferência).
    """
    colunas = colunas or achar_colunas(palavras)
    if colunas is None:
        return [], None
    itens = []
    for g in agrupar_linhas([p for p in palavras if p.cy > colunas.topo]):
        chave = _chave(_juntar(g["palavras"]))
        if any(marca in chave for marca in FIM_TABELA):
            break
        item = _ler_linha(g["palavras"], colunas)
        if item:
            item["y"] = g["cy"]
            itens.append(item)
    return itens, colunas


def _ler_linha(pals, c):
    codigo = [p for p in pals if p.x < c.inicio_descricao - 5]
    desc = [p for p in pals if c.inicio_descricao - 5 <= p.x < c.fim_descricao]
    unid = [p for p in pals if c.esq_unid - 25 <= p.x < c.inicio_qtd]
    qtd = [p for p in pals if c.inicio_qtd <= p.x < c.fim_qtd]
    unit = [p for p in pals if c.fim_qtd <= p.x < c.esq_total - 25]
    total = [p for p in pals if c.esq_total - 25 <= p.x < c.dir_total + 40]

    cod = _juntar(codigo)
    cod = cod if re.fullmatch(r"\d{2,7}", cod) else ""
    descricao = limpar_descricao(_juntar(desc))
    unidade_nota, unidade = normalizar_unidade_nota(_juntar(unid))
    quantidade = next((q for q in (ler_quantidade_nota(p.t) for p in qtd) if q), None)
    valor_unit = next((v for v in (ler_dinheiro(p.t) for p in unit) if v is not None), None)
    valor_total = next((v for v in (ler_dinheiro(p.t) for p in total) if v is not None), None)

    # Não é linha de produto (título, linha solta do OCR): sem descrição, sem código e sem números da tabela.
    if not (cod or descricao) and quantidade is None and valor_unit is None and valor_total is None:
        return None
    if not descricao and not cod and quantidade is None:
        return None

    avisos = []
    if not descricao:
        avisos.append("descrição não foi lida")
    if quantidade is None and valor_unit and valor_total:      # a conta fecha: quantidade = total / unitário
        q = valor_total / valor_unit
        if abs(q - round(q)) < 0.02 and 0 < round(q) < 100000:
            quantidade = float(round(q))
            avisos.append("quantidade calculada pelo valor")
    if quantidade is None:
        avisos.append("quantidade não foi lida")
    elif valor_unit and valor_total and abs(quantidade * valor_unit - valor_total) > max(0.05, valor_total * 0.01):
        avisos.append("quantidade não bate com o valor da nota")
    if unidade_nota is None:
        avisos.append("unidade não foi lida")
    return {"codigo": cod, "descricao": descricao, "unidade_nota": unidade_nota, "unidade": unidade or "unidade",
            "quantidade": quantidade, "valor_unitario": valor_unit, "valor_total": valor_total, "avisos": avisos,
            "caixa": (c.esq_codigo - 8, c.dir_total + 20)}


# ---------------------------------------------------------------------------
# Dados da nota (número, fornecedor, data)
# ---------------------------------------------------------------------------

def dados_da_nota(palavras):
    """Número da nota, nome do fornecedor e data de emissão, quando o OCR conseguiu ler."""
    topo = sorted([p for p in palavras if p.y < 420], key=lambda p: (round(p.cy / 14), p.x))
    texto = " ".join(p.t for p in topo)
    numero = re.search(r"\b(\d{3}\.\d{3}\.\d{3})\b", texto)
    emissao = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
    fornecedor = ""
    linhas = agrupar_linhas([p for p in palavras if p.y < 130 and p.x < 700 and p.w < 500], 12)
    for g in linhas:                               # a 1ª linha do alto, à esquerda, é o nome do emitente
        t = limpar_descricao(_juntar(g["palavras"]))
        if len(t) >= 4 and not re.search(r"DANFE|DOCUMENTO|AUXILIAR|FISCAL|ENTRADA", sem_acento(t).upper()):
            fornecedor = t
            break
    cnpj = re.search(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b", texto)
    dados = {"numero": numero.group(1) if numero else "", "emissao": emissao.group(1) if emissao else "",
             "fornecedor": fornecedor, "cnpj": cnpj.group(1) if cnpj else ""}
    # quem é o fornecedor, para guardar os códigos dele no catálogo: o CNPJ, ou (se não foi lido) o nome
    dados["fornecedor_chave"] = re.sub(r"\D", "", dados["cnpj"]) or (_chave_nome(fornecedor) if fornecedor else "")
    dados["rotulo"] = " – ".join(p for p in (fornecedor, "NF " + dados["numero"] if dados["numero"] else "",
                                             dados["emissao"]) if p)
    return dados


# ---------------------------------------------------------------------------
# Comparar com os materiais que já existem
# ---------------------------------------------------------------------------

def _chave_nome(texto):
    """Só letras e números, minúsculos e sem acento: 'Cola branca 90 g' e 'COLA BRANCA 90g' ficam iguais."""
    return re.sub(r"[^a-z0-9]+", "", sem_acento(texto).lower())


chave_nome = _chave_nome


def _numero_limpo(n):
    return str(int(n)) if float(n).is_integer() else ("%g" % n)


def tamanho_embalagem(texto):
    """
    O tamanho da embalagem, para saber se dois produtos de mesmo nome são o mesmo: 'Frasco 500ml' -> ('vol', 500),
    'Com 2 Litros' -> ('vol', 2000), 'Unid c/ 35 grs' -> ('massa', 35), 'Pacote com 8' -> ('un', 8).
    Sem tamanho que dê para entender ('Unid', 'c/ 500') -> None (não atrapalha: nunca conta como diferente).
    """
    t = sem_acento(texto or "").lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|litros?|lts?|l|kg|gramas?|grs?|g|unidades?|unid|und|un)\b", t)
    if m:
        n, u = float(m.group(1).replace(",", ".")), m.group(2)
        if u == "ml":
            return ("vol", n)
        if u in ("l", "lt", "lts") or u.startswith("litro"):
            return ("vol", n * 1000)
        if u == "kg":
            return ("massa", n * 1000)
        if u in ("g", "gr", "grs") or u.startswith("grama"):
            return ("massa", n)
        return ("un", n)
    m = re.search(r"(?:pacote|pct|caixa|cx)\s*(?:com|c/)\s*(\d+)\b", t)
    return ("un", float(m.group(1))) if m else None


def descrever_tamanho(tamanho):
    """('vol', 500) -> '500 ml'; ('massa', 250) -> '250 g'; ('un', 8) -> '8 un'."""
    if not tamanho:
        return ""
    grandeza, n = tamanho
    if grandeza == "vol":
        return "{} L".format(_numero_limpo(n / 1000)) if n >= 1000 else "{} ml".format(_numero_limpo(n))
    if grandeza == "massa":
        return "{} kg".format(_numero_limpo(n / 1000)) if n >= 1000 else "{} g".format(_numero_limpo(n))
    return "{} un".format(_numero_limpo(n))


def achar_igual(descricao, materiais):
    """
    O material já cadastrado com O MESMO nome (sem contar maiúsculas, acentos, espaços e pontuação).
    Só nome igual de propósito: "Papel Cartão Rosa" e "Papel Cartão Preto" são parecidíssimos, mas são
    produtos diferentes e NÃO podem ser somados no mesmo material.
    """
    alvo = _chave_nome(descricao)
    if not alvo:
        return None
    return next((m for m in materiais if _chave_nome(m["nome"]) == alvo), None)


# ---------------------------------------------------------------------------
# "É o mesmo produto?" (para somar no mesmo material mesmo escrito de jeito diferente)
# ---------------------------------------------------------------------------

# Palavras que não dizem qual é o produto (ligações e abreviações).
_PALAVRAS_VAZIAS = {"de", "da", "do", "das", "dos", "para", "p", "em", "e", "com", "c", "a", "o", "as", "os", "un",
                    "und", "unid", "ref", "tipo", "similar", "ou"}
# Uma cor (ou tom) a mais no nome já é outro produto: "Papel Cartão" e "Papel Cartão Rosa" não se juntam sozinhos.
_CORES = {"amarelo", "amarela", "azul", "verde", "vermelho", "vermelha", "rosa", "preto", "preta", "branco", "branca",
          "laranja", "roxo", "roxa", "marrom", "cinza", "bege", "dourado", "prata", "lilas", "escuro", "claro",
          "royal", "gelo", "colorido"}


# Como a unidade de medida é escrita: "2 litros" = "2 L", "500 gramas" = "500 g", "1 quilo" = "1 kg".
_UNIDADES_ESCRITAS = {"litro": "l", "litros": "l", "lt": "l", "lts": "l", "gramas": "g", "grama": "g", "gr": "g",
                      "grs": "g", "quilo": "kg", "quilos": "kg", "kilo": "kg", "kilos": "kg",
                      "mililitro": "ml", "mililitros": "ml"}


def _palavras_do_nome(texto):
    """
    As palavras (sem acento, minúsculas) separando número de letra e unificando a unidade escrita depois de
    um número: "Sabão em pó 500g" e "Sabão em pó 500 gramas" dão as mesmas palavras de "Sabão em pó 500 g".
    """
    palavras = re.findall(r"\d+|[a-z]+", sem_acento(texto or "").lower())
    for i in range(1, len(palavras)):
        if palavras[i - 1].isdigit() and palavras[i] in _UNIDADES_ESCRITAS:
            palavras[i] = _UNIDADES_ESCRITAS[palavras[i]]
    return palavras


def chave_produto(texto):
    """
    As palavras que identificam o produto: sem acento, sem maiúsculas, sem o que está entre parênteses
    ("tipo Veja similar"), sem palavras de ligação e com o plural simples cortado.
    'Sabão em Pó (marca X)' -> {'sabao', 'po'}.
    """
    sem_parenteses = re.sub(r"\([^)]*\)", " ", texto or "")
    palavras = _palavras_do_nome(sem_parenteses)
    if not [p for p in palavras if p not in _PALAVRAS_VAZIAS]:                 # nome só com parênteses
        palavras = _palavras_do_nome(texto)
    chave = set()
    for p in palavras:
        if p in _PALAVRAS_VAZIAS:
            continue
        if len(p) > 3 and p.endswith("s") and not p.endswith("ss"):
            p = p[:-1]
        chave.add(p)
    return frozenset(chave)


def _mesma_palavra(a, b):
    """Igual, ou quase (uma letra trocada: 'liquida'/'liquido', 'cademo'/'caderno'). Números só se forem iguais."""
    if a == b:
        return True
    if not (a.isalpha() and b.isalpha()) or min(len(a), len(b)) < 5:
        return False
    if a.replace("rn", "m") == b.replace("rn", "m"):               # erro clássico do OCR: "rn" lido como "m"
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.84


def _diferenca(a, b):
    """Palavras de `b` que não aparecem em `a` (comparando de forma tolerante)."""
    return {y for y in b if not any(_mesma_palavra(x, y) for x in a)}


def mesmo_produto(nome_a, nome_b):
    """
    Dois nomes são o mesmo produto quando têm as mesmas palavras, ou um tem só PALAVRAS A MAIS que não mudam o
    produto ("Detergente" e "Detergente líquido"). Não junta se a palavra a mais for uma cor ou tiver número
    ("Papel Cartão Rosa"/"Preto", "Sacos de 100 litros"/"50 litros"), nem se o nome curto for uma palavra solta e
    o outro for comprido ("Papel" e "Papel Cartão 48x66 Rosa").
    """
    a, b = chave_produto(nome_a), chave_produto(nome_b)
    if not a or not b:
        return False
    so_b, so_a = _diferenca(a, b), _diferenca(b, a)
    if not so_a and not so_b:
        return True
    if so_a and so_b:
        return False                                            # cada um tem algo que o outro não tem
    curto, longo, extras = (a, b, so_b) if not so_a else (b, a, so_a)
    if any(re.search(r"\d", p) or p in _CORES for p in extras):
        return False
    return len(curto) >= 2 or len(longo) <= 3


def achar_mesmo(descricao, materiais, tolerante=True):
    """O material já cadastrado que é o mesmo produto (o mais parecido), ou None."""
    if not tolerante:
        return achar_igual(descricao, materiais)
    alvo = chave_produto(descricao)
    melhor, menor = None, None
    for m in materiais:
        if not mesmo_produto(descricao, m["nome"]):
            continue
        distancia = len(alvo ^ chave_produto(m["nome"]))
        if menor is None or distancia < menor:
            melhor, menor = m, distancia
    return melhor


def _conflito_tamanho(item, tamanho_outro):
    """Mesmo nome, mas tamanhos de embalagem diferentes (e a pessoa ainda não decidiu)."""
    atual = tamanho_embalagem(item.get("embalagem") or "")
    return atual is not None and tamanho_outro is not None and atual != tamanho_outro and not item.get("tamanho_resolvido")


def _candidatos_iniciais(materiais, catalogo):
    return [{"nome": m["nome"], "_destino": ("existente", m),
             "tamanho": (catalogo.tamanho_do_nome(m["nome"]) if catalogo else None) or tamanho_embalagem(m["nome"])}
            for m in materiais]


def _igual_com_tamanho(item, candidatos):
    """
    O candidato cujo nome é o do item MAIS o tamanho da embalagem: "Sabão em pó" de 500 g é o material "Sabão em pó
    500 g" (nome do banco de materiais, com o tamanho no nome). Só vale se o nome do item não traz tamanho.
    """
    tam = tamanho_embalagem(item.get("embalagem") or "")
    if tam is None or item.get("separado") or tamanho_embalagem(item["descricao"]) is not None:
        return None
    alvo = chave_produto("{} {}".format(item["descricao"], descrever_tamanho(tam)))
    return next((c for c in candidatos if chave_produto(c["nome"]) == alvo), None)


def _candidato_do_item(item, candidatos, catalogo):
    """O candidato (material do estoque ou item de cima) com que o item se junta: nome igual, ou parecido."""
    if item.get("separado"):
        return achar_igual(item["descricao"], candidatos)
    com_tamanho = _igual_com_tamanho(item, candidatos)
    if com_tamanho is not None:
        return com_tamanho
    achado = achar_mesmo(item["descricao"], candidatos)
    if achado is not None and chave_produto(item["descricao"]) != chave_produto(achado["nome"]) \
            and catalogo is not None and catalogo.sao_diferentes(item["descricao"], achado["nome"]):
        return None                                           # a pessoa já disse que esses dois são diferentes
    return achado


def _novo_candidato(n, item):
    return {"nome": item["descricao"], "_destino": ("junta", n, item["descricao"]),
            "tamanho": tamanho_embalagem(item.get("embalagem") or "")}


def planejar_destinos(itens, materiais, catalogo=None):
    """
    Para cada item, em ordem, onde ele vai ficar: ("existente", material), ("junta", nº do 1º item, nome) quando
    é o mesmo produto de um item de cima da própria lista, ou ("novo",) quando vira um material novo.
    A mesma conta é refeita na hora de cadastrar, então a tela e o resultado sempre combinam.
    """
    candidatos = _candidatos_iniciais(materiais, catalogo)
    destinos = []
    for n, item in enumerate(itens):
        achado = None
        if not (item.get("tamanho_diferente_de") and not item.get("tamanho_resolvido")):
            achado = _candidato_do_item(item, candidatos, catalogo)
            if achado is not None and _conflito_tamanho(item, achado.get("tamanho")):
                achado = None
        if achado is not None:
            destinos.append(achado["_destino"])
        else:
            candidatos.append(_novo_candidato(n, item))
            destinos.append(("novo",))
    return destinos


def _duvida(n, item, motivo, nome_destino, destino, origem, tamanho_outro=None):
    return {"indice": n, "item": item, "motivo": motivo, "nome_destino": nome_destino, "destino": destino,
            "origem": origem, "tamanho_item": descrever_tamanho(tamanho_embalagem(item.get("embalagem") or "")),
            "tamanho_outro": descrever_tamanho(tamanho_outro) if tamanho_outro else ""}


def achar_duvidas(itens, materiais, catalogo=None):
    """
    O que vale PERGUNTAR à pessoa. Dois motivos:
      "nome": parece o mesmo produto de outro (do estoque ou de cima na lista), mas com palavras diferentes
              ("Detergente" e "Detergente líquido"). Nome igual (só acento, maiúscula, plural ou parênteses
              diferente) o programa junta sozinho e não pergunta.
      "tamanho": o nome é igual, mas o tamanho da embalagem é diferente ("Sabão em pó" de 500 g e de 250 g).
    Cada dúvida: {"indice", "item", "motivo", "nome_destino", "destino", "origem", "tamanho_item", "tamanho_outro"}
    (origem = o item de cima, se for da própria lista).
    """
    candidatos = _candidatos_iniciais(materiais, catalogo)
    duvidas = []
    for n, item in enumerate(itens):
        produto = item.get("tamanho_diferente_de")                  # do catálogo: nome igual, tamanho diferente
        if produto and not item.get("tamanho_resolvido"):
            duvidas.append(_duvida(n, item, "tamanho", produto["nome"], ("catalogo", produto), None,
                                   tamanho_embalagem(produto.get("embalagem") or "")))
            continue
        igual = achar_igual(item["descricao"], candidatos)
        if igual is not None:
            if _conflito_tamanho(item, igual.get("tamanho")):
                destino = igual["_destino"]
                duvidas.append(_duvida(n, item, "tamanho", igual["nome"], destino,
                                       itens[destino[1]] if destino[0] == "junta" else None, igual.get("tamanho")))
            continue                                                 # nome igual: junta sozinho
        if _igual_com_tamanho(item, candidatos) is not None:
            continue                                                 # nome + tamanho = o material "X 500 g": junta sozinho
        parecido = _candidato_do_item(item, candidatos, catalogo)
        if parecido is not None:
            if chave_produto(item["descricao"]) != chave_produto(parecido["nome"]):
                destino = parecido["_destino"]
                duvidas.append(_duvida(n, item, "nome", parecido["nome"], destino,
                                       itens[destino[1]] if destino[0] == "junta" else None))
            continue                                                 # junta (sozinho ou depois de perguntar)
        candidatos.append(_novo_candidato(n, item))
    return duvidas


# ---------------------------------------------------------------------------
# Listas simples: ITEM | DESCRIÇÃO | UND | POR FUNC | QUANT.  (material de limpeza mensal, fichas de controle)
# ---------------------------------------------------------------------------

# Se a linha tem um destes trechos, a lista já acabou (rodapé com local, data, assinatura e carimbo).
FIM_LISTA = ("LOCALDAENTREGA", "DATADAENTREGA", "ASSINATURA", "CARIMBO")

_UNIDADES_LISTA = {"unid": "unidade", "unidade": "unidade", "und": "unidade", "pct": "pacote", "pacote": "pacote",
                   "frasco": "frasco", "caixa": "caixa", "cx": "caixa", "litro": "litro", "litros": "litro",
                   "kg": "kg", "rolo": "rolo", "par": "par", "galão": "galão", "galao": "galão"}


class CabecalhoLista:
    """Onde ficam as colunas (centros) e onde começam as linhas de uma lista simples."""

    def __init__(self, item_cx, und_cx, qtd_cx, por_cx, base, esq, dir_):
        self.item_cx, self.und_cx, self.qtd_cx, self.por_cx = item_cx, und_cx, qtd_cx, por_cx
        self.base, self.esq, self.dir = base, esq, dir_

    @property
    def meia_und(self):
        """Metade da largura (aproximada) da coluna da unidade: o que está mais perto que isso é a unidade."""
        return max(110.0, 0.35 * (self.qtd_cx - self.und_cx))


def achar_cabecalho_lista(palavras):
    """Procura os títulos ITEM / DESCRIÇÃO / UND (ou TIPO DE UND.) / QUANT. (ou QT. TOTAIS)."""
    item = next((p for p in palavras if _chave(p.t) == "ITEM"), None)
    if item is None:
        return None
    faixa = [p for p in palavras if item.cy - 30 <= p.cy <= item.cy + 36]
    desc = next((p for p in faixa if _chave(p.t).startswith("DESCRI")), None)
    qtd = (next((p for p in faixa if "TOTAIS" in _chave(p.t)), None)
           or next((p for p in faixa if _chave(p.t).startswith("QUANT")), None))
    und = [p for p in faixa if _chave(p.t) in ("UND", "UNID", "UNIDADE") or _chave(p.t).startswith("TIPODE")]
    if not (desc and qtd and und):
        return None
    und_cx = sum(p.cx for p in und) / len(und)
    por = [p for p in faixa if _chave(p.t).startswith(("POR", "QTPOR", "FUNC")) and und_cx < p.cx < qtd.cx]
    por_cx = sum(p.cx for p in por) / len(por) if por else und_cx + 0.6 * (qtd.cx - und_cx)
    return CabecalhoLista(item_cx=item.cx, und_cx=und_cx, qtd_cx=qtd.cx, por_cx=por_cx,
                          base=max(p.cy for p in faixa) + 20, esq=max(0.0, item.x - 25), dir_=qtd.x + qtd.w + 50)


def converter_und_lista(texto):
    """
    'Com 850 ml' -> ('unidade', '850 ml') ; 'Litro' -> ('litro', '') ; 'Pacote com 8' -> ('pacote', 'pacote com 8') ;
    'Unid c/ 35 grs' -> ('unidade', '35 grs') ; 'PCT 500g' -> ('pacote', 'pacote 500g').
    A unidade serve para contar no estoque; o resto (o tamanho da embalagem) fica à parte, só para a pessoa ver
    na conferência: o mesmo produto escrito com embalagens diferentes nas listas vai para o mesmo material.
    """
    t = re.sub(r"\s+", " ", (texto or "").strip()).lower()
    m = re.match(r"^(unidade|unid|und|pacote|pct|frasco|caixa|cx|litros|litro|kg|rolo|par|gal[aã]o)\b\.?\s*(.*)$", t)
    palavra, resto = (m.group(1), m.group(2)) if m else ("", t)
    tinha_com = bool(re.match(r"^(com|c/)\s*", resto))
    resto = re.sub(r"^(com|c/|de)\s*", "", resto).strip()
    unidade = _UNIDADES_LISTA.get(palavra, "unidade")
    if not resto:
        return unidade, ""
    if unidade in ("unidade", "litro") or not palavra:
        return "unidade" if not palavra else unidade, ("c/ " + resto) if resto.isdigit() else resto
    return unidade, "{} {}{}".format(unidade, "com " if tinha_com else "", resto)


def montar_nome_lista(descricao):
    """'DETERGENTE' -> 'Detergente' (nomes todos em maiúsculas viram frase normal). A embalagem não entra no nome."""
    d = limpar_descricao(descricao)
    sem_parenteses = re.sub(r"\([^)]*\)", "", d)           # "PEDRA SANITÁRIA (desodex ou similar)" também é maiúsculo
    if d and sem_parenteses == sem_parenteses.upper():
        d = d.lower()
        d = d[:1].upper() + d[1:]
    return d


def _ler_linha_lista(pals, c):
    pals = sorted(pals, key=lambda p: p.x)
    num = next((p for p in pals if re.fullmatch(r"\d{1,3}", p.t.strip()) and abs(p.cx - c.item_cx) <= 70), None)
    resto = [p for p in pals if p is not num]
    numericos = sorted((p for p in resto if ler_quantidade_nota(p.t) is not None and p.cx > c.und_cx + c.meia_und * 0.5),
                       key=lambda p: p.x)
    # cada número é da coluna cujo título está mais perto dele (se faltar a quantidade, o "por funcionário"
    # não pode ser tomado por ela)
    qtd_box = next((p for p in reversed(numericos) if abs(p.cx - c.qtd_cx) <= abs(p.cx - c.por_cx)), None)
    por_box = next((p for p in reversed(numericos) if abs(p.cx - c.por_cx) < abs(p.cx - c.qtd_cx)), None)
    und_boxes = [p for p in resto if p is not qtd_box and p is not por_box and abs(p.cx - c.und_cx) <= c.meia_und]
    desc_boxes = [p for p in resto if p.cx < c.und_cx - c.meia_und]

    descricao = limpar_descricao(_juntar(desc_boxes))
    und_texto = _juntar(und_boxes)
    quantidade = ler_quantidade_nota(qtd_box.t) if qtd_box else None
    if (not descricao or len(re.sub(r"[^A-Za-zÀ-ú]", "", descricao)) < 3) and quantidade is None:
        return None
    if num is None and quantidade is None:
        return None
    unidade, detalhe = converter_und_lista(und_texto)
    avisos = []
    if not descricao:
        avisos.append("descrição não foi lida")
    if quantidade is None:
        avisos.append("quantidade não foi lida")
    return {"codigo": num.t.strip() if num else "", "descricao": montar_nome_lista(descricao), "embalagem": detalhe,
            "unidade_nota": und_texto or None, "unidade": unidade, "quantidade": quantidade,
            "valor_unitario": None, "valor_total": None, "avisos": avisos,
            "por_func": ler_quantidade_nota(por_box.t) if por_box else None, "caixa": (c.esq, c.dir)}


def _conferir_por_funcionario(itens):
    """
    Nessas listas a quantidade é "por funcionário" x um número fixo (ex.: 15 x 4 = 60 e 4 x 4 = 16).
    Quem não segue a regra do resto da lista foi provavelmente mal lido: fica marcado para conferir.
    """
    razoes = [round(i["quantidade"] / i["por_func"]) for i in itens if i["quantidade"] and i.get("por_func")]
    if len(razoes) < 4:
        return
    comum, vezes = Counter(razoes).most_common(1)[0]
    if comum < 1 or vezes < 0.6 * len(razoes):
        return
    for i in itens:
        por = i.get("por_func")
        if not por:
            continue
        if i["quantidade"] is None:
            i["quantidade"] = float(por * comum)
            i["avisos"] = [a for a in i["avisos"] if "quantidade não foi lida" not in a]
            i["avisos"].append("quantidade calculada (por funcionário x {})".format(comum))
        elif abs(i["quantidade"] - por * comum) > 0.01:
            i["avisos"].append("quantidade não é {:g} x {} como no resto da lista".format(por, comum))


def extrair_itens_lista(palavras):
    """Itens de UMA página de lista simples. Devolve (itens, cabeçalho) ou ([], None) se a página não é uma lista."""
    cab = achar_cabecalho_lista(palavras)
    if cab is None:
        return [], None
    itens = []
    for g in agrupar_linhas([p for p in palavras if p.cy > cab.base], 16):
        if any(marca in _chave(_juntar(g["palavras"])) for marca in FIM_LISTA):
            break
        item = _ler_linha_lista(g["palavras"], cab)
        if item:
            item["y"] = g["cy"]
            itens.append(item)
    _conferir_por_funcionario(itens)
    return itens, cab


def dados_da_lista(palavras, cab):
    """Mês, DDZ, kit e empresa do alto da lista, e o texto que vai na observação da entrada."""
    topo = sorted((p for p in palavras if p.cy < cab.base), key=lambda p: (round(p.cy / 16), p.x))
    texto = " ".join(p.t for p in topo)
    mes = re.search(r"\b(\d{1,2}/\d{4})\b", texto)

    def valor_depois(rotulo):
        for i, p in enumerate(topo):
            if _chave(p.t).startswith(rotulo):
                t = re.sub(r"^\W*{}\W*".format(rotulo), "", p.t.strip(), flags=re.I).strip()
                if not t and i + 1 < len(topo):
                    t = topo[i + 1].t.strip()
                return t
        return ""

    ddz, kit = valor_depois("DDZ"), valor_depois("KIT")
    empresa = next((p.t.strip() for p in topo if "LTDA" in _chave(p.t)), "")
    partes = ["Material de limpeza" + (" " + mes.group(1) if mes else "")]
    if ddz:
        partes.append("DDZ " + ddz)
    if kit and kit.isdigit():
        partes.append("kit " + kit)
    if empresa:
        partes.append(empresa)
    return {"numero": "", "emissao": mes.group(1) if mes else "", "fornecedor": empresa, "rotulo": " – ".join(partes)}


# ---------------------------------------------------------------------------
# A parte que usa o OCR (precisa do rapidocr, do onnxruntime e do pypdfium2)
# ---------------------------------------------------------------------------

class ErroLeitura(Exception):
    pass


def _pasta_modelos():
    """Onde estão os arquivos do OCR quando o programa é um .exe (PyInstaller) ou roda do código."""
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "modelos_ocr")):
        return os.path.join(base, "modelos_ocr")
    aqui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos_ocr")
    return aqui if os.path.isdir(aqui) else None


def disponivel():
    """(True, '') se este computador consegue ler notas escaneadas; senão (False, motivo)."""
    try:
        import numpy  # noqa: F401
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as erro:
        return False, "falta um componente do programa ({})".format(erro)
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception as erro:
        return False, "o leitor de notas (OCR) não está instalado neste computador ({})".format(erro)
    return True, ""


def endireitar(imagem):
    """
    Corrige a inclinação de uma página escaneada: acha o ângulo em que as linhas de texto ficam
    mais "marcadas" (o escaneamento torto borra as linhas). Devolve (imagem_endireitada, ângulo).
    """
    import numpy as np
    from PIL import Image

    cinza = imagem.convert("L")
    pequena = cinza.resize((800, max(1, round(800 * cinza.height / cinza.width))), Image.BILINEAR)

    def nitidez(angulo):
        r = pequena.rotate(angulo, resample=Image.BILINEAR, fillcolor=255)
        escuro = (np.asarray(r) < 140).sum(axis=1).astype(float)
        return float(np.var(np.diff(escuro)))

    melhor = max((a / 4.0 for a in range(-16, 17)), key=nitidez)            # -4° a +4°, passo de 0,25°
    refino = max((melhor + a / 20.0 for a in range(-5, 6)), key=nitidez)    # passo de 0,05°
    if abs(refino) < 0.08:
        return cinza, 0.0
    return cinza.rotate(refino, resample=Image.BICUBIC, fillcolor=255), refino


class LeitorNota:
    """Lê um PDF de nota fiscal e devolve os itens. Crie um só e reaproveite (carregar o OCR demora)."""

    def __init__(self):
        self._motor = None

    def _ocr(self):
        if self._motor is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            params = {"Rec.lang_type": LangRec.LATIN, "Rec.model_type": ModelType.MOBILE,
                      "Rec.ocr_version": OCRVersion.PPOCRV5, "Global.use_cls": False,
                      "Global.log_level": "critical"}
            pasta = _pasta_modelos()
            if pasta:                                           # modelos que vão junto com o programa
                for nome, chave in (("det.onnx", "Det.model_path"), ("rec.onnx", "Rec.model_path")):
                    caminho = os.path.join(pasta, nome)
                    if os.path.exists(caminho):
                        params[chave] = caminho
            self._motor = RapidOCR(params=params)
        return self._motor

    def _palavras(self, imagem, deslocamento=(0, 0), escala=1.0):
        import numpy as np
        r = self._ocr()(np.asarray(imagem.convert("RGB")))
        if r is None or getattr(r, "boxes", None) is None:
            return []
        saida = []
        for caixa, texto, _nota in zip(r.boxes, r.txts, r.scores):
            xs, ys = [p[0] for p in caixa], [p[1] for p in caixa]
            saida.append(Palavra(texto, min(xs) / escala + deslocamento[0], min(ys) / escala + deslocamento[1],
                                 (max(xs) - min(xs)) / escala, (max(ys) - min(ys)) / escala))
        return saida

    def ler(self, caminho_pdf, progresso=None, cancelado=None):
        """
        Devolve {"itens": [...], "notas": [{"rotulo": ...}], "paginas": n}. `progresso(texto, parte, total)` é
        chamado a cada passo; `cancelado()` devolve True se a pessoa desistiu.
        """
        ok, motivo = disponivel()
        if not ok:
            raise ErroLeitura("Não foi possível ler a nota: " + motivo + ".")
        import pypdfium2 as pdfium

        def avisar(texto, parte, total):
            if progresso:
                progresso(texto, parte, total)

        try:
            pdf = pdfium.PdfDocument(caminho_pdf)
        except Exception as erro:
            raise ErroLeitura("Não consegui abrir o PDF ({}).".format(erro))
        n = min(len(pdf), 12)
        itens, notas = [], []
        passos = n * 2
        for i in range(n):
            if cancelado and cancelado():
                raise ErroLeitura("Leitura cancelada.")
            avisar("Preparando a página {} de {}…".format(i + 1, n), i * 2, passos)
            imagem = pdf[i].render(scale=200 / 72).to_pil()
            imagem, _angulo = endireitar(imagem)
            avisar("Lendo a página {} de {} (leva cerca de 1 minuto)…".format(i + 1, n), i * 2 + 1, passos)
            palavras = self._palavras(imagem)
            achados, colunas = extrair_itens(palavras)                  # nota fiscal (DANFE)?
            if colunas is not None:
                dados, meia_altura = dados_da_nota(palavras), 19
                if not any(n_["numero"] and n_["numero"] == dados["numero"] for n_ in notas):
                    notas.append(dados)
            else:                                                       # ou lista simples (ITEM | DESCRIÇÃO | UND ...)
                achados, cab = extrair_itens_lista(palavras)
                if cab is None:
                    continue
                dados, meia_altura = dados_da_lista(palavras, cab), 22
                notas.append(dados)
            for it in achados:
                it["pagina"] = i + 1
                if colunas is not None:
                    self._completar(imagem, colunas, it)
                x1, x2 = it["caixa"]
                it["imagem"] = imagem.crop((max(0, int(x1)), max(0, int(it["y"] - meia_altura)),
                                            min(imagem.width, int(x2)), min(imagem.height, int(it["y"] + meia_altura))))
            itens += achados
        avisar("Pronto.", passos, passos)
        if not itens:
            raise ErroLeitura("Não encontrei uma tabela de produtos neste PDF (nota fiscal ou lista de material). "
                              "Se a página está de cabeça para baixo ou muito escura, escaneie de novo.")
        return {"itens": itens, "notas": notas, "paginas": n}

    def _completar(self, imagem, colunas, item):
        """Linha com descrição/unidade/quantidade em falta: lê só aquela faixa da nota, ampliada."""
        faltam_desc = not item["descricao"]
        faltam_unid = item["unidade_nota"] is None
        faltam_qtd = item["quantidade"] is None
        if not (faltam_desc or faltam_unid or faltam_qtd):
            return
        y = item["y"]
        if faltam_desc:
            faixa = (colunas.inicio_descricao - 10, y - 20, colunas.fim_descricao + 5, y + 20)
            ps = self._palavras(self._ampliar(imagem.crop([int(v) for v in faixa])),
                                (faixa[0] - 40 / 2.0, faixa[1] - 40 / 2.0), 2.0)
            texto = limpar_descricao(_juntar(sorted(ps, key=lambda p: p.x)))
            if len(texto) >= 4:
                item["descricao"] = texto
                item["avisos"] = [a for a in item["avisos"] if "descrição" not in a] + ["descrição lida de novo, confira"]
        if faltam_unid or faltam_qtd:
            faixa = (colunas.esq_unid - 30, y - 20, colunas.esq_valor_unit - 6, y + 20)
            ps = self._palavras(self._ampliar(imagem.crop([int(v) for v in faixa]), 3),
                                (faixa[0] - 40 / 3.0, faixa[1] - 40 / 3.0), 3.0)
            if faltam_unid:
                for p in sorted(ps, key=lambda p: p.x):
                    u, nome = normalizar_unidade_nota(p.t)
                    if u and p.x < colunas.inicio_qtd:
                        item["unidade_nota"], item["unidade"] = u, nome
                        item["avisos"] = [a for a in item["avisos"] if "unidade" not in a]
                        break
            if faltam_qtd:
                for p in sorted(ps, key=lambda p: p.x):
                    q = ler_quantidade_nota(p.t)
                    if q and p.x >= colunas.inicio_qtd - 5:
                        item["quantidade"] = q
                        item["avisos"] = [a for a in item["avisos"] if "quantidade não foi lida" not in a]
                        break
        valor_u, valor_t, q = item["valor_unitario"], item["valor_total"], item["quantidade"]
        if q and valor_u and valor_t and abs(q * valor_u - valor_t) > max(0.05, valor_t * 0.01):
            if "quantidade não bate com o valor da nota" not in item["avisos"]:
                item["avisos"].append("quantidade não bate com o valor da nota")

    @staticmethod
    def _ampliar(img, fator=2):
        from PIL import Image
        g = img.convert("L").resize((img.width * fator, img.height * fator), Image.LANCZOS)
        fundo = Image.new("L", (g.width + 80, g.height + 80), 255)          # margem branca: o OCR precisa de respiro
        fundo.paste(g, (40, 40))
        return fundo
