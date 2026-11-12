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
import time
import unicodedata
import webbrowser
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

import acesso
import atualizacao
import catalogo
import estoque
import tela_estoque
import tela_login
import tela_usuarios

VERSAO_PROGRAMA = "2.14"
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
ARQ_FREQ = "frequencia.json"


def pasta_downloads():
    """Pasta Downloads do Windows (mesmo se tiver sido mudada de lugar)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                            ("d4", ctypes.c_ubyte * 8)]
            fid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0:
                caminho = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if caminho and os.path.isdir(caminho):
                    return caminho
        except Exception:
            pass
    casa = os.path.expanduser("~")
    for nome in ("Downloads", "Transferências"):
        if os.path.isdir(os.path.join(casa, nome)):
            return os.path.join(casa, nome)
    return casa


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
    "pasta_estoque": "",      # vazio = pasta do programa; os dois PCs usam a mesma para ver o mesmo estoque
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


# ---------------------------------------------------------------------------
# Frequência (PDF "Acompanhamento Diário" do Gier)
# ---------------------------------------------------------------------------

MESES_NUMERO = {sem_acento(m): i + 1 for i, m in enumerate(MESES)}


def _mes_chave(mes):
    return MESES_NUMERO.get(sem_acento(mes), 99)


def importar_frequencia_pdfs(caminhos):
    """
    Lê um ou mais PDFs "Acompanhamento Diário" do Gier e guarda a frequência de
    cada criança por mês em frequencia.json. Um mês já guardado é atualizado.
    """
    import frequencia_gier as fg
    banco = ler_json(ARQ_FREQ, {})
    if not isinstance(banco, dict):
        banco = {}
    meses = banco.setdefault("meses", {})
    resumo = {"arquivos": 0, "criancas": set(), "meses": set(), "turmas": set(), "erros": []}
    for caminho in caminhos:
        nome_arq = os.path.basename(caminho)
        try:
            alunos, info = fg.extrair_dados_pdf(caminho)
        except Exception as erro:
            resumo["erros"].append("{}: não consegui ler ({})".format(nome_arq, erro))
            continue
        if not alunos:
            resumo["erros"].append("{}: não achei a frequência. É o relatório \"Acompanhamento Diário\" "
                                   "do Gier?".format(nome_arq))
            continue
        resumo["arquivos"] += 1
        tem_dias = False
        for al in alunos:
            mes = (al.get("mes") or info.get("mes") or "?").capitalize()
            _p, pct, obs = fg.calcular_presenca(al)
            chave = fg.normalizar(al["nome"])
            reg = {"nome": al["nome"], "turma": al["turma"], "situacao": al["situacao"],
                   "dias": al["dias_letivos"], "faltas": al["faltas"], "fj": al["faltas_justificadas"],
                   "pct": pct, "obs": obs}
            d = meses.setdefault(mes, {})
            # a mesma criança pode aparecer 2 vezes no mês (ex.: TR e depois MA): fica a de mais dias
            if chave not in d or reg["dias"] >= d[chave]["dias"]:
                d[chave] = reg
            if reg["dias"]:                       # linha sem dias letivos não conta como frequência trazida
                resumo["criancas"].add(chave)
                resumo["meses"].add(mes)
                resumo["turmas"].add(al["turma"])
                tem_dias = True
        if not tem_dias:
            resumo["erros"].append("{}: o PDF veio sem dias letivos. No Gier, escolha o componente "
                                   "EDUCAÇÃO INFANTIL (\"AULA DIA\").".format(nome_arq))
        if info.get("ano"):
            banco["ano"] = info["ano"]
    resumo["criancas"] = len(resumo["criancas"])
    banco["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    gravar_json(ARQ_FREQ, banco)
    return banco, resumo


def frequencia_do_aluno(banco, aluno):
    """[(mês, registro)] da criança, em ordem de mês. Casa pelo nome (igual ou bem parecido)."""
    import difflib
    import frequencia_gier as fg
    if not banco or not banco.get("meses"):
        return []
    chaves = [fg.normalizar(aluno.get("nome", "")), fg.normalizar(aluno.get("social", ""))]
    achados = []
    for mes, d in banco["meses"].items():
        reg = next((d[c] for c in chaves if c and c in d), None)
        if reg is None and chaves[0]:
            parecido = difflib.get_close_matches(chaves[0], list(d.keys()), n=1, cutoff=0.87)
            reg = d[parecido[0]] if parecido else None
        if reg is not None and reg.get("dias"):   # mês sem aula não entra no período da declaração
            achados.append((mes, reg))
    return sorted(achados, key=lambda x: _mes_chave(x[0]))


def somar_frequencia(regs):
    """Soma os meses: (percentual de presença, faltas, dias letivos) ou None."""
    dias = sum(r["dias"] for _m, r in regs if r.get("dias"))
    if not dias:
        return None
    faltas = sum(r["faltas"] + r.get("fj", 0) for _m, r in regs if r.get("dias"))
    return round(max(dias - faltas, 0) / dias * 100, 1), faltas, dias


def _nome_periodo(regs):
    """'Abril' para um mês; 'Abril a Novembro' para vários."""
    meses = [m for m, _r in regs]
    return meses[0] if len(meses) == 1 else "{} a {}".format(meses[0], meses[-1])


def pct_br(valor):
    if valor is None:
        return ""
    texto = "{:.1f}".format(valor).replace(".", ",")
    return texto[:-2] if texto.endswith(",0") else texto


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
            if x.get("freq_mes"):
                f += ", com frequência de {}% {}".format(freq, x["freq_mes"])
            else:
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
FONTE = "Arial"             # escolhida pelo Jansey (letra das imagens de revisão)
AUMENTO_LETRA = 1.2         # letras 20% maiores que o padrão do Windows
_ESCALA_BASE = None         # escala original do Tk, guardada na 1ª janela do programa


def aplicar_aumento_de_letra(raiz):
    """
    Letras 20% maiores (o "scaling" do Tk vale para todas as fontes em pontos). O Tk guarda esse valor para o
    processo inteiro, então cada janela nova (a de entrada, a principal, a principal de novo depois do Sair)
    partiria do valor já aumentado: por isso o valor original é guardado na primeira vez.
    """
    global _ESCALA_BASE
    try:
        if _ESCALA_BASE is None:
            _ESCALA_BASE = float(raiz.tk.call("tk", "scaling"))
        raiz.tk.call("tk", "scaling", _ESCALA_BASE * AUMENTO_LETRA)
    except tk.TclError:
        pass

# Frase abaixo do nome do programa, na faixa azul, para cada aba
SUBTITULO_ABA = {
    "declaracoes": "Pesquise o aluno pelo nome e gere a declaração pronta para imprimir.",
    "pedagogico": "Estoque de material pedagógico: entrada, saída e relatório.",
    "limpeza": "Estoque de material de limpeza: entrada, saída e relatório.",
}


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


class AreaRolavel(tk.Frame):
    """
    Área que ganha barra de rolagem só quando a janela é menor que o conteúdo
    (telas baixas, como 1366x768). Quando há espaço, o conteúdo estica como antes.
    Use `.miolo` como pai do conteúdo.
    """

    def __init__(self, pai, bg):
        super().__init__(pai, bg=bg)
        self.tela = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.tela.yview)
        self.tela.configure(yscrollcommand=self.barra.set)
        self.tela.pack(side="left", fill="both", expand=True)
        self.miolo = tk.Frame(self.tela, bg=bg)
        self._janela = self.tela.create_window((0, 0), window=self.miolo, anchor="nw")
        self.tela.bind("<Configure>", lambda e: self.ajustar())
        self._ultimo = None
        self._vigiar()

    def _vigiar(self):
        """O conteúdo muda (aluno, tipo de declaração...): confere a altura de tempos em tempos."""
        try:
            atual = (self.miolo.winfo_reqheight(), self.tela.winfo_height(), self.tela.winfo_width())
        except tk.TclError:
            return
        if atual != self._ultimo:
            self._ultimo = atual
            self.ajustar()
        self.after(250, self._vigiar)

    def ajustar(self):
        largura, altura = self.tela.winfo_width(), self.tela.winfo_height()
        if largura <= 1:
            return
        precisa = self.miolo.winfo_reqheight()
        alto = max(altura, precisa)
        self.tela.itemconfigure(self._janela, width=largura, height=alto)
        self.tela.configure(scrollregion=(0, 0, largura, alto))
        if precisa > altura + 1:
            if not self.barra.winfo_ismapped():
                self.barra.pack(side="right", fill="y", before=self.tela)
        elif self.barra.winfo_ismapped():
            self.barra.pack_forget()
            self.tela.yview_moveto(0)

    def rolar(self, evento):
        """Rola com a rodinha do mouse; devolve True se rolou."""
        if not self.barra.winfo_ismapped():
            return False
        passo = int(-evento.delta / 120) or (-1 if evento.delta > 0 else 1)
        self.tela.yview_scroll(passo, "units")
        return True


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

    def __init__(self, sessao=None):
        super().__init__()
        self.sessao = sessao or acesso.Sessao.completa()      # quem entrou e o que pode ver (sem login: tudo)
        self.trocar_usuario = False
        aplicar_aumento_de_letra(self)
        self.title(NOME_PROGRAMA)
        try:
            self.iconbitmap(default=caminho_recurso("icone_declaracoes.ico"))    # vale também para as janelas menores
        except tk.TclError:
            pass
        largura = min(960, self.winfo_screenwidth() - 40)
        # tamanho ao restaurar; o programa abre maximizado (ver o fim do __init__)
        altura = min(840, self.winfo_screenheight() - 80)
        self.tela_baixa = self.winfo_screenheight() < 900          # ex.: notebooks 1366x768
        self.geometry("{}x{}+{}+{}".format(
            largura, altura, (self.winfo_screenwidth() - largura) // 2,
            max((self.winfo_screenheight() - altura) // 2 - 20, 0)))
        self.minsize(860, 480)
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

        self.sessao_gier = None            # conexão com o Gier: só na memória, até fechar o programa
        self._janelas_gier_fechadas = []
        self.var_busca = tk.StringVar()
        self.var_tipo = tk.StringVar(value="matricula")
        self.var_status = tk.StringVar()
        self.ext = {k: tk.StringVar() for k in (
            "freq", "situacao", "destino", "prazo", "resultado", "proxima", "validade",
            "resp_nome", "resp_cpf", "hora_ini", "hora_fim", "motivo", "parentesco", "freq_periodo")}
        self.freq = ler_json(ARQ_FREQ, {})
        self.ext["parentesco"].set("Mãe")
        self.var_assina = tk.StringVar(value=self.cfg.get("assina") or "gestor")
        self.ext["prazo"].set("30")
        self.ext["validade"].set("5")
        self.ext["situacao"].set("Estava cursando")
        self.ext["resultado"].set("Aprovado(a)")
        self.ext["motivo"].set("atendimento na escola")

        self.livros = {}                  # estoques (material pedagógico e de limpeza)
        self.paineis = {}                 # telas dos estoques, criadas na primeira vez que a aba abre
        self._abrir_livros()

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
        self._mostrar_aba_inicial()
        self._maximizar()
        self.after(150, self._focar_pesquisa)
        self.after(3000, self._conferir_versao)         # aviso de versão nova (em segundo plano)
        if getattr(self.sessao, "por_copia", False):          # entrou pela cópia guardada: o servidor confirma depois
            self.after(1500, self._conferir_acesso)

    def _mostrar_aba_inicial(self):
        """Quem não vê a aba Declarações já abre na primeira aba que pode usar."""
        abas = self.sessao.abas()
        if not abas:
            self.area.pack_forget()
            tk.Label(self, text="O seu acesso ainda não tem nenhuma aba liberada.\n\nFale com o administrador do programa.",
                     bg=COR_FUNDO, fg=COR_AZUL_ESCURO, font=(FONTE, 13, "bold"), justify="center").pack(expand=True)
        elif abas[0] != "declaracoes":
            self._ao_mudar_aba(abas[0])

    def _focar_pesquisa(self):
        """Ao abrir, o cursor já fica piscando na barra de pesquisa."""
        if not self.sessao.pode("declaracoes"):
            return
        try:
            self.focus_force()
            self.entrada_busca.focus_set()
            self._atualizar_dica()
        except tk.TclError:
            pass

    def _maximizar(self):
        """Abre ocupando a tela inteira (o Jansey trabalha com o programa maximizado)."""
        try:
            self.state("zoomed")                  # Windows
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)  # Linux
            except tk.TclError:
                pass

    # -- aviso de versão nova ---------------------------------------------------

    def _conferir_versao(self):
        """Pergunta ao GitHub, em segundo plano, se há versão nova. Sem internet, nada acontece."""
        self._conferencia = atualizacao.Conferencia(VERSAO_PROGRAMA)
        self.after(500, self._esperar_versao)

    def _esperar_versao(self):
        conferencia = self._conferencia
        if not conferencia.pronta:
            self.after(500, self._esperar_versao)
        elif conferencia.nova:
            self._mostrar_aviso_versao(conferencia.nova)

    def _mostrar_aviso_versao(self, nova):
        """Faixa amarela logo abaixo do cabeçalho. O programa nunca baixa nem instala nada sozinho."""
        if getattr(self, "aviso_versao", None) is not None:
            return
        fundo = "#FFF4D6"
        faixa = tk.Frame(self, bg=fundo, highlightthickness=1, highlightbackground="#F0D78C")
        self.aviso_versao = faixa
        texto = tk.Frame(faixa, bg=fundo)
        texto.pack(side="left", padx=(18, 8), pady=6)
        tk.Label(texto, text="Há uma versão nova do programa: {}  (você está usando a {}).".format(nova, VERSAO_PROGRAMA),
                 bg=fundo, fg=COR_TEXTO, font=(FONTE, 10, "bold"), anchor="w").pack(anchor="w")
        self.msg_versao = tk.Label(
            texto, bg=fundo, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w", justify="left",
            text="Clique em Baixar, feche este programa e abra o arquivo baixado. Os seus dados continuam.")
        self.msg_versao.pack(anchor="w")
        botoes = tk.Frame(faixa, bg=fundo)
        botoes.pack(side="right", padx=18, pady=6)
        Botao(botoes, "Agora não", self._fechar_aviso_versao, estilo="suave", pad_y=4, pad_x=12, raio=8
              ).pack(side="right", padx=(8, 0))
        Botao(botoes, "Baixar", self._baixar_versao, estilo="azul", pad_y=4, pad_x=16, raio=8).pack(side="right")
        faixa.pack(fill="x", after=self.cabecalho)

    def _baixar_versao(self):
        """Só abre o endereço no navegador; quem instala é a pessoa."""
        try:
            aberto = webbrowser.open(atualizacao.URL_BAIXAR)
        except Exception:
            aberto = False
        if aberto:
            self.msg_versao.configure(
                text="O download foi aberto no navegador. Quando terminar, feche este programa e abra o arquivo baixado.")
        else:
            messagebox.showinfo(NOME_PROGRAMA, "Não consegui abrir o navegador. Copie este endereço e cole nele:\n\n"
                                + atualizacao.URL_BAIXAR, parent=self)

    def _fechar_aviso_versao(self):
        self.aviso_versao.pack_forget()

    # -- confirmação do acesso (quando entrou NA HORA pela cópia guardada) --------------------

    def _conferir_acesso(self):
        """Confirma com o servidor, em segundo plano, o acesso de quem entrou pela cópia guardada neste computador.
        Sem resposta (rede ruim ou sem internet), nada muda e tenta de novo em 2 minutos."""
        self._conf_acesso = acesso.ConferenciaAcesso(self.sessao)
        self.after(500, self._esperar_acesso)

    def _esperar_acesso(self):
        conferencia = self._conf_acesso
        if not conferencia.pronta:
            self.after(500, self._esperar_acesso)
        elif conferencia.estado == "sem_resposta":
            self.after(120000, self._conferir_acesso)
        elif conferencia.estado == "ok":
            self.sessao.por_copia = False
        elif conferencia.estado == "mudou":
            self._voltar_para_a_entrada(
                "O administrador mudou o seu acesso.\n\nO programa vai voltar para a tela de entrada para a mudança valer.",
                "O seu acesso mudou. Entre de novo para continuar.")
        else:                                                    # cortado
            self._voltar_para_a_entrada(conferencia.texto + "\n\nO programa vai voltar para a tela de entrada.",
                                        conferencia.texto)

    def _voltar_para_a_entrada(self, texto, aviso):
        """O acesso mudou ou foi cancelado: volta para a tela de entrada na hora (sem perguntar sobre listas pendentes)."""
        messagebox.showwarning(NOME_PROGRAMA, texto, parent=self)
        self.aviso_ao_voltar = aviso
        self.trocar_usuario = True
        self.destroy()

    # -- montagem -------------------------------------------------------------

    def _montar_cabecalho(self):
        # Em telas baixas (ex.: 1366x768) a faixa fica mais baixa para sobrar espaço aos quadros.
        baixa = self.tela_baixa
        self.alt_cab = 66 if baixa else ALTURA_CABECALHO
        cab = tk.Canvas(self, height=self.alt_cab, highlightthickness=0, bd=0, bg=COR_AZUL_ESCURO)
        cab.pack(fill="x")
        self.cabecalho = cab
        # Logo: folha com linhas e o "certo" verde (prima da prancheta do Frequência)
        _retangulo_arredondado(cab, 26, 19, 80, 73, 14, fill="#FFFFFF", outline="#FFFFFF", tags="logo")
        cab.create_polygon(40, 29, 58, 29, 66, 37, 66, 63, 40, 63, fill=COR_AZUL, outline=COR_AZUL, tags="logo")
        cab.create_polygon(58, 29, 58, 37, 66, 37, fill="#9DB6E6", outline="#9DB6E6", tags="logo")
        for yy in (40, 46):
            cab.create_line(45, yy, 56, yy, fill="#DCE8FF", width=2, capstyle="round", tags="logo")
        cab.create_line(46, 54, 51, 59, 60, 49, fill="#3DDC84", width=4,
                        capstyle="round", joinstyle="round", tags="logo")
        if baixa:
            cab.scale("logo", 26, 19, 0.78, 0.78)
            cab.move("logo", 0, -9)
        x_texto = 84 if baixa else 98
        cab.create_text(x_texto, 24 if baixa else 35, anchor="w", text=NOME_PROGRAMA, fill="white",
                        font=(FONTE, 16 if baixa else 20, "bold"))
        self._id_sub = cab.create_text(x_texto, 48 if baixa else 63, anchor="w", fill="#D5E1F7", font=(FONTE, 9),
                                       text=SUBTITULO_ABA["declaracoes"])
        y1, y2, y3 = (15, 33, 51) if baixa else (28, 47, 66)
        self._id_escola = cab.create_text(0, y1, anchor="e", text="", fill="white", font=(FONTE, 9, "bold"))
        self._id_data = cab.create_text(0, y2, anchor="e", text="", fill="#D5E1F7", font=(FONTE, 9))
        self._y_links = y3
        quem = self.sessao.nome or self.sessao.email
        if quem and self.sessao.sem_internet:
            quem += "  (sem internet)"
        self._id_quem = cab.create_text(0, y3, anchor="e", text=quem, fill="#D5E1F7", font=(FONTE, 9))
        self._links = {}
        for chave, texto, comando in (("config", "Configuração", self._abrir_configuracao),
                                      ("usuarios", "Usuários", self._abrir_usuarios),
                                      ("sair", "Sair", self._sair)):
            self._links[chave] = cab.create_text(0, y3, anchor="e", text=texto, fill="white", tags=chave,
                                                 font=(FONTE, 9, "underline"))
            cab.tag_bind(chave, "<Button-1>", lambda e, c=comando: c())
            cab.tag_bind(chave, "<Enter>", lambda e: cab.configure(cursor="hand2"))
            cab.tag_bind(chave, "<Leave>", lambda e: cab.configure(cursor=""))
        # Quem não pode não vê o link; sem login configurado, o programa é como sempre foi (sem Usuários, sem Sair).
        visiveis = {"config": self.sessao.pode("configuracao"),
                    "usuarios": self.sessao.pode("usuarios") and not self.sessao.sem_login,
                    "sair": not self.sessao.sem_login}
        for chave, item in self._links.items():
            cab.itemconfigure(item, state="normal" if visiveis[chave] else "hidden")
        cab.bind("<Configure>", self._pintar_cabecalho)

    def _pintar_cabecalho(self, _evento=None):
        cab = self.cabecalho
        largura = max(cab.winfo_width(), 1)
        cab.delete("degrade")
        for x in range(0, largura, 4):
            cab.create_rectangle(x, 0, x + 4, self.alt_cab, outline="", tags="degrade",
                                 fill=_misturar("#17327A", "#2A63C8", x / largura))
        cab.tag_lower("degrade")
        for item in (self._id_escola, self._id_data):
            cab.coords(item, largura - 26, cab.coords(item)[1])
        x = largura - 26                       # os links da 3ª linha, da direita para a esquerda
        for item in (self._links["sair"], self._links["usuarios"], self._links["config"], self._id_quem):
            if cab.itemcget(item, "state") == "hidden" or not cab.itemcget(item, "text"):
                continue
            cab.coords(item, x, self._y_links)
            x = cab.bbox(item)[0] - 16

    def _atualizar_relogio(self):
        agora = datetime.now()
        self.cabecalho.itemconfigure(self._id_escola, text=self.cfg.get("escola") or "Escola não cadastrada")
        self.cabecalho.itemconfigure(self._id_data, text="{}, {}".format(DIAS[agora.weekday()], hoje_extenso(agora)))
        self.after(60000, self._atualizar_relogio)

    # -- abas: Declarações | Estoque pedagógico | Estoque de limpeza ---------------------------

    def _abrir_livros(self):
        """Abre os dois estoques (na pasta do programa ou na pasta escolhida na Configuração)."""
        base = self.cfg.get("pasta_estoque") or os.path.join(pasta_dados(), "estoque")
        pc = estoque.identificar_pc(pasta_dados())
        self.livros = {chave: estoque.Livro(os.path.join(base, chave), pc) for chave in ("pedagogico", "limpeza")}
        self.catalogo = catalogo.Catalogo(os.path.join(base, "catalogo"), pc)     # produtos que o programa conhece
        self.catalogo_federal = catalogo.CatalogoFederal()                        # banco de materiais de fábrica

    def _atualizar_selos(self):
        """Selo laranja na aba: só aparece quando há material pendente (já na lista de entrada ou de
        saída, mas ainda não registrado). Registrou ou limpou a lista, o selo some."""
        if not hasattr(self, "barra_abas"):
            return
        for chave in ("pedagogico", "limpeza"):
            painel = self.paineis.get(chave)
            n = painel.pendentes() if painel is not None else 0
            self.barra_abas.definir_selo(chave, str(n) if n else "")

    def _painel(self, chave):
        if chave not in self.paineis:
            titulo = "Estoque pedagógico" if chave == "pedagogico" else "Estoque de limpeza"
            self.paineis[chave] = tela_estoque.PainelEstoque(
                self, self, self.livros[chave], titulo, chave, baixa=self.tela_baixa, ao_mudar=self._atualizar_selos)
        return self.paineis[chave]

    def _ao_mudar_aba(self, chave):
        self.area.pack_forget()
        for painel in self.paineis.values():
            painel.pack_forget()
        self.cabecalho.itemconfigure(self._id_sub, text=SUBTITULO_ABA[chave])
        if chave == "declaracoes":
            self.area.pack(fill="both", expand=True)
            self._focar_pesquisa()
            return
        painel = self._painel(chave)
        painel.pack(fill="both", expand=True)
        painel.ao_mostrar()

    def _area_ativa(self):
        """A área que rola com a rodinha do mouse: a das declarações ou a do estoque aberto."""
        chave = self.barra_abas.ativa if hasattr(self, "barra_abas") else "declaracoes"
        painel = self.paineis.get(chave)
        return painel.area if painel is not None else self.area

    def _montar_interface(self):
        tela_estoque.usar(sys.modules[__name__])
        tela_usuarios.usar(sys.modules[__name__])
        self._montar_cabecalho()
        nomes = {"declaracoes": "Declarações", "pedagogico": "Estoque pedagógico", "limpeza": "Estoque de limpeza"}
        abas = [(chave, nomes[chave]) for chave in self.sessao.abas()]       # só as abas que a pessoa pode usar
        self.barra_abas = tela_estoque.BarraAbas(
            self, abas or [("declaracoes", "Declarações")], self._ao_mudar_aba, baixa=self.tela_baixa)
        if len(abas) > 1:                                                     # com uma aba só, não precisa da barra
            self.barra_abas.pack(fill="x")
        self._atualizar_selos()
        self.area = AreaRolavel(self, COR_FUNDO)
        self.area.pack(fill="both", expand=True)
        corpo = tk.Frame(self.area.miolo, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=26, pady=(12, 8) if self.tela_baixa else (18, 14))
        corpo.columnconfigure(0, weight=4, uniform="col")
        corpo.columnconfigure(1, weight=5, uniform="col")
        corpo.rowconfigure(2, weight=1)        # o quadro 4 fica colado no 3 e ocupa o resto da coluna
        folga = 7 if self.tela_baixa else 12   # espaço entre os quadros

        # 1 - Pesquisar aluno ------------------------------------------------
        externo, c1, direita = cartao(corpo, "Pesquisar aluno", 1)
        externo.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, folga))
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
                                      insertbackground=COR_AZUL_ESCURO, insertwidth=2,
                                      insertontime=600, insertofftime=400, highlightthickness=0)
        self.entrada_busca.pack(side="left", fill="x", expand=True, ipady=6, padx=(2, 10))
        # clicar em qualquer parte da barra (inclusive na lupa) leva o cursor para o campo
        for w in (caixa, lupa):
            w.bind("<Button-1>", lambda e: self.entrada_busca.focus_set())
        self.entrada_busca.bind("<FocusIn>", lambda e: caixa.configure(highlightbackground=COR_AZUL))
        self.entrada_busca.bind("<FocusOut>", lambda e: caixa.configure(highlightbackground="#CFD8EA"))
        self.entrada_busca.bind("<Return>", lambda e: self._pesquisar())
        self.entrada_busca.bind("<KP_Enter>", lambda e: self._pesquisar())
        self.dica_busca = tk.Label(caixa, text="Digite o nome do aluno (ou parte dele) ou o código",
                                   bg="#FFFFFF", fg="#9AA5B8", font=(FONTE, 12), cursor="xterm")
        self.dica_busca.place(x=self._x_dica(), rely=0.5, anchor="w")
        self.dica_busca.bind("<Button-1>", lambda e: self.entrada_busca.focus_set())
        self.botao_pesquisar = Botao(linha, "Pesquisar", self._pesquisar, estilo="azul",
                                     fonte=(FONTE, 11, "bold"), pad_x=26, pad_y=8)
        self.botao_pesquisar.pack(side="left", padx=(10, 0))

        # Resultado da pesquisa: só aparece depois de clicar em Pesquisar
        self.area_result = tk.Frame(c1, bg=COR_CARTAO, height=70 if self.tela_baixa else 96)
        self.area_result.pack(fill="x", pady=(10, 0))
        self.area_result.pack_propagate(False)
        self.dica_result = tk.Label(self.area_result, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                                    font=(FONTE, 9), anchor="nw", justify="left")
        self.quadro_lista = tk.Frame(self.area_result, bg=COR_CARTAO)
        self.rolagem = ttk.Scrollbar(self.quadro_lista, orient="vertical")
        self.tela = tk.Canvas(self.quadro_lista, bg=COR_CARTAO, highlightthickness=0, bd=0,  # rola sozinha
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
        externo.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 8), pady=(0, folga))
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
        c2.bind("<Configure>", lambda e: self._ajustar_quebras(e.width))

        # 3 - Tipo de declaração ---------------------------------------------
        externo, c3, _ = cartao(corpo, "Tipo de declaração", 3)
        externo.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, folga))
        self._chave_do_nome = {nome: chave for chave, nome in NOME_TIPO.items()}
        self.var_nome_tipo = tk.StringVar(value=NOME_TIPO[self.var_tipo.get()])
        q = campo(c3, "Escolha a declaração", self.var_nome_tipo, opcoes=list(NOME_TIPO.values()), editavel=False)
        q.pack(fill="x", pady=(0, 6))
        self.combo_tipo = q.entrada
        self.var_nome_tipo.trace_add("write", lambda *_: self.var_tipo.set(self._chave_do_nome[self.var_nome_tipo.get()]))
        self.var_tipo.trace_add("write", lambda *_: self._acertar_nome_tipo())
        self.area_extras = tk.Frame(c3, bg=COR_CARTAO)
        self.area_extras.pack(fill="both", expand=True, pady=(4, 0))
        self._montar_extras()

        # 4 - Comandos Gier ---------------------------------------------------
        externo, c4, canto = cartao(corpo, "Comandos Gier", 4)
        externo.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=(0, folga))
        self.estado_gier = tk.Label(canto, text="", bg=COR_CARTAO, font=(FONTE, 10, "bold"))
        self.estado_gier.pack(side="right")
        self.data_frequencia = rotulo(canto, "", fraco=True, tam=9)
        self.data_frequencia.pack(side="right", padx=(0, 14))
        comandos = tk.Frame(c4, bg=COR_CARTAO)
        comandos.pack(fill="x")
        Botao(comandos, "Atualizar frequência", self.atualizar_do_gier, estilo="azul",
              fonte=(FONTE, 10, "bold"), pad_y=5, pad_x=16).pack(side="left", padx=(0, 8))
        Botao(comandos, "Baixar frequência", self.baixar_frequencia_gier, estilo="azul",
              fonte=(FONTE, 10, "bold"), pad_y=5, pad_x=16).pack(side="left")
        self.botao_gier = Botao(comandos, "Entrar no Gier", self._ao_clicar_gier, estilo="suave",
                                fonte=(FONTE, 9, "bold"), pad_y=4, pad_x=12, raio=8)
        self.botao_gier.pack(side="right")
        self.usuario_gier = rotulo(comandos, "", fraco=True, tam=9)
        self.usuario_gier.pack(side="right", padx=(0, 10))
        self.mostrar_estado_gier()
        self.mostrar_data_frequencia()

        # Ação ---------------------------------------------------------------
        acao = tk.Frame(corpo, bg=COR_FUNDO)
        acao.grid(row=3, column=0, columnspan=2, sticky="ew")
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
                 font=(FONTE, 9), anchor="w").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4 if self.tela_baixa else 10, 0))

    def _montar_extras(self):
        """Campos que só alguns tipos de declaração pedem."""
        e = self.ext
        self.extras = {}
        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        rotulo(f, "Não precisa de mais nada. É só gerar.", fraco=True, tam=9).pack(anchor="w")
        self.extras["matricula"] = f

        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x")
        q = campo(linha, "Período (frequência do Gier)", e["freq_periodo"], opcoes=[], editavel=False)
        q.pack(side="left", fill="x", expand=True)
        self.combo_periodo = q.entrada
        campo(linha, "Frequência %", e["freq"], largura=10).pack(side="left", padx=(8, 0))
        self.aviso_freq = rotulo(f, "", fraco=True, tam=9, wraplength=440, justify="left")
        self.aviso_freq.pack(anchor="w", pady=(4, 0))
        e["freq_periodo"].trace_add("write", lambda *_: self._ao_mudar_periodo())
        e["freq"].trace_add("write", lambda *_: self._mostrar_previa_freq())
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
        self.linha_resp = tk.Frame(f, bg=COR_CARTAO, height=34)
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
        self.after_idle(lambda: self.linha_resp.configure(height=max(34, self.entrada_outro.winfo_reqheight() + 4)))
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
        self.resp_just = self._montar_escolha_resp(f, t["resp_nome"], "WhatsApp:", t["telefone"], 14)
        self.extras["justificativa"] = f

        # Termo de compromisso: o que vem do arquivo aparece para conferir; o resto se preenche aqui
        f = tk.Frame(self.area_extras, bg=COR_CARTAO)
        self.info_compromisso = tk.Label(f, text="", bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 9),
                                         anchor="w", justify="left", wraplength=440)
        self.info_compromisso.pack(fill="x")
        self.resp_comp = self._montar_escolha_resp(f, t["c_nome"], "CPF:", t["c_cpf"], 15)
        t["c_cpf"].trace_add("write", lambda *_, w=self.resp_comp["lado"]: self._mascara_cpf(t["c_cpf"], w))
        t["c_nome"].trace_add("write", lambda *_: self._ao_mudar_resp_comp())
        linha = tk.Frame(f, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        campo(linha, "Profissão do responsável", t["profissao"]).pack(side="left", fill="x", expand=True)
        q = campo(linha, "Horário", t["horario"], largura=7)
        q.entrada.configure(justify="center")
        q.pack(side="left", padx=(8, 0))
        t["horario"].trace_add("write", lambda *_, w=q.entrada: self._mascara_hora(t["horario"], w))
        self.extras["compromisso"] = f

    def _montar_escolha_resp(self, pai, var_nome, rotulo_lado, var_lado, largura_lado):
        """Responsável: pílulas Mãe / Pai / Responsável (do arquivo) e Outro (abre campo para digitar)."""
        w = {"escolha": tk.StringVar(), "nome": var_nome, "opcoes": []}
        tk.Label(pai, text="Responsável", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(anchor="w", pady=(6, 0))
        w["chips"] = tk.Frame(pai, bg=COR_CARTAO)
        w["chips"].pack(fill="x", pady=(2, 0))
        linha = tk.Frame(pai, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 0))
        lado = tk.Frame(linha, bg=COR_CARTAO)
        lado.pack(side="right")
        tk.Label(lado, text=rotulo_lado, bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(side="left", padx=(8, 6))
        w["lado"] = ttk.Entry(lado, textvariable=var_lado, style="Campo.TEntry", font=(FONTE, 10), width=largura_lado)
        w["lado"].pack(side="left")
        w["rotulo"] = tk.Label(linha, text="", bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 10, "bold"), anchor="w")
        w["linha"], w["lado_quadro"] = linha, lado
        w["fonte"] = tkfont.Font(family=FONTE, size=10, weight="bold")
        linha.bind("<Configure>", lambda e: self._ajustar_nome_resp(w))
        w["digitar"] = tk.Frame(linha, bg=COR_CARTAO)
        tk.Label(w["digitar"], text="Nome:", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold")).pack(side="left", padx=(0, 6))
        w["entrada"] = ttk.Entry(w["digitar"], textvariable=var_nome, style="Campo.TEntry", font=(FONTE, 10))
        w["entrada"].pack(side="left", fill="x", expand=True)
        w["escolha"].trace_add("write", lambda *_: self._ao_escolher_resp(w))
        return w

    def _preencher_escolha_resp(self, w, a):
        for c in w["chips"].winfo_children():
            c.destroy()
        w["opcoes"] = self._responsaveis(a)
        if a.get("responsavel") and all(sem_acento(n) != sem_acento(a["responsavel"]) for _r, n in w["opcoes"]):
            w["opcoes"].append(("Responsável", a["responsavel"]))
        for rotulo_, _n in w["opcoes"]:
            Chip(w["chips"], rotulo_, w["escolha"], rotulo_).pack(side="left", padx=(0, 6))
        Chip(w["chips"], "Outro", w["escolha"], "Outro").pack(side="left")
        # começa em quem fez a matrícula (se estiver no arquivo)
        padrao = next((r for r, n in w["opcoes"] if a.get("responsavel") and sem_acento(n) == sem_acento(a["responsavel"])),
                      w["opcoes"][0][0] if w["opcoes"] else "Outro")
        if w["escolha"].get() == padrao:
            self._ao_escolher_resp(w)
        else:
            w["escolha"].set(padrao)

    def _ao_escolher_resp(self, w):
        escolha = w["escolha"].get()
        nome = dict(w["opcoes"]).get(escolha, "")
        if escolha != "Outro" and nome:
            w["nome"].set(nome)
            w["digitar"].pack_forget()
            w["rotulo"].pack(side="left", fill="x", expand=True)
            self._ajustar_nome_resp(w)
        else:
            w["nome"].set("")
            w["rotulo"].pack_forget()
            w["digitar"].pack(side="left", fill="x", expand=True)
            if self.aluno and self.var_tipo.get() in TERMOS:
                w["entrada"].focus_set()
        self._reajustar()

    def _ajustar_nome_resp(self, w):
        """Mostra o nome inteiro; se não couber ao lado do CPF/WhatsApp, termina com '…' (só na tela)."""
        if w["escolha"].get() == "Outro":
            return
        nome = w["nome"].get()
        livre = w["linha"].winfo_width() - w["lado_quadro"].winfo_reqwidth() - 12
        texto = nome
        if livre > 40:
            while texto and w["fonte"].measure(texto + "…") > livre:
                texto = texto[:-1]
            texto = nome if texto == nome else texto.rstrip() + "…"
        w["rotulo"].configure(text=texto)

    def _ao_mudar_motivo(self):
        if self.termo["motivo"].get() == "Outro":
            self.campo_motivo_outro.pack(side="left", padx=(8, 0))
            self.campo_motivo_outro.entrada.focus_set()
        else:
            self.campo_motivo_outro.pack_forget()
        self._reajustar()

    def _preparar_termos(self, a):
        """Ao escolher o aluno: limpa os campos dos termos e mostra o que vem do arquivo."""
        t = self.termo
        for k in ("data_falta", "qtd_faltas", "bolsa", "motivo_outro", "profissao", "c_nome", "c_cpf"):
            t[k].set("")
        t["motivo"].set("(em branco)")
        t["telefone"].set(a.get("telefone", ""))
        self._preencher_escolha_resp(self.resp_just, a)
        t["horario"].set(datetime.now().strftime("%H:%M"))
        self._cpf_automatico = ""
        self._preencher_escolha_resp(self.resp_comp, a)
        self._ao_mudar_resp_comp()
        self.info_compromisso.configure(text="Endereço, bairro, telefone, série, turma e turno saem do arquivo.")

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

    def _reajustar(self):
        """Conteúdo mudou de altura: acerta a barra de rolagem na hora (sem esperar a vigia)."""
        try:
            self.update_idletasks()
            self.area.ajustar()
        except (tk.TclError, AttributeError):
            pass

    def _preparar_frequencia(self, a):
        """Ao escolher o aluno: períodos com frequência do Gier e o % já calculado."""
        self.freq_aluno = frequencia_do_aluno(self.freq, a)
        if self.freq_aluno:
            meses = [m for m, _r in self.freq_aluno]
            todos = "Todos os meses ({})".format(meses[0] if len(meses) == 1 else meses[0] + " a " + meses[-1])
            self.combo_periodo.configure(values=[todos] + meses)
            self._periodo_todos = todos
            self.ext["freq_periodo"].set(todos)
            self._ao_mudar_periodo()
        else:
            self.combo_periodo.configure(values=[])
            self._periodo_todos = ""
            self.ext["freq_periodo"].set("")
            self.ext["freq"].set("")
            self.aviso_freq.configure(text="Sem frequência do Gier para este aluno. Clique em "
                                           "\"Atualizar frequência\", no quadro 4, ou digite a %." if self.freq.get("meses") else
                                      "Para preencher sozinho, clique em \"Atualizar frequência\", no quadro 4. "
                                      "Ou digite a %.")

    def _ao_mudar_periodo(self):
        regs = getattr(self, "freq_aluno", [])
        if not regs:
            return
        escolha = self.ext["freq_periodo"].get()
        if escolha != getattr(self, "_periodo_todos", ""):
            regs = [(m, r) for m, r in regs if m == escolha]
        soma = somar_frequencia(regs)
        if soma:
            pct, faltas, dias = soma
            self._aviso_gier = "Do Gier ({}): {} dia(s) letivo(s), {} falta(s).".format(
                _nome_periodo(regs), dias, faltas)
            self._freq_calculada = pct_br(pct)
            self.ext["freq"].set(self._freq_calculada)
        else:
            self._aviso_gier = "O Gier não tem dias letivos para esse período."
            self.ext["freq"].set("")
        self._mostrar_previa_freq()
        self._atualizar_linha_freq()

    def _mostrar_previa_freq(self):
        """Embaixo do período: os números do Gier e como a frase vai sair na declaração."""
        if not getattr(self, "freq_aluno", None) or not getattr(self, "_aviso_gier", ""):
            return
        e = self._extras_atuais()
        texto = self._aviso_gier
        if e.get("freq"):
            texto += "\nNa declaração: frequência de {}% {}.".format(
                e["freq"].replace("%", "").strip(), e.get("freq_mes") or "até a presente data")
        self.aviso_freq.configure(text=texto)

    def _texto_linha_freq(self, regs):
        """A linha 'Frequência' do quadro 2, do período escolhido no quadro 3."""
        soma = somar_frequencia(regs)
        if not soma:
            return ""
        return "{}% de presença · {} falta(s) · {} dia(s) ({})".format(pct_br(soma[0]), soma[1], soma[2], _nome_periodo(regs))

    def _regs_do_periodo(self, regs):
        escolha = self.ext["freq_periodo"].get()
        return [(m, r) for m, r in regs if m == escolha] or regs

    def _atualizar_linha_freq(self):
        rotulo_freq = getattr(self, "_rotulo_freq", None)
        if rotulo_freq is not None and rotulo_freq.winfo_exists():
            texto = self._texto_linha_freq(self._regs_do_periodo(self.freq_aluno))
            rotulo_freq.configure(text=texto or "não consta no arquivo", fg=COR_TEXTO if texto else "#A0A8B8")

    def _mostrar_extras(self):
        for chave, quadro in self.extras.items():
            if chave == self.var_tipo.get():
                quadro.pack(fill="x")
            else:
                quadro.pack_forget()

    # -- banco de dados e pesquisa ------------------------------------------
        self._reajustar()

    def _atualizar_banco(self):
        tem = bool(self.alunos)
        self.marca_banco.configure(text="✓  {} alunos no banco de dados".format(len(self.alunos)) if tem else "")
        self.botao_pesquisar.definir_ativo(tem)
        self._limpar_resultados()
        if tem:
            self._mostrar_area_result(False)       # o espaço das opções só aparece quando há resultado
            self.var_status.set("Pesquise o aluno, escolha o tipo de declaração e clique em Gerar declaração.")
        else:
            self._mostrar_area_result(True)
            self.dica_result.place_forget()
            self.quadro_lista.place_forget()
            self.vazio.place(x=0, y=0, relwidth=1, relheight=1)
            self.var_status.set("Comece abrindo o arquivo de alunos na Configuração.")
        self._atualizar_dica()

    def _x_dica(self):
        """Posição da frase cinza: logo depois do lugar onde o cursor pisca."""
        try:
            return self.entrada_busca.winfo_x() + 8 if self.entrada_busca.winfo_x() > 0 else 48
        except tk.TclError:
            return 48

    def _atualizar_dica(self):
        if self.var_busca.get():
            self.dica_busca.place_forget()
        else:
            self.dica_busca.place(x=self._x_dica(), rely=0.5, anchor="w")

    def _mostrar_area_result(self, mostrar):
        gerenciado = self.area_result.winfo_manager() == "pack"   # vale mesmo antes de a janela aparecer
        if mostrar and not gerenciado:
            self.area_result.pack(fill="x", pady=(10, 0))
        elif not mostrar and gerenciado:
            self.area_result.pack_forget()
        self._reajustar()

    def _mostrar_dica(self, texto):
        self._mostrar_area_result(True)
        self.vazio.place_forget()
        self.quadro_lista.place_forget()
        self.dica_result.configure(text=texto)
        self.dica_result.place(x=0, y=0, relwidth=1, relheight=1)

    def _limpar_resultados(self):
        for w in self.linhas.winfo_children():
            w.destroy()
        self.linhas_resultado = []
        self.achados = []
        self.todos_achados = []
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
        if alvo is None:
            return
        if alvo.winfo_toplevel() is not self:              # rodinha na janela de Configuração
            topo = alvo.winfo_toplevel()
            if hasattr(topo, "area"):
                topo.area.rolar(evento)
            return
        w = alvo
        while w is not None and w is not self.quadro_lista:
            w = w.master
        if w is not None and self.rolagem.winfo_ismapped():
            self.tela.yview_scroll(int(-evento.delta / 120) or (-1 if evento.delta > 0 else 1), "units")
            return
        if alvo.winfo_class() not in ("TCombobox", "Listbox", "Treeview"):
            self._area_ativa().rolar(evento)

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
        self.todos_achados = achados[:100]
        self.dica_result.place_forget()
        self.vazio.place_forget()
        self._mostrar_area_result(True)
        self.quadro_lista.place(x=0, y=0, relwidth=1, relheight=1)
        self._desenhar_linhas(self.todos_achados)
        if len(achados) == 1:               # mesmo com um só, a pessoa confere o nome e clica (pedido do Jansey)
            self.var_status.set("1 aluno encontrado. Clique no nome para escolher.")
        else:
            extra = " (mostrando os 100 primeiros)" if len(achados) > 100 else ""
            self.var_status.set("{} alunos encontrados{}. Clique no aluno certo.".format(len(achados), extra))

    def _desenhar_linhas(self, lista):
        for w in self.linhas.winfo_children():
            w.destroy()
        self.linhas_resultado = []
        self.escolhido = -1
        self.achados = list(lista)
        for i, a in enumerate(self.achados):
            self._linha_resultado(i, a)
        self.tela.yview_moveto(0)
        self.after_idle(self._ajustar_rolagem)

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
        """Escolhe o aluno: o nome vai para o campo de pesquisa e a lista de opções some."""
        a = self.achados[n]
        self._escolher(a)
        self.var_busca.set(a.get("social") or a.get("nome") or "")
        self.entrada_busca.icursor("end")
        self._limpar_resultados()
        self.quadro_lista.place_forget()
        self.dica_result.place_forget()
        self._mostrar_area_result(False)

    def _escolher(self, a):
        self.aluno = {k: v for k, v in a.items() if not k.startswith("_")}
        agora = datetime.now()
        self.ext["proxima"].set(proxima_serie(a.get("serie")))
        self._parentesco_padrao(self.aluno)
        self._preparar_termos(self.aluno)
        self.ext["hora_fim"].set(agora.strftime("%H:%M"))
        self.ext["hora_ini"].set("{:02d}:{:02d}".format(max(agora.hour - 1, 0), agora.minute))
        self._preparar_frequencia(self.aluno)
        self.ext["destino"].set("")
        self._mostrar_aluno()
        self._reajustar()
        self.var_status.set("Escolha o tipo de declaração e clique em Gerar declaração.")

    def _responsaveis(self, a):
        """Responsáveis do aluno que vieram no arquivo: [(rótulo, nome)]."""
        lista = [("Mãe", a.get("mae")), ("Pai", a.get("pai"))]
        if a.get("responsavel") and sem_acento(a["responsavel"]) not in (sem_acento(a.get("mae")), sem_acento(a.get("pai"))):
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
        self._reajustar()

    def _ao_mudar_assinatura(self):
        quem = self.var_assina.get()
        self.cfg["assina"] = quem
        gravar_json(ARQ_CONFIG, self.cfg)
        if not self.cfg.get(quem + "_nome"):
            self.var_status.set("O nome do {} ainda não foi cadastrado na Configuração; a declaração sai só "
                                "com a linha para assinatura.".format("gestor(a)" if quem == "gestor" else "secretário(a)"))

    _quebra_info = 270

    def _ajustar_quebras(self, largura):
        """Com a janela maximizada, o texto do quadro 2 usa a largura toda antes de quebrar a linha."""
        largura = max(largura, 200)
        self.nome_aluno.configure(wraplength=largura)
        self.alerta_aluno.configure(wraplength=largura)
        col0 = max((w.winfo_reqwidth() for w in self.info_aluno.grid_slaves(column=0)), default=90)
        self._quebra_info = max(largura - col0 - 14, 150)
        for w in self.info_aluno.grid_slaves(column=1):
            w.configure(wraplength=self._quebra_info)
        self.info_compromisso.configure(wraplength=max(self.area_extras.winfo_width(), 300))

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
        if self.freq.get("meses"):
            regs = frequencia_do_aluno(self.freq, a)
            itens.append(("Frequência", self._texto_linha_freq(self._regs_do_periodo(regs)) if regs else ""))
        self._rotulo_freq = None
        for i, (titulo, valor) in enumerate(itens):
            tk.Label(self.info_aluno, text=titulo, bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9, "bold"),
                     anchor="nw").grid(row=i, column=0, sticky="nw", padx=(0, 10), pady=1)
            rotulo_valor = tk.Label(self.info_aluno, text=valor or "não consta no arquivo", bg=COR_CARTAO,
                                    fg=COR_TEXTO if valor else "#A0A8B8", font=(FONTE, 9), anchor="nw", justify="left",
                                    wraplength=self._quebra_info)
            rotulo_valor.grid(row=i, column=1, sticky="nw", pady=1)
            if titulo == "Frequência":
                self._rotulo_freq = rotulo_valor
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
        periodo = e.get("freq_periodo", "")
        meses = [m.lower() for m, _r in getattr(self, "freq_aluno", [])]
        if periodo and periodo != getattr(self, "_periodo_todos", ""):
            meses = [periodo.lower()]
        if not periodo or not meses or e.get("freq", "") != getattr(self, "_freq_calculada", None):
            e["freq_mes"] = ""                     # % digitada à mão: "até a presente data"
        elif len(meses) == 1:
            e["freq_mes"] = "no mês de " + meses[0]
        else:
            e["freq_mes"] = "no período de {} a {}".format(meses[0], meses[-1])
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
            w = self.resp_just if tipo == "justificativa" else self.resp_comp
            if w["escolha"].get() == "Outro" and not w["nome"].get().strip():
                self.var_status.set("Digite o nome do responsável (opção Outro).")
                w["entrada"].focus_set()
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
        if not self.sessao.pode("configuracao"):
            messagebox.showinfo(NOME_PROGRAMA, "Só o administrador pode abrir a Configuração.", parent=self)
            return
        JanelaConfiguracao(self)

    def _abrir_usuarios(self):
        """Tela do administrador: quem pode entrar e o que cada pessoa vê."""
        if not self.sessao.pode("usuarios") or self.sessao.sem_login:
            return
        if self.sessao.sem_internet:
            messagebox.showinfo(NOME_PROGRAMA, "Sem internet agora. Para liberar ou cadastrar pessoas, o programa precisa "
                                "estar conectado.", parent=self)
            return
        aberta = getattr(self, "_janela_usuarios", None)
        if aberta is not None and aberta.winfo_exists():
            aberta.lift()
            return
        self._janela_usuarios = tela_usuarios.JanelaUsuarios(self)

    def _sair(self):
        """Fecha a janela e volta para a tela de entrada (para trocar de usuário)."""
        pendentes = sum(p.pendentes() for p in self.paineis.values())
        if pendentes and not messagebox.askyesno(
                NOME_PROGRAMA, "Há material numa lista de entrada ou saída que ainda não foi registrado.\n\n"
                "Sair mesmo assim? O que está na lista será perdido.", icon="warning", parent=self):
            return
        if not self.sessao.sem_login:
            acesso.esquecer_senha(self.sessao.email)      # "Sair" apaga a senha salva neste computador (PC compartilhado)
        self.trocar_usuario = True
        self.destroy()

    # ----- Frequência: "Atualizar frequência do Gier" (busca sozinha, depois do login) -----
    def atualizar_frequencia_tela(self):
        """Frequência nova: refaz só a linha do quadro 2 e o % (sem apagar o que já foi digitado)."""
        self.mostrar_data_frequencia()
        if self.aluno:
            self._preparar_frequencia(self.aluno)
            self._mostrar_aluno()
            self._reajustar()

    def _registrar(self, texto):
        """Anota em gier.log o que aconteceu (para descobrir o que deu errado)."""
        try:
            with open(os.path.join(pasta_dados(), "gier.log"), "a", encoding="utf-8") as f:
                f.write("{}  {}\n".format(datetime.now().strftime("%d/%m/%Y %H:%M:%S"), texto))
        except Exception:
            pass

    def atualizar_do_gier(self, pai=None):
        if getattr(self, "_janela_gier", None) is not None and self._janela_gier.winfo_exists():
            self._janela_gier.lift()
            return
        JanelaGier(self, pai or self)

    def _acertar_nome_tipo(self):
        nome = NOME_TIPO[self.var_tipo.get()]
        if self.var_nome_tipo.get() != nome:
            self.var_nome_tipo.set(nome)

    def mostrar_data_frequencia(self):
        """Quadro 4: de quando é a frequência guardada, que alimenta as porcentagens."""
        try:
            quando = datetime.fromisoformat(self.freq.get("atualizado_em") or "")
            texto = "Porcentagens de {}".format(quando.strftime("%d/%m/%Y às %H:%M"))
        except (ValueError, TypeError):
            texto = "Porcentagens ainda não atualizadas"
        self.data_frequencia.configure(text=texto)

    def mostrar_estado_gier(self):
        """Quadro 4: conectado ou não, como no Frequência Inteligente."""
        conectado = self.sessao_gier is not None and self.sessao_gier.conectado
        self.estado_gier.configure(text="●  Conectado" if conectado else "Não conectado",
                                   fg=COR_VERDE if conectado else COR_TEXTO_FRACO)
        self.usuario_gier.configure(text=(self.cfg.get("gier_usuario") or "") if conectado
                                    else "Entre para usar os comandos.")
        self.botao_gier.definir_texto("Desconectar" if conectado else "Entrar no Gier")

    def _ao_clicar_gier(self):
        if getattr(self, "_janela_gier", None) is not None and self._janela_gier.winfo_exists():
            self._janela_gier.lift()
            return
        if self.sessao_gier is not None and self.sessao_gier.conectado:
            self.sessao_gier.sair()
            self.sessao_gier = None
            self.mostrar_estado_gier()
            self.var_status.set("Desconectado do Gier.")
        else:
            JanelaGier(self, self, depois=lambda: None)

    def baixar_frequencia_gier(self):
        """Quadro 4: entra no Gier, se precisar, e abre a escolha de turmas e meses."""
        if getattr(self, "_janela_gier", None) is not None and self._janela_gier.winfo_exists():
            self._janela_gier.lift()
            return
        if self.sessao_gier is not None and self.sessao_gier.conectado:
            JanelaBaixarFrequencia(self, self)
        else:
            JanelaGier(self, self, depois=lambda: JanelaBaixarFrequencia(self, self))

    def _aviso_flutuante(self, titulo, texto, segundos=8, rodape="Pode baixar a próxima turma."):
        """Aviso verde no canto da tela, que some sozinho."""
        try:
            antigo = getattr(self, "_janela_aviso", None)
            if antigo is not None and antigo.winfo_exists():
                antigo.destroy()
            j = tk.Toplevel(self)
            self._janela_aviso = j
            j.overrideredirect(True)
            j.attributes("-topmost", True)
            caixa = tk.Frame(j, bg=COR_VERDE, padx=18, pady=12)
            caixa.pack()
            tk.Label(caixa, text=titulo, bg=COR_VERDE, fg="#FFFFFF", font=(FONTE, 11, "bold"),
                     anchor="w").pack(anchor="w")
            tk.Label(caixa, text=texto, bg=COR_VERDE, fg="#FFFFFF", font=(FONTE, 9), anchor="w",
                     justify="left", wraplength=420).pack(anchor="w", pady=(2, 0))
            if rodape:
                tk.Label(caixa, text=rodape, bg=COR_VERDE, fg="#DDF5E6",
                         font=(FONTE, 9), anchor="w").pack(anchor="w", pady=(2, 0))
            j.update_idletasks()
            x = j.winfo_screenwidth() - j.winfo_reqwidth() - 24
            y = j.winfo_screenheight() - j.winfo_reqheight() - 72
            j.geometry("+{}+{}".format(max(x, 0), max(y, 0)))
            j.bind("<Button-1>", lambda e: j.destroy())
            for w in caixa.winfo_children() + [caixa]:
                w.bind("<Button-1>", lambda e: j.destroy())
            j.after(segundos * 1000, lambda: j.winfo_exists() and j.destroy())
        except Exception:
            pass

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
        base = self.cfg.get("pasta_estoque") or os.path.join(pasta_dados(), "estoque")
        if self.livros and os.path.normpath(os.path.dirname(self.livros["pedagogico"].pasta)) != os.path.normpath(base):
            self._abrir_livros()                      # a pasta do estoque mudou: lê os livros de lá
            for painel in self.paineis.values():
                painel.destroy()
            self.paineis = {}
            self._atualizar_selos()
            if self.barra_abas.ativa != "declaracoes":
                self._ao_mudar_aba(self.barra_abas.ativa)


def _nome_meses_arquivo(nomes):
    """'Setembro' / 'Agosto a Outubro' (seguidos) / 'Agosto, Outubro'."""
    if len(nomes) == 1:
        return nomes[0]
    numeros = [_mes_chave(n) for n in nomes]
    if numeros == list(range(numeros[0], numeros[0] + len(numeros))):
        return "{} a {}".format(nomes[0], nomes[-1])
    return ", ".join(nomes)


def _caminho_livre(caminho):
    """O mesmo caminho, ou 'nome (2).pdf' se já existir: nada é sobrescrito."""
    if not os.path.exists(caminho):
        return caminho
    base, extensao = os.path.splitext(caminho)
    n = 2
    while os.path.exists("{} ({}){}".format(base, n, extensao)):
        n += 1
    return "{} ({}){}".format(base, n, extensao)


class JanelaBaixarFrequencia(tk.Toplevel):
    """Quadro 4: a pessoa escolhe turmas e meses e recebe um PDF do Gier por turma."""

    def __init__(self, app, pai):
        super().__init__(pai)
        import queue
        self.app = app
        self.pai = pai
        app._janela_gier = self
        self.title("Baixar frequência do Gier")
        self.configure(bg=COR_FUNDO)
        self.transient(pai)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._fechar_pedido)
        self.fila = queue.Queue()
        self._parar = False
        self._ocupado = False
        self.filtros = None
        self.vars_turmas, self.vars_meses = [], []
        self.pasta = os.path.join(app.cfg.get("pasta_saida") or os.path.join(pasta_documentos(), "Declarações Escolares"),
                                  "Frequência do Gier")
        self.ultima_pasta = ""
        caixa = tk.Frame(self, bg=COR_CARTAO, highlightthickness=1, highlightbackground=COR_BORDA)
        caixa.pack(fill="both", expand=True, padx=14, pady=14)
        self.dentro = tk.Frame(caixa, bg=COR_CARTAO)
        self.dentro.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(self.dentro, text="Baixar frequência do Gier", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold"), anchor="w").pack(anchor="w")
        rotulo(self.dentro, "Escolha as turmas e os meses. O programa salva um PDF por turma.",
               fraco=True, tam=9).pack(anchor="w", pady=(2, 8))

        self.area_escolha = tk.Frame(self.dentro, bg=COR_CARTAO)
        self.area_escolha.pack(fill="x")
        self.var_andamento = tk.StringVar(value="Abrindo o relatório de frequência...")
        self.andamento = tk.Label(self.dentro, textvariable=self.var_andamento, bg=COR_LINHA, fg=COR_TEXTO,
                                  font=(FONTE, 10, "bold"), anchor="w", justify="left", wraplength=620,
                                  padx=12, pady=8, highlightthickness=1, highlightbackground=COR_BORDA)
        self.andamento.pack(fill="x", pady=(10, 0))

        linha = tk.Frame(self.dentro, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        rotulo(linha, "Salvar em:", fraco=True, negrito=True, tam=9).pack(side="left")
        self.rotulo_pasta = rotulo(linha, "", tam=9)
        self.rotulo_pasta.pack(side="left", padx=(6, 8))
        self.botao_pasta = Botao(linha, "Trocar pasta", self._trocar_pasta, estilo="tracejado",
                                 fonte=(FONTE, 9, "bold"), pad_x=10, pad_y=3, raio=8)
        self.botao_pasta.pack(side="right")
        self._mostrar_pasta()

        botoes = tk.Frame(self.dentro, bg=COR_CARTAO)
        botoes.pack(anchor="e", pady=(12, 0))
        self.botao_abrir = Botao(botoes, "Abrir pasta", self._abrir_pasta, estilo="suave")
        self.botao_abrir.pack(side="left", padx=(0, 8))
        self.botao_abrir.definir_ativo(False)
        self.botao_fechar = Botao(botoes, "Fechar", self._fechar_pedido, estilo="suave")
        self.botao_fechar.pack(side="left", padx=(0, 8))
        self.botao_baixar = Botao(botoes, "Baixar PDF", self._baixar, estilo="principal")
        self.botao_baixar.pack(side="left")
        self.botao_baixar.definir_ativo(False)

        import threading
        threading.Thread(target=self._carregar, daemon=True).start()
        self.after(150, self._olhar_fila)
        self.update_idletasks()
        self._centralizar()
        self.grab_set()

    def _centralizar(self):
        self.update_idletasks()
        x = self.pai.winfo_rootx() + (self.pai.winfo_width() - self.winfo_reqwidth()) // 2
        y = self.pai.winfo_rooty() + max((self.pai.winfo_height() - self.winfo_reqheight()) // 3, 0)
        self.geometry("+{}+{}".format(max(x, 0), max(y, 0)))

    def _mostrar_pasta(self):
        texto = self.pasta
        self.rotulo_pasta.configure(text=texto if len(texto) <= 62 else "..." + texto[-59:])

    def _trocar_pasta(self):
        escolhida = filedialog.askdirectory(parent=self, title="Onde salvar os PDFs", initialdir=self.pasta)
        if escolhida:
            self.pasta = os.path.normpath(escolhida)
            self._mostrar_pasta()

    def _abrir_pasta(self):
        if self.ultima_pasta:
            abrir_arquivo(self.ultima_pasta)

    # -- carregar turmas e meses (em segundo plano) ---------------------------
    def _carregar(self):
        import gier_auto
        import gier_online
        try:
            filtros = gier_auto.preparar_relatorio(self.app.sessao_gier, self.app._registrar)
            turmas = gier_auto.listar_turmas(filtros, self.app._registrar)
            meses = [m for m in filtros.opcoes_fixas("mes") if str(m["id"]) != "-1"]
            self.fila.put(("carregou", (filtros, turmas, meses)))
        except gier_online.ErroGier as erro:
            self.fila.put(("sessao" if erro.codigo == "sessao_expirada" else "erro_carregar",
                           gier_online.texto_do_erro(erro)))
        except Exception as erro:
            self.app._registrar("ERRO ao abrir Baixar frequência: {}".format(type(erro).__name__))
            self.fila.put(("erro_carregar", "Não foi possível abrir o relatório. Tente novamente."))

    def _montar_escolha(self, turmas, meses):
        esquerda = tk.Frame(self.area_escolha, bg=COR_CARTAO)
        esquerda.pack(side="left", fill="both", expand=True, padx=(0, 16))
        direita = tk.Frame(self.area_escolha, bg=COR_CARTAO)
        direita.pack(side="left", fill="y")

        def titulo(pai, texto, marcar):
            cab = tk.Frame(pai, bg=COR_CARTAO)
            cab.pack(fill="x", pady=(0, 4))
            rotulo(cab, texto, negrito=True).pack(side="left")
            ligacao = tk.Label(cab, text="Limpar", bg=COR_CARTAO, fg=COR_AZUL, cursor="hand2", font=(FONTE, 9, "underline"))
            ligacao.pack(side="right", padx=(10, 0))
            ligacao.bind("<Button-1>", lambda e: marcar(False))
            ligacao = tk.Label(cab, text="Marcar todas" if texto == "Turmas" else "Marcar todos", bg=COR_CARTAO,
                               fg=COR_AZUL, cursor="hand2", font=(FONTE, 9, "underline"))
            ligacao.pack(side="right")
            ligacao.bind("<Button-1>", lambda e: marcar(True))

        def marcar_turmas(valor):
            for var, _t in self.vars_turmas:
                var.set(valor)

        def marcar_meses(valor):
            for var, _m in self.vars_meses:
                var.set(valor)

        titulo(esquerda, "Turmas", marcar_turmas)
        moldura = tk.Frame(esquerda, bg=COR_CARTAO, highlightthickness=1, highlightbackground=COR_BORDA)
        moldura.pack(fill="both", expand=True)
        tela = tk.Canvas(moldura, bg=COR_CARTAO, highlightthickness=0, bd=0, width=360, height=270)
        barra = ttk.Scrollbar(moldura, orient="vertical", command=tela.yview)
        tela.configure(yscrollcommand=barra.set)
        tela.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        grade = tk.Frame(tela, bg=COR_CARTAO)
        tela.create_window(0, 0, window=grade, anchor="nw")
        for i, turma in enumerate(turmas):
            var = tk.BooleanVar(value=False)
            self.vars_turmas.append((var, turma))
            ttk.Checkbutton(grade, text=turma["descricao"], variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=1)
        grade.update_idletasks()
        tela.configure(scrollregion=(0, 0, grade.winfo_reqwidth(), grade.winfo_reqheight()))
        if grade.winfo_reqheight() > 270:
            barra.pack(side="right", fill="y")
            for w in [tela, grade] + grade.winfo_children():
                w.bind("<MouseWheel>", lambda e: tela.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        titulo(direita, "Meses", marcar_meses)
        grade_meses = tk.Frame(direita, bg=COR_CARTAO, highlightthickness=1, highlightbackground=COR_BORDA)
        grade_meses.pack(fill="both", expand=True)
        for i, mes in enumerate(meses):
            var = tk.BooleanVar(value=False)
            self.vars_meses.append((var, mes))
            ttk.Checkbutton(grade_meses, text=mes["descricao"], variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)
        self.botao_baixar.definir_ativo(True)
        self._centralizar()

    # -- baixar ----------------------------------------------------------------
    def _baixar(self):
        turmas = [t for var, t in self.vars_turmas if var.get()]
        meses = [m for var, m in self.vars_meses if var.get()]
        if not turmas or not meses:
            self.var_andamento.set("Marque pelo menos uma turma e um mês.")
            return
        import threading
        self._ocupado = True
        self._parar = False
        self.botao_baixar.definir_ativo(False)
        self.botao_pasta.definir_ativo(False)
        self.botao_abrir.definir_ativo(False)
        self.botao_fechar.definir_texto("Cancelar")
        todos = len(meses) == len(self.vars_meses)
        threading.Thread(target=self._trabalhar, args=(turmas, meses, todos, self.pasta), daemon=True).start()

    def _trabalhar(self, turmas, meses, todos, pasta):
        import gier_auto
        import gier_online
        codigos = ["-1"] if todos else [str(m["id"]) for m in meses]
        nomes = [m["descricao"] for m in meses]
        periodo = "Todos os meses" if todos else _nome_meses_arquivo(nomes)
        salvos, problemas, sem_dias = [], [], []
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError as erro:
            self.fila.put(("fim", ([], ["Não consegui criar a pasta ({}).".format(type(erro).__name__)], [], False)))
            return
        for n, turma in enumerate(turmas, 1):
            if self._parar:
                self.fila.put(("fim", (salvos, problemas, sem_dias, True)))
                return
            self.fila.put(("andamento", "Baixando: turma {} de {} ({})".format(n, len(turmas), turma["descricao"])))
            caminho = _caminho_livre(os.path.join(pasta, nome_arquivo_seguro(
                "{} - {}".format(turma["descricao"], periodo)) + ".pdf"))
            try:
                motivo, vazio = gier_auto.baixar_pdf_da_turma(
                    self.filtros, turma, codigos, caminho, self.app._registrar, None if todos else nomes)
            except gier_online.ErroGier as erro:
                if erro.codigo == "sessao_expirada":
                    self.fila.put(("sessao", gier_online.texto_do_erro(erro)))
                    return
                motivo, vazio = gier_online.texto_do_erro(erro), False
            except Exception as erro:
                self.app._registrar("ERRO ao baixar {}: {}".format(turma["descricao"], type(erro).__name__))
                motivo, vazio = "não foi possível gravar o PDF", False
            if motivo:
                problemas.append("{}: {}".format(turma["descricao"], motivo))
            else:
                salvos.append(caminho)
                if vazio:
                    sem_dias.append(turma["descricao"])
        self.fila.put(("fim", (salvos, problemas, sem_dias, False)))

    def _terminou_download(self, salvos, problemas, sem_dias, cancelado):
        self._ocupado = False
        self.botao_fechar.definir_texto("Fechar")
        self.botao_baixar.definir_ativo(True)
        self.botao_pasta.definir_ativo(True)
        self.ultima_pasta = self.pasta if salvos else self.ultima_pasta
        self.botao_abrir.definir_ativo(bool(self.ultima_pasta))
        partes = ["{} PDF(s) salvos.".format(len(salvos))]
        if cancelado:
            partes.insert(0, "Cancelado.")
        if sem_dias:
            partes.append("Sem dias letivos no período: {}.".format(", ".join(sem_dias[:6])))
        if problemas:
            partes.append("Não deu para baixar {}: {}".format(len(problemas), " ".join(problemas[:3])))
        self.var_andamento.set(" ".join(partes))
        self.app.var_status.set("Frequência do Gier: {} PDF(s) salvos em {}.".format(len(salvos), self.pasta))
        self.app._registrar("Baixar frequência: {} PDF(s), {} problema(s)".format(len(salvos), len(problemas)))
        self._centralizar()

    def _olhar_fila(self):
        import queue
        if not self.winfo_exists():            # fechada: o que ainda chegar é ignorado
            return
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "andamento":
                    self.var_andamento.set(dado)
                elif tipo == "carregou":
                    self.filtros, turmas, meses = dado
                    self.var_andamento.set("Marque as turmas e os meses e clique em Baixar PDF.")
                    self._montar_escolha(turmas, meses)
                elif tipo == "erro_carregar":
                    self.var_andamento.set(dado)
                elif tipo == "sessao":
                    self.app.sessao_gier = None
                    self.app.mostrar_estado_gier()
                    self.var_andamento.set("A conexão com o Gier expirou. Feche esta janela e clique em "
                                           "Baixar frequência de novo.")
                    self._ocupado = False
                    self.botao_baixar.definir_ativo(False)
                elif tipo == "fim":
                    self._terminou_download(*dado)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._olhar_fila)

    def _fechar_pedido(self):
        # Fecha na hora. O download para sozinho na próxima turma; o PDF da turma em
        # andamento ainda pode ser salvo, porque ele não fica pela metade.
        if self._ocupado:
            self._parar = True
            self.app.var_status.set("Download cancelado. Os PDFs já baixados estão em {}.".format(self.pasta))
        self._fechar()

    def _fechar(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.app._janela_gier = None
        self.app._janelas_gier_fechadas.append(self)   # ver JanelaGier._fechar
        if self.winfo_exists():
            self.destroy()


class JanelaGier(tk.Toplevel):
    """O Gier dentro do programa: pede usuário e senha aqui mesmo e busca a frequência sem navegador.
    A senha só passa pela memória; a conexão termina quando o programa fecha."""

    def __init__(self, app, pai, depois=None):
        super().__init__(pai)
        self.app = app
        self.pai = pai
        self.depois = depois           # o que fazer depois de entrar; sem isso, atualiza a frequência
        app._janela_gier = self
        self.title("Entrar no Gier" if depois else "Atualizar frequência do Gier")
        self.configure(bg=COR_FUNDO)
        self.transient(pai)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        caixa = tk.Frame(self, bg=COR_CARTAO, highlightthickness=1, highlightbackground=COR_BORDA)
        caixa.pack(fill="both", expand=True, padx=16, pady=16)
        self.dentro = tk.Frame(caixa, bg=COR_CARTAO)
        self.dentro.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(self.dentro, text="Entrar no Gier" if depois else "Atualizar frequência do Gier", bg=COR_CARTAO,
                 fg=COR_AZUL_ESCURO, font=(FONTE, 13, "bold"), anchor="w").pack(anchor="w")

        # Tela 1: usuário e senha
        self.tela_login = tk.Frame(self.dentro, bg=COR_CARTAO)
        rotulo(self.tela_login, "Entre com o mesmo usuário e senha do Gier. A senha não é gravada." if depois else
                                "Entre com o mesmo usuário e senha do Gier. O programa busca sozinho "
                                "todas as turmas e todos os meses. A senha não é gravada.",
               fraco=True, tam=9, wraplength=440, justify="left").pack(anchor="w", pady=(6, 10))
        self.var_usuario = tk.StringVar(value=app.cfg.get("gier_usuario", ""))
        self.var_senha = tk.StringVar()
        q = campo(self.tela_login, "Usuário", self.var_usuario)
        q.pack(fill="x")
        self.entrada_usuario = q.entrada
        q = campo(self.tela_login, "Senha", self.var_senha)
        q.pack(fill="x", pady=(8, 0))
        self.entrada_senha = q.entrada
        self.entrada_senha.configure(show="•")
        self.aviso_login = tk.Label(self.tela_login, text="", bg=COR_CARTAO, fg="#B3261E", font=(FONTE, 9, "bold"),
                                    anchor="w", justify="left", wraplength=440)
        self.aviso_login.pack(anchor="w", pady=(8, 0))
        botoes = tk.Frame(self.tela_login, bg=COR_CARTAO)
        botoes.pack(anchor="e", pady=(8, 0))
        Botao(botoes, "Cancelar", self._cancelar, estilo="suave").pack(side="left", padx=(0, 8))
        self.botao_entrar = Botao(botoes, "Entrar no Gier", self._entrar, estilo="azul")
        self.botao_entrar.pack(side="left")
        self.entrada_usuario.bind("<Return>", lambda e: self._entrar())
        self.entrada_senha.bind("<Return>", lambda e: self._entrar())

        # Tela 2: andamento
        self.tela_busca = tk.Frame(self.dentro, bg=COR_CARTAO)
        self.var = tk.StringVar(value="Preparando...")
        tk.Label(self.tela_busca, textvariable=self.var, bg=COR_LINHA, fg=COR_TEXTO, font=(FONTE, 10, "bold"),
                 anchor="w", justify="left", wraplength=440, padx=12, pady=10, highlightthickness=1,
                 highlightbackground=COR_BORDA).pack(fill="x", pady=(10, 0))
        self.botao = Botao(self.tela_busca, "Cancelar", self._cancelar, estilo="suave")
        self.botao.pack(anchor="e", pady=(14, 0))

        import queue
        self.fila = queue.Queue()
        self._parar = False
        self._terminou = False
        self._ocupado = False
        sessao = app.sessao_gier
        if sessao is not None and sessao.conectado:      # já entrou nesta abertura do programa
            self._iniciar_busca()
        else:
            self._mostrar_login()
        self.after(200, self._olhar_fila)
        self.update_idletasks()
        x = pai.winfo_rootx() + (pai.winfo_width() - self.winfo_reqwidth()) // 2
        y = pai.winfo_rooty() + (pai.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry("+{}+{}".format(max(x, 0), max(y, 0)))
        self.grab_set()

    def _mostrar_login(self, aviso=""):
        self.tela_busca.pack_forget()
        self.tela_login.pack(fill="x")
        self.aviso_login.configure(text=aviso)
        self.botao_entrar.definir_ativo(True)
        (self.entrada_senha if self.var_usuario.get().strip() else self.entrada_usuario).focus_set()

    def _entrar(self):
        if self._ocupado:
            return
        usuario, senha = self.var_usuario.get().strip(), self.var_senha.get()
        if not usuario or not senha:
            self.aviso_login.configure(text="Digite o usuário e a senha.")
            return
        import threading
        self._ocupado = True
        self.aviso_login.configure(text="")
        self.botao_entrar.definir_ativo(False)
        self.var_senha.set("")                            # a senha não fica no campo
        threading.Thread(target=self._fazer_login, args=(usuario, senha), daemon=True).start()

    def _fazer_login(self, usuario, senha):
        import gier_online
        sessao = gier_online.SessaoGier()
        resposta = sessao.entrar(usuario, senha)
        self.fila.put(("login", (usuario, sessao, resposta)))

    def _depois_do_login(self, usuario, sessao, resposta):
        import gier_online
        self._ocupado = False
        if not resposta.get("ok"):
            self._mostrar_login(gier_online.mensagem_do_erro(resposta))
            return
        self.app.sessao_gier = sessao
        if self.app.cfg.get("gier_usuario") != usuario:   # só o usuário fica lembrado, nunca a senha
            self.app.cfg["gier_usuario"] = usuario
            gravar_json(ARQ_CONFIG, self.app.cfg)
        self.app.mostrar_estado_gier()
        if self.depois:
            self._terminou = True
            self._fechar()
            self.depois()
            return
        self._iniciar_busca()

    def _iniciar_busca(self):
        import threading
        self.tela_login.pack_forget()
        self.tela_busca.pack(fill="x")
        self.var.set("Entrando no Gier...")
        threading.Thread(target=self._trabalhar, args=(self.app.sessao_gier,), daemon=True).start()

    def _trabalhar(self, sessao):
        import gier_auto
        import gier_online
        pasta_pdfs = os.path.join(pasta_dados(), "gier_pdfs")
        try:
            for nome in os.listdir(pasta_pdfs):
                if nome.lower().endswith(".pdf"):
                    os.remove(os.path.join(pasta_pdfs, nome))
        except OSError:
            pass
        try:
            caminhos, problemas = gier_auto.buscar_frequencia(
                sessao, pasta_pdfs,
                lambda texto: self.fila.put(("andamento", texto)), lambda: self._parar,
                registrar=self.app._registrar)
            self.fila.put(("fim", (caminhos, problemas)))
        except gier_auto.Cancelado as erro:
            self.fila.put(("cancelado", str(erro)))
        except gier_online.ErroGier as erro:
            self.fila.put(("sessao" if erro.codigo == "sessao_expirada" else "erro", gier_online.texto_do_erro(erro)))
        except Exception as erro:
            import traceback
            self.app._registrar("ERRO: " + traceback.format_exc())
            self.fila.put(("erro", str(erro)))

    def _olhar_fila(self):
        import queue
        if self._terminou:                     # fechada: o que ainda chegar é ignorado
            return
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "andamento":
                    self.app._registrar(dado)
                    self.var.set(dado)
                elif tipo == "login":
                    self._depois_do_login(*dado)
                    if self._terminou:
                        return
                elif tipo == "sessao":
                    self.app.sessao_gier = None
                    self.app.mostrar_estado_gier()
                    self._mostrar_login("A conexão com o Gier expirou. Entre de novo.")
                else:
                    self._terminar(tipo, dado)
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(200, self._olhar_fila)

    def _terminar(self, tipo, dado):
        self._terminou = True
        app = self.app
        self._fechar()
        if tipo == "cancelado":
            app.var_status.set("Atualização da frequência cancelada.")
            return
        if tipo == "erro":
            app._registrar("erro: " + dado)
            messagebox.showerror(NOME_PROGRAMA, "Não consegui buscar a frequência no Gier.\n\n{}".format(dado),
                                 parent=app)
            return
        caminhos, problemas = dado
        for p in problemas:
            app._registrar("problema: " + p)
        if not caminhos:
            messagebox.showerror(NOME_PROGRAMA, "O Gier não entregou nenhuma frequência.\n\n" +
                                 "\n".join(problemas[:12]), parent=app)
            return
        banco, resumo = importar_frequencia_pdfs(caminhos)
        app.freq = banco
        app.atualizar_frequencia_tela()
        if getattr(app, "_ao_atualizar_freq", None):
            try:
                app._ao_atualizar_freq()
            except Exception:
                app._ao_atualizar_freq = None
        meses = sorted(resumo["meses"], key=_mes_chave)
        periodo = (meses[0] if len(meses) == 1 else "{} a {}".format(meses[0], meses[-1])) if meses else ""
        app._registrar("OK: {} turma(s), {}, {} crianças".format(len(resumo["turmas"]), periodo, resumo["criancas"]))
        texto = "{} turma(s) · {} · {} crianças".format(len(resumo["turmas"]), periodo, resumo["criancas"])
        app.var_status.set("Frequência do Gier atualizada: " + texto + ".")
        aviso = problemas + resumo["erros"]
        if aviso:
            messagebox.showwarning(NOME_PROGRAMA, "Frequência atualizada: {}.\n\nNão deu para trazer:\n{}".format(
                texto, "\n".join(aviso[:12])), parent=app)
        else:
            app._aviso_flutuante("✓  Frequência do Gier atualizada", texto, rodape="")

    def _cancelar(self):
        if self._terminou:
            return
        # Fecha na hora. A busca em segundo plano para sozinha na próxima turma, sem usar a janela,
        # e o que ela ainda entregar é ignorado.
        busca = self.tela_busca.winfo_ismapped()
        self._parar = True
        self._terminou = True
        self._fechar()
        if busca:
            self.app.var_status.set("Atualização da frequência cancelada.")

    def _fechar(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.app._janela_gier = None
        # Fica guardada até o programa fechar: os campos dela não podem ser limpos da
        # memória por outra thread, porque só a thread principal pode mexer no Tk.
        self.app._janelas_gier_fechadas.append(self)
        if self.winfo_exists():
            self.destroy()
        if self.pai is not self.app:          # a Configuração volta a ser a janela da frente
            try:
                if self.pai.winfo_exists():
                    self.pai.grab_set()
            except Exception:
                pass


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
        largura, altura = min(1060, app.winfo_screenwidth() - 40), min(800, app.winfo_screenheight() - 80)
        self.geometry("{}x{}+{}+{}".format(largura, altura, app.winfo_rootx() + 30, max(app.winfo_rooty() - 20, 0)))
        self.minsize(820, 420)
        cfg = app.cfg
        self.vars = {k: tk.StringVar(value=str(cfg.get(k, ""))) for _, k, *_ in self.CAMPOS}
        self.var_numero = tk.StringVar(value=str(cfg.get("numero", 1)))
        self.var_numerar = tk.BooleanVar(value=bool(cfg.get("numerar", True)))
        self.var_pdf = tk.BooleanVar(value=bool(cfg.get("pdf", True)))
        self.var_word = tk.BooleanVar(value=bool(cfg.get("word", False)))
        self.var_pasta = tk.StringVar(value=cfg.get("pasta_saida") or
                                      os.path.join(pasta_documentos(), "Declarações Escolares"))
        self.pasta_estoque_padrao = os.path.join(pasta_dados(), "estoque")
        self.var_pasta_estoque = tk.StringVar(value=cfg.get("pasta_estoque") or self.pasta_estoque_padrao)

        self.area = AreaRolavel(self, COR_FUNDO)
        self.area.pack(fill="both", expand=True)
        corpo = tk.Frame(self.area.miolo, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=22 if largura >= 1000 else 10, pady=18)
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
        rotulo(c, "Frequência das turmas, buscada no Gier (todos os meses).",
               fraco=True, tam=9, wraplength=360, justify="left").pack(anchor="w", pady=(12, 0))
        self.linha_freq = tk.Label(c, text="", bg=COR_LINHA, fg=COR_TEXTO, font=(FONTE, 9, "bold"),
                                   anchor="w", justify="left", highlightthickness=1,
                                   highlightbackground=COR_BORDA, padx=10, pady=6, wraplength=360)
        self.linha_freq.pack(fill="x", pady=(6, 8))
        botoes = tk.Frame(c, bg=COR_CARTAO)
        botoes.pack(anchor="w")
        Botao(botoes, "Atualizar do Gier", lambda: self.app.atualizar_do_gier(self), estilo="azul").pack(side="left")
        Botao(botoes, "Abrir PDF...", self._importar_freq, estilo="tracejado").pack(side="left", padx=(8, 0))
        self.app._ao_atualizar_freq = self._mostrar_banco
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
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        campo(linha, "Pasta do estoque de material", self.var_pasta_estoque).pack(side="left", fill="x", expand=True)
        Botao(linha, "Escolher...", self._escolher_pasta_estoque, pad_y=5, pad_x=12).pack(side="left", padx=(8, 0), pady=(18, 0))
        rotulo(c, "Para ver o mesmo estoque nos dois computadores, escolha nos dois a mesma pasta (por exemplo, uma "
                  "pasta do OneDrive). Ao trocar, copie antes a pasta antiga para a nova.",
               fraco=True, tam=9, wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

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
        meses = sorted((app.freq or {}).get("meses", {}).keys(), key=_mes_chave)
        if meses:
            criancas = len({c for m in meses for c in app.freq["meses"][m]})
            quando = ""
            try:
                quando = "\nAtualizada em " + datetime.fromisoformat(app.freq["atualizado_em"]).strftime(
                    "%d/%m/%Y às %H:%M")
            except Exception:
                pass
            self.linha_freq.configure(text="{}: {} ({} crianças){}".format(
                app.freq.get("ano", ""), ", ".join(meses), criancas, quando))
        else:
            self.linha_freq.configure(text="Nenhuma frequência aberta ainda.")

    def _importar_freq(self):
        caminhos = filedialog.askopenfilenames(
            parent=self, title="Frequência do Gier (Acompanhamento Diário)",
            filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")])
        if not caminhos:
            return
        try:
            banco, resumo = importar_frequencia_pdfs(caminhos)
        except Exception as erro:
            messagebox.showerror(NOME_PROGRAMA, "Não consegui ler a frequência.\n\n{}".format(erro), parent=self)
            return
        self.app.freq = banco
        self._mostrar_banco()
        self.app.atualizar_frequencia_tela()
        texto = "{} arquivo(s) lido(s): {}, {} turma(s).".format(
            resumo["arquivos"], ", ".join(sorted(resumo["meses"], key=_mes_chave)) or "nenhum mês",
            len(resumo["turmas"]))
        if resumo["erros"]:
            texto += "\n\n" + "\n".join(resumo["erros"])
        (messagebox.showwarning if resumo["erros"] else messagebox.showinfo)(NOME_PROGRAMA, texto, parent=self)

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

    def _escolher_pasta_estoque(self):
        pasta = filedialog.askdirectory(parent=self, title="Pasta do estoque de material")
        if pasta:
            self.var_pasta_estoque.set(os.path.normpath(pasta))

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
        pasta_estoque = os.path.normpath(self.var_pasta_estoque.get().strip() or self.pasta_estoque_padrao)
        cfg["pasta_estoque"] = "" if pasta_estoque == os.path.normpath(self.pasta_estoque_padrao) else pasta_estoque
        for velho in ("assinante", "cargo", "registro"):
            cfg.pop(velho, None)
        gravar_json(ARQ_CONFIG, cfg)
        self.app.configuracao_salva()
        self.destroy()


def testar_pdf_linha_de_comando(caminho, saida):
    """DeclaracoesEscolares.exe --testar-pdf ARQUIVO.pdf RESULTADO.json (sem abrir a janela)."""
    res = {"versao": VERSAO_PROGRAMA, "pasta_downloads": pasta_downloads()}
    try:
        import pypdfium2
        import frequencia_gier as fg
        res["pypdfium2"] = getattr(pypdfium2, "V_PYPDFIUM2", "ok")
        res["parece_acompanhamento"] = fg.parece_acompanhamento(caminho)
        alunos, info = fg.extrair_dados_pdf(caminho)
        res["criancas"] = len(alunos)
        res["meses"] = info.get("meses")
    except Exception as erro:
        res["erro"] = repr(erro)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)


def testar_gier_linha_de_comando(saida):
    """DeclaracoesEscolares.exe --testar-gier RESULTADO.json (usa GIER_BASE; para o teste no GitHub)."""
    import tempfile
    import gier_auto
    import gier_online
    res = {"versao": VERSAO_PROGRAMA}
    try:
        if not os.environ.get("GIER_BASE"):
            raise RuntimeError("este teste só roda no Gier de mentira (GIER_BASE)")
        pasta = tempfile.mkdtemp()
        sessao = gier_online.SessaoGier()
        res["senha_errada"] = sessao.entrar("teste", "errada").get("erro")
        res["login"] = sessao.entrar("teste", "x").get("ok")
        caminhos, problemas = gier_auto.buscar_frequencia(sessao, os.path.join(pasta, "pdfs"),
                                                          lambda t: None, lambda: False)
        res["pdfs"] = len(caminhos)
        res["problemas"] = problemas
        import frequencia_gier as fg
        res["criancas"] = sum(len(fg.extrair_dados_pdf(c)[0]) for c in caminhos)
    except Exception as erro:
        res["erro"] = repr(erro)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)


def testar_nota_linha_de_comando(caminho, saida):
    """DeclaracoesEscolares.exe --testar-nota LISTA.pdf RESULTADO.json (sem abrir a janela): confere, DENTRO do .exe,
    o leitor de notas (OCR), os catálogos de fábrica e os módulos do login e do aviso de versão."""
    res = {"versao": VERSAO_PROGRAMA, "congelado": bool(getattr(sys, "frozen", False))}
    try:
        import leitor_nota
        res["ocr_disponivel"], res["ocr_motivo"] = leitor_nota.disponivel()
        res["modelos_junto"] = bool(leitor_nota._pasta_modelos())
        lida = leitor_nota.LeitorNota().ler(caminho)
        res["itens"] = [{"descricao": i["descricao"], "unidade": i.get("unidade"), "quantidade": i["quantidade"]}
                        for i in lida["itens"]]
    except Exception as erro:
        res["erro_ocr"] = repr(erro)
    try:
        import catalogo
        res["catalogo_federal"] = len(catalogo.CatalogoFederal())
        res["catalogo_base_bytes"] = os.path.getsize(catalogo.caminho_base())
    except Exception as erro:
        res["erro_catalogo"] = repr(erro)
    try:
        import atualizacao
        import tela_login
        import tela_usuarios
        res["modulos_novos"] = True
        res["aviso_de_versao"] = atualizacao.mais_nova("99.0", VERSAO_PROGRAMA) and not atualizacao.mais_nova(VERSAO_PROGRAMA, VERSAO_PROGRAMA)
        res["senha_fraca"] = acesso.senha_fraca("12345678") and not acesso.senha_fraca("Boa-Senha-77")
        # criptografia da senha salva (DPAPI do Windows), só na memória: não grava nada no disco
        res["dpapi"] = (not acesso.pode_guardar_senha()) or acesso._dpapi(False, acesso._dpapi(True, b"teste")) == b"teste"
    except Exception as erro:
        res["erro_modulos"] = repr(erro)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--testar-pdf":
        testar_pdf_linha_de_comando(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--testar-gier":
        testar_gier_linha_de_comando(sys.argv[2])
        return
    if len(sys.argv) >= 4 and sys.argv[1] == "--testar-nota":
        testar_nota_linha_de_comando(sys.argv[2], sys.argv[3])
        return
    import registro
    registro.iniciar(VERSAO_PROGRAMA)
    aviso = ""
    while True:
        sessao = None                                   # sem login configurado, o programa abre como sempre
        if acesso.configurado():
            tela_login.usar(sys.modules[__name__])
            sessao = tela_login.pedir_acesso(aviso)
            if sessao is None:
                return                                  # fechou a tela de entrada
        app = Aplicacao(sessao)
        if not app.alunos and app.sessao.pode("configuracao"):
            app.after(400, app._abrir_configuracao)
        app.mainloop()
        if not app.trocar_usuario:
            return
        aviso = getattr(app, "aviso_ao_voltar", "") or "Você saiu. Entre de novo para continuar."


if __name__ == "__main__":
    main()
