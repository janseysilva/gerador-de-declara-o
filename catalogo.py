# -*- coding: utf-8 -*-
"""
Catálogo de materiais do Declarações Escolares: os produtos que o programa já conhece, para reconhecer o que
vem nas notas fiscais e nas listas (PDF) mesmo escrito de outro jeito.

Cada produto do catálogo tem: nome padrão, unidade, tamanho da embalagem, outros jeitos de escrever (apelidos)
e os códigos que cada fornecedor usa na nota fiscal ("4448" = Almofada Pilot, para o fornecedor X).

Há dois catálogos: este (que RECONHECE e APRENDE o que vem nas notas) e o CatalogoFederal, mais abaixo (um banco
de materiais de fábrica, só para pesquisar e cadastrar na Entrada).

De onde vem:
  - catalogo_base.json: vai junto com o programa (montado a partir das listas de material de limpeza da SEMED);
  - o que o programa aprende: cada entrada confirmada pela pessoa grava novos produtos, apelidos e códigos,
    e cada resposta "Não juntar" grava que dois nomes são produtos diferentes.

O que foi aprendido fica na pasta do estoque (um arquivo por computador, como o estoque), então os dois
computadores da escola dividem o catálogo sem um apagar o do outro.
"""

import json
import os
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta

import leitor_nota as ln


def caminho_base():
    """O catálogo que vai com o programa (ao lado do .py, ou dentro do .exe)."""
    pasta = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(pasta, "catalogo_base.json")


def caminho_federal():
    """O catálogo federal que vai com o programa (ao lado do .py, ou dentro do .exe)."""
    pasta = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(pasta, "catalogo_federal.json")


def _normalizar(texto):
    """Minúsculas, sem acento e com espaços simples (a mesma conta de estoque.normalizar)."""
    sem = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem.lower()).strip()


def _palavras(texto_normalizado):
    """As palavras de um texto já normalizado; hífen e barra separam ("limpa-vidros" = "limpa" + "vidros")."""
    return [p for p in re.split(r"[\s\-/]+", texto_normalizado) if p]


class CatalogoFederal:
    """
    O banco de materiais que vem de fábrica: os padrões do Catálogo de Materiais (CATMAT) do Governo Federal que
    interessam a uma escola, mais alguns complementos do programa (folha de EVA, papel toalha...). Só LEITURA:
    serve para a pessoa achar o material digitando, em vez de cadastrar tudo à mão. Quem escolhe um item daqui
    na Entrada o cadastra no estoque (com o nome e a unidade do catálogo) na hora de adicionar à lista.
    Cada produto tem nome, unidade usual, tipo (limpeza, pedagogico ou ambos) e apelidos de busca ("sulfite" acha
    "Papel A4"). O que a pessoa separa por cor, tamanho ou cheiro tem uma opção para cada variação ("Cartolina
    azul", "TNT preto", "Luva descartável M"). Montado por ferramentas/montar_catalogo_federal.py.
    """

    def __init__(self, arquivo=None):
        self.arquivo = arquivo if arquivo is not None else caminho_federal()
        self.entradas = []
        self._texto = []
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                self.entradas = json.load(f).get("entradas", [])
        except (OSError, ValueError, AttributeError):
            self.entradas = []                                  # sem o arquivo o programa funciona, só sem sugestões
        for e in self.entradas:
            e.setdefault("unidade", "unidade")
            e.setdefault("apelidos", [])
            nome, apelidos = _normalizar(e["nome"]), _normalizar(" ".join(e["apelidos"]))
            self._texto.append((nome, apelidos, tuple(_palavras(nome + " " + apelidos)), tuple(_palavras(nome))))

    def __len__(self):
        return len(self.entradas)

    def buscar(self, texto, tipo=None, ja_cadastrados=(), limite=30):
        """
        Produtos cujo nome ou apelido tem todas as palavras digitadas. `tipo` é "limpeza" ou "pedagogico" (traz
        também os "ambos"); `ja_cadastrados` são nomes (normalizados) que o estoque já tem e não devem aparecer
        de novo. Os que começam com o que foi digitado vêm primeiro, depois os de nome, depois os só de apelido.
        """
        q = _normalizar(texto)
        termos = _palavras(q)
        if not termos:
            return []
        achados = []
        for e, (nome, apelidos, palavras, palavras_do_nome) in zip(self.entradas, self._texto):
            if tipo and e.get("tipo") not in (tipo, "ambos"):
                continue
            if nome in ja_cadastrados:
                continue
            # cada coisa digitada tem de ser o COMEÇO de uma palavra ("cola" não acha "sacola" nem "escolar")
            if not all(any(p.startswith(t) for p in palavras) for t in termos):
                continue
            if nome.startswith(q):
                posicao = 0
            elif all(any(p.startswith(t) for p in palavras_do_nome) for t in termos):
                posicao = 1
            else:
                posicao = 2
            ordem = e.get("ordem", 0)
            # os produtos vêm antes das suas variações (cor, tamanho): "Cartolina" e depois "Cartolina branca",
            # "Cartolina azul"...; as variações ficam na ordem em que o catálogo as lista (as cores mais comuns primeiro)
            achados.append((ordem > 0, posicao, e.get("origem") != "complemento", e.get("grupo", nome), ordem, nome, e))
        achados.sort(key=lambda x: x[:6])
        saida = []
        for *_, e in achados[:limite]:
            saida.append({"id": None, "do_catalogo": True, "nome": e["nome"], "unidade": e["unidade"],
                          "tipo": e.get("tipo", ""), "categoria": e.get("categoria", ""), "saldo": 0.0,
                          "situacao": ""})
        return saida


class Catalogo:
    def __init__(self, pasta, nome_pc, arquivo_base=None):
        self.pasta = pasta
        self.nome_pc = nome_pc
        self.arquivo_base = arquivo_base if arquivo_base is not None else caminho_base()
        self._ultimo = ""
        self.entradas = {}
        self.diferentes = set()
        self.recarregar()

    # ------------------------------------------------------------------ ler e gravar

    def recarregar(self):
        """Lê o catálogo de fábrica e depois o que cada computador aprendeu (na ordem em que foi gravado)."""
        self.entradas, self.diferentes = {}, set()
        try:
            with open(self.arquivo_base, encoding="utf-8") as f:
                for e in json.load(f):
                    self.entradas[e["id"]] = self._completar(dict(e))
        except (OSError, ValueError):
            pass
        eventos = []
        try:
            nomes = sorted(n for n in os.listdir(self.pasta) if n.lower().endswith(".jsonl"))
        except OSError:
            nomes = []
        for nome in nomes:
            try:
                with open(os.path.join(self.pasta, nome), encoding="utf-8") as f:
                    for linha in f:
                        try:
                            eventos.append(json.loads(linha))
                        except ValueError:
                            continue                        # linha estragada (queda de luz): ignora só ela
            except OSError:
                continue
        for ev in sorted(eventos, key=lambda e: e.get("gravado", "")):
            if ev.get("tipo") == "entrada":
                self.entradas[ev["dados"]["id"]] = self._completar(dict(ev["dados"]))
            elif ev.get("tipo") == "diferentes":
                self.diferentes.add(frozenset(ev["dados"]["chaves"]))

    @staticmethod
    def _completar(e):
        e.setdefault("unidade", "unidade")
        e.setdefault("tipo", "")
        e.setdefault("embalagem", "")
        e["apelidos"] = list(e.get("apelidos") or [])
        e["codigos"] = {k: list(v) for k, v in (e.get("codigos") or {}).items()}
        return e

    def _gravar(self, tipo, dados):
        agora = datetime.now()
        if self._ultimo and agora.isoformat(timespec="microseconds") <= self._ultimo:
            agora = datetime.fromisoformat(self._ultimo) + timedelta(microseconds=1)
        self._ultimo = agora.isoformat(timespec="microseconds")
        os.makedirs(self.pasta, exist_ok=True)
        caminho = os.path.join(self.pasta, "eventos-{}.jsonl".format(self.nome_pc))
        with open(caminho, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"gravado": self._ultimo, "pc": self.nome_pc, "tipo": tipo, "dados": dados},
                               ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _salvar_entrada(self, e):
        self.entradas[e["id"]] = e
        self._gravar("entrada", e)

    # ------------------------------------------------------------------ procurar

    def por_codigo(self, fornecedor, codigo):
        if not fornecedor or not codigo:
            return None
        return next((e for e in self.entradas.values() if str(codigo) in e["codigos"].get(fornecedor, [])), None)

    def por_nome(self, descricao):
        """Os produtos cujo nome (ou apelido) é o mesmo que `descricao` (mesmas palavras, sem contar acento etc.)."""
        alvo = ln.chave_produto(descricao)
        if not alvo:
            return []
        return [e for e in self.entradas.values()
                if any(ln.chave_produto(n) == alvo for n in [e["nome"]] + e["apelidos"])]

    def tamanho_do_nome(self, nome):
        """Tamanho da embalagem do produto com esse nome (para comparar com o de uma lista), ou None."""
        for e in self.por_nome(nome):
            t = ln.tamanho_embalagem(e["embalagem"])
            if t is not None:
                return t
        return None

    def sao_diferentes(self, nome_a, nome_b):
        return frozenset((ln.chave_nome(nome_a), ln.chave_nome(nome_b))) in self.diferentes

    # ------------------------------------------------------------------ reconhecer o que foi lido

    def reconhecer(self, item, fornecedor=""):
        """
        Procura o item no catálogo: primeiro pelo código do fornecedor, depois pelo nome. Devolve (produto, "código"
        ou "nome"), ou (None, None). Se o nome é igual mas o TAMANHO da embalagem é diferente, não reconhece:
        guarda o produto em item["tamanho_diferente_de"] e a tela pergunta se é o mesmo.
        """
        e = self.por_codigo(fornecedor, item.get("codigo"))
        if e is not None:
            return e, "código"
        tam = ln.tamanho_embalagem(item.get("embalagem") or "")
        if tam is not None:                                    # a variante guardada com o tamanho no nome ("Sabão em pó - 250 g")
            variante = [c for c in self.por_nome("{} - {}".format(item["descricao"], ln.descrever_tamanho(tam)))
                        if ln.tamanho_embalagem(c["embalagem"]) in (None, tam)]
            if variante:
                return variante[0], "nome"
        candidatos = self.por_nome(item["descricao"])
        if not candidatos:
            return None, None
        compativeis = [c for c in candidatos
                       if tam is None or ln.tamanho_embalagem(c["embalagem"]) in (None, tam)]
        if compativeis:
            exato = [c for c in compativeis if tam is not None and ln.tamanho_embalagem(c["embalagem"]) == tam]
            return (exato or compativeis)[0], "nome"
        item["tamanho_diferente_de"] = candidatos[0]
        return None, None

    def aplicar(self, itens, fornecedor=""):
        """Troca, nos itens reconhecidos, o nome e a unidade pelos do catálogo (e guarda como foi reconhecido)."""
        for item in itens:
            item.setdefault("descricao_lida", item["descricao"])
            e, como = self.reconhecer(item, fornecedor)
            if e is None:
                continue
            item["descricao"] = e["nome"]
            item["unidade"] = e["unidade"] or item["unidade"]
            item["catalogo"] = e["id"]
            item["reconhecido"] = como
        return itens

    # ------------------------------------------------------------------ aprender

    def aprender(self, item, nome_material, unidade, tipo, fornecedor=""):
        """
        Depois que a entrada foi confirmada: garante o produto no catálogo com o nome do material onde o item entrou,
        e acrescenta o jeito como o item estava escrito (apelido) e o código do fornecedor.
        """
        e = self.entradas.get(item.get("catalogo")) if item.get("catalogo") else None
        if e is None or ln.chave_produto(e["nome"]) != ln.chave_produto(nome_material):
            tam = ln.tamanho_embalagem(item.get("embalagem") or "")
            candidatos = [c for c in self.por_nome(nome_material)
                          if tam is None or ln.tamanho_embalagem(c["embalagem"]) in (None, tam)]
            e = candidatos[0] if candidatos else None
        novo = e is None
        if novo:
            e = self._completar({"id": "u-" + uuid.uuid4().hex[:10], "nome": nome_material, "unidade": unidade,
                                 "tipo": tipo, "embalagem": item.get("embalagem") or ""})
        mudou = novo
        lida = (item.get("descricao_lida") or item["descricao"]).strip()
        if lida and not item.get("variante") and ln.chave_produto(lida) != ln.chave_produto(e["nome"]) \
                and lida not in e["apelidos"] \
                and all(ln.chave_produto(lida) != ln.chave_produto(a) for a in e["apelidos"]):
            e["apelidos"].append(lida)
            mudou = True
        codigo = str(item.get("codigo") or "")
        if fornecedor and codigo and codigo not in e["codigos"].get(fornecedor, []):
            e["codigos"].setdefault(fornecedor, []).append(codigo)
            mudou = True
        if not e["embalagem"] and item.get("embalagem"):
            e["embalagem"] = item["embalagem"]
            mudou = True
        if mudou:
            self._salvar_entrada(e)
        return e

    def marcar_diferentes(self, nome_a, nome_b):
        """A pessoa disse "Não juntar": esses dois nomes são produtos diferentes (não pergunta de novo)."""
        chaves = sorted((ln.chave_nome(nome_a), ln.chave_nome(nome_b)))
        if chaves[0] == chaves[1] or frozenset(chaves) in self.diferentes:
            return
        self.diferentes.add(frozenset(chaves))
        self._gravar("diferentes", {"chaves": chaves})
