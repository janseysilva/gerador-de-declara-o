# -*- coding: utf-8 -*-
"""
Monta o `catalogo_federal.json` (o banco de materiais que vai junto com o programa).

De onde vêm os dados: Catálogo de Materiais (CATMAT) do Governo Federal, pela API de Dados Abertos do
Compras.gov.br (https://dadosabertos.compras.gov.br, módulo "modulo-material"). É dado público e aberto.
Usamos o nível "padrão descritivo de material" (PDM): o nome genérico do produto ("Tesoura escolar",
"Papel crepom", "Detergente"). Só as classes de interesse de uma escola entram, só os padrões ATIVOS.

Este script NÃO faz parte do programa: roda só quando se quer atualizar o catálogo.

    python ferramentas/montar_catalogo_federal.py            # baixa da internet e grava catalogo_federal.json

O CATMAT descreve a CLASSE do produto, não a marca nem a variação ("sabão em pó" e "em barra" são um só
padrão). Por isso o catálogo tem também:
  - APELIDOS de busca (quem digita "sulfite" acha "Papel A4");
  - COMPLEMENTOS: produtos comuns em escola que o CATMAT não traz com esse nome (folha de EVA, papel toalha...).
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import date

BASE_API = "https://dadosabertos.compras.gov.br/modulo-material/"
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(os.path.dirname(AQUI), "catalogo_federal.json")

# classe do CATMAT -> tipo de estoque onde o produto aparece ("limpeza", "pedagogico" ou "ambos").
CLASSES = {
    # limpeza e higiene
    7910: "limpeza",      # enceradeiras e aspiradores de pó
    7920: "limpeza",      # vassouras, escovas, rodos, esponjas e esfregões
    7930: "limpeza",      # compostos e preparados para limpeza e polimento
    8520: "limpeza",      # sabonetes, artigos para barbear e dentifrícios
    8530: "limpeza",      # artigos para higiene pessoal
    8540: "limpeza",      # artigos de papel para higiene (papel higiênico, guardanapo)
    7240: "limpeza",      # recipientes de uso doméstico (balde, lixeira, dispenser)
    9320: "limpeza",      # artigos de borracha (luva de borracha...)
    6840: "limpeza",      # pesticidas e desinfetantes (só alguns, ver FILTRO_CLASSE)
    8105: "ambos",        # sacos e bolsas (saco de lixo, envelope plástico)
    7350: "ambos",        # louça e artigos de mesa (copo e prato descartáveis)
    # material pedagógico e de escritório
    7510: "pedagogico",   # artigos para escritório
    7520: "pedagogico",   # acessórios e dispositivos para escritório
    7530: "pedagogico",   # formulários oficiais
    7540: "pedagogico",   # formulários padronizados (livro ata, livro de ponto)
    7610: "pedagogico",   # livros e folhetos (livro didático)
    7810: "pedagogico",   # equipamento para atletismo e desporto
    7820: "pedagogico",   # jogos, brinquedos
    7830: "pedagogico",   # equipamento para ginástica e recreação
    8010: "pedagogico",   # tintas, vernizes
    8020: "pedagogico",   # pincel para artistas
    8040: "pedagogico",   # adesivos (cola, fita)
    9310: "pedagogico",   # papéis e papelões (cartolina, crepom, sulfite)
    8305: "pedagogico",   # tecidos (só TNT, feltro... ver FILTRO_CLASSE)
}

# Classes grandes demais ou com muita coisa que não é de escola: só estes nomes (comparados sem acento/maiúscula).
FILTRO_CLASSE = {
    6840: {"detergente saneante", "hipoclorito de sodio", "inseticida", "detergente enzimatico"},
    8305: {"tnt", "feltro", "tecido", "tela de pintura", "pelucia - tecido", "retalho tecido"},
    9320: {"luva borracha"},
    8105: {"saco", "saco plastico lixo", "sacola", "envelope plastico", "envelope plastico aba adesiva", "malote"},
    7350: {"copo", "copo de vidro", "copo descartavel", "xicara", "xicara descartavel", "prato", "prato porcelana",
           "canudo refresco", "palito", "tigela", "caneca", "caneca de plastico", "bandeja de refeicao",
           "suporte de garrafao de agua", "pote alimentos", "pote vidro", "tampa copo"},
}

# Padrões do CATMAT que NÃO entram porque um complemento do programa os substitui (nome mais comum no dia a dia).
IGNORAR_CATMAT = {"sabao exceto toucador", "sabao barra", "sabao po", "desinfetante saneante", "toalha de papel",
                  "papel a4", "papel cartao olimpo", "papel cartao pergamenata", "papel cartao pergamenata naturale",
                  "papel cartao thorchons"}

# Palavras que tiram um padrão do catálogo: o CATMAT atende o governo inteiro (pesca, oficina, veículo, academia,
# gráfica...) e aqui só interessa o que uma escola guarda em estoque. Comparadas por palavra inteira, sem acento.
EXCLUIR = """
cabelo cabelos barba barbear unha manicure pedicure esmalte navalha pente prendedor tintura menstrual absorvente
jateamento injetor microcomputador veiculo veiculos automotiv automotiva pneu calcado piscina molde rolha
alicate agulha locao creme condicionador talco corte banho graxa raspador silicone haste equipamento aparelho
alisar pesca anzol arpao carretilha molinete tarrafa panagem rede esteira haltere anilha peso bicicleta sueco
elastica pancada patim patinete triciclo velocipede parque escorregadeira escorregador balanco gangorra taco
antena poste barreira plataforma catraca raia antimarola estante boxe goleiro esgrima munhequeira joelheira
cotoveleira tornozeleira caneleira genital colete natacao prancha hidroginastica cinto cinturao dardo alvo
arremesso podio premiacao sinuca pebolim futmesa squash polo medicinal receituario laudo ingresso fiscal producao
vale requisicao laborativa amostras digital papilar tatuagem hidraulica hidraulico motor vulcanizacao industrial
serigrafica serigrafico ofsete mimeografo duplicador teleimpressora escrever calcular registradora protocoladora
fax disquete heliografico termosensivel eletrossensibilizado cheque ambassador carmen chambril gainsborough
lorenzo marrakech opaline westerledger westerpost westerprint martelado polen quest premium photo polyester
indigo debre cartucho joystick indutor algarismo ferro canteador lixamento estencil decalque enegrecedor emulsao
fixador diluente coagulante corante amaciador pigmento reagente redutor removedor solvente selador selante
verniz corrida maritima niveladora polir poncar oleo aguarras secante pistola revestimento asfaltica tingidor
trincha predial laca aluminio primer condutiva fosforescente tecnico publicacao regulamento passaporte soc estat
esportiva esportivo desporto basquetebol futebol futsal handebol voleibol tenis ginastica condicionamento
ginasio diversao flexivel aspiracao cachepo funil regador costura processo prontuario protocolo recibo despacho
sinete olivetti copiadora teclado telefone datador pericial registrador speed supremo visita balsamo envernizamento
canaleta mosquetao visor urna zarcao targeta palmar maca bibliocanto esporte r encadernador impressora fac-simile
""".split()

# Unidade usual de alguns produtos (o resto fica "unidade"; a pessoa muda no cadastro se quiser).
UNIDADE_POR_NOME = {
    "fita adesiva": "rolo", "fita crepe": "rolo", "fita dupla face": "rolo", "barbante": "rolo",
    "papel higienico": "rolo", "giz": "caixa", "giz cera": "caixa", "caixa giz": "caixa", "clipe": "caixa",
    "grampo grampeador": "caixa", "percevejo": "caixa", "elastico de latex": "pacote", "cartolina": "folha",
    "papel cartao": "folha", "papel crepom": "folha", "papel crepel": "folha", "papel seda": "folha",
    "papel kraft": "folha", "papel pardo": "folha", "papel vegetal": "folha", "papel celofane": "folha",
    "papel espelho": "folha", "papel camurca": "folha", "papel dobradura": "pacote", "papel color set": "pacote",
    "papel color plus": "pacote", "papel jornal": "folha", "papel laminado": "folha", "tnt": "metro",
    "feltro": "metro", "tecido": "metro", "agua sanitaria": "litro", "alcool etilico limpeza de ambientes": "litro",
    "lapis de cor": "caixa", "caneta hidrografica": "caixa", "sabao liquido": "litro", "detergente": "frasco", "guardanapo de papel": "pacote", "copo descartavel": "pacote",
    "prato descartavel": "pacote", "palito": "pacote", "canudo refresco": "pacote", "saco plastico lixo": "pacote",
    "sacola": "pacote", "luva borracha": "par", "touca descartavel": "pacote", "papel toalha": "pacote",
}

SIGLAS = {"tnt", "eva", "pvc", "usb", "led", "cd", "dvd", "epi", "pet", "pdf", "mdf", "tv", "cd-r", "dvd-r",
          "a0", "a1", "a2", "a3", "a4", "a5", "b5"}

# Jeitos comuns de falar, para a busca achar o padrão do CATMAT (chave = nome já humanizado, sem acento, minúsculo).
APELIDOS = {
    "papel a4": ["sulfite", "papel sulfite", "resma", "papel oficio", "papel branco"],
    "papel a3": ["sulfite a3"],
    "desinfetante saneante": ["desinfetante", "pinho sol", "lisoforme"],
    "detergente": ["detergente liquido", "lava loucas", "lava-loucas", "detergente neutro"],
    "saco plastico lixo": ["saco de lixo", "saco para lixo", "sacola de lixo", "saco lixo"],
    "massa modelar": ["massa de modelar"],
    "sabao liquido": ["sabao liquido", "sabao em gel"],
    "tinta guache": ["guache", "tinta guache"],
    "giz cera": ["giz de cera", "giz de cera"],
    "caneta hidrografica": ["hidrocor", "canetinha", "caneta hidrocor"],
    "papel higienico": ["papel higienico", "papel de banheiro"],
    "hipoclorito de sodio": ["cloro", "agua sanitaria"],
    "agua sanitaria": ["cloro", "agua sanitaria"],
    "papel crepom": ["crepom", "papel crepe"],
    "papel cartao": ["cartao", "papel cartao"],
    "copo descartavel": ["copo plastico", "copo de plastico", "copinho"],
    "xicara descartavel": ["copinho de cafe", "copo de cafe"],
    "tesoura escolar": ["tesoura", "tesoura sem ponta"],
    "cola": ["cola branca", "cola escolar"],
    "cola bastao": ["cola em bastao", "bastao de cola"],
    "pincel": ["pincel escolar"],
    "fita adesiva": ["durex", "fita durex", "fita transparente"],
    "corda de pular": ["corda"],
    "apagador quadro branco": ["apagador", "apagador de quadro"],
    "esponja limpeza": ["esponja", "esponja de cozinha", "bombril"],
    "vassoura": ["vassoura", "vassoura de piacava"],
    "rodo": ["rodo de piso", "rodo de chao"],
    "pano de chao": ["pano de chao", "pano de piso", "saco de chao"],
    "pano limpeza": ["pano", "pano de prato", "pano multiuso"],
    "balde": ["balde de plastico"],
    "lixeira": ["lixeira", "cesto de lixo"],
    "luva borracha": ["luva de limpeza", "luva de borracha", "luva de latex"],
    "aspirador po": ["aspirador"],
    "enceradeira": ["lustradeira"],
}

# Nomes do CATMAT que ficam estranhos para quem usa no dia a dia: como mostrar.
NOME_BONITO = {
    "sabao exceto toucador": "Sabão (em pó, em barra ou pastoso)",
    "solucao limpeza multiuso": "Limpador multiuso",
    "aspirador po": "Aspirador de pó",
    "pano limpeza": "Pano de limpeza",
    "esponja limpeza": "Esponja de limpeza",
    "saco plastico lixo": "Saco plástico para lixo",
    "limpador impurezas": "Limpador de impurezas",
    "pa coletora lixo": "Pá coletora de lixo",
    "giz cera": "Giz de cera",
    "lapis cera": "Lápis de cera",
    "massa modelar": "Massa de modelar",
    "pintura dedo": "Tinta para pintura a dedo",
    "papel cartolina": "Cartolina",
    "caneta esferografica": "Caneta esferográfica",
    "caneta marca-texto": "Caneta marca-texto",
    "cola bastao": "Cola em bastão",
    "limpa-vidro": "Limpa-vidros",
    "esfregao": "Esfregão",
    "escova limpeza geral": "Escova de limpeza geral",
}

# Produtos comuns em escola que o CATMAT não traz com este nome: (nome, unidade, tipo, apelidos).
COMPLEMENTOS = [
    ("Folha de EVA", "folha", "pedagogico", ["eva", "e.v.a", "placa de eva", "papel eva"]),
    ("Glitter", "pacote", "pedagogico", ["gliter", "purpurina", "brilho"]),
    ("Cola colorida", "unidade", "pedagogico", ["cola glitter"]),
    ("Cola em bastão", "unidade", "pedagogico", ["cola bastao", "bastao de cola", "cola em bastao"]),
    ("Lantejoula", "pacote", "pedagogico", ["lantejoulas"]),
    ("Olho móvel", "pacote", "pedagogico", ["olhinho", "olhos moveis"]),
    ("Palito de picolé", "pacote", "pedagogico", ["palito de sorvete", "palito"]),
    ("Palito de churrasco", "pacote", "pedagogico", []),
    ("Pompom", "pacote", "pedagogico", ["pom pom", "pompons"]),
    ("Chenille", "pacote", "pedagogico", ["limpador de cachimbo", "arame felpudo"]),
    ("Tinta para tecido", "unidade", "pedagogico", ["tinta de tecido"]),
    ("Tinta para pintura a dedo", "unidade", "pedagogico", ["tinta a dedo", "tinta de dedo"]),
    ("Papel sulfite colorido", "resma", "pedagogico", ["papel colorido", "sulfite colorido"]),
    ("Papel A4 branco 75 g", "resma", "pedagogico", ["sulfite", "resma", "papel sulfite", "papel a4"]),
    ("Papel A4 branco 90 g", "resma", "pedagogico", ["sulfite 90", "papel sulfite 90", "papel a4 90"]),
    ("Papel A3 branco 75 g", "resma", "pedagogico", ["sulfite a3", "papel sulfite a3", "papel a3"]),
    ("Pincel escolar", "unidade", "pedagogico", ["pincel", "pincel chato", "pincel redondo", "pincel de pintura"]),
    ("Papel laminado", "folha", "pedagogico", ["papel laminado"]),
    ("Fita crepe", "rolo", "pedagogico", ["durex de papel"]),
    ("Fita dupla face", "rolo", "pedagogico", []),
    ("Elástico de látex", "pacote", "pedagogico", ["elastico de dinheiro", "elastiquinho"]),
    ("Barbante", "rolo", "pedagogico", []),
    ("Pasta com elástico", "unidade", "pedagogico", ["pasta aba elastica"]),
    ("Papel toalha", "pacote", "limpeza", ["papel toalha interfolhado", "papel toalha bobina"]),
    ("Papel higiênico rolão", "rolo", "limpeza", ["rolao", "papel higienico rolao"]),
    ("Sabonete líquido", "frasco", "limpeza", ["sabonete", "sabonete liquido", "saboneteira refil"]),
    ("Álcool em gel", "frasco", "limpeza", ["alcool gel", "alcool 70", "alcool"]),
    ("Álcool líquido 70%", "litro", "limpeza", ["alcool 70", "alcool liquido"]),
    ("Água sanitária", "litro", "limpeza", ["cloro", "agua sanitaria"]),
    ("Desinfetante", "frasco", "limpeza", ["pinho", "lavanda", "eucalipto", "desinfetante floral"]),
    ("Sabão em pó", "pacote", "limpeza", ["sabao em po", "omo", "ype"]),
    ("Sabão em barra", "pacote", "limpeza", ["sabao em barra", "barra de sabao"]),
    ("Saco de lixo 100 L", "pacote", "limpeza", ["saco de lixo", "saco 100 litros"]),
    ("Saco de lixo 50 L", "pacote", "limpeza", ["saco de lixo", "saco 50 litros"]),
    ("Saco de lixo 30 L", "pacote", "limpeza", ["saco de lixo", "saco 30 litros"]),
    ("Saco de lixo 20 L", "pacote", "limpeza", ["saco de lixo", "saco 20 litros"]),
    ("Saco de lixo 200 L", "pacote", "limpeza", ["saco de lixo", "saco 200 litros"]),
    ("Luva descartável", "caixa", "limpeza", ["luva de procedimento", "luva latex descartavel"]),
    ("Máscara descartável", "caixa", "limpeza", ["mascara", "mascara tripla"]),
    ("Touca descartável", "pacote", "limpeza", ["touca"]),
    ("Pano multiuso", "rolo", "limpeza", ["perfex", "pano perfex"]),
    ("Prato descartável", "pacote", "ambos", ["prato de plastico", "prato de isopor"]),
    ("Garfo descartável", "pacote", "ambos", []),
    ("Colher descartável", "pacote", "ambos", []),
    ("Pincel para quadro branco", "unidade", "pedagogico", ["marcador de quadro branco", "caneta de quadro branco",
                                                           "pincel de quadro branco", "marcador quadro branco"]),
    ("Guardanapo de papel", "pacote", "ambos", ["guardanapo"]),
    ("Lâmpada LED", "unidade", "limpeza", ["lampada"]),
    ("Pilha AA", "unidade", "pedagogico", ["pilha pequena", "pilha"]),
    ("Pilha AAA", "unidade", "pedagogico", ["pilha palito", "pilha"]),
]


# Cores na ordem em que mais aparecem numa escola (a pesquisa mostra as primeiras). Masculino -> feminino.
CORES = ["branco", "azul", "amarelo", "verde", "vermelho", "rosa", "preto", "laranja", "roxo", "marrom",
         "cinza", "bege", "lilás", "azul claro", "verde claro"]
METALICAS = ["dourado", "prateado"]
FEMININO = {"branco": "branca", "amarelo": "amarela", "vermelho": "vermelha", "preto": "preta", "roxo": "roxa",
            "dourado": "dourada", "prateado": "prateada"}


def cores(genero, so=None, metalicas=False):
    """Os rótulos de cor de um produto ("m" = Papel crepom branco; "f" = Cartolina branca)."""
    lista = list(so) if so else CORES + (METALICAS if metalicas else [])
    return [FEMININO.get(c, c) if genero == "f" else c for c in lista]


QUATRO = ("azul", "preto", "vermelho", "verde")


def frascos(*tamanhos):
    """Tamanhos de líquido: o estoque conta FRASCOS, então a variação é em "frasco" (o produto em si pode ser em litro)."""
    return [(t, "frasco") for t in tamanhos]

# Produtos que a pessoa precisa separar por cor, tamanho ou cheiro: o nome do produto (sem acento, minúsculo,
# como fica no catálogo) -> as variações. Cada uma vira uma opção própria na pesquisa ("Cartolina azul").
# O produto sem variação ("Cartolina") continua existindo, para quem não quer separar.
VARIACOES = {
    "cartolina": cores("f"),
    "tnt": cores("m"),
    "folha de eva": cores("f", metalicas=True),
    "feltro": cores("m"),
    "papel crepom": cores("m"),
    "papel cartao": cores("m"),
    "papel celofane": cores("m"),
    "papel seda": cores("m"),
    "papel laminado": cores("m", metalicas=True),
    "papel espelho": cores("m", metalicas=True),
    "papel camurca": cores("m"),
    "papel dobradura": cores("m"),
    "papel sulfite colorido": cores("m"),
    "tinta guache": [("kit 6 cores", "caixa"), ("kit 12 cores", "caixa")] + cores("f"),
    "tinta para tecido": cores("f"),
    "tinta acrilica": cores("f"),
    "tinta para pintura a dedo": cores("f"),
    "cola colorida": cores("f", metalicas=True),
    "massa de modelar": [("kit 6 a 12 cores", "caixa")] + cores("f"),
    "chenille": cores("m"),
    "pompom": cores("m"),
    "glitter": cores("m", metalicas=True),
    "caneta esferografica": cores("f", so=("azul", "preto", "vermelho", "verde")),
    "caneta marca-texto": cores("f", so=("amarelo", "verde", "rosa", "laranja", "azul")),
    "pincel atomico": cores("m", so=QUATRO),
    "pincel para quadro branco": cores("m", so=QUATRO),
    # kits e modelos (a faixa "6 a 12 cores" é a padrão do mercado para o uso escolar; jumbo = grosso, para os pequenos)
    "lapis de cor": ["6 a 12 cores", "24 cores", "36 cores", "48 cores", "72 cores", "jumbo 6 a 12 cores"],
    "giz de cera": ["6 a 12 cores", "24 cores", "jumbo 6 a 12 cores"],
    "caneta hidrografica": ["6 a 12 cores", "24 cores", "48 cores", "ponta grossa 6 a 12 cores"],
    "lapis preto": ["nº 2", "jumbo", "triangular", "nº 1"],
    "cola": ["branca 90 g", "branca 40 g", "branca 500 g", "branca 1 kg"],
    "cola em bastao": ["10 g", "20 g", "40 g"],
    "tesoura": ["escolar sem ponta", "escolar com ponta", "grande"],
    "caderno": ["brochura 96 folhas", "brochura 48 folhas", "brochura 200 folhas", "espiral 96 folhas",
                "espiral 200 folhas", "de desenho", "de caligrafia"],
    "fita adesiva": ["transparente larga", "transparente estreita", "marrom"],
    "fita crepe": ["18 mm", "24 mm", "48 mm"],
    "pincel escolar": ["nº 2", "nº 6", "nº 10", "nº 14", "chato nº 10"],
    "grampo grampeador": ["26/6", "23/8"],
    # limpeza: o tamanho vai no NOME, no mesmo formato que o programa usa nas notas ("500 g", "1 kg", "2 L"),
    # porque embalagens de tamanhos diferentes são materiais diferentes no estoque
    "sabao em po": ["500 g", "1 kg", "250 g", "2 kg"],
    "sabao em barra": ["200 g", "5 un"],
    "sabao liquido": frascos("1 L", "2 L", "3 L", "5 L", "500 ml"),
    "detergente": frascos("500 ml", "5 L") + ["neutro", "coco", "limão", "maçã"],
    "desinfetante": frascos("2 L", "1 L", "500 ml", "5 L") + ["lavanda", "eucalipto", "pinho", "floral", "citronela", "talco"],
    "agua sanitaria": frascos("2 L", "1 L", "5 L"),
    "alcool em gel": frascos("500 ml", "1 L", "5 L"),
    "alcool liquido 70%": frascos("1 L", "500 ml", "5 L"),
    "amaciante de roupa": frascos("2 L", "5 L"),
    "limpador multiuso": frascos("500 ml", "2 L", "5 L"),
    "limpa-vidros": frascos("500 ml", "1 L"),
    "sabonete liquido": frascos("500 ml", "1 L", "5 L"),
    "inseticida": ["aerosol 300 ml", "aerosol 450 ml"],
    "vassoura": ["de piaçava", "de nylon", "de pelo", "de palha"],
    "rodo": ["30 cm", "40 cm", "60 cm"],
    "balde": ["10 L", "12 L", "20 L"],
    "lixeira": ["15 L", "50 L", "100 L"],
    "flanela": cores("f", so=("branco", "amarelo", "laranja")),
    "luva descartavel": ["P", "M", "G"],
    "luva borracha": ["P", "M", "G"],
    "copo descartavel": ["50 ml", "180 ml", "200 ml", "300 ml", "400 ml"],
    "papel toalha": ["interfolhado", "bobina"],
    "papel higienico": ["folha simples", "folha dupla"],
}


# ---------------------------------------------------------------------- utilidades

def sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def chave(texto):
    return re.sub(r"\s+", " ", sem_acento(texto).lower().replace('"', " ")).strip()


def pegar(endpoint, **filtros):
    consulta = "&".join("{}={}".format(k, v) for k, v in filtros.items())
    erro = None
    for _ in range(5):
        try:
            pedido = urllib.request.Request(BASE_API + endpoint + "?" + consulta, headers={"accept": "application/json"})
            with urllib.request.urlopen(pedido, timeout=120) as r:
                return json.load(r)
        except Exception as e:                    # noqa: BLE001 - rede instável: tenta de novo
            erro = e
            time.sleep(4)
    raise erro


def todas_as_paginas(endpoint, **filtros):
    saida, pagina = [], 1
    while True:
        d = pegar(endpoint, pagina=pagina, tamanhoPagina=500, **filtros)
        saida += d["resultado"]
        if pagina >= d.get("totalPaginas", 1):
            return saida
        pagina += 1


# Palavrinhas que existem com e sem acento e NÃO devem ser "consertadas".
SEM_CONSERTO = {"a", "o", "e", "as", "os", "de", "da", "do", "em", "na", "no", "um", "uma", "para", "por", "com",
                "sem", "ou", "ao", "mais", "esta", "este", "ate", "ha", "la", "ja", "so", "pais", "tipo", "pelo",
                "pela", "sera", "ira", "uso", "ser"}


def montar_vocabulario(todos_os_nomes):
    """Palavra sem acento -> a forma com acento mais comum no próprio catálogo (conserta "LAPIS" -> "lápis")."""
    formas = defaultdict(Counter)
    for nome in todos_os_nomes:
        for palavra in re.findall(r"[A-Za-zÀ-ÿ]+", nome):
            formas[sem_acento(palavra).lower()][palavra.lower()] += 1
    vocab = {"po": "pó", "chao": "chão", "magica": "mágica", "acucar": "açúcar"}
    for base, contagem in formas.items():
        if base in SEM_CONSERTO or base in vocab or len(base) < 3:
            continue
        com_acento = [(f, n) for f, n in contagem.items() if f != base]
        if not com_acento:
            continue
        melhor, n_com = max(com_acento, key=lambda x: x[1])
        n_sem = contagem.get(base, 0)
        # o próprio CATMAT escreve a mesma palavra com e sem acento; só confia na forma acentuada se ela for
        # frequente (um "FÍTA" digitado errado uma vez não vale) ou se a palavra nunca aparece sem acento
        if n_sem == 0 or (n_com >= 2 and n_com >= 0.3 * n_sem):
            vocab[base] = melhor
    return vocab


def humanizar(nome, vocab):
    texto = re.sub(r"\s+", " ", nome.replace('"', " ")).strip()
    if chave(texto) in NOME_BONITO:
        return NOME_BONITO[chave(texto)]
    texto = re.sub(r"\(\s*", "(", texto)
    texto = re.sub(r"\s*\)", ")", texto)
    palavras = []
    for p in texto.split(" "):
        minuscula = p.lower()
        base = sem_acento(minuscula)
        if base in SIGLAS:
            palavras.append(base.upper())
            continue
        if re.fullmatch(r"[a-z]\d+", base):                       # A4, A3
            palavras.append(base.upper())
            continue
        # só conserta a palavra se ela veio sem nenhum acento
        if minuscula == base and base in vocab:
            minuscula = vocab[base]
        palavras.append(minuscula)
    saida = " ".join(palavras)
    return saida[:1].upper() + saida[1:]


_RE_EXCLUIR = re.compile(r"\b(?:{})\b".format("|".join(re.escape(w) for w in sorted(set(EXCLUIR), key=len, reverse=True))))


def excluido(nome):
    return bool(_RE_EXCLUIR.search(chave(nome)))


# ---------------------------------------------------------------------- montagem

def montar():
    print("Baixando os grupos e padrões do CATMAT (Compras.gov.br)...")
    grupos = [g["codigoGrupo"] for g in todas_as_paginas("1_consultarGrupoMaterial")]
    todos = []
    for g in grupos:
        todos += todas_as_paginas("3_consultarPdmMaterial", codigoGrupo=g)
        print("  grupo", g, "->", len(todos), "padrões", flush=True)
    vocab = montar_vocabulario(p["nomePdm"] for p in todos)

    vistos, entradas = {}, []
    for p in todos:
        classe = p["codigoClasse"]
        if classe not in CLASSES or not p.get("statusPdm"):
            continue
        if classe in FILTRO_CLASSE and chave(p["nomePdm"]) not in FILTRO_CLASSE[classe]:
            continue
        if chave(p["nomePdm"]) in IGNORAR_CATMAT or excluido(p["nomePdm"]):
            continue
        nome = humanizar(p["nomePdm"], vocab)
        k = chave(nome)
        if k in vistos:
            continue
        apelidos = APELIDOS.get(chave(p["nomePdm"])) or APELIDOS.get(k, [])
        unidade = UNIDADE_POR_NOME.get(chave(p["nomePdm"])) or UNIDADE_POR_NOME.get(k, "unidade")
        entradas.append({"id": "fed-{}".format(p["codigoPdm"]), "nome": nome, "unidade": unidade,
                         "tipo": CLASSES[classe], "categoria": humanizar(p["nomeClasse"], vocab),
                         "apelidos": apelidos, "catmat": p["codigoPdm"], "origem": "catmat"})
        vistos[k] = len(entradas) - 1

    for nome, unidade, tipo, apelidos in COMPLEMENTOS:
        k = chave(nome)
        if k in vistos:                                           # o CATMAT já tem: só acrescenta os apelidos e a unidade
            e = entradas[vistos[k]]
            e["unidade"] = unidade
            e["apelidos"] = sorted(set(e["apelidos"]) | set(apelidos))
            continue
        entradas.append({"id": "comp-{}".format(re.sub(r"[^a-z0-9]+", "-", k).strip("-")), "nome": nome,
                         "unidade": unidade, "tipo": tipo, "categoria": "Complemento do programa",
                         "apelidos": apelidos, "catmat": None, "origem": "complemento"})
        vistos[k] = len(entradas) - 1

    # variações: cada cor, tamanho ou cheiro vira uma opção própria ("Cartolina azul"), logo depois do produto
    for e in entradas:
        e["grupo"], e["ordem"] = chave(e["nome"]), 0
    por_chave = {chave(e["nome"]): e for e in entradas}
    novas = []
    for k_base, rotulos in VARIACOES.items():
        base = por_chave.get(k_base)
        if base is None:
            print("AVISO: produto sem base para variações:", k_base)
            continue
        for n, rotulo in enumerate(rotulos, 1):
            unidade = base["unidade"]
            if isinstance(rotulo, tuple):                  # ("kit 12 cores", "caixa"): a variação tem unidade própria
                rotulo, unidade = rotulo
            nome = "{} {}".format(base["nome"], rotulo)
            if chave(nome) in por_chave:
                continue
            apelidos = list(base["apelidos"])
            litros = re.fullmatch(r"(\d+(?:,\d+)?) L", rotulo)
            if litros:                                     # quem digita "2 litros" acha "2 L"
                apelidos.append("{} {} {}".format(base["nome"], litros.group(1), "litro" if litros.group(1) == "1" else "litros"))
            novas.append({"id": "{}-{}".format(base["id"], re.sub(r"[^a-z0-9]+", "-", chave(rotulo)).strip("-")),
                          "nome": nome, "unidade": unidade, "tipo": base["tipo"],
                          "categoria": base["categoria"], "apelidos": apelidos, "catmat": base["catmat"],
                          "origem": base["origem"], "grupo": k_base, "ordem": n, "variacao": rotulo})
    entradas += novas
    entradas.sort(key=lambda e: chave(e["nome"]))
    dados = {"fonte": "Catálogo de Materiais (CATMAT) - Governo Federal, Dados Abertos do Compras.gov.br "
                      "(https://dadosabertos.compras.gov.br), nível 'padrão descritivo de material', só padrões ativos; "
                      "mais complementos do programa.",
             "gerado_em": date.today().isoformat(), "entradas": entradas}
    with open(SAIDA, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dados, f, ensure_ascii=False, indent=0, separators=(",", ":"))
    contagem = Counter(e["tipo"] for e in entradas)
    print("Gravado", SAIDA, "-", len(entradas), "produtos:", dict(contagem))


if __name__ == "__main__":
    sys.exit(montar())
