# -*- coding: utf-8 -*-
"""
Declarações Escolares - SEMED Manaus

Lê o arquivo de alunos exportado do sistema da SEMED (TXTALUNO_xxxxx.txt),
guarda como banco de dados no computador e gera a declaração pronta (PDF e/ou
Word) com uma pesquisa pelo nome do aluno. Mesmo visual do Frequência
Inteligente.

Declarações: Matrícula, Frequência, Transferência, Conclusão e
Comparecimento. A data sai do relógio do computador.

Build do executável:
    python -m PyInstaller DeclaracoesEscolares.spec
"""

import os
import re
import sys
import json
import math
import zlib
import base64
import struct
import shutil
import subprocess
import unicodedata
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

VERSAO_PROGRAMA = "1.7"
NOME_PROGRAMA = "Declarações Escolares"


# ---------------------------------------------------------------------------
# Pastas e arquivos do programa
# ---------------------------------------------------------------------------

def caminho_recurso(nome):
    """Arquivo que acompanha o programa (dentro do .exe ou ao lado do .py)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nome)


def pasta_dados():
    """Onde ficam o banco de dados, a configuração e o histórico."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    pasta = os.path.join(base, "Declaracoes Escolares")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def pasta_documentos():
    casa = os.path.expanduser("~")
    for nome in ("Documents", "Documentos"):
        if os.path.isdir(os.path.join(casa, nome)):
            return os.path.join(casa, nome)
    return casa


ARQ_CONFIG = "config.json"
ARQ_ALUNOS = "alunos.json"
ARQ_HISTORICO = "historico.json"
ARQ_LOGO = "logotipo.png"


def ler_json(nome, padrao):
    try:
        with open(os.path.join(pasta_dados(), nome), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def gravar_json(nome, dados):
    caminho = os.path.join(pasta_dados(), nome)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(temporario, caminho)


CONFIG_PADRAO = {
    "cab1": "Prefeitura de Manaus",
    "cab2": "Secretaria Municipal de Educação – SEMED",
    "escola": "",
    "inep": "",
    "endereco": "",
    "cidade": "Manaus",
    "uf": "AM",
    "telefone": "",
    "email": "",
    "gestor_nome": "",
    "gestor_cargo": "Gestor(a) Escolar",
    "gestor_registro": "",
    "secretario_nome": "",
    "secretario_cargo": "Secretário(a) Escolar",
    "secretario_registro": "",
    "assina": "gestor",
    "numero": 1,
    "numerar": True,
    "pdf": True,
    "word": False,
    "pasta_saida": "",
}


# ---------------------------------------------------------------------------
# Textos, datas e nomes
# ---------------------------------------------------------------------------

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
DIAS = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
        "Sexta-feira", "Sábado", "Domingo"]
PARTICULAS = {"da", "de", "do", "das", "dos", "e", "di", "du"}


def sem_acento(texto):
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().lower()


def nome_proprio(texto):
    """'MARIA DA SILVA' -> 'Maria da Silva' (se já vier misturado, respeita)."""
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if not texto or (texto != texto.upper() and texto != texto.lower()):
        return texto
    palavras = texto.lower().split(" ")
    return " ".join(p if (i and p in PARTICULAS) else p[:1].upper() + p[1:]
                    for i, p in enumerate(palavras))


def partes_data(valor):
    """Aceita 'aaaa-mm-dd' e 'dd/mm/aaaa'. Devolve (ano, mes, dia) ou None."""
    valor = str(valor or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", valor)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", valor)
    if m:
        ano = int(m.group(3))
        if ano < 100:
            ano += 1900 if ano > 50 else 2000
        return ano, int(m.group(2)), int(m.group(1))
    return None


def data_br(valor):
    p = partes_data(valor)
    return "{:02d}/{:02d}/{}".format(p[2], p[1], p[0]) if p else str(valor or "")


def hoje_br():
    return datetime.now().strftime("%d/%m/%Y")


def hoje_extenso(momento=None):
    h = momento or datetime.now()
    dia = "1º" if h.day == 1 else str(h.day)
    return "{} de {} de {}".format(dia, MESES[h.month - 1], h.year)


def idade(valor):
    p = partes_data(valor)
    if not p:
        return None
    h = datetime.now()
    anos = h.year - p[0] - ((h.month, h.day) < (p[1], p[2]))
    return anos if 0 <= anos < 120 else None


def hora_texto(valor):
    m = re.match(r"^(\d{1,2})[:h](\d{2})$", str(valor or "").strip())
    if not m:
        return str(valor or "").strip()
    h, mi = int(m.group(1)), m.group(2)
    return "{}h".format(h) if mi == "00" else "{}h{}".format(h, mi)


# ---------------------------------------------------------------------------
# Leitura do arquivo de alunos (o "banco de dados")
# ---------------------------------------------------------------------------

def decodificar(dados):
    """O Bloco de Notas antigo e o sistema da SEMED salvam em ANSI."""
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def campo_do_titulo(titulo):
    h = re.sub(r"[:.*#]", "", sem_acento(titulo)).strip()
    if not h:
        return None
    if "nome social" in h:
        return "social"
    if re.search(r"cpf.*resp", h):
        return "cpf_resp"
    if re.search(r"cod(igo)? (da )?turma|cod bai|bai of|cpf|\brg\b|sus|sangu|idade|e-?mail|\bnis\b|inep|"
                 r"ano letivo|exercicio|escola|unidade|municipio|cidade|\buf\b|situacao|data (da )?matricula", h):
        return "outro"
    if re.search(r"telefone|fone|celular|contato|whats", h):
        return "telefone2" if re.search(r"altern|recado|2|secund", h) else "telefone"
    if re.search(r"endereco|logradouro", h):
        return "endereco"
    if "bairro" in h:
        return "bairro"
    if h.startswith("cep"):
        return "cep"
    if re.search(r"\bmae\b|filiacao ?1|genitora", h):
        return "mae"
    if re.search(r"\bpai\b|filiacao ?2|genitor\b", h):
        return "pai"
    if re.search(r"responsavel|\bresp\b", h):           # 'Nome Resp. Matrícula'
        return "responsavel"
    if re.search(r"nasc|^dn$", h):
        return "nasc"
    if re.fullmatch(r"sexo|genero", h):
        return "sexo"
    if "turno" in h:
        return "turno"
    if h == "turma":
        return "turma"
    if re.search(r"etapa|ensino|modalidade|nivel|segmento", h):
        return "etapa"
    if re.search(r"^fase$|serie|^ano( escolar| de escolaridade)?$|^periodo$|^grupo$", h):
        return "serie"
    if re.search(r"matricula|codigo|^cod|^id$|^ra$", h):
        return "matricula"
    if re.search(r"nome|aluno|aluna|estudante", h):
        return "nome"
    return None


def formatar_fone(valor):
    numeros = re.sub(r"\D", "", str(valor or ""))
    if not numeros or set(numeros) == {"0"}:
        return ""
    if len(numeros) == 11:
        return "({}) {}-{}".format(numeros[:2], numeros[2:7], numeros[7:])
    if len(numeros) == 10:
        return "({}) {}-{}".format(numeros[:2], numeros[2:6], numeros[6:])
    if len(numeros) == 9:
        return "{}-{}".format(numeros[:5], numeros[5:])
    if len(numeros) == 8:
        return "{}-{}".format(numeros[:4], numeros[4:])
    return str(valor).strip()


def limpar_endereco(valor):
    """'Rua RUA ANDORRA,13,CASA -CIDADE NOVA 2 -MANAUS' -> 'Rua Andorra, 13, Casa – Cidade Nova 2 – Manaus'."""
    s = re.sub(r"\s+", " ", str(valor or "")).strip()
    if not s:
        return ""
    s = re.sub(r"^(\w+)(\.?)\s+\1\.?(?=\s)", r"\1\2", s, flags=re.I)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s+-\s*|\s*-\s+", " – ", s)
    letras = [c for c in s if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) > 0.7 * len(letras):
        s = " ".join(p.lower() if (i and p.lower() in PARTICULAS) else p[:1].upper() + p[1:].lower()
                     for i, p in enumerate(s.split(" ")))
    return s.strip(" ,–")


def etapa_da_serie(serie):
    s = str(serie or "").lower()
    m = re.match(r"\s*(\d+)", s)
    n = int(m.group(1)) if m else 0
    if re.search(r"per[ií]odo", s):
        return "ei"
    if "etapa" in s:
        return "eja"
    if "ano" in s and 1 <= n <= 5:
        return "efi"
    if "ano" in s and 6 <= n <= 9:
        return "eff"
    return ""


def normalizar(a):
    r = {
        "nome": nome_proprio(a.get("nome")),
        "social": nome_proprio(a.get("social")),
        "matricula": str(a.get("matricula") or "").strip(),
        "sexo": "", "nasc": "",
        "mae": nome_proprio(a.get("mae")), "pai": nome_proprio(a.get("pai")),
        "serie": "", "etapa": "",
        "turma": str(a.get("turma") or "").strip(), "turno": "",
        "responsavel": nome_proprio(a.get("responsavel")),
        "endereco": limpar_endereco(a.get("endereco")),
        "bairro": nome_proprio(a.get("bairro")),
        "cep": str(a.get("cep") or "").strip(),
        "telefone": formatar_fone(a.get("telefone")),
        "telefone2": formatar_fone(a.get("telefone2")),
        "cpf_resp": formatar_cpf(a.get("cpf_resp")),
    }
    sx = sem_acento(a.get("sexo"))[:1]
    r["sexo"] = "F" if sx == "f" else "M" if sx == "m" else ""
    p = partes_data(a.get("nasc"))
    if p:
        r["nasc"] = "{:04d}-{:02d}-{:02d}".format(*p)
    se = str(a.get("serie") or "").strip()
    se = re.sub(r"^(\d{1,2})\s*[ºª°o.]?\s*(ano|s[eé]rie)\b", r"\1º ano", se, flags=re.I)
    se = re.sub(r"^(\d{1,2})\s*[ºª°o.]?\s*per[ií]odo\b", r"\1º período", se, flags=re.I)
    se = re.sub(r"^(\d{1,2})\s*[ºª°a.]?\s*etapa\b", r"\1ª etapa", se, flags=re.I)
    r["serie"] = se
    tn = sem_acento(a.get("turno"))
    r["turno"] = ("Matutino" if re.search(r"matut|manha", tn) else
                  "Vespertino" if re.search(r"vesp|tarde", tn) else
                  "Noturno" if re.search(r"notur|noite", tn) else
                  "Integral" if "integ" in tn else "")
    et = sem_acento(a.get("etapa"))
    r["etapa"] = ("ei" if re.search(r"infantil|creche|pre", et) else
                  "eja" if re.search(r"eja|jovens", et) else
                  "eff" if "finais" in et else
                  "efi" if "iniciais" in et else etapa_da_serie(r["serie"]))
    return r


def _adivinhar(celulas):
    """Linha sem títulos: descobre cada coluna pelo conteúdo."""
    a, textos = {}, []
    for c in celulas:
        s = sem_acento(c)
        if not s:
            continue
        if "nasc" not in a and partes_data(c):
            a["nasc"] = c
        elif "sexo" not in a and re.fullmatch(r"m|f|masc|fem|masculino|feminino", s):
            a["sexo"] = c
        elif "turno" not in a and re.fullmatch(r"matutino|vespertino|noturno|integral|manha|tarde|noite", s):
            a["turno"] = c
        elif "serie" not in a and re.match(r"^\d{1,2}\s*[ºª°o.]?\s*(ano|periodo|etapa|serie)", s):
            a["serie"] = c
        elif re.fullmatch(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", s):
            pass                                    # CPF: ignora
        elif "matricula" not in a and re.fullmatch(r"[\d.-]{5,}", s):
            a["matricula"] = c
        elif "turma" not in a and re.fullmatch(r"[a-z0-9]{1,4}", s):
            a["turma"] = c
        else:
            textos.append(c)
    for chave, valor in zip(("nome", "mae", "pai"), textos):
        a[chave] = valor
    return a


def ler_lista(texto):
    """Lê o arquivo de alunos em vários formatos. Devolve a lista de alunos."""
    linhas = texto.splitlines()
    cheias = [l for l in linhas if l.strip()]
    if not cheias:
        return []

    # Formato em blocos: "Nome: Fulano" / "Mãe: Beltrana" / linha em branco
    com_chave = [l for l in cheias if re.match(r"^\s*[^:\t;|]{2,40}:\s*\S", l)
                 and campo_do_titulo(l.split(":")[0])]
    if (len(com_chave) >= len(cheias) * 0.6
            and any(campo_do_titulo(l.split(":")[0]) == "nome" for l in com_chave)):
        lista, atual = [], {}
        for l in linhas + [""]:
            if not l.strip():
                if atual.get("nome"):
                    lista.append(atual)
                atual = {}
                continue
            if ":" not in l:
                continue
            chave, valor = l.split(":", 1)
            campo = campo_do_titulo(chave)
            if not campo or campo == "outro":
                continue
            if campo == "nome" and atual.get("nome"):
                lista.append(atual)
                atual = {}
            atual.setdefault(campo, valor.strip())
        return [a for a in map(normalizar, lista) if a["nome"]]

    # Formato em colunas
    def maioria(padrao):
        return sum(1 for l in cheias if re.search(padrao, l)) >= len(cheias) * 0.6
    sep = ("\t" if maioria(r"\t") else ";" if maioria(";") else "|" if maioria(r"\|")
           else "  +" if maioria(r"\S {2,}\S") else "," if maioria(",") else None)

    def partir(l):
        if sep is None:
            return [l.strip()]
        partes = re.split(sep, l) if sep == "  +" else l.split(sep)
        return [re.sub(r'^"(.*)"$', r"\1", p.strip()).strip() for p in partes]

    corpo = [partir(l) for l in cheias]
    corpo = [c for c in corpo if not all(re.fullmatch(r"[-=+_ ]*", x) for x in c)]
    if not corpo:
        return []
    titulos = [campo_do_titulo(c) for c in corpo[0]]
    if "nome" in titulos or sum(1 for t in titulos if t) >= 2:
        coluna = _escolher_colunas(corpo, titulos)
        alunos = []
        for c in corpo[1:]:
            a = {}
            for t, i in coluna.items():
                if i < len(c) and c[i]:
                    a[t] = c[i]
            if "nome" not in titulos and c:
                a["nome"] = c[0]
            alunos.append(normalizar(a))
        return [a for a in alunos if a["nome"]]
    return [a for a in (normalizar(_adivinhar(c)) for c in corpo)
            if a["nome"] and len(a["nome"]) > 2]


def _escolher_colunas(corpo, titulos):
    """
    Quando mais de uma coluna parece ser o mesmo dado (ex.: 'Código do Aluno' e
    outra coluna com 'código'), fica a que tem mais valores diferentes. Um código
    igual para todos (como 2026) não é o código do aluno.
    """
    linhas = corpo[1:]
    candidatas = {}
    for i, t in enumerate(titulos):
        if t and t != "outro":
            candidatas.setdefault(t, []).append(i)

    def valores(i):
        return [l[i].strip() for l in linhas if i < len(l) and l[i].strip()]

    confere = {
        "serie": lambda x: bool(re.search(r"[A-Za-zº]", x)),          # '2026' não é fase
        "nasc": lambda x: partes_data(x) is not None,
        "sexo": lambda x: sem_acento(x)[:1] in ("m", "f"),
        "matricula": lambda x: bool(re.search(r"\d", x)),
        "cpf_resp": lambda x: 8 <= len(re.sub(r"\D", "", x)) <= 11,
        "nome": lambda x: bool(re.search(r"[A-Za-z]{2,}\s+[A-Za-z]", sem_acento(x))),
        "mae": lambda x: bool(re.search(r"[A-Za-z]", x)),
        "pai": lambda x: bool(re.search(r"[A-Za-z]", x)),
    }

    def proporcao(t, v):
        f = confere.get(t)
        return 1.0 if not f or not v else sum(1 for x in v if f(x)) / len(v)

    escolha = {}
    for t, idxs in candidatas.items():
        def pontos(i):
            v = valores(i)
            titulo = sem_acento(corpo[0][i])
            preferida = (t == "matricula" and bool(re.search(r"aluno|matric", titulo))) or \
                        (t == "nome" and bool(re.search(r"aluno|estudante", titulo)))
            return (proporcao(t, v) >= 0.5, len(set(v)) > 1, preferida, len(set(v)), len(v), -i)
        melhor = max(idxs, key=pontos)
        v = valores(melhor)
        if v and proporcao(t, v) < 0.5:
            continue                                  # o conteúdo não tem cara desse dado
        if t == "matricula" and len(v) > 5 and len(set(v)) == 1:
            continue                                  # mesmo valor para todos: não é código
        escolha[t] = melhor
    return escolha


def ordem_serie(serie):
    m = re.match(r"\s*(\d+)", serie or "")
    return (int(m.group(1)) if m else 99, serie or "")


def proxima_serie(serie):
    s = str(serie or "")
    m = re.match(r"\s*(\d+)", s)
    n = int(m.group(1)) if m else 0
    if re.search(r"per[ií]odo", s, re.I):
        return "2º período da Educação Infantil" if n == 1 else "1º ano do Ensino Fundamental"
    if re.search(r"ano", s, re.I) and 1 <= n < 9:
        return "{}º ano do Ensino Fundamental".format(n + 1)
    if re.search(r"ano", s, re.I) and n == 9:
        return "1º ano do Ensino Médio"
    if re.search(r"etapa", s, re.I) and 1 <= n < 4:
        return "{}ª etapa da EJA".format(n + 1)
    return ""


# ---------------------------------------------------------------------------
# Texto da declaração
# ---------------------------------------------------------------------------

TIPOS = [
    ("matricula", "Matrícula", "DECLARAÇÃO DE MATRÍCULA"),
    ("frequencia", "Frequência", "DECLARAÇÃO DE FREQUÊNCIA"),
    ("transferencia", "Transferência", "DECLARAÇÃO DE TRANSFERÊNCIA"),
    ("conclusao", "Conclusão", "DECLARAÇÃO DE CONCLUSÃO"),
    ("comparecimento", "Comparecimento", "DECLARAÇÃO DE COMPARECIMENTO"),
    ("justificativa", "Justificativa de falta", "TERMO DE JUSTIFICATIVA DE FALTA"),
    ("compromisso", "Termo de compromisso", "TERMO DE CIÊNCIA, COMPROMISSO E RESPONSABILIDADE"),
]
TERMOS = {"justificativa", "compromisso"}        # formulários: saem preenchidos com o que houver no arquivo
FILEIRAS_TIPOS = [["matricula", "frequencia", "transferencia"], ["conclusao", "comparecimento"],
                  ["justificativa", "compromisso"]]
NOME_TIPO = {t[0]: t[1] for t in TIPOS}
TITULO_TIPO = {t[0]: t[2] for t in TIPOS}

ETAPAS = {
    "ei": "da Educação Infantil",
    "efi": "do Ensino Fundamental – Anos Iniciais",
    "eff": "do Ensino Fundamental – Anos Finais",
    "eja": "da Educação de Jovens e Adultos – EJA",
}


# Declarações que não levam "filho(a) de ..." (nome da mãe e do pai)
SEM_FILIACAO = {"matricula"}


def genero(sexo):
    s = str(sexo or "").strip().upper()[:1]
    if s == "F":
        return {"o": "a", "art": "a", "aluno": "aluna", "pelo": "pela", "do": "da", "Art": "A"}
    if s == "M":
        return {"o": "o", "art": "o", "aluno": "aluno", "pelo": "pelo", "do": "do", "Art": "O"}
    return {"o": "o(a)", "art": "o(a)", "aluno": "aluno(a)", "pelo": "pelo(a)", "do": "do(a)", "Art": "O(A)"}


def _curso(a, prep):
    e = ETAPAS.get(a.get("etapa") or etapa_da_serie(a.get("serie")), "")
    if a.get("serie"):
        if re.search(r"ª|etapa|s[ée]rie", a["serie"], re.I):          # feminino: "na 1ª etapa"
            prep = {"no": "na", "o": "a"}.get(prep, prep)
        return "{} {}{}".format(prep, a["serie"], " " + e if e else "")
    if prep == "no":
        return re.sub(r"^do ", "no ", re.sub(r"^da ", "na ", e))
    return re.sub(r"^do ", "o ", re.sub(r"^da ", "a ", e))


def _turma_turno(a):
    t = ""
    if a.get("turma"):
        t += ", turma " + a["turma"]
    if a.get("turno"):
        t += ", turno " + a["turno"].lower()
    return t


def paragrafos(tipo, a, extras, ano_letivo):
    """
    Devolve a declaração como lista de parágrafos; cada parágrafo é uma
    lista de pedaços (texto, negrito).
    """
    g = genero(a.get("sexo"))
    o = g["o"]

    q = []
    if a.get("social"):
        q += [(a["social"].upper(), True), (" (nome civil: {})".format(a["nome"]), False)]
    else:
        q += [((a.get("nome") or "NOME DO ALUNO").upper(), True)]
    resto = ""
    if a.get("matricula"):
        resto += ", código do aluno nº " + a["matricula"]
    if a.get("nasc"):
        resto += ", nascid{} em {}".format(o, data_br(a["nasc"]))
    mae, pai = a.get("mae"), a.get("pai")
    if tipo in SEM_FILIACAO:
        mae = pai = ""
    if mae and pai:
        resto += ", filh{} de {} e de {}".format(o, mae, pai)
    elif mae or pai:
        resto += ", filh{} de {}".format(o, mae or pai)
    q.append((resto, False))

    ini = ("Declaramos, para os devidos fins, que ", False)
    matric = "nesta Unidade de Ensino, {}{}, no ano letivo de {}".format(
        _curso(a, "no"), _turma_turno(a), ano_letivo)
    x = extras
    p = []

    if tipo == "matricula":
        p.append([ini] + q + [(", encontra-se regularmente matriculad{} {}.".format(o, matric), False)])

    elif tipo == "frequencia":
        f = ", encontra-se regularmente matriculad{} {}, frequentando as aulas regularmente".format(o, matric)
        freq = str(x.get("freq") or "").replace("%", "").replace(".", ",").strip()
        if freq:
            f += ", com frequência de {}% até a presente data".format(freq)
        p.append([ini] + q + [(f + ".", False)])

    elif tipo == "transferencia":
        f = (", esteve regularmente matriculad{} {}, tendo sido requerida a sua "
             "transferência em {}").format(o, matric, hoje_br())
        if x.get("destino"):
            f += ", com destino à unidade de ensino " + x["destino"]
        p.append([ini] + q + [(f + ".", False)])
        sit = x.get("situacao")
        if sit == "cursando":
            p.append([("{} {} encontrava-se cursando regularmente a referida etapa na data "
                       "da transferência.".format(g["Art"], g["aluno"]), False)])
        elif sit == "aprovado":
            p.append([("{} {} foi aprovad{} na referida etapa.".format(g["Art"], g["aluno"], o), False)])
        elif sit == "reprovado":
            p.append([("{} {} foi reprovad{} na referida etapa.".format(g["Art"], g["aluno"], o), False)])
        if str(x.get("prazo") or "").strip():
            p.append([("O Histórico Escolar será expedido no prazo de até {} dias, a contar "
                       "da data desta declaração.".format(x["prazo"]), False)])

    elif tipo == "conclusao":
        res = "aprovad" + o + (" pelo Conselho de Classe" if x.get("resultado") == "conselho" else "")
        f = ", concluiu {} nesta Unidade de Ensino, no ano letivo de {}, tendo sido {}".format(
            _curso(a, "o"), ano_letivo, res)
        if x.get("proxima"):
            f += ", estando apt{} a cursar o {}".format(o, x["proxima"])
        p.append([ini] + q + [(f + ".", False)])

    elif tipo == "comparecimento":
        nome_aluno = (a.get("social") or a.get("nome") or "").upper()
        f = [ini, ((x.get("resp_nome") or "NOME DO RESPONSÁVEL").upper(), True)]
        meio = ""
        if x.get("resp_cpf"):
            meio += ", CPF nº " + x["resp_cpf"]
        parentesco = x.get("parentesco")
        if parentesco == "mae":
            meio += ", mãe {} {} ".format(g["do"], g["aluno"])
        elif parentesco == "pai":
            meio += ", pai {} {} ".format(g["do"], g["aluno"])
        else:
            meio += ", responsável {} {} ".format(g["pelo"], g["aluno"])
        f += [(meio, False), (nome_aluno, True)]
        fim = ""
        if a.get("matricula"):
            fim += " (código nº {})".format(a["matricula"])
        fim += ", matriculad{} {}{}, compareceu a esta Unidade de Ensino no dia {}".format(
            o, _curso(a, "no"), _turma_turno(a), hoje_br())
        if x.get("hora_ini") and x.get("hora_fim"):
            fim += ", com entrada às {} e saída às {}".format(hora_texto(x["hora_ini"]), hora_texto(x["hora_fim"]))
        elif x.get("hora_ini"):
            fim += ", às {}".format(hora_texto(x["hora_ini"]))
        if x.get("motivo"):
            fim += ", para " + x["motivo"]
        f.append((fim + ".", False))
        p.append(f)

    p.append([("Por ser expressão da verdade, firmamos a presente declaração.", False)])
    return p


# ---------------------------------------------------------------------------
# Arquivos de saída: PDF e Word
# ---------------------------------------------------------------------------

AZUL_DOC = (0x17 / 255, 0x32 / 255, 0x7A / 255)


def _linhas_cabecalho(cfg):
    linhas = []
    if cfg.get("cab1"):
        linhas.append((cfg["cab1"].upper(), "Times-Roman", 10.5, False, "preto"))
    if cfg.get("cab2"):
        linhas.append((cfg["cab2"].upper(), "Times-Roman", 10.5, False, "preto"))
    linhas.append(((cfg.get("escola") or "NOME DA ESCOLA").upper(), "Times-Bold", 13, True, "azul"))
    if cfg.get("inep"):
        linhas.append(("Código INEP: " + cfg["inep"], "Times-Roman", 9.5, False, "cinza"))
    return linhas


def _rodape(cfg):
    cidade_uf = " – ".join(v for v in (cfg.get("cidade"), cfg.get("uf")) if v)
    itens = [cfg.get("endereco"), cidade_uf,
             "Tel.: " + cfg["telefone"] if cfg.get("telefone") else "", cfg.get("email")]
    return " · ".join(i for i in itens if i)


def gerar_pdf(caminho, cfg, tipo, paras, numero_txt, logo):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Paragraph

    largura, altura = A4
    esq, dir_ = 22 * mm, 22 * mm
    c = rl_canvas.Canvas(caminho, pagesize=A4)
    c.setTitle(TITULO_TIPO[tipo].title())
    c.setAuthor(cfg.get("escola") or NOME_PROGRAMA)
    c.setCreator(NOME_PROGRAMA)

    # Cabeçalho (com o logotipo à esquerda, se houver)
    linhas = _linhas_cabecalho(cfg)
    alturas = [tam * 1.32 for _, _, tam, _, _ in linhas]
    topo = altura - 18 * mm
    bloco = sum(alturas)
    if logo and os.path.exists(logo):
        try:
            lado = 22 * mm
            c.drawImage(logo, esq, topo - max(bloco, lado) / 2 - lado / 2, width=lado, height=lado,
                        preserveAspectRatio=True, anchor="c", mask="auto")
        except Exception:
            pass
    y = topo
    for (texto, fonte, tam, _negrito, cor), alt in zip(linhas, alturas):
        y -= alt
        c.setFont(fonte, tam)
        c.setFillColorRGB(*(AZUL_DOC if cor == "azul" else (0.27, 0.27, 0.27) if cor == "cinza" else (0.07, 0.07, 0.07)))
        espaco = 0.6 if tam <= 10.5 and cor == "preto" else 0
        largura_txt = c.stringWidth(texto, fonte, tam) + espaco * max(len(texto) - 1, 0)
        c.drawString((largura - largura_txt) / 2, y, texto, charSpace=espaco)
    y -= 4 * mm
    c.setStrokeColorRGB(*AZUL_DOC)
    c.setLineWidth(1.2)
    c.line(esq, y, largura - dir_, y)

    # Título e número
    y -= 18 * mm
    titulo = TITULO_TIPO[tipo]
    c.setFillColorRGB(0.07, 0.07, 0.07)
    c.setFont("Times-Bold", 15)
    largura_txt = c.stringWidth(titulo, "Times-Bold", 15) + 1.8 * (len(titulo) - 1)
    c.drawString((largura - largura_txt) / 2, y, titulo, charSpace=1.8)
    y -= 7 * mm
    if numero_txt:
        c.setFont("Times-Roman", 10.5)
        c.setFillColorRGB(0.27, 0.27, 0.27)
        c.drawCentredString(largura / 2, y, numero_txt)
    y -= 12 * mm

    # Corpo
    estilo = ParagraphStyle("corpo", fontName="Times-Roman", fontSize=12.5, leading=19,
                            alignment=TA_JUSTIFY, firstLineIndent=15 * mm,
                            textColor=(0.07, 0.07, 0.07))
    for pedacos in paras:
        marcado = "".join("<b>{}</b>".format(xml_escape(t)) if neg else xml_escape(t)
                          for t, neg in pedacos)
        par = Paragraph(marcado, estilo)
        _, alt = par.wrap(largura - esq - dir_, y)
        par.drawOn(c, esq, y - alt)
        y -= alt + 5 * mm

    # Local e data
    y -= 6 * mm
    c.setFont("Times-Roman", 12.5)
    c.setFillColorRGB(0.07, 0.07, 0.07)
    local = (cfg.get("cidade") + ", " if cfg.get("cidade") else "") + hoje_extenso() + "."
    c.drawRightString(largura - dir_, y, local)

    # Assinatura
    y -= 28 * mm
    c.setStrokeColorRGB(0.07, 0.07, 0.07)
    c.setLineWidth(0.8)
    c.line(largura / 2 - 47.5 * mm, y, largura / 2 + 47.5 * mm, y)
    y -= 5.5 * mm
    c.setFont("Times-Bold", 12)
    c.drawCentredString(largura / 2, y, cfg.get("assinante") or "Assinatura e carimbo")
    if cfg.get("cargo"):
        y -= 5 * mm
        c.setFont("Times-Roman", 11)
        c.drawCentredString(largura / 2, y, cfg["cargo"])
    if cfg.get("registro"):
        y -= 4.6 * mm
        c.setFont("Times-Roman", 10)
        c.setFillColorRGB(0.27, 0.27, 0.27)
        c.drawCentredString(largura / 2, y, cfg["registro"])

    # Rodapé
    rodape = _rodape(cfg)
    if rodape or cfg.get("escola"):
        base = 16 * mm
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.setLineWidth(0.6)
        c.line(esq, base + 9 * mm, largura - dir_, base + 9 * mm)
        c.setFont("Helvetica", 8.5)
        c.setFillColorRGB(0.27, 0.27, 0.27)
        c.drawCentredString(largura / 2, base + 5 * mm, cfg.get("escola") or "")
        if rodape:
            c.drawCentredString(largura / 2, base + 1.2 * mm, rodape)
    c.showPage()
    c.save()


def gerar_word(caminho, cfg, tipo, paras, numero_txt, logo):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.6)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)

    def par(texto="", tam=12, negrito=False, alinhar=WD_ALIGN_PARAGRAPH.CENTER,
            antes=0, depois=0, cor=None):
        p = doc.add_paragraph()
        p.alignment = alinhar
        p.paragraph_format.space_before = Pt(antes)
        p.paragraph_format.space_after = Pt(depois)
        if texto:
            r = p.add_run(texto)
            r.font.size = Pt(tam)
            r.bold = negrito
            if cor:
                r.font.color.rgb = RGBColor.from_string(cor)
        return p

    if logo and os.path.exists(logo):
        try:
            par().add_run().add_picture(logo, height=Cm(2))
        except Exception:
            pass
    for texto, _f, tam, negrito, cor in _linhas_cabecalho(cfg):
        par(texto, tam, negrito, cor="17327A" if cor == "azul" else "444444" if cor == "cinza" else None)
    par("_" * 78, 8, cor="17327A", depois=6)
    par(TITULO_TIPO[tipo], 15, True, antes=30, depois=2)
    par(numero_txt or "", 10.5, cor="444444", depois=26)
    for pedacos in paras:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(1.5)
        p.paragraph_format.line_spacing = 1.5
        p.paragraph_format.space_after = Pt(10)
        for texto, negrito in pedacos:
            r = p.add_run(texto)
            r.bold = negrito
    local = (cfg.get("cidade") + ", " if cfg.get("cidade") else "") + hoje_extenso() + "."
    par(local, 12, alinhar=WD_ALIGN_PARAGRAPH.RIGHT, antes=18, depois=54)
    par("_" * 42, 12)
    par(cfg.get("assinante") or "Assinatura e carimbo", 12, True)
    if cfg.get("cargo"):
        par(cfg["cargo"], 11)
    if cfg.get("registro"):
        par(cfg["registro"], 10, cor="444444")
    rodape = _rodape(cfg)
    if rodape or cfg.get("escola"):
        pe = sec.footer.paragraphs[0]
        pe.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = pe.add_run((cfg.get("escola") or "") + ("\n" + rodape if rodape else ""))
        r.font.size = Pt(8.5)
        r.font.name = "Arial"
        r.font.color.rgb = RGBColor.from_string("444444")
    doc.save(caminho)


# ---------------------------------------------------------------------------
# Termos (formulários): Justificativa de falta e Termo de compromisso (CEMASP)
# ---------------------------------------------------------------------------

MOTIVOS_FALTA = [
    "Chuva forte / alagamento",
    "Transporte (ônibus/van) / dificuldade de locomoção",
    "Motivo de saúde (sem documento)",
    "Motivo familiar",
    "Consulta/compromisso (sem comprovante)",
]

CABECALHO_CEMASP = [
    "PREFEITURA DE MANAUS",
    "SUBSECRETARIA DE GESTÃO EDUCACIONAL",
    "DEPARTAMENTO DE GESTÃO EDUCACIONAL",
    "DIVISÃO DE APOIO À GESTÃO ESCOLAR – DAGE",
    "CENTRO MUNICIPAL DE ATENDIMENTO SOCIOPSICOPEDAGÓGICO",
]


def formatar_cpf(valor):
    n = re.sub(r"\D", "", str(valor or ""))
    if 8 <= len(n) < 11:
        n = n.zfill(11)              # o sistema da SEMED tira os zeros da frente
    if len(n) == 11 and set(n) != {"0"}:
        return "{}.{}.{}-{}".format(n[:3], n[3:6], n[6:9], n[9:])
    return ""


def _turma_texto(a):
    return " – ".join(v for v in (a.get("serie"), a.get("turma") and "Turma " + a["turma"]) if v)


def dados_termo(a):
    """O que os termos levam do banco de dados; o resto fica em branco para preencher à mão."""
    resp = a.get("responsavel", "")
    if resp and sem_acento(resp) == sem_acento(a.get("mae")):
        parentesco = "mae"
    elif resp and sem_acento(resp) == sem_acento(a.get("pai")):
        parentesco = "pai"
    else:
        parentesco = "responsavel" if resp else ""
    return {"resp_nome": resp, "cpf": a.get("cpf_resp", "") if resp else "", "telefone": a.get("telefone", ""),
            "parentesco": parentesco, "profissao": "", "horario": ""}


def blocos_justificativa(cfg, a, d):
    """Termo de Justificativa de Falta (modelo da escola)."""
    turno = (a.get("turno") or "").capitalize()
    bolsa = {"Sim": "Sim", "Não": "Não"}.get(d.get("bolsa"))
    return [
        ("titulo", "TERMO DE JUSTIFICATIVA DE FALTA"),
        ("secao", "IDENTIFICAÇÃO DO ALUNO(A):"),
        ("campo", "Aluno(a)", (a.get("social") or a.get("nome") or "").upper()),
        ("campo", "Série/Turma", _turma_texto(a), 0.55),
        ("marcar", "Turno", ["Matutino", "Vespertino"], turno),
        ("marcar", "Beneficiário do Bolsa Família", ["Sim", "Não"], bolsa),
        ("espaco", 3),
        ("campo", "Data da falta", d.get("data_falta", "")),
        ("campo", "Quantidade de Faltas", d.get("qtd_faltas", "")),
        ("secao", "MOTIVO DA AUSÊNCIA:"),
        ("lista", MOTIVOS_FALTA, d.get("motivo"), d.get("motivo_outro", "")),
        ("secao", "DECLARAÇÃO DO(A) RESPONSÁVEL:"),
        ("par", [("Declaro, para os devidos fins, que a ausência do(a) aluno(a) acima identificado(a) na "
                  "data informada ocorreu pelo motivo assinalado. Assumo a responsabilidade pelas "
                  "informações prestadas, estando ciente de que a escola poderá solicitar esclarecimentos "
                  "adicionais, se necessário.", False)], 0),
        ("secao", "ASSINATURA E CONTATO DO(A) RESPONSÁVEL:"),
        ("campo", "Nome do(a) responsável", (d.get("resp_nome") or "").upper()),
        ("campo", "Telefone/WhatsApp", d.get("telefone", "")),
        ("campo", "Assinatura", ""),
        ("secao", "USO DA ESCOLA (Secretaria):"),
        ("campo", "Recebido por", "", 0.75),
        ("campo", "Data do recebimento", hoje_br()),
    ]


def blocos_compromisso(cfg, a, d):
    """Termo de Ciência, Compromisso e Responsabilidade (modelo do CEMASP)."""
    def ou_linha(valor, tam=18):
        return valor if valor else "_" * tam
    par = d.get("parentesco")
    marca = lambda k: "(X)" if par == k else "(   )"
    aluno = (a.get("social") or a.get("nome") or "").upper()
    endereco = a.get("endereco", "")
    bairro = a.get("bairro", "")
    if bairro and sem_acento(bairro) in sem_acento(endereco):
        endereco = re.split(r"\s+–\s+", endereco)[0]          # o bairro vai no campo dele
    ident = [
        ("Eu, ", False), (ou_linha((d.get("resp_nome") or "").upper(), 40), True),
        (", Identidade/CPF nº {}, profissão: {}, domiciliado(a) em {}, bairro {}, município de {}, "
         "telefone {}, sou pai {} mãe {} responsável {} do(a) estudante ".format(
             ou_linha(d.get("cpf")), ou_linha(d.get("profissao")), ou_linha(endereco, 30),
             ou_linha(bairro), cfg.get("cidade") or "Manaus", ou_linha(d.get("telefone")),
             marca("pai"), marca("mae"), marca("responsavel")), False),
        (aluno, True),
        (", matriculado(a) na Unidade de Ensino ", False), ((cfg.get("escola") or "").upper(), True),
        (", Série/Ano {}, Turma {}, Turno {}, declaro para os devidos fins que estou ciente dos preceitos "
         "legais e regulamentares, assim como ".format(
             ou_linha(a.get("serie"), 8), ou_linha(a.get("turma"), 4), ou_linha((a.get("turno") or "").lower(), 10)), False),
        ("atentarei para não incorrer no descumprimento deles, particularmente", True), (":", False),
    ]
    itens = [
        [("A ", False), ("Constituição Federal, no Art 229, Cap. VII", True),
         (", informa que os pais têm o dever de assistir e educar os filhos menores de idade.", False)],
        [("A ", False), ("Lei 8.069/90, em seu Art. 129, Inciso V", True),
         (", determina que os pais têm a “", False),
         ("obrigação de matricular o filho ou pupilo e acompanhar sua frequência e aproveitamento escolar.", True),
         ("”", False)],
        [("A ", False), ("Lei de Diretrizes Bases da Educação (LDB), 9.394/96", True),
         (", no artigo 2º diz que “", False), ("a educação é dever da família e do Estado", True), ("”.", False)],
        [("O ", False), ("Estatuto da Criança e do Adolescente – ECA, Art. 22", True), (" adverte que ", False),
         ("a omissão dos Direitos da Criança e do Adolescente ao acesso à educação configura-se como crime de "
          "abandono intelectual, passível de penalidades", True), (".", False)],
        [("O ", False), ("Código Penal no Art. 246", True), (" prevê ", False),
         ("pena de detenção de 15 dias a 1 mês ou multa", True), (" nos casos de ", False),
         ("deixar de prover a instrução primária de seus filhos de idade escolar", True), (".", False)],
        [("A ", False), ("Lei nº 13.803/ 2019, VIII do art. 12", True), (" instrui “", False),
         ("Notificar ao Conselho Tutelar do Município a relação dos alunos que apresentem quantidade de faltas "
          "acima de 30% (trinta por cento) do percentual permitido em lei", True), ("”", False)],
    ]
    final = [
        ("Declaro para os devidos fins de comprovação que o responsável pelo(a) aluno(a) acima identificado(a), "
         "se fez presente nesta Unidade Educacional no dia {}, no horário de {} h, está ciente das orientações "
         "fornecidas pelo CEMASP referentes ao compromisso de exercerem responsabilidade dos deveres inerentes "
         "ao poder familiar e que em caso de ".format(hoje_br(), d.get("horario") or "____:____"), False),
        ("reincidência de faltas não justificadas", True),
        (", a Ficha de Controle do Aluno Infrequente (FICAI) será ", False),
        ("encaminhada para o Conselho Tutelar", True),
        (", para as devidas providências. E para constar, foi firmado o presente termo.", False),
    ]
    blocos = [("titulo", "TERMO DE CIÊNCIA, COMPROMISSO E RESPONSABILIDADE"), ("par", ident, 0)]
    for letra, item in zip("abcdef", itens):
        blocos.append(("item", letra, item))
    blocos += [
        ("par", final, 0),
        ("secao", "ASSINATURAS:"),
        ("assinatura_linha", "Pedagogo(a)", ""),
        ("assinatura_linha", "Gestor(a) da escola", cfg.get("gestor_nome", "")),
        ("assinatura_centro", "Assinatura do Responsável", (d.get("resp_nome") or "").upper()),
    ]
    return blocos


def gerar_pdf_termo(caminho, cfg, cab_linhas, blocos, logo, titulo_doc):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Paragraph

    largura, altura = A4
    esq, dir_ = 20 * mm, 20 * mm
    util = largura - esq - dir_
    c = rl_canvas.Canvas(caminho, pagesize=A4)
    c.setTitle(titulo_doc)
    c.setAuthor(cfg.get("escola") or NOME_PROGRAMA)
    c.setCreator(NOME_PROGRAMA)
    preto = (0.07, 0.07, 0.07)

    # cabeçalho
    topo = altura - 14 * mm
    lado = 20 * mm
    if logo and os.path.exists(logo):
        try:
            c.drawImage(logo, esq, topo - lado, width=lado, height=lado,
                        preserveAspectRatio=True, anchor="c", mask="auto")
        except Exception:
            pass
    y = topo
    for i, (texto, negrito, tam) in enumerate(cab_linhas):
        y -= tam * 1.3
        c.setFont("Helvetica-Bold" if negrito else "Helvetica", tam)
        c.setFillColorRGB(*(AZUL_DOC if (negrito and tam >= 10) else preto))
        c.drawCentredString(largura / 2, y, texto)
    y = min(y, topo - lado) - 6 * mm

    estilo = ParagraphStyle("t", fontName="Helvetica", fontSize=10.5, leading=15.5,
                            alignment=TA_JUSTIFY, textColor=preto)

    def marcado(pedacos):
        return "".join("<b>{}</b>".format(xml_escape(t)) if n else xml_escape(t) for t, n in pedacos)

    def linha_campo(rotulo, valor, fracao=1.0):
        nonlocal y
        y -= 8 * mm
        c.setFont("Helvetica-Bold", 10.5)
        c.setFillColorRGB(*preto)
        texto = rotulo + ":"
        c.drawString(esq, y, texto)
        x0 = esq + c.stringWidth(texto, "Helvetica-Bold", 10.5) + 4
        x1 = esq + util * fracao
        c.setLineWidth(0.6)
        c.line(x0, y - 2, x1, y - 2)
        if valor:
            c.setFont("Helvetica", 10.5)
            c.drawString(x0 + 3, y + 1, valor)

    for b in blocos:
        tipo = b[0]
        if tipo == "titulo":
            y -= 4 * mm
            c.setFont("Helvetica-Bold", 14)
            c.setFillColorRGB(*preto)
            c.drawCentredString(largura / 2, y, b[1])
            y -= 4 * mm
        elif tipo == "secao":
            y -= 9 * mm
            c.setFont("Helvetica-Bold", 10.5)
            c.setFillColorRGB(*preto)
            c.drawString(esq, y, b[1])
            y += 1.5 * mm
        elif tipo == "campo":
            linha_campo(b[1], b[2], b[3] if len(b) > 3 else 1.0)
        elif tipo == "marcar":
            y -= 8 * mm
            c.setFont("Helvetica-Bold", 10.5)
            c.drawString(esq, y, b[1] + ":")
            x = esq + c.stringWidth(b[1] + ":", "Helvetica-Bold", 10.5) + 6
            c.setFont("Helvetica", 10.5)
            for opc in b[2]:
                texto = "( {} ) {}".format("X" if b[3] == opc else "  ", opc)
                c.drawString(x, y, texto)
                x += c.stringWidth(texto, "Helvetica", 10.5) + 12
        elif tipo == "espaco":
            y -= b[1] * mm
        elif tipo == "lista":
            opcoes, escolhido, outro = b[1], b[2], b[3]
            c.setFont("Helvetica", 10.5)
            for opc in opcoes:
                y -= 6.5 * mm
                c.drawString(esq, y, "( {} ) {};".format("X" if escolhido == opc else "  ", opc))
            y -= 6.5 * mm
            texto = "( {} ) Outro:".format("X" if escolhido == "Outro" else "  ")
            c.drawString(esq, y, texto)
            x0 = esq + c.stringWidth(texto, "Helvetica", 10.5) + 4
            c.setLineWidth(0.6)
            c.line(x0, y - 2, esq + util, y - 2)
            if escolhido == "Outro" and outro:
                c.drawString(x0 + 3, y + 1, outro)
        elif tipo in ("par", "item"):
            if tipo == "item":
                est = ParagraphStyle("i", parent=estilo, leftIndent=8 * mm, firstLineIndent=-5 * mm,
                                     fontSize=10, leading=14)
                par = Paragraph("{})&nbsp;&nbsp;{}".format(b[1], marcado(b[2])), est)
                espaco = 1.5 * mm
            else:
                par = Paragraph(marcado(b[1]), estilo)
                espaco = 4 * mm
            _, alt = par.wrap(util, y)
            y -= espaco
            par.drawOn(c, esq, y - alt)
            y -= alt
        elif tipo == "assinatura_linha":
            y -= 11 * mm
            c.setFont("Helvetica", 10.5)
            c.setFillColorRGB(*preto)
            texto = b[1] + ":"
            c.drawString(esq, y, texto)
            x0 = esq + c.stringWidth(texto, "Helvetica", 10.5) + 4
            c.setLineWidth(0.6)
            c.line(x0, y - 2, x0 + 95 * mm, y - 2)
            if b[2]:
                c.setFont("Helvetica", 8)
                c.setFillColorRGB(0.35, 0.35, 0.35)
                c.drawCentredString(x0 + 47.5 * mm, y - 5.5 * mm, b[2])
        elif tipo == "assinatura_centro":
            y -= 18 * mm
            c.setStrokeColorRGB(*preto)
            c.setLineWidth(0.6)
            c.line(largura / 2 - 50 * mm, y, largura / 2 + 50 * mm, y)
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*preto)
            c.drawCentredString(largura / 2, y - 4.5 * mm, b[1])
            if b[2]:
                c.setFont("Helvetica", 8.5)
                c.drawCentredString(largura / 2, y - 8.5 * mm, b[2])
    c.showPage()
    c.save()


def gerar_word_termo(caminho, cfg, cab_linhas, blocos, logo):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2)
    sec.top_margin, sec.bottom_margin = Cm(1.4), Cm(1.4)
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)

    def par(alinhar=WD_ALIGN_PARAGRAPH.LEFT, antes=0, depois=2):
        p = doc.add_paragraph()
        p.alignment = alinhar
        p.paragraph_format.space_before = Pt(antes)
        p.paragraph_format.space_after = Pt(depois)
        return p

    if logo and os.path.exists(logo):
        try:
            par(WD_ALIGN_PARAGRAPH.CENTER).add_run().add_picture(logo, height=Cm(1.8))
        except Exception:
            pass
    for texto, negrito, tam in cab_linhas:
        r = par(WD_ALIGN_PARAGRAPH.CENTER, depois=0).add_run(texto)
        r.bold, r.font.size = negrito, Pt(tam)
    for b in blocos:
        t = b[0]
        if t == "titulo":
            r = par(WD_ALIGN_PARAGRAPH.CENTER, antes=14, depois=8).add_run(b[1])
            r.bold, r.font.size = True, Pt(14)
        elif t == "secao":
            par(antes=10).add_run(b[1]).bold = True
        elif t == "campo":
            p = par(antes=4)
            p.add_run(b[1] + ": ").bold = True
            p.add_run(b[2] if b[2] else "_" * 60)
        elif t == "marcar":
            p = par(antes=4)
            p.add_run(b[1] + ": ").bold = True
            p.add_run("   ".join("( {} ) {}".format("X" if b[3] == o else " ", o) for o in b[2]))
        elif t == "lista":
            for o in b[1]:
                par().add_run("( {} ) {};".format("X" if b[2] == o else " ", o))
            par().add_run("( {} ) Outro: {}".format("X" if b[2] == "Outro" else " ",
                                                    b[3] if b[2] == "Outro" and b[3] else "_" * 50))
        elif t in ("par", "item"):
            p = par(WD_ALIGN_PARAGRAPH.JUSTIFY, antes=6 if t == "par" else 2)
            if t == "item":
                p.paragraph_format.left_indent = Cm(0.8)
                p.add_run(b[1] + ")  ")
                pedacos = b[2]
            else:
                pedacos = b[1]
            for texto, negrito in pedacos:
                p.add_run(texto).bold = negrito
        elif t == "assinatura_linha":
            p = par(antes=16)
            p.add_run("{}: {}".format(b[1], "_" * 45))
            if b[2]:
                par().add_run(" " * 30 + b[2]).font.size = Pt(8)
        elif t == "assinatura_centro":
            par(WD_ALIGN_PARAGRAPH.CENTER, antes=30).add_run("_" * 50)
            par(WD_ALIGN_PARAGRAPH.CENTER).add_run(b[1]).bold = True
            if b[2]:
                par(WD_ALIGN_PARAGRAPH.CENTER).add_run(b[2]).font.size = Pt(8.5)
    doc.save(caminho)


def cabecalho_escola(cfg):
    linhas = []
    for k in ("cab1", "cab2"):
        if cfg.get(k):
            linhas.append((cfg[k].upper(), False, 9.5))
    linhas.append(((cfg.get("escola") or "NOME DA ESCOLA").upper(), True, 11))
    if cfg.get("endereco"):
        linhas.append((cfg["endereco"].upper(), False, 9))
    if cfg.get("telefone"):
        linhas.append(("FONE: " + cfg["telefone"], False, 9))
    return linhas


def cabecalho_cemasp(cfg):
    return [(t, True, 9) for t in CABECALHO_CEMASP]


def abrir_arquivo(caminho):
    try:
        if hasattr(os, "startfile"):
            os.startfile(caminho)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", caminho])
        else:
            subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def nome_arquivo_seguro(texto):
    texto = re.sub(r'[\\/:*?"<>|]+', " ", texto)
    return re.sub(r"\s+", " ", texto).strip()[:120]


# ---------------------------------------------------------------------------
# Interface gráfica (mesmo visual do Frequência Inteligente)
# ---------------------------------------------------------------------------

COR_FUNDO = "#F2F5FA"
COR_CARTAO = "#FFFFFF"
COR_AZUL = "#2A63C8"
COR_AZUL_ESCURO = "#17327A"
COR_AZUL_CLARO = "#5B8AD9"
COR_TEXTO = "#1F2937"
COR_TEXTO_FRACO = "#6B7280"
COR_BORDA = "#DDE5F3"
COR_LINHA = "#F4F7FC"
COR_VERDE = "#1E8E4E"
COR_LARANJA = "#C55A11"
ALTURA_CABECALHO = 92
FONTE = "Segoe UI"


def _misturar(cor_a, cor_b, t):
    a = [int(cor_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(cor_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#{:02x}{:02x}{:02x}".format(*(round(x + (y - x) * t) for x, y in zip(a, b)))


def _retangulo_arredondado(tela, x1, y1, x2, y2, raio, **opcoes):
    pontos = [x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio,
              x2, y2 - raio, x2, y2, x2 - raio, y2, x1 + raio, y2,
              x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1]
    return tela.create_polygon(pontos, smooth=True, **opcoes)


class Botao(tk.Canvas):
    """Botão de cantos arredondados (igual ao do Frequência Inteligente)."""

    ESTILOS = {
        "principal": {"fundo": "#1E8E4E", "passa": "#27A35F", "off": "#A9CDB8",
                      "texto": "#FFFFFF", "texto_off": "#FFFFFF", "borda": None},
        "suave": {"fundo": "#E6ECF7", "passa": "#D5DFF1", "off": "#F1F3F7",
                  "texto": "#17327A", "texto_off": "#AAB2C4", "borda": None},
        "azul": {"fundo": "#2A63C8", "passa": "#3A73D8", "off": "#A9BCE3",
                 "texto": "#FFFFFF", "texto_off": "#FFFFFF", "borda": None},
        "tracejado": {"fundo": None, "passa": "#EAF1FF", "off": None,
                      "texto": "#2A63C8", "texto_off": "#AAB2C4", "borda": "#9DB6E6"},
    }

    def __init__(self, pai, texto, comando, estilo="suave",
                 fonte=(FONTE, 10, "bold"), pad_x=18, pad_y=9, raio=10):
        self._est = self.ESTILOS[estilo]
        self._tracejado = estilo == "tracejado"
        self._texto = texto
        self._comando = comando
        self._raio = raio
        self._pad_x = pad_x
        self._fonte = tkfont.Font(family=fonte[0], size=fonte[1],
                                  weight=fonte[2] if len(fonte) > 2 else "normal")
        self._fundo_pai = pai["bg"]
        self._ativo = True
        self._sobre = False
        largura = self._fonte.measure(texto) + 2 * pad_x
        altura = self._fonte.metrics("linespace") + 2 * pad_y
        super().__init__(pai, width=largura, height=altura, bg=self._fundo_pai,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._mudar_sobre(True))
        self.bind("<Leave>", lambda e: self._mudar_sobre(False))
        self.bind("<Configure>", lambda e: self._desenhar())
        self.bind("<ButtonRelease-1>", self._soltou)
        self._desenhar()

    def definir_ativo(self, ativo):
        self._ativo = bool(ativo)
        self.configure(cursor="hand2" if self._ativo else "")
        self._desenhar()

    def definir_texto(self, texto):
        self._texto = texto
        self.configure(width=self._fonte.measure(texto) + 2 * self._pad_x)
        self._desenhar()

    def _mudar_sobre(self, sobre):
        self._sobre = sobre
        self._desenhar()

    def _soltou(self, evento):
        if self._ativo and 0 <= evento.x <= self.winfo_width() and 0 <= evento.y <= self.winfo_height():
            self._comando()

    def _desenhar(self):
        self.delete("all")
        est = self._est
        largura, altura = self.winfo_width(), self.winfo_height()
        if largura <= 1:
            largura, altura = int(float(self["width"])), int(float(self["height"]))
        if not self._ativo:
            fundo, texto = est["off"], est["texto_off"]
        else:
            fundo = est["passa"] if self._sobre else est["fundo"]
            texto = est["texto"]
        fundo = fundo or self._fundo_pai
        borda = est["borda"]
        opcoes = {"fill": fundo, "outline": borda or fundo, "width": 1.5 if borda else 1}
        if self._tracejado:
            opcoes["dash"] = (4, 3)
        _retangulo_arredondado(self, 1, 1, largura - 1, altura - 1, self._raio, **opcoes)
        self.create_text(largura / 2, altura / 2, text=self._texto, font=self._fonte, fill=texto)


def _rgb(cor):
    return tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))


def _cobertura(distancia):
    return min(1.0, max(0.0, 0.5 - distancia))


def _dist_retangulo(x, y, cx, cy, meia_larg, meia_alt, raio):
    qx = abs(x - cx) - (meia_larg - raio)
    qy = abs(y - cy) - (meia_alt - raio)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - raio


def _dist_segmento(x, y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def _por_cima(pixel, cor, cobertura):
    r, g, b, a = pixel
    resto = 1.0 - cobertura
    return (cor[0] * cobertura + r * resto, cor[1] * cobertura + g * resto,
            cor[2] * cobertura + b * resto, cobertura + a * resto)


def _png_de_pixels(largura, altura, linhas):
    def bloco(tipo, dados):
        corpo = tipo + dados
        return struct.pack(">I", len(dados)) + corpo + struct.pack(">I", zlib.crc32(corpo) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 6, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bytes(linhas), 6))
            + bloco(b"IEND", b""))


def _imagem_disco(diametro, cor):
    rgb = _rgb(cor)
    raio = diametro / 2
    linhas = bytearray()
    for py in range(diametro):
        linhas.append(0)
        for px in range(diametro):
            cob = _cobertura(math.hypot(px + 0.5 - raio, py + 0.5 - raio) - raio)
            linhas += bytes(rgb) + bytes((round(cob * 255),))
    return tk.PhotoImage(data=base64.b64encode(_png_de_pixels(diametro, diametro, linhas)))


class Chip(tk.Canvas):
    """
    Pílula com bolinha e "certo" (a mesma do Frequência Inteligente).
    Com `valor`, vira uma opção de escolha única (a variável guarda o valor
    escolhido); sem `valor`, liga e desliga.
    """

    ALTURA = 30
    PAD_ESQ, ICONE, ESPACO, PAD_DIR = 11, 16, 8, 15
    BORDA = 1.5

    def __init__(self, pai, texto, variavel, valor=None, largura=None):
        self._var = variavel
        self._valor = valor
        self._texto = texto
        self._sobre = False
        self._imagens = {}
        self._fonte = tkfont.Font(family=FONTE, size=10, weight="bold")
        self._largura = max(largura or 0, self.PAD_ESQ + self.ICONE + self.ESPACO
                            + self._fonte.measure(texto) + self.PAD_DIR)
        super().__init__(pai, width=self._largura, height=self.ALTURA, bg=pai["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: self._clicar())
        self.bind("<Enter>", lambda e: self._mudar_sobre(True))
        self.bind("<Leave>", lambda e: self._mudar_sobre(False))
        self._trace = variavel.trace_add("write", lambda *_: self._desenhar())
        self.bind("<Destroy>", lambda e: self._soltar())
        self._desenhar()

    def _soltar(self):
        try:
            self._var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass

    def _ligado(self):
        if self._valor is None:
            return bool(self._var.get())
        return self._var.get() == self._valor

    def _clicar(self):
        if self._valor is None:
            self._var.set(not self._var.get())
        else:
            self._var.set(self._valor)

    def _mudar_sobre(self, sobre):
        self._sobre = sobre
        self._desenhar()

    def _imagem(self, ligado, sobre):
        chave = (ligado, sobre)
        if chave in self._imagens:
            return self._imagens[chave]
        if ligado:
            fundo, borda = ("#DCE8FF" if sobre else "#EAF1FF"), COR_AZUL
        else:
            fundo, borda = (("#F3F6FC", "#9DB6E6") if sobre else ("#FFFFFF", "#B8C4DC"))
        fundo, borda = _rgb(fundo), _rgb(borda)
        azul, branco = _rgb(COR_AZUL), (255, 255, 255)
        largura, altura, esp = self._largura, self.ALTURA, self.BORDA
        cx, cy = largura / 2, altura / 2
        ix, iy, ir = self.PAD_ESQ + self.ICONE / 2, cy, self.ICONE / 2
        a1, b1, c1 = (ix - 3.4, iy + 0.2), (ix - 0.9, iy + 2.9), (ix + 3.6, iy - 2.6)
        linhas = bytearray()
        for py in range(altura):
            linhas.append(0)
            y = py + 0.5
            for px in range(largura):
                x = px + 0.5
                pixel = (0.0, 0.0, 0.0, 0.0)
                pixel = _por_cima(pixel, borda, _cobertura(_dist_retangulo(x, y, cx, cy, cx, cy, cy)))
                pixel = _por_cima(pixel, fundo, _cobertura(
                    _dist_retangulo(x, y, cx, cy, cx - esp, cy - esp, cy - esp)))
                d_bola = math.hypot(x - ix, y - iy)
                if ligado:
                    pixel = _por_cima(pixel, azul, _cobertura(d_bola - ir))
                    d_certo = min(_dist_segmento(x, y, *a1, *b1), _dist_segmento(x, y, *b1, *c1))
                    pixel = _por_cima(pixel, branco, _cobertura(d_certo - 0.95))
                else:
                    pixel = _por_cima(pixel, borda, _cobertura(d_bola - ir))
                    pixel = _por_cima(pixel, fundo, _cobertura(d_bola - (ir - esp)))
                r, g, b, a = pixel
                if a <= 0:
                    linhas += b"\x00\x00\x00\x00"
                else:
                    linhas += bytes((round(r / a), round(g / a), round(b / a), round(a * 255)))
        self._imagens[chave] = tk.PhotoImage(
            data=base64.b64encode(_png_de_pixels(largura, altura, linhas)))
        return self._imagens[chave]

    def _desenhar(self):
        self.delete("all")
        ligado = self._ligado()
        self.create_image(0, 0, image=self._imagem(ligado, self._sobre), anchor="nw")
        cor = "#1F4FA8" if ligado else ("#17327A" if self._sobre else "#5F6F8F")
        self.create_text(self.PAD_ESQ + self.ICONE + self.ESPACO, self.ALTURA / 2,
                         text=self._texto, font=self._fonte, fill=cor, anchor="w")


def cartao(pai, titulo, numero):
    """Bloco branco com borda e título numerado: (externo, corpo, canto direito)."""
    externo = tk.Frame(pai, bg=COR_BORDA, bd=0)
    interno = tk.Frame(externo, bg=COR_CARTAO, bd=0)
    interno.pack(fill="both", expand=True, padx=1, pady=1)
    cab = tk.Frame(interno, bg=COR_CARTAO)
    cab.pack(fill="x", padx=18, pady=(12, 0))
    selo = tk.Canvas(cab, width=26, height=26, bg=COR_CARTAO, highlightthickness=0, bd=0)
    selo.disco = _imagem_disco(26, COR_AZUL)
    selo.create_image(0, 0, image=selo.disco, anchor="nw")
    selo.create_text(13, 13, text=str(numero), fill="white", font=(FONTE, 10, "bold"))
    selo.pack(side="left")
    tk.Label(cab, text=titulo, bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
             font=(FONTE, 12, "bold")).pack(side="left", padx=(9, 0))
    direita = tk.Frame(cab, bg=COR_CARTAO)
    direita.pack(side="right")
    corpo = tk.Frame(interno, bg=COR_CARTAO, bd=0)
    corpo.pack(fill="both", expand=True, padx=18, pady=(6, 14))
    return externo, corpo, direita


def configurar_estilo(raiz):
    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass
    estilo.configure("TFrame", background=COR_CARTAO)
    estilo.configure("TLabel", background=COR_CARTAO, foreground=COR_TEXTO, font=(FONTE, 10))
    estilo.configure("Campo.TEntry", fieldbackground="#FFFFFF", bordercolor="#CFD8EA",
                     lightcolor="#CFD8EA", darkcolor="#CFD8EA", borderwidth=1, padding=6)
    estilo.map("Campo.TEntry", bordercolor=[("focus", COR_AZUL)], lightcolor=[("focus", COR_AZUL)])
    estilo.configure("Campo.TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF",
                     bordercolor="#CFD8EA", lightcolor="#CFD8EA", darkcolor="#CFD8EA",
                     arrowcolor=COR_AZUL_ESCURO, padding=5)
    estilo.map("Campo.TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
               bordercolor=[("focus", COR_AZUL)])
    estilo.configure("TCheckbutton", background=COR_CARTAO, foreground=COR_TEXTO, font=(FONTE, 10))
    estilo.map("TCheckbutton", background=[("active", COR_CARTAO)])
    estilo.configure("Vertical.TScrollbar", background="#C9D3E8", troughcolor="#F1F4FA",
                     bordercolor="#F1F4FA", arrowcolor="#5B6B8D", relief="flat")
    estilo.configure("Lista.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF",
                     foreground=COR_TEXTO, rowheight=26, font=(FONTE, 10),
                     bordercolor=COR_BORDA, lightcolor=COR_BORDA, darkcolor=COR_BORDA, borderwidth=1)
    estilo.configure("Lista.Treeview.Heading", background=COR_LINHA, foreground=COR_AZUL_ESCURO,
                     font=(FONTE, 9, "bold"), relief="flat", bordercolor=COR_BORDA,
                     lightcolor=COR_LINHA, darkcolor=COR_BORDA, padding=(6, 5))
    estilo.map("Lista.Treeview", background=[("selected", "#DCE8FF")],
               foreground=[("selected", COR_AZUL_ESCURO)])
    estilo.map("Lista.Treeview.Heading", background=[("active", "#E6ECF7")])
    raiz.option_add("*TCombobox*Listbox.font", (FONTE, 10))
    raiz.option_add("*TCombobox*Listbox.selectBackground", "#DCE8FF")
    raiz.option_add("*TCombobox*Listbox.selectForeground", COR_AZUL_ESCURO)


def rotulo(pai, texto, fraco=False, negrito=False, tam=10, **k):
    return tk.Label(pai, text=texto, bg=pai["bg"],
                    fg=COR_TEXTO_FRACO if fraco else COR_TEXTO,
                    font=(FONTE, tam, "bold" if negrito else "normal"), anchor="w", **k)


def campo(pai, titulo, variavel, largura=None, opcoes=None, editavel=True):
    """Rótulo pequeno em cima + caixa de texto (ou lista de opções)."""
    quadro = tk.Frame(pai, bg=pai["bg"])
    tk.Label(quadro, text=titulo, bg=pai["bg"], fg=COR_TEXTO_FRACO,
             font=(FONTE, 9, "bold"), anchor="w").pack(anchor="w")
    if opcoes is not None:
        w = ttk.Combobox(quadro, textvariable=variavel, values=opcoes, style="Campo.TCombobox",
                         font=(FONTE, 10), state="normal" if editavel else "readonly")
    else:
        w = ttk.Entry(quadro, textvariable=variavel, style="Campo.TEntry", font=(FONTE, 10))
    if largura:
        w.configure(width=largura)
    w.pack(fill="x", pady=(2, 0))
    quadro.entrada = w
    return quadro


class Aplicacao(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(NOME_PROGRAMA)
        try:
            self.iconbitmap(caminho_recurso("icone_declaracoes.ico"))
        except tk.TclError:
            pass
        largura = min(960, self.winfo_screenwidth() - 40)
        # um pouco mais alta que o Frequência: o quadro 3 precisa caber inteiro com a Segoe UI
        altura = min(840, self.winfo_screenheight() - 80)
        self.geometry("{}x{}+{}+{}".format(
            largura, altura, (self.winfo_screenwidth() - largura) // 2,
            max((self.winfo_screenheight() - altura) // 2 - 20, 0)))
        self.minsize(860, 640)
        self.configure(bg=COR_FUNDO)

        self.cfg = dict(CONFIG_PADRAO)
        salvo = ler_json(ARQ_CONFIG, {})
        self.cfg.update(salvo)
        if "gestor_nome" not in salvo and salvo.get("assinante"):    # configuração da versão 1.0
            self.cfg["gestor_nome"] = salvo.get("assinante", "")
            self.cfg["gestor_cargo"] = salvo.get("cargo") or "Gestor(a) Escolar"
            self.cfg["gestor_registro"] = salvo.get("registro", "")
        banco = ler_json(ARQ_ALUNOS, {})
        self.alunos = banco.get("alunos", []) if isinstance(banco, dict) else []
        self.origem = banco.get("origem", "") if isinstance(banco, dict) else ""
        for a in self.alunos:
            a["_chave"] = sem_acento(" ".join((a.get("nome", ""), a.get("social", ""), a.get("matricula", ""))))
        self.alunos.sort(key=lambda a: a["_chave"])
        self.achados = []
        self.aluno = None               # aluno escolhido (cópia, pode ser corrigida)
        self.ultimo_arquivo = ""
        self.linhas_resultado = []
        self.escolhido = -1

        self.var_busca = tk.StringVar()
        self.var_tipo = tk.StringVar(value="matricula")
        self.var_status = tk.StringVar()
        self.ext = {k: tk.StringVar() for k in (
            "freq", "situacao", "destino", "prazo", "resultado", "proxima", "validade",
            "resp_nome", "resp_cpf", "hora_ini", "hora_fim", "motivo", "parentesco")}
        self.ext["parentesco"].set("Mãe")
        self.var_assina = tk.StringVar(value=self.cfg.get("assina") or "gestor")
        self.ext["prazo"].set("30")
        self.ext["validade"].set("5")
        self.ext["situacao"].set("Estava cursando")
        self.ext["resultado"].set("Aprovado(a)")
        self.ext["motivo"].set("atendimento na escola")

        configurar_estilo(self)
        self._montar_interface()
        self.var_busca.trace_add("write", lambda *_: self._atualizar_dica())
        self.var_tipo.trace_add("write", lambda *_: self._mostrar_extras())
        self.var_assina.trace_add("write", lambda *_: self._ao_mudar_assinatura())
        self.ext["parentesco"].trace_add("write", lambda *_: self._ao_mudar_parentesco())
        self._atualizar_banco()
        self._mostrar_extras()
        self._mostrar_aluno()
        self._parentesco_padrao({})
        self._atualizar_relogio()
        self.after(100, self.entrada_busca.focus_set)

    # -- montagem -------------------------------------------------------------

    def _montar_cabecalho(self):
        cab = tk.Canvas(self, height=ALTURA_CABECALHO, highlightthickness=0, bd=0, bg=COR_AZUL_ESCURO)
        cab.pack(fill="x")
        self.cabecalho = cab
        # Logo: folha com linhas e o "certo" verde (prima da prancheta do Frequência)
        _retangulo_arredondado(cab, 26, 19, 80, 73, 14, fill="#FFFFFF", outline="#FFFFFF")
        cab.create_polygon(40, 29, 58, 29, 66, 37, 66, 63, 40, 63, fill=COR_AZUL, outline=COR_AZUL)
        cab.create_polygon(58, 29, 58, 37, 66, 37, fill="#9DB6E6", outline="#9DB6E6")
        for yy in (40, 46):
            cab.create_line(45, yy, 56, yy, fill="#DCE8FF", width=2, capstyle="round")
        cab.create_line(46, 54, 51, 59, 60, 49, fill="#3DDC84", width=4,
                        capstyle="round", joinstyle="round")
        cab.create_text(98, 35, anchor="w", text=NOME_PROGRAMA, fill="white", font=(FONTE, 20, "bold"))
        cab.create_text(98, 63, anchor="w", fill="#D5E1F7", font=(FONTE, 9),
                        text="Pesquise o aluno pelo nome e gere a declaração pronta para imprimir.")
        self._id_escola = cab.create_text(0, 28, anchor="e", text="", fill="white", font=(FONTE, 9, "bold"))
        self._id_data = cab.create_text(0, 47, anchor="e", text="", fill="#D5E1F7", font=(FONTE, 9))
        self._id_config = cab.create_text(0, 66, anchor="e", text="Configuração", fill="white",
                                          tags="config", font=(FONTE, 9, "underline"))
        cab.tag_bind("config", "<Button-1>", lambda e: self._abrir_configuracao())
        cab.tag_bind("config", "<Enter>", lambda e: cab.configure(cursor="hand2"))
        cab.tag_bind("config", "<Leave>", lambda e: cab.configure(cursor=""))
        cab.bind("<Configure>", self._pintar_cabecalho)

    def _pintar_cabecalho(self, _evento=None):
        cab = self.cabecalho
        largura = max(cab.winfo_width(), 1)
        cab.delete("degrade")
        for x in range(0, largura, 4):
            cab.create_rectangle(x, 0, x + 4, ALTURA_CABECALHO, outline="", tags="degrade",
                                 fill=_misturar("#17327A", "#2A63C8", x / largura))
        cab.tag_lower("degrade")
        for item in (self._id_escola, self._id_data, self._id_config):
            cab.coords(item, largura - 26, cab.coords(item)[1])

    def _atualizar_relogio(self):
        agora = datetime.now()
        self.cabecalho.itemconfigure(self._id_escola, text=self.cfg.get("escola") or "Escola não cadastrada")
        self.cabecalho.itemconfigure(self._id_data, text="{}, {}".format(DIAS[agora.weekday()], hoje_extenso(agora)))
        self.after(60000, self._atualizar_relogio)

    def _montar_interface(self):
        self._montar_cabecalho()
        corpo = tk.Frame(self, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=26, pady=(18, 16))
        corpo.columnconfigure(0, weight=4, uniform="col")
        corpo.columnconfigure(1, weight=5, uniform="col")
        corpo.rowconfigure(1, weight=1)

        # 1 - Pesquisar aluno ------------------------------------------------
        externo, c1, direita = cartao(corpo, "Pesquisar aluno", 1)
        externo.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
        self.marca_banco = tk.Label(direita, text="", bg=COR_CARTAO, fg=COR_VERDE, font=(FONTE, 10, "bold"))
        self.marca_banco.pack(side="right")

        linha = tk.Frame(c1, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        caixa = tk.Frame(linha, bg=COR_CARTAO, highlightthickness=1, highlightbackground="#CFD8EA")
        caixa.pack(side="left", fill="x", expand=True)
        lupa = tk.Canvas(caixa, width=34, height=34, bg="#FFFFFF", highlightthickness=0, bd=0)
        lupa.create_oval(10, 9, 22, 21, outline=COR_AZUL_CLARO, width=2)
        lupa.create_line(20.5, 19.5, 26, 25, fill=COR_AZUL_CLARO, width=2.4, capstyle="round")
        lupa.pack(side="left", padx=(4, 0))
        self.entrada_busca = tk.Entry(caixa, textvariable=self.var_busca, bd=0, relief="flat",
                                      font=(FONTE, 12), bg="#FFFFFF", fg=COR_TEXTO,
                                      insertbackground=COR_AZUL_ESCURO, highlightthickness=0)
        self.entrada_busca.pack(side="left", fill="x", expand=True, ipady=6, padx=(2, 10))
        self.entrada_busca.bind("<FocusIn>", lambda e: caixa.configure(highlightbackground=COR_AZUL))
        self.entrada_busca.bind("<FocusOut>", lambda e: caixa.configure(highlightbackground="#CFD8EA"))
        self.entrada_busca.bind("<Return>", lambda e: self._pesquisar())
        self.entrada_busca.bind("<KP_Enter>", lambda e: self._pesquisar())
        self.dica_busca = tk.Label(caixa, text="Digite o nome do aluno (ou parte dele) ou o código",
                                   bg="#FFFFFF", fg="#9AA5B8", font=(FONTE, 12), cursor="xterm")
        self.dica_busca.place(x=38, rely=0.5, anchor="w")
        self.dica_busca.bind("<Button-1>", lambda e: self.entrada_busca.focus_set())
        self.botao_pesquisar = Botao(linha, "Pesquisar", self._pesquisar, estilo="azul",
                                     fonte=(FONTE, 11, "bold"), pad_x=26, pad_y=8)
        self.botao_pesquisar.pack(side="left", padx=(10, 0))

        # Resultado da pesquisa: só aparece depois de clicar em Pesquisar
        self.area_result = tk.Frame(c1, bg=COR_CARTAO, height=96)
        self.area_result.pack(fill="x", pady=(10, 0))
        self.area_result.pack_propagate(False)
        self.dica_result = tk.Label(self.area_result, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                                    font=(FONTE, 9), anchor="nw", justify="left")
        self.quadro_lista = tk.Frame(self.area_result, bg=COR_CARTAO)
        self.rolagem = ttk.Scrollbar(self.quadro_lista, orient="vertical")
        self.tela = tk.Canvas(self.quadro_lista, bg=COR_CARTAO, highlightthickness=0, bd=0,
                              yscrollcommand=self.rolagem.set)
        self.rolagem.configure(command=self.tela.yview)
        self.tela.pack(side="left", fill="both", expand=True)
        self.linhas = tk.Frame(self.tela, bg=COR_CARTAO)
        self._janela_linhas = self.tela.create_window((0, 0), window=self.linhas, anchor="nw")
        self.linhas.bind("<Configure>", lambda e: self._ajustar_rolagem())
        self.tela.bind("<Configure>", lambda e: (self.tela.itemconfigure(self._janela_linhas, width=e.width),
                                                 self._ajustar_rolagem()))
        self.bind_all("<MouseWheel>", self._roda_do_mouse)

        self.vazio = tk.Frame(self.area_result, bg=COR_LINHA, highlightthickness=1, highlightbackground=COR_BORDA)
        tk.Label(self.vazio, text="Ainda não há alunos no banco de dados.", bg=COR_LINHA,
                 fg=COR_AZUL_ESCURO, font=(FONTE, 10, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        tk.Label(self.vazio, text="Abra o arquivo de alunos do sistema da SEMED (TXTALUNO) na Configuração. "
                 "Ele fica guardado e só precisa ser aberto de novo quando a lista mudar.",
                 justify="left", wraplength=820, bg=COR_LINHA, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9)).pack(anchor="w", padx=14)
        Botao(self.vazio, "Abrir a Configuração", self._abrir_configuracao, estilo="tracejado",
              pad_y=5).pack(anchor="w", padx=14, pady=(8, 10))

        # 2 - Aluno escolhido -------------------------------------------------
        externo, c2, self.canto_aluno = cartao(corpo, "Aluno", 2)
        externo.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.botao_corrigir = Botao(self.canto_aluno, "Corrigir", self._corrigir_aluno,
                                    estilo="tracejado", fonte=(FONTE, 9, "bold"), pad_y=3, pad_x=10, raio=8)
        self.nome_aluno = tk.Label(c2, text="", bg=COR_CARTAO, fg=COR_AZUL_ESCURO, font=(FONTE, 12, "bold"),
                                   anchor="w", justify="left", wraplength=340)
        self.nome_aluno.pack(fill="x")
        self.info_aluno = tk.Frame(c2, bg=COR_CARTAO)
        self.info_aluno.pack(fill="x", pady=(4, 0))
        self.info_aluno.columnconfigure(1, weight=1)
        self.alerta_aluno = tk.Label(c2, text="", bg=COR_CARTAO, fg=COR_LARANJA, font=(FONTE, 9, "bold"),
                                     anchor="w", justify="left", wraplength=340)
        self.alerta_aluno.pack(fill="x", pady=(4, 0))

        # 3 - Tipo de declaração ---------------------------------------------
        externo, c3, _ = cartao(corpo, "Tipo de declaração", 3)
        externo.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        grade = tk.Frame(c3, bg=COR_CARTAO)
        grade.pack(fill="x")
        for chaves in FILEIRAS_TIPOS:
            fileira = tk.Frame(grade, bg=COR_CARTAO)
            fileira.pack(fill="x", pady=(0, 4))
            for chave in chaves:
                Chip(fileira, NOME_TIPO[chave], self.var_tipo, chave).pack(side="left", padx=(0, 6))
        self.area_extras = tk.Frame(c3, bg=COR_CARTAO)
        self.area_extras.pack(fill="both", expand=True, pady=(4, 0))
        self._montar_extras()

        # Ação ---------------------------------------------------------------
        acao = tk.Frame(corpo, bg=COR_FUNDO)
        acao.grid(row=2, column=0, columnspan=2, sticky="ew")
        assina = tk.Frame(acao, bg=COR_FUNDO)
        assina.pack(side="left", padx=(0, 12))
        tk.Label(assina, text="Quem assina", bg=COR_FUNDO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(anchor="w")
        chips = tk.Frame(assina, bg=COR_FUNDO)
        chips.pack(anchor="w")
        Chip(chips, "Gestor(a)", self.var_assina, "gestor").pack(side="left", padx=(0, 6))
        Chip(chips, "Secretário(a)", self.var_assina, "secretario").pack(side="left")
        self.botao_gerar = Botao(acao, "▶   Gerar declaração", self._gerar, estilo="principal",
                                 fonte=(FONTE, 14, "bold"), pad_y=11, raio=12)
        self.botao_gerar.pack(side="left", fill="x", expand=True, pady=(4, 0))
        self.botao_abrir = Botao(acao, "Abrir pasta", self._abrir_pasta, estilo="suave",
                                 pad_x=24, pad_y=11, raio=12)
        self.botao_abrir.pack(side="left", padx=(10, 0), pady=(4, 0))
        tk.Label(corpo, textvariable=self.var_status, bg=COR_FUNDO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9), anchor="w").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _montar_extras(self):
        """Campos que só alguns tipos de declaração pedem."""
        e = self.ext
        self.extras = {}
        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        rotulo(f, "Não precisa de mais nada. É só gerar.", fraco=True, tam=9).pack(anchor="w")
        self.extras["matricula"] = f

        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        campo(f, "Frequência % (opcional)", e["freq"], largura=12).pack(anchor="w")
        self.extras["frequencia"] = f

        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        f.columnconfigure(0, weight=1)
        campo(f, "Situação do aluno", e["situacao"], opcoes=[
            "Estava cursando", "Aprovado(a)", "Reprovado(a)", "Não informar"], editavel=False
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        campo(f, "Histórico (dias)", e["prazo"], largura=8).grid(row=0, column=1, sticky="w")
        campo(f, "Escola de destino (opcional)", e["destino"]).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.extras["transferencia"] = f

        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        f.columnconfigure(0, weight=1)
        campo(f, "Resultado", e["resultado"], opcoes=["Aprovado(a)", "Aprovado(a) pelo Conselho de Classe"],
              editavel=False).grid(row=0, column=0, sticky="ew")
        campo(f, "Apto(a) a cursar", e["proxima"]).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.extras["conclusao"] = f

        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        self.chips_resp = tk.Frame(f, bg=COR_CARTAO)
        self.chips_resp.pack(fill="x")
        self.linha_resp = tk.Frame(f, bg=COR_CARTAO, height=32)
        self.linha_resp.pack(fill="x", pady=(4, 0))
        self.linha_resp.pack_propagate(False)
        self.nome_resp = tk.Label(self.linha_resp, text="", bg=COR_CARTAO, fg=COR_TEXTO,
                                  font=(FONTE, 10), anchor="w")
        self.outro_resp = tk.Frame(self.linha_resp, bg=COR_CARTAO)
        tk.Label(self.outro_resp, text="Nome:", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(side="left", padx=(0, 6))
        self.entrada_outro = ttk.Entry(self.outro_resp, textvariable=e["resp_nome"], style="Campo.TEntry",
                                       font=(FONTE, 10))
        self.entrada_outro.pack(side="left", fill="x", expand=True)
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        campo(linha, "Motivo", e["motivo"], opcoes=[
            "atendimento na escola", "reunião de pais e mestres", "atendimento com a equipe pedagógica",
            "atendimento com a gestão escolar", "entrega de boletim"]).pack(side="left", fill="x", expand=True)
        for titulo, chave in (("Entrada", "hora_ini"), ("Saída", "hora_fim")):
            q = campo(linha, titulo, e[chave], largura=7)
            q.entrada.configure(justify="center")
            q.pack(side="left", padx=(8, 0))
            e[chave].trace_add("write", lambda *_, v=e[chave], w=q.entrada: self._mascara_hora(v, w))
        self.extras["comparecimento"] = f

        # Justificativa de falta: o que não vem do arquivo se preenche aqui
        t = self.termo = {k: tk.StringVar() for k in (
            "data_falta", "qtd_faltas", "bolsa", "motivo", "motivo_outro", "resp_nome", "telefone",
            "profissao", "horario", "c_nome", "c_cpf")}
        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x")
        campo(linha, "Data da falta", t["data_falta"]).pack(side="left", fill="x", expand=True)
        campo(linha, "Qtd. de faltas", t["qtd_faltas"], largura=8).pack(side="left", padx=(8, 0))
        campo(linha, "Bolsa Família", t["bolsa"], opcoes=["", "Sim", "Não"], editavel=False,
              largura=7).pack(side="left", padx=(8, 0))
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        campo(linha, "Motivo da ausência", t["motivo"], editavel=False,
              opcoes=["(em branco)"] + MOTIVOS_FALTA + ["Outro"]).pack(side="left", fill="x", expand=True)
        self.campo_motivo_outro = campo(linha, "Qual?", t["motivo_outro"], largura=18)
        t["motivo"].trace_add("write", lambda *_: self._ao_mudar_motivo())
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        q = campo(linha, "Responsável (escolha ou digite outro nome)", t["resp_nome"], opcoes=[])
        q.pack(side="left", fill="x", expand=True)
        self.combo_resp_just = q.entrada
        campo(linha, "Telefone/WhatsApp", t["telefone"], largura=15).pack(side="left", padx=(8, 0))
        self.extras["justificativa"] = f

        # Termo de compromisso: o que vem do arquivo aparece para conferir; o resto se preenche aqui
        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        self.info_compromisso = tk.Label(f, text="", bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 9),
                                         anchor="w", justify="left", wraplength=440)
        self.info_compromisso.pack(fill="x")
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(6, 0))
        q = campo(linha, "Responsável (escolha ou digite outro nome)", t["c_nome"], opcoes=[])
        q.pack(side="left", fill="x", expand=True)
        self.combo_resp_comp = q.entrada
        q = campo(linha, "CPF", t["c_cpf"], largura=16)
        q.pack(side="left", padx=(8, 0))
        t["c_cpf"].trace_add("write", lambda *_, w=q.entrada: self._mascara_cpf(t["c_cpf"], w))
        t["c_nome"].trace_add("write", lambda *_: self._ao_mudar_resp_comp())
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        campo(linha, "Profissão do responsável", t["profissao"]).pack(side="left", fill="x", expand=True)
        q = campo(linha, "Horário", t["horario"], largura=7)
        q.entrada.configure(justify="center")
        q.pack(side="left", padx=(8, 0))
        t["horario"].trace_add("write", lambda *_, w=q.entrada: self._mascara_hora(t["horario"], w))
        self.extras["compromisso"] = f

    def _ao_mudar_motivo(self):
        if self.termo["motivo"].get() == "Outro":
            self.campo_motivo_outro.pack(side="left", padx=(8, 0))
            self.campo_motivo_outro.entrada.focus_set()
        else:
            self.campo_motivo_outro.pack_forget()

    def _preparar_termos(self, a):
        """Ao escolher o aluno: limpa os campos dos termos e mostra o que vem do arquivo."""
        t = self.termo
        for k in ("data_falta", "qtd_faltas", "bolsa", "motivo_outro", "profissao", "c_nome", "c_cpf"):
            t[k].set("")
        t["motivo"].set("(em branco)")
        t["telefone"].set(a.get("telefone", ""))
        nomes = [n for _r, n in self._responsaveis(a)]
        if a.get("responsavel") and a["responsavel"] not in nomes:
            nomes.insert(0, a["responsavel"])
        self.combo_resp_just.configure(values=nomes)
        t["resp_nome"].set(a.get("responsavel") or (nomes[0] if nomes else ""))
        t["horario"].set(datetime.now().strftime("%H:%M"))
        self.combo_resp_comp.configure(values=nomes)
        self._cpf_automatico = ""
        t["c_nome"].set(a.get("responsavel") or (nomes[0] if nomes else ""))
        self._ao_mudar_resp_comp()
        self.info_compromisso.configure(text="Endereço, bairro, telefone, série, turma e turno saem do arquivo. "
                                             "Confira o responsável e o CPF; o que ficar vazio sai em branco no papel.")

    def _mascara_cpf(self, var, entrada):
        """CPF no formato 000.000.000-00 enquanto digita."""
        atual = var.get()
        n = re.sub(r"\D", "", atual)[:11]
        partes = [n[:3], n[3:6], n[6:9]]
        certo = ".".join(p for p in partes if p)
        if len(n) > 9:
            certo += "-" + n[9:]
        if certo != atual:
            var.set(certo)
            entrada.icursor("end")

    def _ao_mudar_resp_comp(self):
        """O CPF do arquivo é de quem fez a matrícula: entra quando esse nome é o escolhido."""
        if not self.aluno:
            return
        a, t = self.aluno, self.termo
        nome = t["c_nome"].get().strip()
        cpf_atual = t["c_cpf"].get()
        self._cpf_automatico = getattr(self, "_cpf_automatico", "")
        if a.get("cpf_resp") and a.get("responsavel") and sem_acento(nome) == sem_acento(a["responsavel"]):
            if not cpf_atual or cpf_atual == self._cpf_automatico:
                t["c_cpf"].set(a["cpf_resp"])
                self._cpf_automatico = t["c_cpf"].get()
        elif cpf_atual and cpf_atual == self._cpf_automatico:
            t["c_cpf"].set("")                     # trocou de pessoa: o CPF do arquivo não serve
            self._cpf_automatico = ""

    def _dados_termo_preenchidos(self, tipo):
        t = {k: v.get().strip() for k, v in self.termo.items()}
        d = dados_termo(self.aluno)
        if tipo == "justificativa":
            d.update(data_falta=t["data_falta"], qtd_faltas=t["qtd_faltas"], bolsa=t["bolsa"],
                     motivo=None if t["motivo"] in ("", "(em branco)") else t["motivo"],
                     motivo_outro=t["motivo_outro"], resp_nome=t["resp_nome"], telefone=t["telefone"])
        else:
            a = self.aluno
            nome = t["c_nome"]
            if nome and sem_acento(nome) == sem_acento(a.get("mae")):
                parentesco = "mae"
            elif nome and sem_acento(nome) == sem_acento(a.get("pai")):
                parentesco = "pai"
            else:
                parentesco = "responsavel" if nome else ""
            d.update(profissao=t["profissao"], horario=t["horario"], resp_nome=nome,
                     cpf=t["c_cpf"], parentesco=parentesco)
        return d

    def _mascara_hora(self, var, entrada):
        """Hora sempre no formato 00:00: só números, os dois-pontos entram sozinhos."""
        atual = var.get()
        numeros = re.sub(r"\D", "", atual)[:4]
        certo = numeros if len(numeros) <= 2 else numeros[:2] + ":" + numeros[2:]
        if certo != atual:
            var.set(certo)
            entrada.icursor("end")

    @staticmethod
    def _hora_valida(texto):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", texto or "")
        return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60

    def _mostrar_extras(self):
        for chave, quadro in self.extras.items():
            if chave == self.var_tipo.get():
                quadro.pack(fill="x")
            else:
                quadro.pack_forget()

    # -- banco de dados e pesquisa ------------------------------------------

    def _atualizar_banco(self):
        tem = bool(self.alunos)
        self.marca_banco.configure(text="✓  {} alunos no banco de dados".format(len(self.alunos)) if tem else "")
        self.botao_pesquisar.definir_ativo(tem)
        self._limpar_resultados()
        if tem:
            self._mostrar_dica("Digite o nome do aluno (ou só uma parte dele) e clique em Pesquisar.\n"
                               "Os alunos encontrados aparecem aqui; clique no certo.")
            self.var_status.set("Pesquise o aluno, escolha o tipo de declaração e clique em Gerar declaração.")
        else:
            self.dica_result.place_forget()
            self.quadro_lista.place_forget()
            self.vazio.place(x=0, y=0, relwidth=1, relheight=1)
            self.var_status.set("Comece abrindo o arquivo de alunos na Configuração.")
        self._atualizar_dica()

    def _atualizar_dica(self):
        if self.var_busca.get():
            self.dica_busca.place_forget()
        else:
            self.dica_busca.place(x=38, rely=0.5, anchor="w")

    def _mostrar_dica(self, texto):
        self.vazio.place_forget()
        self.quadro_lista.place_forget()
        self.dica_result.configure(text=texto)
        self.dica_result.place(x=0, y=0, relwidth=1, relheight=1)

    def _limpar_resultados(self):
        for w in self.linhas.winfo_children():
            w.destroy()
        self.linhas_resultado = []
        self.achados = []
        self.escolhido = -1

    def _ajustar_rolagem(self):
        self.tela.configure(scrollregion=self.tela.bbox("all"))
        precisa = self.linhas.winfo_reqheight() > self.tela.winfo_height() + 2
        if precisa and not self.rolagem.winfo_ismapped():
            self.rolagem.pack(side="right", fill="y", before=self.tela)
        elif not precisa and self.rolagem.winfo_ismapped():
            self.rolagem.pack_forget()

    def _roda_do_mouse(self, evento):
        alvo = self.winfo_containing(evento.x_root, evento.y_root)
        while alvo is not None and alvo is not self.quadro_lista:
            alvo = alvo.master
        if alvo is not None and self.rolagem.winfo_ismapped():
            self.tela.yview_scroll(int(-evento.delta / 120) or (-1 if evento.delta > 0 else 1), "units")

    def _pesquisar(self):
        if not self.alunos:
            return
        q = sem_acento(self.var_busca.get())
        termos = q.split()
        self._limpar_resultados()
        self.aluno = None               # pesquisa nova: escolhe de novo
        self._mostrar_aluno()
        if not termos:
            self._mostrar_dica("Digite o nome do aluno (ou só uma parte dele) e clique em Pesquisar.")
            self.entrada_busca.focus_set()
            return
        achados = [a for a in self.alunos if all(t in a["_chave"] for t in termos)]
        achados.sort(key=lambda a: (not a["_chave"].startswith(q), a["_chave"]))
        if not achados:
            self._mostrar_dica("Nenhum aluno encontrado com “{}”.\nConfira a grafia ou digite só uma parte "
                               "do nome (por exemplo, o primeiro nome e o último sobrenome).".format(self.var_busca.get().strip()))
            self.var_status.set("Nenhum aluno encontrado.")
            return
        self.achados = achados[:100]
        self.dica_result.place_forget()
        self.vazio.place_forget()
        self.quadro_lista.place(x=0, y=0, relwidth=1, relheight=1)
        for i, a in enumerate(self.achados):
            self._linha_resultado(i, a)
        self.tela.yview_moveto(0)
        self.after_idle(self._ajustar_rolagem)
        if len(achados) == 1:
            self._clicar_resultado(0)
            self.var_status.set("1 aluno encontrado e escolhido. Escolha o tipo e clique em Gerar declaração.")
        else:
            extra = " (mostrando os 100 primeiros)" if len(achados) > 100 else ""
            self.var_status.set("{} alunos encontrados{}. Clique no aluno certo.".format(len(achados), extra))

    def _linha_resultado(self, i, a):
        linha = tk.Frame(self.linhas, bg=COR_LINHA, highlightthickness=1, highlightbackground=COR_BORDA,
                         cursor="hand2")
        linha.pack(fill="x", pady=(0, 4), padx=(0, 4))
        nome = tk.Label(linha, text=a.get("social") or a.get("nome"), bg=COR_LINHA, fg=COR_TEXTO,
                        font=(FONTE, 10, "bold"), anchor="w", cursor="hand2")
        nome.pack(side="left", padx=(12, 10), pady=5)
        partes = [" – ".join(v for v in (a.get("serie"), a.get("turma") and "turma " + a["turma"]) if v),
                  a.get("nasc") and "nasc. " + data_br(a["nasc"]),
                  a.get("matricula") and "cód. " + a["matricula"]]
        detalhe = tk.Label(linha, text="   ·   ".join(p for p in partes if p), bg=COR_LINHA,
                           fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w", cursor="hand2")
        detalhe.pack(side="left")
        seta = tk.Label(linha, text="Escolher  ›", bg=COR_LINHA, fg=COR_AZUL, font=(FONTE, 9, "bold"),
                        cursor="hand2")
        seta.pack(side="right", padx=12)
        partes_linha = (linha, nome, detalhe, seta)
        for w in partes_linha:
            w.bind("<Button-1>", lambda e, n=i: self._clicar_resultado(n))
            w.bind("<Double-1>", lambda e, n=i: (self._clicar_resultado(n), self._gerar()))
            w.bind("<Enter>", lambda e, n=i: self._pintar_linha(n, sobre=True))
            w.bind("<Leave>", lambda e, n=i: self._pintar_linha(n, sobre=False))
        self.linhas_resultado.append(partes_linha)

    def _pintar_linha(self, n, sobre=False):
        if n >= len(self.linhas_resultado):
            return
        linha, nome, detalhe, seta = self.linhas_resultado[n]
        if n == self.escolhido:
            fundo, borda, texto_seta = "#DCE8FF", COR_AZUL, "✓  Escolhido"
        elif sobre:
            fundo, borda, texto_seta = "#EAF1FF", "#9DB6E6", "Escolher  ›"
        else:
            fundo, borda, texto_seta = COR_LINHA, COR_BORDA, "Escolher  ›"
        linha.configure(bg=fundo, highlightbackground=borda)
        for w in (nome, detalhe, seta):
            w.configure(bg=fundo)
        seta.configure(text=texto_seta, fg=COR_VERDE if n == self.escolhido else COR_AZUL)

    def _clicar_resultado(self, n):
        anterior, self.escolhido = self.escolhido, n
        if 0 <= anterior < len(self.linhas_resultado):
            self._pintar_linha(anterior)
        self._pintar_linha(n)
        self._escolher(self.achados[n])

    def _escolher(self, a):
        self.aluno = {k: v for k, v in a.items() if not k.startswith("_")}
        agora = datetime.now()
        self.ext["proxima"].set(proxima_serie(a.get("serie")))
        self._parentesco_padrao(self.aluno)
        self._preparar_termos(self.aluno)
        self.ext["hora_fim"].set(agora.strftime("%H:%M"))
        self.ext["hora_ini"].set("{:02d}:{:02d}".format(max(agora.hour - 1, 0), agora.minute))
        self.ext["freq"].set("")
        self.ext["destino"].set("")
        self._mostrar_aluno()
        self.var_status.set("Escolha o tipo de declaração e clique em Gerar declaração.")

    def _responsaveis(self, a):
        """Responsáveis do aluno que vieram no arquivo: [(rótulo, nome)]."""
        lista = [("Mãe", a.get("mae")), ("Pai", a.get("pai"))]
        if a.get("responsavel") and a["responsavel"] not in (a.get("mae"), a.get("pai")):
            lista.append(("Responsável", a["responsavel"]))
        return [(r, n) for r, n in lista if n]

    def _parentesco_padrao(self, a):
        """Monta as pílulas com quem pode receber a declaração de comparecimento."""
        for w in self.chips_resp.winfo_children():
            w.destroy()
        tk.Label(self.chips_resp, text="Quem compareceu", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(anchor="w")
        linha = tk.Frame(self.chips_resp, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(2, 0))
        opcoes = self._responsaveis(a)
        for rotulo_, _nome in opcoes:
            Chip(linha, rotulo_, self.ext["parentesco"], rotulo_).pack(side="left", padx=(0, 6))
        Chip(linha, "Outra pessoa", self.ext["parentesco"], "Outra pessoa").pack(side="left")
        escolha = opcoes[0][0] if opcoes else "Outra pessoa"
        self.ext["resp_nome"].set("")
        if self.ext["parentesco"].get() == escolha:
            self._ao_mudar_parentesco()
        else:
            self.ext["parentesco"].set(escolha)

    def _ao_mudar_parentesco(self):
        a = self.aluno or {}
        escolha = self.ext["parentesco"].get()
        nome = dict(self._responsaveis(a)).get(escolha, "")
        if nome:
            self.ext["resp_nome"].set(nome)
            self.outro_resp.pack_forget()
            self.nome_resp.configure(text="{}:  {}".format(escolha, nome), font=(FONTE, 10, "bold"))
            self.nome_resp.pack(fill="x", pady=(4, 0))
        else:
            self.ext["resp_nome"].set("")
            self.nome_resp.pack_forget()
            self.outro_resp.pack(fill="x", pady=(2, 0))
            if self.aluno and self.var_tipo.get() == "comparecimento":
                self.entrada_outro.focus_set()

    def _ao_mudar_assinatura(self):
        quem = self.var_assina.get()
        self.cfg["assina"] = quem
        gravar_json(ARQ_CONFIG, self.cfg)
        if not self.cfg.get(quem + "_nome"):
            self.var_status.set("O nome do {} ainda não foi cadastrado na Configuração; a declaração sai só "
                                "com a linha para assinatura.".format("gestor(a)" if quem == "gestor" else "secretário(a)"))

    def _mostrar_aluno(self):
        a = self.aluno
        if not a:
            self.nome_aluno.configure(text="Nenhum aluno escolhido", fg=COR_TEXTO_FRACO)
            for w in self.info_aluno.winfo_children():
                w.destroy()
            tk.Label(self.info_aluno, text="Pesquise acima e clique no nome do aluno.", bg=COR_CARTAO,
                     fg=COR_TEXTO, font=(FONTE, 9)).grid(row=0, column=0, sticky="w")
            self.alerta_aluno.configure(text="")
            self.botao_corrigir.pack_forget()
            self.botao_gerar.definir_ativo(False)
            return
        self.nome_aluno.configure(text=a.get("social") or a.get("nome"), fg=COR_AZUL_ESCURO)
        for w in self.info_aluno.winfo_children():
            w.destroy()
        itens = []
        turma = " · ".join(v for v in (a.get("serie"), a.get("turma") and "Turma " + a["turma"], a.get("turno")) if v)
        itens.append(("Turma", turma))
        if a.get("nasc"):
            anos = idade(a["nasc"])
            itens.append(("Nascimento", "{}{}".format(data_br(a["nasc"]), " ({} anos)".format(anos) if anos is not None else "")))
        sexo = {"F": "Feminino", "M": "Masculino"}.get(a.get("sexo"), "")
        itens.append(("Código", "   ·   ".join(v for v in (a.get("matricula"), sexo) if v)))
        itens.append(("Mãe", a.get("mae")))
        itens.append(("Pai", a.get("pai")))
        if a.get("responsavel") and a["responsavel"] not in (a.get("mae"), a.get("pai")):
            itens.append(("Responsável", a["responsavel"]))
        endereco = a.get("endereco", "")
        if a.get("bairro") and sem_acento(a["bairro"]) not in sem_acento(endereco):
            endereco = " – ".join(v for v in (endereco, a["bairro"]) if v)
        if a.get("cep"):
            endereco += ("   ·   " if endereco else "") + "CEP " + a["cep"]
        itens.append(("Endereço", endereco))
        itens.append(("Telefone", "   ·   ".join(v for v in (a.get("telefone"), a.get("telefone2")) if v)))
        for i, (titulo, valor) in enumerate(itens):
            tk.Label(self.info_aluno, text=titulo, bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9, "bold"),
                     anchor="nw").grid(row=i, column=0, sticky="nw", padx=(0, 10), pady=1)
            tk.Label(self.info_aluno, text=valor or "não consta no arquivo", bg=COR_CARTAO,
                     fg=COR_TEXTO if valor else "#A0A8B8", font=(FONTE, 9), anchor="nw", justify="left",
                     wraplength=270).grid(row=i, column=1, sticky="nw", pady=1)
        faltam = [n for n, k in (("sexo", "sexo"), ("fase/ano", "serie"), ("nascimento", "nasc")) if not a.get(k)]
        self.alerta_aluno.configure(text="Faltou na lista: " + ", ".join(faltam) + ". Use “Corrigir”." if faltam else "")
        self.botao_corrigir.pack(side="right")
        self.botao_gerar.definir_ativo(True)

    # -- correção dos dados do aluno ----------------------------------------

    def _corrigir_aluno(self):
        if not self.aluno:
            return
        janela = tk.Toplevel(self)
        janela.title("Corrigir dados do aluno")
        janela.configure(bg=COR_FUNDO)
        janela.transient(self)
        janela.resizable(False, False)
        externo, c, _ = cartao(janela, "Dados só para esta declaração", "✎")
        externo.pack(fill="both", expand=True, padx=18, pady=18)
        a = self.aluno
        vars_ = {k: tk.StringVar(value=a.get(k, "")) for k in
                 ("nome", "social", "matricula", "nasc", "mae", "pai", "responsavel", "serie", "turma", "turno",
                  "endereco", "telefone", "telefone2")}
        vars_["nasc"].set(data_br(a.get("nasc")))
        sexo = tk.StringVar(value={"F": "Feminino", "M": "Masculino"}.get(a.get("sexo"), "Não informado"))
        g = tk.Frame(c, bg=COR_CARTAO)
        g.pack(fill="both")
        for col in range(2):
            g.columnconfigure(col, weight=1, minsize=210)
        itens = [("Nome completo", "nome", 0, 0, 2), ("Nome social", "social", 1, 0, 1),
                 ("Código do aluno", "matricula", 1, 1, 1), ("Nascimento (dd/mm/aaaa)", "nasc", 2, 0, 1),
                 ("Fase / ano", "serie", 3, 0, 1), ("Turma", "turma", 3, 1, 1),
                 ("Mãe", "mae", 4, 0, 1), ("Pai", "pai", 4, 1, 1), ("Responsável", "responsavel", 5, 0, 1),
                 ("Endereço", "endereco", 6, 0, 2), ("Telefone", "telefone", 7, 0, 1),
                 ("Outro telefone", "telefone2", 7, 1, 1)]
        for titulo, k, lin, col, span in itens:
            campo(g, titulo, vars_[k]).grid(row=lin, column=col, columnspan=span, sticky="ew", padx=4, pady=4)
        campo(g, "Sexo", sexo, opcoes=["Feminino", "Masculino", "Não informado"], editavel=False).grid(
            row=2, column=1, sticky="ew", padx=4, pady=4)
        campo(g, "Turno", vars_["turno"], opcoes=["", "Matutino", "Vespertino", "Noturno", "Integral"],
              editavel=False).grid(row=5, column=1, sticky="ew", padx=4, pady=4)
        rotulo(c, "A correção vale só para esta declaração; o banco de dados não muda.",
               fraco=True, tam=9).pack(anchor="w", pady=(8, 0))

        def salvar():
            novo = {k: v.get().strip() for k, v in vars_.items()}
            p = partes_data(novo["nasc"])
            novo["nasc"] = "{:04d}-{:02d}-{:02d}".format(*p) if p else ""
            novo["sexo"] = {"Feminino": "F", "Masculino": "M"}.get(sexo.get(), "")
            novo["etapa"] = etapa_da_serie(novo["serie"]) or a.get("etapa", "")
            self.aluno.update(novo)
            self.ext["proxima"].set(proxima_serie(novo["serie"]))
            self._mostrar_aluno()
            self._parentesco_padrao(self.aluno)
            janela.destroy()

        botoes = tk.Frame(c, bg=COR_CARTAO)
        botoes.pack(fill="x", pady=(12, 0))
        Botao(botoes, "Usar estes dados", salvar, estilo="principal").pack(side="right")
        Botao(botoes, "Cancelar", janela.destroy).pack(side="right", padx=(0, 8))
        janela.grab_set()

    # -- gerar ----------------------------------------------------------------

    def _extras_atuais(self):
        e = {k: v.get().strip() for k, v in self.ext.items()}
        e["situacao"] = {"Estava cursando": "cursando", "Aprovado(a)": "aprovado",
                         "Reprovado(a)": "reprovado"}.get(e["situacao"], "")
        e["resultado"] = "conselho" if "Conselho" in e["resultado"] else "aprovado"
        e["parentesco"] = {"Mãe": "mae", "Pai": "pai"}.get(e["parentesco"], "responsavel")
        return e

    def _gerar(self):
        if not self.aluno:
            self.var_status.set("Escolha um aluno primeiro.")
            return
        if self.var_tipo.get() in TERMOS:
            tipo = self.var_tipo.get()
            if tipo == "compromisso" and self.termo["horario"].get() and not self._hora_valida(self.termo["horario"].get()):
                self.var_status.set("Confira o horário (formato 14:30).")
                return
            if tipo == "compromisso" and len(re.sub(r"\D", "", self.termo["c_cpf"].get())) not in (0, 11):
                self.var_status.set("O CPF do responsável está incompleto: são 11 números (ou deixe vazio).")
                return
            if tipo == "justificativa" and self.termo["motivo"].get() == "Outro" and not self.termo["motivo_outro"].get().strip():
                self.var_status.set("Escreva qual é o outro motivo.")
                return
            self.gerar_termo(tipo, self._dados_termo_preenchidos(tipo))
            return
        if self.var_tipo.get() == "comparecimento":
            if not self.ext["resp_nome"].get().strip():
                self.var_status.set("Digite o nome da pessoa que compareceu.")
                self.entrada_outro.focus_set()
                return
            for chave, nome in (("hora_ini", "entrada"), ("hora_fim", "saída")):
                if not self._hora_valida(self.ext[chave].get()):
                    self.var_status.set("Confira a hora de {} (use o formato 14:30).".format(nome))
                    return
            if self.ext["hora_fim"].get() < self.ext["hora_ini"].get().zfill(5):
                self.var_status.set("A hora de saída está antes da hora de entrada.")
                return
        cfg = self.cfg
        if not cfg.get("pdf") and not cfg.get("word"):
            cfg["pdf"] = True
        quem = self.var_assina.get()
        doc = dict(cfg, assinante=cfg.get(quem + "_nome", ""),
                   cargo=cfg.get(quem + "_cargo") or ("Gestor(a) Escolar" if quem == "gestor" else "Secretário(a) Escolar"),
                   registro=cfg.get(quem + "_registro", ""))
        tipo = self.var_tipo.get()
        agora = datetime.now()
        numero = int(cfg.get("numero") or 1) if cfg.get("numerar", True) else None
        numero_txt = "Nº {:03d}/{}".format(numero, agora.year) if numero else ""
        paras = paragrafos(tipo, self.aluno, self._extras_atuais(), agora.year)

        pasta = cfg.get("pasta_saida") or os.path.join(pasta_documentos(), "Declarações Escolares")
        pasta = os.path.join(pasta, str(agora.year))
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não consegui criar a pasta:\n{}\n\n{}".format(pasta, erro))
            return
        nome_aluno = self.aluno.get("social") or self.aluno.get("nome") or "Aluno"
        base = nome_arquivo_seguro("{} - {} - {}".format(
            "{:03d}".format(numero) if numero else agora.strftime("%Y%m%d-%H%M%S"),
            NOME_TIPO[tipo], nome_aluno.upper()))
        logo = os.path.join(pasta_dados(), ARQ_LOGO)
        logo = logo if os.path.exists(logo) else ""
        arquivos = []
        try:
            if cfg.get("pdf"):
                caminho = os.path.join(pasta, base + ".pdf")
                gerar_pdf(caminho, doc, tipo, paras, numero_txt, logo)
                arquivos.append(caminho)
            if cfg.get("word"):
                caminho = os.path.join(pasta, base + ".docx")
                gerar_word(caminho, doc, tipo, paras, numero_txt, logo)
                arquivos.append(caminho)
        except PermissionError:
            messagebox.showerror(NOME_PROGRAMA, "O arquivo está aberto em outro programa. "
                                 "Feche-o e tente de novo.")
            return
        except Exception as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não foi possível gerar a declaração:\n{}".format(erro))
            return

        hist = ler_json(ARQ_HISTORICO, [])
        hist.append({"data": agora.isoformat(timespec="seconds"), "numero": numero, "tipo": tipo,
                     "aluno": nome_aluno, "codigo": self.aluno.get("matricula", ""), "arquivo": arquivos[0]})
        gravar_json(ARQ_HISTORICO, hist[-2000:])
        if numero:
            cfg["numero"] = numero + 1
            gravar_json(ARQ_CONFIG, cfg)
        self.ultimo_arquivo = arquivos[0]
        abrir_arquivo(arquivos[0])
        self.var_status.set("Declaração {}de {} gerada e aberta para imprimir: {}".format(
            numero_txt + " " if numero_txt else "", nome_aluno, os.path.basename(arquivos[0])))

    def gerar_termo(self, tipo, dados):
        """Chamado pela janela do termo depois de completar os dados."""
        cfg = self.cfg
        if not cfg.get("pdf") and not cfg.get("word"):
            cfg["pdf"] = True
        a = self.aluno
        agora = datetime.now()
        if tipo == "justificativa":
            blocos, cab = blocos_justificativa(cfg, a, dados), cabecalho_escola(cfg)
        else:
            blocos, cab = blocos_compromisso(cfg, a, dados), cabecalho_cemasp(cfg)
        pasta = os.path.join(cfg.get("pasta_saida") or os.path.join(pasta_documentos(), "Declarações Escolares"),
                             str(agora.year))
        nome_aluno = a.get("social") or a.get("nome") or "Aluno"
        base = nome_arquivo_seguro("{} - {} - {}".format(agora.strftime("%Y%m%d-%H%M%S"), NOME_TIPO[tipo],
                                                          nome_aluno.upper()))
        logo = os.path.join(pasta_dados(), ARQ_LOGO)
        logo = logo if os.path.exists(logo) else ""
        arquivos = []
        try:
            os.makedirs(pasta, exist_ok=True)
            if cfg.get("pdf"):
                arquivos.append(os.path.join(pasta, base + ".pdf"))
                gerar_pdf_termo(arquivos[-1], cfg, cab, blocos, logo, TITULO_TIPO[tipo].title())
            if cfg.get("word"):
                arquivos.append(os.path.join(pasta, base + ".docx"))
                gerar_word_termo(arquivos[-1], cfg, cab, blocos, logo)
        except PermissionError:
            messagebox.showerror(NOME_PROGRAMA, "O arquivo está aberto em outro programa. Feche-o e tente de novo.")
            return False
        except Exception as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não foi possível gerar o termo:\n{}".format(erro))
            return False
        hist = ler_json(ARQ_HISTORICO, [])
        hist.append({"data": agora.isoformat(timespec="seconds"), "numero": None, "tipo": tipo,
                     "aluno": nome_aluno, "codigo": a.get("matricula", ""), "arquivo": arquivos[0]})
        gravar_json(ARQ_HISTORICO, hist[-2000:])
        self.ultimo_arquivo = arquivos[0]
        abrir_arquivo(arquivos[0])
        self.var_status.set("Pronto: {} de {}, aberto para imprimir.".format(NOME_TIPO[tipo].lower(), nome_aluno))
        return True

    def _abrir_pasta(self):
        pasta = os.path.dirname(self.ultimo_arquivo) if self.ultimo_arquivo else \
            os.path.join(self.cfg.get("pasta_saida") or os.path.join(pasta_documentos(), "Declarações Escolares"))
        os.makedirs(pasta, exist_ok=True)
        abrir_arquivo(pasta)

    # -- configuração ----------------------------------------------------------

    def _abrir_configuracao(self):
        JanelaConfiguracao(self)

    def importar_alunos(self, caminho):
        with open(caminho, "rb") as f:
            texto = decodificar(f.read())
        alunos = ler_lista(texto)
        if not alunos:
            raise ValueError("Não encontrei nomes de alunos nesse arquivo.")
        self.origem = os.path.basename(caminho)
        gravar_json(ARQ_ALUNOS, {"origem": self.origem, "importado_em": datetime.now().isoformat(timespec="seconds"),
                                 "alunos": alunos})
        for a in alunos:
            a["_chave"] = sem_acento(" ".join((a.get("nome", ""), a.get("social", ""), a.get("matricula", ""))))
        self.alunos = sorted(alunos, key=lambda a: a["_chave"])
        self.var_busca.set("")
        self._atualizar_banco()
        return len(alunos)

    def configuracao_salva(self):
        self._atualizar_relogio()


class JanelaConfiguracao(tk.Toplevel):

    CAMPOS = [("Cabeçalho, linha 1", "cab1", 0, 0, 2), ("Cabeçalho, linha 2", "cab2", 1, 0, 2),
              ("Nome da escola", "escola", 2, 0, 2), ("Código INEP", "inep", 3, 0, 1),
              ("Telefone", "telefone", 3, 1, 1), ("Endereço", "endereco", 4, 0, 2),
              ("Cidade", "cidade", 5, 0, 1), ("UF", "uf", 5, 1, 1), ("E-mail", "email", 6, 0, 2),
              ("Gestor(a): nome", "gestor_nome", 0, 0, 0), ("Cargo", "gestor_cargo", 0, 0, 0),
              ("Matrícula / Portaria", "gestor_registro", 0, 0, 0),
              ("Secretário(a): nome", "secretario_nome", 0, 0, 0), ("Cargo", "secretario_cargo", 0, 0, 0),
              ("Matrícula / Portaria", "secretario_registro", 0, 0, 0)]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Configuração – " + NOME_PROGRAMA)
        self.configure(bg=COR_FUNDO)
        self.transient(app)
        largura, altura = 900, min(760, app.winfo_screenheight() - 80)
        self.geometry("{}x{}+{}+{}".format(largura, altura, app.winfo_rootx() + 30, max(app.winfo_rooty() - 20, 0)))
        self.minsize(820, 560)
        cfg = app.cfg
        self.vars = {k: tk.StringVar(value=str(cfg.get(k, ""))) for _, k, *_ in self.CAMPOS}
        self.var_numero = tk.StringVar(value=str(cfg.get("numero", 1)))
        self.var_numerar = tk.BooleanVar(value=bool(cfg.get("numerar", True)))
        self.var_pdf = tk.BooleanVar(value=bool(cfg.get("pdf", True)))
        self.var_word = tk.BooleanVar(value=bool(cfg.get("word", False)))
        self.var_pasta = tk.StringVar(value=cfg.get("pasta_saida") or
                                      os.path.join(pasta_documentos(), "Declarações Escolares"))

        corpo = tk.Frame(self, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=22, pady=18)
        corpo.columnconfigure(0, weight=1, uniform="c")
        corpo.columnconfigure(1, weight=1, uniform="c")
        corpo.rowconfigure(1, weight=1)

        # 1 - Banco de dados
        externo, c, self.canto_banco = cartao(corpo, "Banco de dados dos alunos", 1)
        externo.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        self.marca = tk.Label(self.canto_banco, text="", bg=COR_CARTAO, fg=COR_VERDE, font=(FONTE, 10, "bold"))
        self.marca.pack()
        rotulo(c, "Arquivo TXT de alunos do sistema da SEMED. Um arquivo novo substitui o anterior.",
               fraco=True, tam=9, wraplength=360, justify="left").pack(anchor="w")
        self.linha_banco = tk.Label(c, text="", bg=COR_LINHA, fg=COR_TEXTO, font=(FONTE, 9, "bold"),
                                    anchor="w", justify="left", highlightthickness=1,
                                    highlightbackground=COR_BORDA, padx=10, pady=8)
        self.linha_banco.pack(fill="x", pady=(8, 8))
        Botao(c, "Abrir arquivo de alunos...", self._importar, estilo="tracejado").pack(anchor="w")
        self._mostrar_banco()

        # 3 - Declarações
        externo, c, _ = cartao(corpo, "Declarações", 3)
        externo.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x")
        campo(linha, "Próximo número", self.var_numero, largura=8).pack(side="left")
        Chip(linha, "Numerar as declarações", self.var_numerar).pack(side="left", padx=(14, 0), pady=(18, 0))
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        rotulo(linha, "Salvar como:").pack(side="left", padx=(0, 10))
        Chip(linha, "PDF", self.var_pdf).pack(side="left", padx=(0, 8))
        Chip(linha, "Word", self.var_word).pack(side="left")
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        campo(linha, "Pasta onde as declarações ficam salvas", self.var_pasta).pack(side="left", fill="x", expand=True)
        Botao(linha, "Escolher...", self._escolher_pasta, pad_y=5, pad_x=12).pack(side="left", padx=(8, 0), pady=(18, 0))

        # 2 - Dados da escola
        externo, c, _ = cartao(corpo, "Dados da escola e de quem assina", 2)
        externo.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
        g = tk.Frame(c, bg=COR_CARTAO)
        g.pack(fill="both", expand=True)
        posicoes = {"cab1": (0, 0, 2), "cab2": (0, 2, 2), "escola": (1, 0, 3), "inep": (1, 3, 1),
                    "endereco": (2, 0, 2), "cidade": (2, 2, 1), "uf": (2, 3, 1),
                    "telefone": (3, 0, 1), "email": (3, 1, 1),
                    "gestor_nome": (4, 0, 2), "gestor_cargo": (4, 2, 1), "gestor_registro": (4, 3, 1),
                    "secretario_nome": (5, 0, 2), "secretario_cargo": (5, 2, 1), "secretario_registro": (5, 3, 1)}
        for col in range(4):
            g.columnconfigure(col, weight=1, uniform="g")
        for titulo, k, *_ in self.CAMPOS:
            lin, col, span = posicoes[k]
            campo(g, titulo, self.vars[k], opcoes=["Gestor(a) Escolar", "Secretário(a) Escolar", "Diretor(a)",
                                                    "Pedagogo(a)"] if k.endswith("_cargo") else None
                  ).grid(row=lin, column=col, columnspan=span, sticky="ew", padx=4, pady=3)
        logo = tk.Frame(g, bg=COR_CARTAO)
        logo.grid(row=3, column=2, columnspan=2, sticky="sew", padx=4, pady=3)
        tk.Label(logo, text="Logotipo (opcional)", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold"), anchor="w").pack(anchor="w")
        linha = tk.Frame(logo, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(2, 0))
        self.rotulo_logo = rotulo(linha, "", fraco=True, tam=9)
        self.rotulo_logo.pack(side="left")
        Botao(linha, "Remover", self._remover_logo, pad_y=4, pad_x=12).pack(side="right")
        Botao(linha, "Escolher imagem...", self._escolher_logo, pad_y=4, pad_x=12).pack(side="right", padx=(0, 8))
        self._mostrar_logo()

        botoes = tk.Frame(corpo, bg=COR_FUNDO)
        botoes.grid(row=2, column=0, columnspan=2, sticky="ew")
        Botao(botoes, "Salvar", self._salvar, estilo="principal", fonte=(FONTE, 11, "bold"),
              pad_x=28).pack(side="right")
        Botao(botoes, "Cancelar", self.destroy).pack(side="right", padx=(0, 10))
        self.grab_set()

    def _mostrar_banco(self):
        app = self.app
        if app.alunos:
            series = {}
            for a in app.alunos:
                series[a.get("serie") or "sem fase"] = series.get(a.get("serie") or "sem fase", 0) + 1
            resumo = " · ".join("{} no {}".format(n, s) for s, n in sorted(series.items(), key=lambda x: ordem_serie(x[0])))
            self.marca.configure(text="✓  {} alunos".format(len(app.alunos)))
            com_pais = sum(1 for a in app.alunos if a.get("mae") or a.get("pai"))
            self.linha_banco.configure(text="{}\n{}\nCom nome da mãe ou do pai: {} de {}".format(
                app.origem or "arquivo importado", resumo, com_pais, len(app.alunos)))
        else:
            self.marca.configure(text="")
            self.linha_banco.configure(text="Nenhum arquivo aberto ainda.")

    def _importar(self):
        caminho = filedialog.askopenfilename(
            parent=self, title="Arquivo de alunos",
            filetypes=[("Arquivo de texto", "*.txt *.csv"), ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        try:
            n = self.app.importar_alunos(caminho)
        except Exception as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não consegui ler esse arquivo.\n\n{}".format(erro), parent=self)
            return
        self._mostrar_banco()
        messagebox.showinfo(NOME_PROGRAMA, "{} alunos guardados no banco de dados.".format(n), parent=self)

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(parent=self, title="Pasta das declarações")
        if pasta:
            self.var_pasta.set(pasta)

    def _mostrar_logo(self):
        tem = os.path.exists(os.path.join(pasta_dados(), ARQ_LOGO))
        self.rotulo_logo.configure(text="✓ cadastrado" if tem else "nenhum")

    def _escolher_logo(self):
        caminho = filedialog.askopenfilename(
            parent=self, title="Logotipo da escola",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.gif *.bmp"), ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        destino = os.path.join(pasta_dados(), ARQ_LOGO)
        try:
            try:
                from PIL import Image
                img = Image.open(caminho)
                img.thumbnail((600, 600))
                img.save(destino, "PNG")
            except ImportError:
                shutil.copyfile(caminho, destino)
        except Exception as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não consegui usar essa imagem.\n\n{}".format(erro), parent=self)
        self._mostrar_logo()

    def _remover_logo(self):
        try:
            os.remove(os.path.join(pasta_dados(), ARQ_LOGO))
        except OSError:
            pass
        self._mostrar_logo()

    def _salvar(self):
        cfg = self.app.cfg
        for k, v in self.vars.items():
            cfg[k] = v.get().strip()
        try:
            cfg["numero"] = max(1, int(self.var_numero.get()))
        except ValueError:
            pass
        cfg["numerar"] = bool(self.var_numerar.get())
        cfg["pdf"] = bool(self.var_pdf.get()) or not self.var_word.get()
        cfg["word"] = bool(self.var_word.get())
        cfg["pasta_saida"] = self.var_pasta.get().strip()
        for velho in ("assinante", "cargo", "registro"):
            cfg.pop(velho, None)
        gravar_json(ARQ_CONFIG, cfg)
        self.app.configuracao_salva()
        self.destroy()


def main():
    app = Aplicacao()
    if not app.alunos:
        app.after(400, app._abrir_configuracao)
    app.mainloop()


if __name__ == "__main__":
    main()
