# -*- coding: utf-8 -*-
"""
Pendências de lançamento do Gier: o relatório "Relação de Pendências de Lançamento de
Aula" da caixa "Imprimir Relatórios" em Pedagógico / Frequência.

No navegador o caminho é:
  1. Pedagógico → Frequência (/Paginas/Pedagogico/Frequencia.aspx). As turmas do ano
     vêm no oculto CabecalhoFiltro$hdfFiltroGeral (IdTurma, CodigoTurma, IdCursosCiclos,
     IdModalidade, IdDisciplina, IdTipoComponenteDisciplina, IdProfessor). Escolher as
     caixas só preenche os ocultos hdfAnoLetivo/Modalidade/Ciclo/Turma/Disciplina/
     TipoComponenteDisciplina/Professor; "Pesquisar" é um postback comum na mesma página.
  2. Na caixa "Imprimir Relatórios" (ctl00$cphContent$ddlImprimir) a opção 524 faz um
     postback assíncrono (UpdatePanel1) cuja resposta chama abreRelatorio(), que abre
     /RelatorioVisualizarImpressao.aspx: o relatório fica guardado na sessão.
  3. GET /RelatorioVisualizar.aspx devolve o PDF da turma.

O relatório é da TURMA: numa turma com duas professoras, as duas dão o mesmo PDF
(conferido em 16/11/2026), então basta pedir uma vez com a primeira.
"""

import re
import urllib.parse
from datetime import date

import gier_online
import registro
from gier_online import ErroGier
from pareceres_gier import (_abrir_pagina, _json, _ler, _texto_do_pdf, com_tentativas, ler_delta,
                            simples)

CAMINHO_FREQUENCIA = "/Paginas/Pedagogico/Frequencia.aspx"
CAMINHO_PDF = "/RelatorioVisualizar.aspx"
CAMINHO_IMPRESSAO = "/RelatorioVisualizarImpressao.aspx"
PREFIXO = "ctl00$cphContent$CabecalhoFiltro$"
BOTAO_PESQUISAR = PREFIXO + "btnPesquisar"
CAIXA_IMPRIMIR = "ctl00$cphContent$ddlImprimir"
SCRIPT_MANAGER = "ctl00$cphHeader$ScriptManager1"
PAINEL = "ctl00$cphContent$UpdatePanel1"
ID_RELATORIO_PADRAO = "524"

__all__ = ["carregar_frequencia", "baixar_pendencias", "com_tentativas", "texto_do_erro"]


class PaginaFrequencia:
    """Frequencia.aspx já aberta: as turmas do ano letivo atual (uma entrada por turma)."""

    def __init__(self, leitor, url):
        self.url = url
        self.campos = leitor.campos
        self.ano = str(self.campos.get(PREFIXO + "hdfAnoLetivo") or "").strip()
        entradas = _json(self.campos.get(PREFIXO + "hdfFiltroGeral"))
        if not self.ano and entradas:
            self.ano = str(max(int(t.get("AnoLetivo") or 0) for t in entradas))
        turmas = {}
        for t in entradas:
            if str(t.get("AnoLetivo")) != self.ano or not t.get("IdTurma"):
                continue
            ident = str(t.get("IdTurma"))
            if ident in turmas:          # outra professora da mesma turma: o relatório é o mesmo
                continue
            turmas[ident] = {
                "id": ident, "descricao": str(t.get("CodigoTurma") or "").strip(),
                "ciclo": str(t.get("IdCursosCiclos") or ""), "modalidade": str(t.get("IdModalidade") or ""),
                "disciplina": str(t.get("IdDisciplina") or ""),
                "tipo_componente": str(t.get("IdTipoComponenteDisciplina") or ""),
                "professor": str(t.get("IdProfessor") or ""),
            }
        self.turmas = sorted(turmas.values(), key=lambda t: (simples(t["descricao"]).replace(" ", ""), t["id"]))


def id_do_relatorio(html):
    """O código da opção "Relação de Pendências..." na caixa Imprimir Relatórios (524 hoje)."""
    for valor, texto in re.findall(r"""<option[^>]*value=["'](\d+)["'][^>]*>([^<]*)</option>""", html or ""):
        if "PENDENCIA" in simples(texto) and "LANCAMENTO" in simples(texto):
            return valor
    return ID_RELATORIO_PADRAO


def carregar_frequencia(sessao):
    """Abre Pedagógico / Frequência e lê as turmas do ano."""
    html, url = _abrir_pagina(sessao, gier_online.ORIGEM_GIER + CAMINHO_FREQUENCIA, etapa="pendencias.frequencia")
    leitor = _ler(html)
    if PREFIXO + "hdfFiltroGeral" not in leitor.campos or BOTAO_PESQUISAR not in leitor.botoes:
        raise ErroGier("sem_frequencia")
    pagina = PaginaFrequencia(leitor, url)
    registro.info("pendencias.frequencia", ano=pagina.ano, turmas=len(pagina.turmas))
    if not pagina.turmas:
        raise ErroGier("sem_turmas")
    return pagina


def turma_no_pdf(descricao, dados):
    """True se o nome da turma está no PDF (ou se o PDF não tem texto para conferir)."""
    texto = simples(_texto_do_pdf(dados)).replace(" ", "")
    if not texto:
        return True
    return simples(descricao).replace(" ", "") in texto


def baixar_pendencias(sessao, turma, hoje=None):
    """Pesquisa a turma na tela Frequência, pede o relatório de pendências e baixa o PDF."""
    pagina = carregar_frequencia(sessao)
    atual = next((t for t in pagina.turmas if t["id"] == str(turma["id"])), None)
    if atual is None:
        raise ErroGier("sem_turma", turma["descricao"])
    campos = dict(pagina.campos)
    campos.update({
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
        PREFIXO + "hdfAnoLetivo": pagina.ano,
        PREFIXO + "hdfModalidade": atual["modalidade"],
        PREFIXO + "hdfCiclo": atual["ciclo"],
        PREFIXO + "hdfTurma": atual["id"],
        PREFIXO + "hdfDisciplina": atual["disciplina"],
        PREFIXO + "hdfTipoComponenteDisciplina": atual["tipo_componente"],
        PREFIXO + "hdfProfessor": atual["professor"],
        PREFIXO + "hdfDataReferencia": (hoje or date.today()).isoformat(),
        BOTAO_PESQUISAR: "Pesquisar",
    })
    html, url = _abrir_pagina(sessao, pagina.url, urllib.parse.urlencode(campos).encode("utf-8"), {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": gier_online.ORIGEM_GIER, "Referer": pagina.url,
    }, etapa="pendencias.pesquisar")
    leitor = _ler(html)
    if CAIXA_IMPRIMIR not in leitor.campos:
        raise ErroGier("sem_lista", atual["descricao"])
    id_relatorio = id_do_relatorio(html)   # a caixa só aparece depois do Pesquisar

    # "Imprimir Relatórios" → Pendências: postback assíncrono, como o navegador faz.
    campos = dict(leitor.campos)
    campos.update({
        SCRIPT_MANAGER: "{}|{}".format(PAINEL, CAIXA_IMPRIMIR),
        "__EVENTTARGET": CAIXA_IMPRIMIR, "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        CAIXA_IMPRIMIR: id_relatorio, "__ASYNCPOST": "true",
    })
    texto, _url = _abrir_pagina(sessao, url, urllib.parse.urlencode(campos).encode("utf-8"), {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*", "Origin": gier_online.ORIGEM_GIER, "Referer": url,
    }, etapa="pendencias.imprimir")
    blocos = ler_delta(texto)
    for tipo, _ident, conteudo in blocos:
        if tipo == "pageRedirect" and "login" in conteudo.lower():
            raise ErroGier("sessao_expirada")
        if tipo == "error":
            raise ErroGier("site", "o Gier recusou o pedido")
    registro.info("pendencias.resposta", blocos=len(blocos),
                  abre=any("abrerelatorio" in c.lower() for _t, _i, c in blocos))

    def ler_pdf(resposta):
        pdf = resposta.read()
        if pdf[:4] != b"%PDF":
            if gier_online._caiu_no_login(resposta):
                raise ErroGier("sessao_expirada")
            registro.info("pendencias.sem_pdf", tipo=resposta.headers.get_content_type(), bytes=len(pdf))
            raise ErroGier("sem_relatorio_pendencias")
        if b"%%EOF" not in pdf[-2048:]:
            raise ErroGier("pdf_incompleto", "{} bytes".format(len(pdf)))
        return pdf

    origem = gier_online.ORIGEM_GIER
    pdf = gier_online._chamar_site(lambda: sessao.abrir(origem + CAMINHO_PDF, cabecalhos={
        "Referer": origem + CAMINHO_IMPRESSAO}, etapa="pendencias.pdf"), ler_pdf)
    if not turma_no_pdf(atual["descricao"], pdf):
        raise ErroGier("outra_turma")
    registro.info("pendencias.pdf", id_turma=atual["id"], bytes=len(pdf))
    return pdf


MENSAGENS = {
    "sem_frequencia": "A tela Pedagógico / Frequência do Gier não abriu para esta conta.",
    "sem_turma": "Esta turma não aparece na tela Frequência do Gier.",
    "sem_lista": "O Gier não abriu a turma na tela Frequência.",
    "sem_relatorio_pendencias": "O Gier não gerou o relatório de pendências desta turma.",
    "outra_turma": "O PDF recebido é de outra turma.",
}


def texto_do_erro(erro):
    if erro.codigo in MENSAGENS:
        frase = MENSAGENS[erro.codigo]
        return "{} ({})".format(frase, erro.detalhe) if erro.detalhe else frase
    return gier_online.texto_do_erro(erro)
