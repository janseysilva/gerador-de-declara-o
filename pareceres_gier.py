# -*- coding: utf-8 -*-
"""
Pareceres do Gier: o relatório do ícone da impressora em Pedagógico / Avaliação.

No navegador o caminho é:
  1. Pedagógico → Avaliação (/Paginas/Pedagogico/Avaliacao.aspx). As caixas Ano
     letivo, Etapa, Ciclo, Turma e Unidade letiva são preenchidas pela própria
     página, com listas que já vêm nos campos ocultos hdfFiltroGeral (turmas) e
     hdfFiltroUnidadeLetiva (semestres). "Pesquisar" é um postback comum que leva
     para AvaliacaoQuestionario.aspx?c=..., com um aluno por linha.
  2. Cada linha tem a situação (lblSituacao_N: "Lançamento Completo", "Sem
     lançamentos"...) e o ícone da impressora (ctl00$cphContent$dtlAlunos$ctlNN$
     btnImprimirQuestionario). O clique é um postback assíncrono (UpdatePanel1) cuja
     resposta abre /RelatorioVisualizarImpressao.aspx: o relatório fica guardado na
     sessão.
  3. GET /RelatorioVisualizar.aspx devolve o PDF daquele aluno.

Este módulo faz o mesmo com a SessaoGier (urllib, sem navegador). Como o relatório
fica na sessão, os pedidos precisam ser um de cada vez. A página de alunos traz um
campo oculto de ~1 MB (__VIEWSTATE), que vai e volta a cada aluno: cada parecer
leva alguns segundos.

Nomes de alunos só aparecem na tela do programa e nos nomes dos arquivos: nunca no
registro técnico.
"""

import json
import re
import unicodedata
import urllib.parse
from html.parser import HTMLParser

import gier_online
import registro
from gier_online import ErroGier

CAMINHO_AVALIACAO = "/Paginas/Pedagogico/Avaliacao.aspx"
CAMINHO_QUESTIONARIO = "/Paginas/Pedagogico/AvaliacaoQuestionario.aspx"
CAMINHO_IMPRESSAO = "/RelatorioVisualizarImpressao.aspx"
CAMINHO_PDF = "/RelatorioVisualizar.aspx"
BOTAO_PESQUISAR = "ctl00$cphContent$btnPesquisar"
SCRIPT_MANAGER = "ctl00$cphHeader$ScriptManager1"
PAINEL = "ctl00$cphContent$UpdatePanel1"
SEM_LANCAMENTOS = "SEM LANCAMENTOS"


def simples(texto):
    """Sem acento, maiúsculas e um espaço só: para comparar nomes."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def sem_lancamentos(aluno):
    return simples(aluno.get("situacao")) == SEM_LANCAMENTOS


# -- leitura das páginas -------------------------------------------------------
class _LeitorFormulario(HTMLParser):
    """Guarda os campos do formulário (como o navegador os enviaria) e os textos por id."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.campos = {}           # nome -> valor (hidden, text, select escolhido)
        self.botoes = {}           # nome -> valor dos <input type=submit>
        self.por_id = {}           # id -> valor dos campos ocultos (para os JSON)
        self.textos = {}           # id -> texto, só dos elementos que interessam
        self._select = None
        self._primeira = None
        self._escolhida = None
        self._opcao = None
        self._abertos = []         # ids de span/div sendo lidos
        self.texto = []

    _IDS = re.compile(r"cphContent_dtlAlunos_(lblNomeAluno|lblSituacao)_\d+$")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            nome, tipo = a.get("name"), (a.get("type") or "text").lower()
            valor = a.get("value") or ""
            if a.get("id") and tipo == "hidden":
                self.por_id[a["id"]] = valor
            if not nome:
                return
            if tipo == "submit":
                self.botoes[nome] = valor
            elif tipo in ("hidden", "text", "password", "number", "date"):
                self.campos[nome] = valor
            elif tipo in ("checkbox", "radio") and "checked" in a:
                self.campos[nome] = valor or "on"
        elif tag == "select":
            self._select = a.get("name")
            self._primeira = self._escolhida = None
        elif tag == "option" and self._select is not None:
            valor = a.get("value", "")
            if self._primeira is None:
                self._primeira = valor
            if "selected" in a:
                self._escolhida = valor
        elif tag in ("span", "div") and a.get("id") and self._IDS.search(a["id"]):
            self._abertos.append([a["id"], tag, 0, []])
        elif self._abertos and tag == self._abertos[-1][1]:
            self._abertos[-1][2] += 1

    def handle_endtag(self, tag):
        if tag == "select" and self._select is not None:
            valor = self._escolhida if self._escolhida is not None else self._primeira
            if self._select and valor is not None:
                self.campos[self._select] = valor
            self._select = None
        elif self._abertos and tag == self._abertos[-1][1]:
            if self._abertos[-1][2]:
                self._abertos[-1][2] -= 1
            else:
                ident, _t, _n, partes = self._abertos.pop()
                self.textos[ident] = " ".join("".join(partes).split())

    def handle_data(self, data):
        for aberto in self._abertos:
            aberto[3].append(data)
        self.texto.append(data)


def _ler(html):
    leitor = _LeitorFormulario()
    leitor.feed(html)
    leitor.close()
    return leitor


def _json(valor):
    try:
        dados = json.loads(valor or "[]")
    except ValueError:
        raise ErroGier("site", "lista do Gier ilegível") from None
    return dados if isinstance(dados, list) else []


class PaginaAvaliacao:
    """Avaliacao.aspx já aberta: turmas e semestres do ano letivo atual."""

    def __init__(self, leitor, url):
        self.url = url
        self.campos = leitor.campos
        self.ano = str(leitor.por_id.get("hdfAnoLetivo") or self.campos.get("ctl00$cphContent$hdfAnoLetivo") or "")
        turmas = _json(leitor.por_id.get("hdfFiltroGeral"))
        unidades = _json(leitor.por_id.get("hdfFiltroUnidadeLetiva"))
        if not self.ano and turmas:
            self.ano = str(max(int(t.get("AnoLetivo") or 0) for t in turmas))
        self.turmas = sorted(
            ({"id": str(t.get("IdTurma")), "descricao": str(t.get("CodigoTurma") or "").strip(),
              "ciclo": str(t.get("IdCursosCiclos") or ""), "nome_ciclo": str(t.get("NomeCiclo") or ""),
              "modalidade": str(t.get("IdModalidade") or "")}
             for t in turmas if str(t.get("AnoLetivo")) == self.ano and t.get("IdTurma")),
            key=lambda t: (simples(t["descricao"]).replace(" ", ""), t["id"]))
        vistos, self.semestres = set(), []
        for u in unidades:
            ident = str(u.get("IdUnidadeLetiva") or "")
            descricao = str(u.get("Descricao") or "").strip()
            if (str(u.get("AnoLetivo")) == self.ano and ident and ident not in vistos
                    and "SEMESTRE" in simples(descricao)):
                vistos.add(ident)
                self.semestres.append({"id": ident, "descricao": descricao})
        self.semestres.sort(key=lambda s: int(s["id"]) if s["id"].isdigit() else 0)


def _abrir_pagina(sessao, url, dados=None, cabecalhos=None, etapa="pareceres"):
    def ler(resposta):
        if gier_online._caiu_no_login(resposta):
            raise ErroGier("sessao_expirada")
        return gier_online._ler_pagina(resposta), resposta.geturl()
    return gier_online._chamar_site(lambda: sessao.abrir(url, dados, cabecalhos, etapa=etapa), ler)


def carregar_avaliacao(sessao):
    """Abre Pedagógico / Avaliação e lê as turmas e os semestres."""
    html, url = _abrir_pagina(sessao, gier_online.ORIGEM_GIER + CAMINHO_AVALIACAO, etapa="pareceres.avaliacao")
    leitor = _ler(html)
    if "hdfFiltroGeral" not in leitor.por_id or BOTAO_PESQUISAR not in leitor.botoes:
        raise ErroGier("sem_avaliacao")
    pagina = PaginaAvaliacao(leitor, url)
    registro.info("pareceres.avaliacao", ano=pagina.ano, turmas=len(pagina.turmas), semestres=len(pagina.semestres))
    if not pagina.turmas:
        raise ErroGier("sem_turmas")
    return pagina


class ListaAlunos:
    """AvaliacaoQuestionario.aspx de uma turma e semestre."""

    def __init__(self, leitor, url, turma):
        self.url = url
        self.turma = turma
        self.campos = leitor.campos
        self.alunos = []
        for nome_botao in leitor.botoes:
            m = re.search(r"dtlAlunos\$ctl(\d+)\$btnImprimirQuestionario$", nome_botao)
            if not m:
                continue
            n = int(m.group(1))
            self.alunos.append({
                "ordem": n + 1,
                "nome": leitor.textos.get("cphContent_dtlAlunos_lblNomeAluno_{}".format(n), "").strip(),
                "situacao": leitor.textos.get("cphContent_dtlAlunos_lblSituacao_{}".format(n), "").strip(),
                "botao": nome_botao,
                "valor_botao": leitor.botoes[nome_botao],
            })
        self.alunos.sort(key=lambda a: a["ordem"])


def abrir_turma(sessao, turma, semestre):
    """Faz o "Pesquisar" da tela Avaliação e devolve a lista de alunos da turma.
    Abre a tela Avaliação de novo a cada turma, como o navegador faria."""
    pagina = carregar_avaliacao(sessao)
    atual = next((t for t in pagina.turmas if t["id"] == str(turma["id"])), None)
    if atual is None:
        raise ErroGier("sem_turma", turma["descricao"])
    campos = dict(pagina.campos)
    campos.update({
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
        "ctl00$cphContent$hdfAnoLetivo": pagina.ano,
        "ctl00$cphContent$hdfModalidade": atual["modalidade"],
        "ctl00$cphContent$hdfCiclo": atual["ciclo"],
        "ctl00$cphContent$hdfTurma": atual["id"],
        "ctl00$cphContent$hdfUnidadeLetiva": str(semestre["id"]),
        BOTAO_PESQUISAR: "Pesquisar",
    })
    dados = urllib.parse.urlencode(campos).encode("utf-8")
    html, url = _abrir_pagina(sessao, pagina.url, dados, {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": gier_online.ORIGEM_GIER, "Referer": pagina.url,
    }, etapa="pareceres.pesquisar")
    if CAMINHO_QUESTIONARIO.lower() not in urllib.parse.urlsplit(url).path.lower():
        raise ErroGier("sem_lista", turma["descricao"])
    leitor = _ler(html)
    lista = ListaAlunos(leitor, url, atual)
    # Confere se a página é desta turma (o cabeçalho traz "ANO / SEMESTRE / CICLO / TURMA").
    texto = simples(" ".join(leitor.texto)).replace(" ", "")
    if simples(atual["descricao"]).replace(" ", "") not in texto:
        raise ErroGier("outra_turma")
    registro.info("pareceres.turma", id_turma=atual["id"], semestre=semestre["id"], alunos=len(lista.alunos),
                  sem_lancamentos=sum(1 for a in lista.alunos if sem_lancamentos(a)))
    return lista


def ler_delta(texto):
    """A resposta do postback assíncrono do ASP.NET: blocos 'tamanho|tipo|id|conteúdo|'."""
    blocos, i = [], 0
    while i < len(texto):
        j = texto.find("|", i)
        if j < 0 or not texto[i:j].isdigit():
            raise ErroGier("site", "resposta assíncrona ilegível")
        tamanho = int(texto[i:j])
        k = texto.find("|", j + 1)
        m = texto.find("|", k + 1)
        if k < 0 or m < 0:
            raise ErroGier("site", "resposta assíncrona ilegível")
        conteudo = texto[m + 1:m + 1 + tamanho]
        blocos.append((texto[j + 1:k], texto[k + 1:m], conteudo))
        i = m + 1 + tamanho + 1
    return blocos


def _texto_do_pdf(dados):
    try:
        import pypdfium2 as pdfium
        documento = pdfium.PdfDocument(dados)
        partes = []
        for pagina in documento:
            pagina_texto = pagina.get_textpage()
            partes.append(pagina_texto.get_text_range())
        return " ".join(partes)
    except Exception:
        return ""


def nome_no_pdf(nome, dados):
    """True se o nome do aluno está no PDF (ou se o PDF não tem texto para conferir)."""
    texto = simples(_texto_do_pdf(dados))
    if not texto.strip():
        return True
    palavras = set(re.findall(r"[A-Z0-9]+", texto))
    return all(p in palavras for p in re.findall(r"[A-Z0-9]+", simples(nome)))


def baixar_parecer(sessao, lista, aluno):
    """Clica na impressora do aluno e baixa o PDF. Devolve os bytes do PDF."""
    campos = dict(lista.campos)
    campos.update({
        SCRIPT_MANAGER: "{}|{}".format(PAINEL, aluno["botao"]),
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__ASYNCPOST": "true",
        aluno["botao"]: aluno.get("valor_botao", ""),
    })
    dados = urllib.parse.urlencode(campos).encode("utf-8")
    texto, _url = _abrir_pagina(sessao, lista.url, dados, {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*", "Origin": gier_online.ORIGEM_GIER, "Referer": lista.url,
    }, etapa="pareceres.imprimir")
    blocos = ler_delta(texto)
    abriu = False
    for tipo, ident, conteudo in blocos:
        if tipo == "hiddenField":
            lista.campos[ident] = conteudo      # o __VIEWSTATE novo vale para o próximo aluno
        elif tipo == "pageRedirect" and "login" in conteudo.lower():
            raise ErroGier("sessao_expirada")
        elif tipo == "error":
            raise ErroGier("site", "o Gier recusou o pedido")
        if "relatoriovisualizarimpressao" in conteudo.lower().replace("\\", ""):
            abriu = True
    # No Gier de verdade a resposta é igual à do navegador, mas o endereço do relatório não vem
    # escrito nela de forma reconhecível (13/11/2026). Por isso não é exigido: o que decide é o
    # PDF que vem em seguida, conferido pelo nome do aluno.
    registro.info("pareceres.resposta", blocos=len(blocos), endereco=abriu,
                  tipos=",".join(sorted({tipo for tipo, _i, _c in blocos})))

    def ler_pdf(resposta):
        pdf = resposta.read()
        if pdf[:4] != b"%PDF":
            if gier_online._caiu_no_login(resposta):
                raise ErroGier("sessao_expirada")
            registro.info("pareceres.sem_pdf", tipo=resposta.headers.get_content_type(), bytes=len(pdf),
                          final=urllib.parse.urlsplit(resposta.geturl()).path)
            raise ErroGier("sem_relatorio")
        if b"%%EOF" not in pdf[-2048:]:
            raise ErroGier("pdf_incompleto", "{} bytes".format(len(pdf)))
        return pdf

    origem = gier_online.ORIGEM_GIER
    pdf = gier_online._chamar_site(lambda: sessao.abrir(origem + CAMINHO_PDF, cabecalhos={
        "Referer": origem + CAMINHO_IMPRESSAO}, etapa="pareceres.pdf"), ler_pdf)
    if aluno.get("nome") and not nome_no_pdf(aluno["nome"], pdf):
        raise ErroGier("outro_aluno")
    registro.info("pareceres.pdf", ordem=aluno["ordem"], bytes=len(pdf))
    return pdf


# A rede da escola perde conexões de vez em quando (13/11/2026: 2 de 18 alunos caíram no meio da
# resposta ou ao abrir a conexão). Refazer o aluno é seguro: o clique só gera o relatório de novo.
ESPERAS_NOVA_TENTATIVA = (3, 8)     # segundos antes da 2ª e da 3ª tentativa


def com_tentativas(sessao, funcao, *args, esperar=None, parar=None):
    """Chama funcao(sessao, *args) e, se a conexão cair, tenta de novo (até 3 vezes no total)."""
    import time
    esperar = esperar or time.sleep
    for n, espera in enumerate(ESPERAS_NOVA_TENTATIVA + (None,), 1):
        try:
            return funcao(sessao, *args)
        except ErroGier as erro:
            if erro.codigo != "conexao" or espera is None or (parar and parar()):
                raise
            registro.info("pareceres.nova_tentativa", etapa=getattr(funcao, "__name__", "?"), tentativa=n + 1,
                          detalhe=erro.detalhe[:60])
            esperar(espera)


MENSAGENS = {
    "sem_avaliacao": "A tela Pedagógico / Avaliação do Gier não abriu para esta conta.",
    "sem_turma": "Esta turma não aparece na tela Avaliação do Gier.",
    "sem_lista": "O Gier não abriu a lista de alunos desta turma.",
    "sem_relatorio": "O Gier não gerou o parecer deste aluno.",
    "outro_aluno": "O PDF recebido é de outro aluno.",
}


def texto_do_erro(erro):
    if erro.codigo in MENSAGENS:
        frase = MENSAGENS[erro.codigo]
        return "{} ({})".format(frase, erro.detalhe) if erro.detalhe else frase
    return gier_online.texto_do_erro(erro)
