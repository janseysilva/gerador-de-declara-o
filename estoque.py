# -*- coding: utf-8 -*-
"""
Estoque de material (pedagógico e de limpeza) do Declarações Escolares.

Este arquivo só tem as regras, sem tela. Cada estoque é um "livro de registros":
tudo o que acontece (material cadastrado, entrada, saída, estorno) é uma linha
escrita no fim de um arquivo. O saldo de cada material nunca é digitado: é sempre
a soma das entradas menos as saídas, por isso não fica errado.

Cada computador escreve só no seu próprio arquivo (eventos-NOME.jsonl) e lê os
arquivos de todos os computadores da pasta. Assim, se os dois PCs da escola usarem
a mesma pasta (por exemplo, uma pasta do OneDrive), um não sobrescreve o outro.
"""

import json
import math
import os
import re
import socket
import unicodedata
import uuid
from datetime import datetime, timedelta

UNIDADES = ["unidade", "caixa", "pacote", "resma", "rolo", "par", "kg", "litro",
            "frasco", "galão", "metro", "folha", "kit"]

NOME_ESTOQUE = {"pedagogico": "Material pedagógico", "limpeza": "Material de limpeza"}


class ErroEstoque(Exception):
    """Erro que a pessoa precisa ler (já vem escrito em português)."""


# ---------------------------------------------------------------------------
# Textos e números
# ---------------------------------------------------------------------------

def sem_acento(texto):
    texto = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def normalizar(texto):
    """Minúsculas, sem acento e com espaços simples: para comparar e pesquisar."""
    return re.sub(r"\s+", " ", sem_acento(texto).lower()).strip()


def limpar_nome(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def ler_numero(texto):
    """'2', '2,5', '2.5' e '1.000' viram número. Devolve None se não for número."""
    t = str(texto).strip().replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def ler_quantidade(texto):
    t = str(texto).strip()
    if not t:
        raise ErroEstoque("Digite a quantidade.")
    v = ler_numero(t)
    if v is None:
        raise ErroEstoque("A quantidade “{}” não é um número.".format(t))
    if v <= 0:
        raise ErroEstoque("A quantidade precisa ser maior que zero.")
    if v > 1000000:
        raise ErroEstoque("A quantidade está grande demais. Confira o número digitado.")
    return round(v, 3)


def ler_minimo(texto):
    """Estoque mínimo: vazio vale zero (sem aviso)."""
    t = str(texto).strip()
    if not t:
        return 0.0
    v = ler_numero(t)
    if v is None or v < 0:
        raise ErroEstoque("O estoque mínimo “{}” não é válido. Use um número (ou deixe vazio).".format(t))
    return round(v, 3)


def texto_quantidade(valor):
    """3 -> '3'; 2.5 -> '2,5'."""
    v = round(float(valor or 0), 3)
    if v == int(v):
        return str(int(v))
    return ("{:.3f}".format(v)).rstrip("0").rstrip(".").replace(".", ",")


def texto_data_hora(quando):
    return quando.strftime("%d/%m/%Y %H:%M")


def _seguro(texto):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", sem_acento(texto)).strip("-")[:40] or "pc"


def identificar_pc(pasta_local):
    """Nome estável deste computador (fica numa pasta só dele, nunca na pasta compartilhada)."""
    caminho = os.path.join(pasta_local, "estoque_pc.txt")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            nome = _seguro(f.read())
            if nome:
                return nome
    except OSError:
        pass
    nome = "{}-{}".format(_seguro(socket.gethostname()), uuid.uuid4().hex[:4])
    try:
        os.makedirs(pasta_local, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(nome)
    except OSError:
        pass
    return nome


# ---------------------------------------------------------------------------
# O livro de registros
# ---------------------------------------------------------------------------

class Livro:
    """Um estoque (pedagógico ou de limpeza), guardado numa pasta."""

    def __init__(self, pasta, nome_pc="pc"):
        self.pasta = pasta
        self.nome_pc = _seguro(nome_pc)
        self.linhas_ruins = 0
        self._ultimo = ""            # último carimbo gravado por este computador
        self._zerar()
        self.recarregar()

    # -- leitura ---------------------------------------------------------------

    def _zerar(self):
        self._materiais = {}
        self._destinatarios = {}
        self._movs = {}
        self._ordem = []
        self._saldos = {}

    def recarregar(self):
        """Lê de novo os arquivos de todos os computadores (use antes de conferir um saldo)."""
        eventos, vistos, ruins = [], set(), 0
        try:
            nomes = sorted(n for n in os.listdir(self.pasta) if n.lower().endswith(".jsonl"))
        except OSError:
            nomes = []
        for nome in nomes:
            try:
                with open(os.path.join(self.pasta, nome), "r", encoding="utf-8") as f:
                    for linha in f:
                        linha = linha.strip()
                        if not linha:
                            continue
                        try:
                            ev = json.loads(linha)
                            chave = ev["id"]
                            ev["quando"], ev["tipo"]
                        except (ValueError, KeyError, TypeError):
                            ruins += 1
                            continue
                        if chave in vistos:            # cópia repetida (ex.: conflito do OneDrive)
                            continue
                        vistos.add(chave)
                        eventos.append(ev)
            except OSError:
                continue
        self.linhas_ruins = ruins
        # A ordem vale pelo carimbo fino de quando foi gravado ("gravado", com microssegundos), não pela
        # hora do registro: duas linhas no mesmo segundo (criar e editar um material) não podem se trocar.
        eventos.sort(key=lambda e: (str(e.get("gravado") or e.get("quando")), str(e.get("id"))))
        proprios = [str(e.get("gravado") or "") for e in eventos if e.get("pc") == self.nome_pc]
        self._ultimo = max([self._ultimo] + proprios)

        self._zerar()
        estornos = []
        for ev in eventos:
            tipo, d = ev.get("tipo"), ev.get("dados") or {}
            if tipo == "material" and d.get("id"):
                atual = self._materiais.setdefault(d["id"], {"criado_em": ev["quando"]})
                atual.update(d)
            elif tipo == "destinatario" and d.get("id"):
                atual = self._destinatarios.setdefault(d["id"], {"criado_em": ev["quando"]})
                atual.update(d)
            elif tipo in ("entrada", "saida"):
                self._movs[ev["id"]] = {
                    "id": ev["id"], "tipo": tipo, "quando": ev["quando"], "pc": ev.get("pc", ""),
                    "itens": list(d.get("itens") or []), "destinatario": d.get("destinatario"),
                    "obs": d.get("obs") or "", "estornado_em": None, "motivo_estorno": ""}
                self._ordem.append(ev["id"])
            elif tipo == "estorno":
                estornos.append((ev, d))
        for ev, d in estornos:
            mov = self._movs.get(d.get("de"))
            if mov and not mov["estornado_em"]:
                mov["estornado_em"] = ev["quando"]
                mov["motivo_estorno"] = d.get("motivo") or ""
        for mov in self._movs.values():
            if mov["estornado_em"]:
                continue
            sinal = 1 if mov["tipo"] == "entrada" else -1
            for item in mov["itens"]:
                m = item.get("material")
                self._saldos[m] = round(self._saldos.get(m, 0.0) + sinal * float(item.get("quantidade") or 0), 3)

    # -- escrita ---------------------------------------------------------------

    def _gravar(self, tipo, dados, quando=None):
        agora = datetime.now()
        if self._ultimo and agora.isoformat(timespec="microseconds") <= self._ultimo:
            agora = datetime.fromisoformat(self._ultimo) + timedelta(microseconds=1)   # sempre cresce
        gravado = agora.isoformat(timespec="microseconds")
        self._ultimo = gravado
        ev = {"id": uuid.uuid4().hex, "quando": (quando or agora).isoformat(timespec="seconds"),
              "gravado": gravado, "pc": self.nome_pc, "tipo": tipo, "dados": dados}
        caminho = os.path.join(self.pasta, "eventos-{}.jsonl".format(self.nome_pc))
        try:
            os.makedirs(self.pasta, exist_ok=True)
            with open(caminho, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as erro:
            raise ErroEstoque("Não consegui gravar o estoque na pasta:\n{}\n\n{}".format(self.pasta, erro))
        self.recarregar()
        return ev["id"]

    # -- materiais ---------------------------------------------------------------

    def saldo(self, material_id):
        return self._saldos.get(material_id, 0.0)

    def material(self, material_id):
        m = self._materiais.get(material_id)
        return self._com_saldo(material_id, m) if m else None

    def _com_saldo(self, mid, m):
        saldo = self.saldo(mid)
        minimo = float(m.get("minimo") or 0)
        if saldo <= 0:
            situacao = "zerado"
        elif minimo > 0 and saldo <= minimo:
            situacao = "baixo"
        else:
            situacao = "ok"
        return {"id": mid, "nome": m.get("nome", ""), "unidade": m.get("unidade") or "unidade",
                "minimo": minimo, "ativo": m.get("ativo", True), "saldo": saldo, "situacao": situacao}

    def materiais(self, incluir_ocultos=False):
        lista = [self._com_saldo(mid, m) for mid, m in self._materiais.items()
                 if incluir_ocultos or m.get("ativo", True)]
        lista.sort(key=lambda m: normalizar(m["nome"]))
        return lista

    def buscar_materiais(self, texto, limite=60):
        return self._buscar(self.materiais(), texto, limite)

    @staticmethod
    def _buscar(lista, texto, limite):
        q = normalizar(texto)
        termos = q.split()
        if not termos:
            return []
        achados = [x for x in lista if all(t in normalizar(x["nome"]) for t in termos)]
        achados.sort(key=lambda x: (not normalizar(x["nome"]).startswith(q), normalizar(x["nome"])))
        return achados[:limite]

    def _nome_repetido(self, nome, ignorar=None):
        n = normalizar(nome)
        for mid, m in self._materiais.items():
            if mid != ignorar and normalizar(m.get("nome")) == n:
                return m
        return None

    def cadastrar_material(self, nome, unidade="unidade", minimo=0):
        nome = limpar_nome(nome)
        if not nome:
            raise ErroEstoque("Digite o nome do material.")
        repetido = self._nome_repetido(nome)
        if repetido:
            extra = " (ele está oculto: edite-o para voltar a usar)" if not repetido.get("ativo", True) else ""
            raise ErroEstoque("Já existe um material com o nome “{}”{}.".format(repetido["nome"], extra))
        mid = uuid.uuid4().hex[:12]
        self._gravar("material", {"id": mid, "nome": nome, "unidade": limpar_nome(unidade) or "unidade",
                                  "minimo": float(minimo or 0), "ativo": True})
        return mid

    def editar_material(self, material_id, nome=None, unidade=None, minimo=None, ativo=None):
        atual = self._materiais.get(material_id)
        if not atual:
            raise ErroEstoque("Esse material não foi encontrado.")
        dados = {"id": material_id}
        if nome is not None:
            nome = limpar_nome(nome)
            if not nome:
                raise ErroEstoque("Digite o nome do material.")
            if self._nome_repetido(nome, ignorar=material_id):
                raise ErroEstoque("Já existe outro material com o nome “{}”.".format(nome))
            dados["nome"] = nome
        if unidade is not None:
            dados["unidade"] = limpar_nome(unidade) or "unidade"
        if minimo is not None:
            dados["minimo"] = float(minimo)
        if ativo is not None:
            dados["ativo"] = bool(ativo)
        self._gravar("material", dados)
        return material_id

    # -- destinatários ---------------------------------------------------------------

    def destinatario(self, destinatario_id):
        d = self._destinatarios.get(destinatario_id)
        return {"id": destinatario_id, "nome": d.get("nome", ""), "setor": d.get("setor", "")} if d else None

    def destinatarios(self):
        lista = [self.destinatario(i) for i in self._destinatarios]
        lista.sort(key=lambda d: normalizar(d["nome"]))
        return lista

    def buscar_destinatarios(self, texto, limite=60):
        return self._buscar(self.destinatarios(), texto, limite)

    def cadastrar_destinatario(self, nome, setor=""):
        nome, setor = limpar_nome(nome), limpar_nome(setor)
        if not nome:
            raise ErroEstoque("Digite o nome de quem recebe o material.")
        for d in self.destinatarios():
            if normalizar(d["nome"]) == normalizar(nome) and normalizar(d["setor"]) == normalizar(setor):
                raise ErroEstoque("“{}” já está cadastrado.".format(d["nome"]))
        did = uuid.uuid4().hex[:12]
        self._gravar("destinatario", {"id": did, "nome": nome, "setor": setor})
        return did

    # -- entradas e saídas ---------------------------------------------------------------

    def _juntar_itens(self, itens):
        """Soma o mesmo material que aparece duas vezes e confere se cada um existe."""
        total = {}
        for item in itens or []:
            mid = item.get("material")
            m = self._materiais.get(mid)
            if not m or not m.get("ativo", True):
                raise ErroEstoque("Um dos materiais da lista não existe mais ou foi ocultado.")
            total[mid] = round(total.get(mid, 0.0) + float(item.get("quantidade") or 0), 3)
        if not total:
            raise ErroEstoque("A lista de materiais está vazia.")
        for mid, q in total.items():
            if q <= 0:
                raise ErroEstoque("A quantidade de “{}” precisa ser maior que zero.".format(self._materiais[mid]["nome"]))
        return [{"material": mid, "quantidade": q} for mid, q in total.items()]

    def registrar_entrada(self, itens, obs="", quando=None):
        itens = self._juntar_itens(itens)
        return self._gravar("entrada", {"itens": itens, "obs": limpar_nome(obs)}, quando)

    def registrar_saida(self, destinatario_id, itens, obs="", quando=None):
        if not self.destinatario(destinatario_id):
            raise ErroEstoque("Escolha quem recebe o material.")
        self.recarregar()                    # confere com o que os outros computadores já registraram
        itens = self._juntar_itens(itens)
        faltas = []
        for item in itens:
            m = self._com_saldo(item["material"], self._materiais[item["material"]])
            if item["quantidade"] > m["saldo"] + 1e-9:
                faltas.append("{}: há {} {} e a saída pede {}".format(
                    m["nome"], texto_quantidade(m["saldo"]), m["unidade"], texto_quantidade(item["quantidade"])))
        if faltas:
            raise ErroEstoque("Não há saldo suficiente:\n" + "\n".join(faltas))
        return self._gravar("saida", {"destinatario": destinatario_id, "itens": itens, "obs": limpar_nome(obs)}, quando)

    def estornar(self, mov_id, motivo=""):
        """Desfaz uma entrada ou saída (o registro continua no histórico, marcado como estornado)."""
        self.recarregar()
        mov = self._movs.get(mov_id)
        if not mov:
            raise ErroEstoque("Esse registro não foi encontrado.")
        if mov["estornado_em"]:
            raise ErroEstoque("Esse registro já foi estornado.")
        if mov["tipo"] == "entrada":
            faltas = []
            for item in mov["itens"]:
                m = self._materiais.get(item.get("material"), {})
                restante = self.saldo(item.get("material")) - float(item.get("quantidade") or 0)
                if restante < -1e-9:
                    faltas.append("{} (saldo atual: {})".format(m.get("nome", "?"), texto_quantidade(self.saldo(item["material"]))))
            if faltas:
                raise ErroEstoque("Não dá para estornar esta entrada: parte do material já saiu.\n" + "\n".join(faltas))
        return self._gravar("estorno", {"de": mov_id, "motivo": limpar_nome(motivo)})

    # -- consultas ---------------------------------------------------------------

    def _expandir(self, mov):
        quando = datetime.fromisoformat(mov["quando"])
        itens = []
        for item in mov["itens"]:
            m = self._materiais.get(item.get("material"), {})
            itens.append({"material": item.get("material"), "nome": m.get("nome", "(material removido)"),
                          "unidade": m.get("unidade") or "unidade", "quantidade": float(item.get("quantidade") or 0)})
        dest = self.destinatario(mov["destinatario"]) if mov.get("destinatario") else None
        resumo = ", ".join("{} ({} {})".format(i["nome"], texto_quantidade(i["quantidade"]), i["unidade"]) for i in itens)
        estornado_em = None
        if mov["estornado_em"]:
            try:
                estornado_em = datetime.fromisoformat(mov["estornado_em"])
            except ValueError:
                estornado_em = quando
        return {"id": mov["id"], "tipo": mov["tipo"], "quando": quando, "itens": itens, "resumo": resumo,
                "destinatario": dest, "obs": mov["obs"], "estornado": bool(mov["estornado_em"]),
                "estornado_em": estornado_em, "motivo_estorno": mov["motivo_estorno"], "pc": mov["pc"]}

    def movimentos(self, tipo=None, texto="", incluir_estornados=True):
        """Entradas e saídas, da mais nova para a mais antiga."""
        q = normalizar(texto)
        lista = []
        for mid in reversed(self._ordem):
            mov = self._movs[mid]
            if tipo and mov["tipo"] != tipo:
                continue
            if mov["estornado_em"] and not incluir_estornados:
                continue
            x = self._expandir(mov)
            if q:
                alvo = normalizar(" ".join([x["resumo"], x["obs"],
                                            (x["destinatario"] or {}).get("nome", ""),
                                            (x["destinatario"] or {}).get("setor", "")]))
                if not all(t in alvo for t in q.split()):
                    continue
            lista.append(x)
        return lista

    def movimento(self, mov_id):
        mov = self._movs.get(mov_id)
        return self._expandir(mov) if mov else None

    def resumo(self):
        lista = self.materiais()
        return {"materiais": len(lista),
                "baixo": sum(1 for m in lista if m["situacao"] == "baixo"),
                "zerado": sum(1 for m in lista if m["situacao"] == "zerado")}
