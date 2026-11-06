# -*- coding: utf-8 -*-
"""
Busca a frequência no Gier por dentro do programa, sem abrir navegador.

A conversa com o site fica em gier_online.py; aqui está a regra do programa: um PDF por
turma, com todos os meses, sempre no componente da frequência diária.

O Gier lista o componente como "EDUCAÇÃO INFANTIL", e o PDF sai com "AULA DIA" no
cabeçalho. "EDUCAÇÃO FÍSICA" vem primeiro na lista, mas volta sem dias letivos: é sempre
ignorada (pedido do Jansey). Um PDF só é aceito se alguma criança tiver dias letivos.
"""

import os
import time

import gier_online
from gier_online import ErroGier


TENTATIVAS = 3                  # o Gier às vezes responde 502 e dá certo logo depois
PAUSA_ENTRE_TENTATIVAS = 3      # segundos
ERROS_PASSAGEIROS = ("conexao", "site", "nao_pdf", "pdf_incompleto")


class Cancelado(Exception):
    pass


def _sem_acento(texto):
    return gier_online._simples(texto)


def _com_tentativas(funcao, rotulo, registrar):
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return funcao()
        except ErroGier as erro:
            if erro.codigo not in ERROS_PASSAGEIROS or tentativa == TENTATIVAS:
                raise
            registrar("{}: {} (tentativa {})".format(rotulo, gier_online.texto_do_erro(erro), tentativa))
            time.sleep(PAUSA_ENTRE_TENTATIVAS)


def listar_turmas(filtros, registrar):
    """Todas as turmas da escola: [{"id", "descricao", "etapa"}]."""
    for parametro in ("IdModalidade", "IdTurma", "IdTipoComponente", "IdDisciplina"):
        filtros.definir(parametro, "")
    etapas = _com_tentativas(lambda: filtros.opcoes("Etapa/Modalidade"), "lista de etapas", registrar)
    turmas = []
    for etapa in etapas:
        filtros.definir("IdModalidade", etapa["id"])
        filtros.definir("IdTurma", "")
        lista = _com_tentativas(lambda: filtros.opcoes("Turma"), "lista de turmas", registrar)
        turmas.extend({"id": t["id"], "descricao": t["descricao"], "etapa": etapa["id"]} for t in lista)
    return turmas


def componentes_da_turma(filtros, turma):
    """Componentes da turma, sem Educação Física, com a frequência diária primeiro."""
    filtros.definir("IdModalidade", turma["etapa"])
    filtros.definir("IdTurma", turma["id"])
    filtros.definir("IdTipoComponente", "")
    filtros.definir("IdDisciplina", "")
    vistos, lista = set(), []
    for tipo in filtros.opcoes("TIPO DE FREQUENCIA"):
        filtros.definir("IdTipoComponente", tipo["id"])
        for item in filtros.opcoes("Componente Curricular"):
            if item["id"] in vistos or "EDUCACAO FISICA" in _sem_acento(item["descricao"]):
                continue
            vistos.add(item["id"])
            lista.append(item)

    def nota(item):
        nome = _sem_acento(item["descricao"])
        return 0 if "AULA DIA" in nome else 1 if "EDUCACAO INFANTIL" in nome else 2
    return sorted(lista, key=nota)


def _so_letras(texto):
    return "".join(c for c in _sem_acento(texto) if c.isalnum())


def _conferir_pdf(caminho, turma, nomes_meses):
    """Lê o PDF recebido. Sem aluno, de outra turma ou com mês não pedido é erro.
    Devolve True se alguma criança tem dias letivos."""
    import frequencia_gier as fg
    alunos, _info = fg.extrair_dados_pdf(caminho)
    if not alunos:
        raise ErroGier("sem_alunos")
    for aluno in alunos:
        veio = aluno.get("turma") or ""
        if _so_letras(veio) != _so_letras(turma["descricao"]):
            raise ErroGier("outra_turma", "veio {}".format(veio))
        if nomes_meses and _sem_acento(aluno.get("mes") or "") not in nomes_meses:
            raise ErroGier("outro_mes", "veio {}".format(aluno.get("mes")))
    return any(a.get("dias_letivos") for a in alunos)


def baixar_pdf_da_turma(filtros, turma, meses, caminho, registrar, nomes_meses=None):
    """
    Grava em `caminho` o PDF da turma nos meses pedidos (["-1"] = todos).
    Devolve (motivo, sem_dias): motivo "" se deu certo; sem_dias True se o PDF é válido,
    mas nenhum dos meses teve aula, como janeiro. `nomes_meses`: para conferir o que veio.
    """
    rotulo = turma["descricao"]
    pedidos = {_sem_acento(n) for n in nomes_meses} if nomes_meses else None
    componentes = _com_tentativas(lambda: componentes_da_turma(filtros, turma),
                                  rotulo + " | lista de componentes", registrar)
    if not componentes:
        return "o Gier não mostrou o componente curricular", False
    motivo = "o Gier não trouxe a frequência desta turma"
    parcial, reserva = caminho + ".parcial", None
    try:
        for componente in componentes:
            try:
                dados = _com_tentativas(
                    lambda: gier_online.baixar_ficha(filtros, turma, None, componente, meses),
                    "{} | {}".format(rotulo, componente["descricao"]), registrar)
                with open(parcial, "wb") as arquivo:
                    arquivo.write(dados)
                com_dias = _conferir_pdf(parcial, turma, pedidos)
            except ErroGier as erro:
                if erro.codigo in ("sessao_expirada", "fila"):
                    raise
                motivo = gier_online.texto_do_erro(erro)
                continue
            except OSError as erro:
                raise ErroGier("gravar", type(erro).__name__) from None
            if com_dias:
                os.replace(parcial, caminho)
                registrar("{} | componente: {}".format(rotulo, componente["descricao"]))
                return "", False
            registrar("{} | {}: veio sem dias letivos".format(rotulo, componente["descricao"]))
            reserva = reserva or dados
        if reserva is not None:                 # mês sem aula: o PDF existe, só não tem dias
            with open(caminho, "wb") as arquivo:
                arquivo.write(reserva)
            return "", True
        return motivo, False
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)


def _baixar_turma(filtros, turma, caminho, registrar):
    """Para a frequência das declarações: um PDF sem nenhum dia letivo não serve."""
    motivo, sem_dias = baixar_pdf_da_turma(filtros, turma, ["-1"], caminho, registrar)
    if sem_dias:
        os.remove(caminho)
        return "o Gier não trouxe dias letivos para esta turma"
    return motivo


def preparar_relatorio(sessao, registrar):
    """Abre o site do relatório com a sessão conectada e devolve os filtros."""
    resposta = sessao.entrar_relatorio()
    if not resposta.get("ok"):
        raise ErroGier(resposta.get("erro") or "site", resposta.get("detalhe") or "")
    filtros = _com_tentativas(lambda: gier_online.carregar_filtros(sessao), "página do relatório", registrar)
    filtros.definir("CompensacaoFalta", "1")
    return filtros


def buscar_frequencia(sessao, pasta_pdfs, avisar, cancelado, registrar=None):
    """
    Com a sessão já conectada, baixa um PDF por turma. Devolve (caminhos, problemas).
    avisar(texto) mostra o andamento; cancelado() -> True para parar.
    Sessão vencida ou acesso recusado saem como ErroGier.
    """
    registrar = registrar or (lambda texto: None)
    avisar("Abrindo o relatório de frequência...")
    filtros = preparar_relatorio(sessao, registrar)

    avisar("Procurando as turmas...")
    turmas = listar_turmas(filtros, registrar)
    if not turmas:
        raise ErroGier("sem_turmas")

    os.makedirs(pasta_pdfs, exist_ok=True)
    caminhos, problemas = [], []
    for n, turma in enumerate(turmas, 1):
        if cancelado():
            raise Cancelado("Cancelado.")
        avisar("Baixando a frequência: turma {} de {} ({})".format(n, len(turmas), turma["descricao"]))
        nome = "".join(c if c.isalnum() else "_" for c in turma["descricao"]).strip("_") or "turma"
        caminho = os.path.join(pasta_pdfs, "{:02d}_{}.pdf".format(n, nome))
        try:
            motivo = _baixar_turma(filtros, turma, caminho, registrar)
        except ErroGier as erro:
            if erro.codigo == "sessao_expirada":
                raise
            motivo = gier_online.texto_do_erro(erro)
        if motivo:
            problemas.append("{}: {}".format(turma["descricao"], motivo))
        else:
            caminhos.append(caminho)
    return caminhos, problemas
