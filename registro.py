# -*- coding: utf-8 -*-
"""
Registro técnico do programa: um arquivo por dia, para descobrir onde um erro aconteceu.

Fica em %APPDATA%\\Declaracoes Escolares\\logs e guarda etapas, tempos, códigos e endereços do
site. Nunca pode guardar senha, cookies, dados da pessoa conectada, nomes de alunos ou
conteúdo de relatórios. Por isso as exceções entram pelo tipo e pela posição no código,
não pela mensagem, que pode trazer dados.

O registro nunca atrapalha o programa: se ele falhar, o programa segue sem registrar.
"""

import faulthandler
import logging
import os
import platform
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request


PASTA_DADOS = "Declaracoes Escolares"       # a mesma pasta dos dados salvos pelo programa
DIAS_GUARDADOS = 30

ARQUIVO = None                          # caminho do registro de hoje, depois de iniciar()

_logger = logging.getLogger("declaracoes_escolares")
_logger.addHandler(logging.NullHandler())
_logger.setLevel(logging.INFO)
_logger.propagate = False
_arquivo_quedas = None                  # precisa ficar aberto até o programa terminar


def _texto(valor):
    texto = " ".join(str(valor).split())
    return '"{}"'.format(texto) if " " in texto or not texto else texto


def _linha(etapa, campos):
    partes = ["{}={}".format(nome, _texto(valor)) for nome, valor in campos.items()]
    return "{} | {}".format(etapa, " ".join(partes)) if partes else etapa


def descrever(erro):
    """Tipo e códigos do erro, sem a mensagem."""
    if isinstance(erro, urllib.error.HTTPError):
        return "HTTP {}".format(erro.code)
    if isinstance(erro, urllib.error.URLError) and isinstance(erro.reason, BaseException):
        erro = erro.reason
    partes = [type(erro).__name__]
    for nome in ("errno", "winerror"):
        valor = getattr(erro, nome, None)
        if valor is not None:
            partes.append("{}={}".format(nome, valor))
    if isinstance(erro, ssl.SSLError) and erro.reason:
        partes.append("motivo={}".format(erro.reason))
    return " ".join(partes)


def posicao(erro):
    """Onde o erro aconteceu, do ponto mais fundo para o mais externo."""
    quadros = traceback.extract_tb(erro.__traceback__)[-6:]
    return " < ".join("{}:{} {}".format(os.path.basename(q.filename), q.lineno, q.name)
                      for q in reversed(quadros))


def info(etapa, /, **campos):
    try:
        _logger.info(_linha(etapa, campos))
    except Exception:
        pass


def aviso(etapa, /, **campos):
    try:
        _logger.warning(_linha(etapa, campos))
    except Exception:
        pass


def falha(etapa, erro=None, /, **campos):
    try:
        if erro is not None:
            campos = {"erro": descrever(erro), **campos, "onde": posicao(erro)}
        _logger.error(_linha(etapa, campos))
    except Exception:
        pass


def _apagar_antigos(pasta):
    limite = time.time() - DIAS_GUARDADOS * 86400
    for nome in os.listdir(pasta):
        caminho = os.path.join(pasta, nome)
        if nome.startswith("registro-") and nome.endswith(".log") \
                and os.path.getmtime(caminho) < limite:
            os.remove(caminho)


def _instalar_ganchos():
    """Erros que antes sumiam: no programa sem console, ninguém veria o stderr."""
    excepthook_original = sys.excepthook

    def erro_geral(tipo, valor, rastro):
        falha("erro.nao_tratado", valor)
        excepthook_original(tipo, valor, rastro)
    sys.excepthook = erro_geral

    def erro_em_thread(args):
        if args.exc_value is not None:
            falha("erro.thread", args.exc_value)
    threading.excepthook = erro_em_thread

    import tkinter
    tk_original = tkinter.Tk.report_callback_exception

    def erro_na_janela(self, tipo, valor, rastro):
        falha("erro.janela", valor)
        if sys.stderr:
            tk_original(self, tipo, valor, rastro)
    tkinter.Tk.report_callback_exception = erro_na_janela


def iniciar(versao):
    """Abre o registro de hoje. Chamar uma vez, no começo do programa."""
    global ARQUIVO, _arquivo_quedas
    if ARQUIVO:
        return
    try:
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        pasta = os.path.join(base, PASTA_DADOS, "logs")
        os.makedirs(pasta, exist_ok=True)
        try:
            _apagar_antigos(pasta)
        except OSError:
            pass
        arquivo = os.path.join(pasta, "registro-{}.log".format(time.strftime("%Y-%m-%d")))
        manipulador = logging.FileHandler(arquivo, encoding="utf-8")
        manipulador.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(threadName)s | %(message)s",
            "%Y-%m-%d %H:%M:%S"))
        _logger.addHandler(manipulador)
        logging.raiseExceptions = False
        ARQUIVO = arquivo

        # Queda do próprio Python ou do Tcl: fica só o rastro das funções, sem dados.
        _arquivo_quedas = open(arquivo, "a", encoding="utf-8")
        faulthandler.enable(_arquivo_quedas)
        _instalar_ganchos()
    except Exception:
        return
    proxies = urllib.request.getproxies()       # só se existe: o endereço pode ter senha
    info("programa.inicio", versao=versao, windows=platform.version(),
         python=platform.python_version(), empacotado=bool(getattr(sys, "frozen", False)),
         proxy="sim" if proxies else "nao")
