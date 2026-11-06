# -*- coding: utf-8 -*-
"""
Login no sistema Gier (manaus.gier.com.br).

O Gier é um site ASP.NET WebForms, sem API: o login é o mesmo POST de formulário
que o navegador faz. Primeiro baixa a tela de login (que traz os campos ocultos
e o cookie de sessão) e depois envia esses campos junto com o usuário e a senha.

Os relatórios ficam em outro site, sem login próprio. O Gier passa a sessão para
ele: o swap.aspx traz os dados da pessoa numa chamada a ChamarControlador(url,
dados, ...), e o navegador os envia a /Conta/LoginAuto. entrar_relatorio() faz o
mesmo caminho, sem navegador.

Depois disso, carregar_filtros() e baixar_ficha() fazem o mesmo que a página do
relatório: consultam as opções em cascata (PesquisarOpcoes) e pedem o PDF
(/relatorio/imprimir).

A senha só passa pela memória durante a chamada: nada é gravado em disco. A
sessão também vive só na memória e termina quando o programa fecha. Os dados da
passagem têm informações pessoais: não os grave nem os mostre em mensagens, e
só os envie para ORIGEM_RELATORIO.

Usa só a biblioteca padrão (urllib), para empacotar leve.
"""

import base64
import calendar
import http.client
import http.cookiejar
import itertools
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from datetime import date
from html.parser import HTMLParser

import registro


URL_LOGIN = "https://manaus.gier.com.br/Login.aspx"
TEMPO_LIMITE = 30  # segundos
# Abrir a conexão é rápido (no download real, a mais lenta levou 0,156 s) ou não acontece:
# as que falharam ficaram 19,5 s sem nenhuma resposta. Ver _abrir_com_tentativas.
TEMPO_ABRIR_CONEXAO = 5  # segundos, em cada tentativa
TENTATIVAS_ABRIR_CONEXAO = 3
COOKIE_AUTENTICACAO = ".ASPXAUTH"  # o servidor só cria depois do login aceito

ORIGEM_GIER = "https://manaus.gier.com.br"
ORIGEM_RELATORIO = "https://app-manaus-mvc-prd-frontend-001.azurewebsites.net"
# Só nos testes: GIER_BASE aponta tudo para o Gier de mentira (testes/gier_falso.py).
if os.environ.get("GIER_BASE"):
    ORIGEM_GIER = ORIGEM_RELATORIO = os.environ["GIER_BASE"].rstrip("/")
    URL_LOGIN = ORIGEM_GIER + "/Login.aspx"
URL_SWAP = ORIGEM_GIER + "/swap.aspx?areaGrupoId=3&inovacao=2&IdNavegacaoRota=350"
CAMINHO_RELATORIO = "/Relatorio/RelatorioFiltro/348"
COOKIE_RELATORIO = ".AspNetCore.Cookies"
ID_RELATORIO = "348"

# Padrões dos filtros: é a ficha diária que o programa sabe cruzar com a lista de alunos.
TIPO_PADRAO = "FREQUENCIA DIARIA"
COMPONENTE_PADRAO = "EDUCACAO INFANTIL"


class ErroGier(Exception):
    """Falha na conversa com o site de relatórios. `codigo` serve a mensagem_do_erro."""

    def __init__(self, codigo, detalhe=""):
        super().__init__(codigo)
        self.codigo = codigo
        self.detalhe = detalhe          # para a mensagem; nunca com dados de alunos

# Alguns sites ASP.NET mudam a página conforme o navegador informado.
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DeclaracoesEscolares"


class _LeitorDoLogin(HTMLParser):
    """Separa da tela de login os campos ocultos e a mensagem de erro."""

    def __init__(self):
        super().__init__()
        self.ocultos = {}
        self.campos = set()
        self.erro = ""
        self._dentro_do_erro = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.campos.add(attrs["name"])
            if attrs.get("type") == "hidden":
                self.ocultos[attrs["name"]] = attrs.get("value") or ""
        elif tag == "span" and attrs.get("id") == "lblErro":
            self._dentro_do_erro = True

    def handle_endtag(self, tag):
        if tag == "span":
            self._dentro_do_erro = False

    def handle_data(self, data):
        if self._dentro_do_erro:
            self.erro += data


class _LeitorDosFiltros(HTMLParser):
    """Separa da página do relatório os filtros (campos com data-parametro), as
    opções já escritas nela (meses, por exemplo) e os demais campos ocultos."""

    def __init__(self):
        super().__init__()
        self.valores = {}               # parâmetro -> valor, na ordem da página
        self.ocultos = {}               # id do campo -> valor
        self.fixas = {}                 # parâmetro -> [{"id", "descricao"}]
        self._atual = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("id"):
            self.ocultos[attrs["id"]] = attrs.get("value") or ""
        if tag == "input" and attrs.get("data-parametro"):
            self._atual = attrs["data-parametro"]
            self.valores[self._atual] = attrs.get("value") or ""
            self.fixas.setdefault(self._atual, [])
        elif self._atual and "data-valor" in attrs and attrs.get("data-descricao"):
            itens = self.fixas[self._atual]
            if not any(i["id"] == attrs["data-valor"] for i in itens):
                itens.append({"id": attrs["data-valor"],
                              "descricao": attrs["data-descricao"].strip()})


def _ler_pagina(resposta):
    charset = resposta.headers.get_content_charset() or "utf-8"
    return resposta.read().decode(charset, "replace")


def _analisar(html):
    leitor = _LeitorDoLogin()
    leitor.feed(html)
    return leitor


ESCAPES_JS = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "0": "\0",
              "v": "\v"}


def _ler_texto_js(texto, i):
    """Le o texto JavaScript entre aspas que comeca em `i`. Devolve (valor, fim)."""
    aspas = texto[i]
    partes = []
    i += 1
    while i < len(texto):
        c = texto[i]
        if c == aspas:
            return "".join(partes), i + 1
        if c != "\\":
            partes.append(c)
            i += 1
            continue
        seguinte = texto[i + 1:i + 2]
        if seguinte == "u":
            partes.append(chr(int(texto[i + 2:i + 6], 16)))
            i += 6
        elif seguinte == "x":
            partes.append(chr(int(texto[i + 2:i + 4], 16)))
            i += 4
        else:
            partes.append(ESCAPES_JS.get(seguinte, seguinte))
            i += 2
    raise ValueError("texto sem fim")


def _ler_objeto_js(texto, i):
    """Le um objeto {...} escrito direto na chamada. Devolve (texto do objeto, fim)."""
    profundidade = 0
    inicio = i
    while i < len(texto):
        c = texto[i]
        if c in "\"'`":
            _, i = _ler_texto_js(texto, i)
            continue
        if c == "{":
            profundidade += 1
        elif c == "}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio:i + 1], i + 1
        i += 1
    raise ValueError("objeto sem fim")


def _pular_para_argumento(texto, i):
    while i < len(texto) and texto[i] in " \t\r\n,":
        i += 1
    return i


def ler_passagem(html):
    """Acha no swap.aspx a chamada ChamarControlador(url, dados, ...) com dados de
    verdade. Devolve (url, dados em texto JSON) ou (None, None)."""
    marca = "ChamarControlador("
    posicao = html.find(marca)
    while posicao >= 0:
        i = _pular_para_argumento(html, posicao + len(marca))
        try:
            if html[i:i + 1] in ("'", '"', "`"):
                url, i = _ler_texto_js(html, i)
                i = _pular_para_argumento(html, i)
                if html[i:i + 1] in ("'", '"', "`"):
                    dados, _ = _ler_texto_js(html, i)
                elif html[i:i + 1] == "{":
                    dados, _ = _ler_objeto_js(html, i)
                else:
                    dados = ""
                if isinstance(json.loads(dados), dict):
                    return url, dados
        except ValueError:
            pass                        # nao era a chamada com os dados
        posicao = html.find(marca, posicao + len(marca))
    return None, None


# -- medição de cada pedido, para o registro técnico ------------------------------------

_pedidos = itertools.count(1)
_medicao_atual = threading.local()      # cada thread mede o próprio pedido
NOMES_DAS_FASES = {
    "dns": "procurando o endereço do site",
    "tcp": "abrindo a conexão",
    "tls": "abrindo a conexão segura",
    "envio": "enviando o pedido",
    "espera": "esperando a resposta",
    "leitura": "recebendo a resposta",
}


class _Medicao:
    """Quanto tempo um pedido passou em cada fase e por qual endereço ele foi."""

    def __init__(self, etapa):
        self.etapa = etapa
        self.fase = "preparo"
        self.rede = {}
        self._tempos = []
        self._marca = time.monotonic()

    def entrar(self, fase):
        agora = time.monotonic()
        self._tempos.append((self.fase, agora - self._marca))
        self.fase, self._marca = fase, agora

    def fases(self):
        tempos = self._tempos + [(self.fase, time.monotonic() - self._marca)]
        partes = ["{}={:.3f}".format(fase, segundos) for fase, segundos in tempos]
        partes.append("total={:.3f}".format(sum(segundos for _, segundos in tempos)))
        return " ".join(partes)


def _fase(nome):
    medicao = getattr(_medicao_atual, "atual", None)
    if medicao:
        medicao.entrar(nome)


def _abrir_com_tentativas(endereco, tempo, origem):
    """Abre a conexão, tentando de novo se ela não abrir. É a única repetição automática do
    programa e é segura: nesta fase nada foi enviado ao site, então nenhum pedido se repete."""
    medicao = getattr(_medicao_atual, "atual", None)
    etapa = medicao.etapa if medicao else "-"
    inicio = time.monotonic()
    for tentativa in range(1, TENTATIVAS_ABRIR_CONEXAO + 1):
        try:
            conexao = socket.create_connection(endereco, min(tempo, TEMPO_ABRIR_CONEXAO), origem)
            break
        except OSError as erro:
            registro.aviso("conexao.nao_abriu", etapa=etapa,
                           tentativa="{}/{}".format(tentativa, TENTATIVAS_ABRIR_CONEXAO),
                           segundos="{:.3f}".format(time.monotonic() - inicio),
                           erro=registro.descrever(erro))
            if tentativa == TENTATIVAS_ABRIR_CONEXAO:
                raise
    conexao.settimeout(tempo)           # daqui em diante vale o limite normal
    if tentativa > 1:
        registro.info("conexao.voltou", etapa=etapa, tentativa=tentativa,
                      segundos="{:.3f}".format(time.monotonic() - inicio))
    return conexao


class _ConexaoMedida:
    """Marca as fases da conexão. Só mede: quem abre e confere o certificado é o Python."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = self._abrir_socket

    def _abrir_socket(self, endereco, tempo, origem=None):
        socket.getaddrinfo(endereco[0], endereco[1], type=socket.SOCK_STREAM)
        _fase("tcp")
        conexao = _abrir_com_tentativas(endereco, tempo, origem)
        medicao = getattr(_medicao_atual, "atual", None)
        if medicao:
            medicao.rede["servidor"] = "{}:{}".format(*conexao.getpeername()[:2])
            medicao.rede["porta_local"] = conexao.getsockname()[1]
        _fase("tls")
        return conexao

    def connect(self):
        _fase("dns")
        super().connect()
        medicao = getattr(_medicao_atual, "atual", None)
        if medicao and hasattr(self.sock, "version"):
            medicao.rede["tls"] = self.sock.version()
        _fase("envio")

    def getresponse(self):
        _fase("espera")
        resposta = super().getresponse()
        _fase("leitura")
        return resposta


class _HttpsMedido(_ConexaoMedida, http.client.HTTPSConnection):
    pass


class _HttpMedido(_ConexaoMedida, http.client.HTTPConnection):
    pass


class _ManipuladorHttps(urllib.request.HTTPSHandler):

    def __init__(self):
        self._contexto = ssl.create_default_context()
        self._contexto.set_alpn_protocols(["http/1.1"])
        super().__init__(context=self._contexto)

    def https_open(self, pedido):
        return self.do_open(_HttpsMedido, pedido, context=self._contexto)


class _ManipuladorHttp(urllib.request.HTTPHandler):

    def http_open(self, pedido):
        return self.do_open(_HttpMedido, pedido)


def _rastros(cabecalhos):
    """Cabeçalhos que ajudam a achar o pedido no servidor. Cookies nunca entram aqui."""
    campos = {}
    for nome in ("Retry-After", "x-ms-request-id", "x-azure-ref"):
        valor = cabecalhos.get(nome) if cabecalhos else None
        if valor:
            campos[nome.lower().replace("-", "_")] = valor
    return campos


def _registrar_falha(rotulo, medicao, erro):
    campos = {"fase": medicao.fase, "fases": medicao.fases(), **medicao.rede}
    if isinstance(erro, urllib.error.HTTPError):
        campos.update(status=erro.code, **_rastros(erro.headers))
    registro.falha("http " + rotulo, erro, **campos)


class _RespostaMedida:
    """A resposta do site, que registra o pedido quando a leitura termina."""

    def __init__(self, resposta, rotulo, medicao):
        self._resposta = resposta
        self._rotulo = rotulo
        self._medicao = medicao

    @property
    def headers(self):
        return self._resposta.headers

    def geturl(self):
        return self._resposta.geturl()

    def read(self):
        try:
            dados = self._resposta.read()
        except Exception as erro:
            _registrar_falha(self._rotulo, self._medicao, erro)
            raise
        registro.info("http " + self._rotulo, status=self._resposta.status,
                      tipo=self.headers.get_content_type(), bytes=len(dados),
                      final=urllib.parse.urlsplit(self.geturl()).path,
                      fases=self._medicao.fases(), **self._medicao.rede,
                      **_rastros(self.headers))
        return dados

    def __enter__(self):
        return self

    def __exit__(self, *_erro):
        self._resposta.close()


def _detalhe_de_conexao(erro):
    """Em qual pedido e em qual fase a conexão falhou, mais o tipo do erro."""
    if isinstance(erro, urllib.error.URLError) and isinstance(erro.reason, BaseException):
        erro = erro.reason
    medicao = getattr(_medicao_atual, "atual", None)
    if not medicao:
        return type(erro).__name__
    return "{}: {}, {}".format(medicao.etapa, NOMES_DAS_FASES.get(medicao.fase, medicao.fase),
                               type(erro).__name__)


class SessaoGier:
    """Uma conexão com o Gier. Depois de entrar(), `abrir` já vai autenticado."""

    def __init__(self, url_login=URL_LOGIN):
        self.url_login = url_login
        self.usuario = ""
        self.pagina_inicial = ""
        self._cookies = http.cookiejar.CookieJar()
        self._abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies),
            _ManipuladorHttps(), _ManipuladorHttp())

    @property
    def conectado(self):
        return any(c.name == COOKIE_AUTENTICACAO for c in self._cookies)

    def abrir(self, url, dados=None, cabecalhos=None, etapa="site"):
        """Faz o pedido e o registra. No registro entram o endereço sem os parâmetros, os
        tempos e o código da resposta: nunca o corpo do pedido, o da resposta ou cookies."""
        partes = urllib.parse.urlsplit(url)
        rotulo = "#{} {} {} {}{}".format(next(_pedidos), etapa, "POST" if dados else "GET",
                                         partes.netloc, partes.path)
        medicao = _medicao_atual.atual = _Medicao(etapa)
        pedido = urllib.request.Request(url, data=dados, headers={
            "User-Agent": NAVEGADOR, **(cabecalhos or {})})
        try:
            resposta = self._abridor.open(pedido, timeout=TEMPO_LIMITE)
        except Exception as erro:
            _registrar_falha(rotulo, medicao, erro)
            raise
        return _RespostaMedida(resposta, rotulo, medicao)

    def entrar(self, usuario, senha):
        """Faz o login. Devolve {"ok": True} ou {"ok": False, "erro": ...}, com
        "erro" em: "senha" (o Gier recusou; a frase dele vem em "mensagem"),
        "conexao" ou "formulario" (a tela de login mudou)."""
        resposta = self._entrar(usuario, senha)
        registro.info("gier.login", ok=bool(resposta.get("ok")), erro=resposta.get("erro", "-"))
        return resposta

    def _entrar(self, usuario, senha):
        self.sair()
        try:
            with self.abrir(self.url_login, etapa="login.pagina") as resposta:
                tela = _analisar(_ler_pagina(resposta))
            if not {"txtLogin", "txtSenha1", "btnAcessar"} <= tela.campos:
                return {"ok": False, "erro": "formulario"}

            campos = dict(tela.ocultos)
            campos.update(txtLogin=usuario, txtSenha1=senha, btnAcessar="Acessar")
            dados = urllib.parse.urlencode(campos).encode("utf-8")
            with self.abrir(self.url_login, dados, {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.url_login,
            }, etapa="login.enviar") as resposta:
                html = _ler_pagina(resposta)
                destino = resposta.geturl()
        except urllib.error.URLError as erro:
            return {"ok": False, "erro": "conexao", "detalhe": str(erro.reason)}
        except (ValueError, OSError, http.client.HTTPException) as erro:
            registro.falha("gier.login", erro)
            return {"ok": False, "erro": "conexao", "detalhe": str(erro)}

        if not self.conectado:
            return {"ok": False, "erro": "senha",
                    "mensagem": _analisar(html).erro.strip()}
        self.usuario = usuario
        self.pagina_inicial = destino
        return {"ok": True}

    @property
    def conectado_relatorio(self):
        return any(c.name == COOKIE_RELATORIO for c in self._cookies)

    def entrar_relatorio(self):
        """Passa a sessão do Gier para o site do relatório e confirma abrindo-o.
        Devolve {"ok": True, "url": ...} ou {"ok": False, "erro": ...}, com "erro" em:
        "sem_login", "sessao_expirada", "sem_dados" (o swap.aspx não trouxe a chamada),
        "destino" (a chamada aponta para outro site), "recusado" (o site não aceitou),
        "nao_abriu" (voltou para o login) ou "conexao"."""
        resposta = self._entrar_relatorio()
        registro.info("gier.passagem", ok=bool(resposta.get("ok")), erro=resposta.get("erro", "-"))
        return resposta

    def _entrar_relatorio(self):
        if not self.conectado:
            return {"ok": False, "erro": "sem_login"}
        origem = ORIGEM_RELATORIO.rstrip("/")
        try:
            with self.abrir(URL_SWAP, etapa="passagem.swap") as resposta:
                html = _ler_pagina(resposta)
                if "login.aspx" in resposta.geturl().lower():
                    return {"ok": False, "erro": "sessao_expirada"}

            controlador, dados = ler_passagem(html)
            if not dados:
                return {"ok": False, "erro": "sem_dados"}
            # Os dados sao pessoais: so podem ir para o site oficial do relatorio.
            if not (controlador + "/").lower().startswith(origem.lower() + "/"):
                return {"ok": False, "erro": "destino"}

            codigo = base64.b64encode(ORIGEM_GIER.encode("utf-8")).decode("ascii")
            separador = "&" if "?" in controlador else "?"
            pagina = "{}{}origem={}".format(controlador, separador,
                                            urllib.parse.quote(codigo, safe=""))
            with self.abrir(pagina, cabecalhos={"Referer": ORIGEM_GIER + "/"},
                            etapa="passagem.pagina") as resposta:
                resposta.read()

            with self.abrir(origem + "/Conta/LoginAuto", dados.encode("utf-8"), {
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Origin": origem,
                "Referer": pagina,
            }, etapa="passagem.enviar") as resposta:
                resultado = json.loads(_ler_pagina(resposta) or "{}")
            if not resultado.get("success") or not self.conectado_relatorio:
                return {"ok": False, "erro": "recusado"}

            with self.abrir(origem + CAMINHO_RELATORIO, cabecalhos={"Referer": pagina},
                            etapa="passagem.confirmar") as resposta:
                resposta.read()
                destino = resposta.geturl()
        except urllib.error.URLError as erro:
            return {"ok": False, "erro": "conexao", "detalhe": str(erro.reason)}
        except (ValueError, OSError, http.client.HTTPException) as erro:
            registro.falha("gier.passagem", erro)
            return {"ok": False, "erro": "conexao", "detalhe": type(erro).__name__}

        caminho = urllib.parse.urlsplit(destino).path.lower()
        if not caminho.startswith(CAMINHO_RELATORIO.lower()):
            return {"ok": False, "erro": "nao_abriu"}
        return {"ok": True, "url": destino}

    def enviar_json(self, caminho, dados, etapa="site"):
        """POST JSON ao site de relatórios, como a página faz. Devolve a resposta aberta."""
        origem = ORIGEM_RELATORIO.rstrip("/")
        return self.abrir(origem + caminho, json.dumps(dados).encode("utf-8"), {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": origem,
            "Referer": origem + CAMINHO_RELATORIO,
        }, etapa=etapa)

    def sair(self):
        """Esquece a sessão neste programa. O Gier a encerra quando ela expira."""
        self._cookies.clear()
        self.usuario = ""
        self.pagina_inicial = ""


class FiltrosRelatorio:
    """Estado dos filtros do relatório, como a página os mantém nos campos ocultos."""

    def __init__(self, sessao, leitor):
        self.sessao = sessao
        self._valores = dict(leitor.valores)
        self._ocultos = dict(leitor.ocultos)
        self._fixas = leitor.fixas

    def valor(self, parametro):
        return self._valores.get(parametro, "")

    def definir(self, parametro, valor):
        self._valores[parametro] = str(valor)

    def opcoes_fixas(self, parametro):
        return list(self._fixas.get(parametro, []))

    def opcoes(self, elemento):
        """Pergunta ao site as opções de um filtro: [{"id":..., "descricao":...}]."""
        filtros = []
        for parametro, valor in self._valores.items():
            for parte in str(valor).split(","):
                filtros.append({"Parametro": parametro, "Valor": parte})
        return _chamar_site(lambda: self.sessao.enviar_json(
            "/Relatorio/RelatorioFiltro/PesquisarOpcoes",
            {"Elemento": elemento, "Filtros": filtros}, etapa="opcoes." + elemento),
            _resposta_em_lista)

    def parametros_impressao(self, meses, hoje=None):
        """Os parâmetros que a página envia ao imprimir este relatório."""
        hoje = hoje or date.today()
        ano = self.valor("AnoLetivo")
        maior = max(int(m) for m in meses)
        if maior == -1 or (hoje.month == maior and str(hoje.year) == str(ano)):
            referencia = hoje.isoformat()
        else:
            ultimo = calendar.monthrange(int(ano), maior)[1]
            referencia = "{}-{:02d}-{:02d}".format(ano, maior, ultimo)
        return [
            {"Descricao": "AnoLetivo", "Valor": ano},
            {"Descricao": "IdTurma", "Valor": self.valor("IdTurma")},
            {"Descricao": "IdDisciplina", "Valor": self.valor("IdDisciplina")},
            {"Descricao": "Mes", "Valor": ", ".join(meses)},
            {"Descricao": "CompensacaoFalta", "Valor": self.valor("CompensacaoFalta")},
            {"Descricao": "DataReferencia", "Valor": referencia},
            {"Descricao": "IdEstrutura", "Valor": self._ocultos.get("hdfIdEstrutura", "")},
            {"Descricao": "IdUsuario", "Valor": self._ocultos.get("hdfIPessoa", "")},
            {"Descricao": "nomeusuario", "Valor": self._ocultos.get("hdfNomeUsuario", "")},
            {"Descricao": "urlorigem", "Valor": ORIGEM_RELATORIO.rstrip("/").lower() + " "},
        ]


def _chamar_site(abrir, tratar):
    """Abre, lê e traduz qualquer falha em ErroGier (sem dados da pessoa na mensagem)."""
    try:
        with abrir() as resposta:
            return tratar(resposta)
    except urllib.error.HTTPError as erro:
        if erro.code in (401, 403):
            raise ErroGier("sessao_expirada") from None
        raise ErroGier("site", "código {}".format(erro.code)) from None
    except urllib.error.URLError as erro:
        raise ErroGier("conexao", _detalhe_de_conexao(erro)) from None
    except (OSError, http.client.HTTPException) as erro:
        raise ErroGier("conexao", _detalhe_de_conexao(erro)) from None


def _caiu_no_login(resposta):
    return "/login" in urllib.parse.urlsplit(resposta.geturl()).path.lower()


def _resposta_em_lista(resposta):
    if _caiu_no_login(resposta):
        raise ErroGier("sessao_expirada")
    try:
        dados = json.loads(_ler_pagina(resposta) or "[]")
    except ValueError:
        raise ErroGier("site") from None
    if not isinstance(dados, list):
        raise ErroGier("site")
    return dados


def carregar_filtros(sessao):
    """Abre a página do relatório e lê os filtros dela."""
    origem = ORIGEM_RELATORIO.rstrip("/")

    def ler(resposta):
        if _caiu_no_login(resposta):
            raise ErroGier("sessao_expirada")
        leitor = _LeitorDosFiltros()
        leitor.feed(_ler_pagina(resposta))
        if "IdTurma" not in leitor.valores or "mes" not in leitor.valores:
            raise ErroGier("filtros")
        return FiltrosRelatorio(sessao, leitor)

    return _chamar_site(lambda: sessao.abrir(origem + CAMINHO_RELATORIO, etapa="filtros.pagina"),
                        ler)


def baixar_ficha(filtros, turma, tipo, componente, meses):
    """Baixa o PDF de uma turma e confere se ele chegou inteiro. Quem chama decide o que
    fazer com a falha. `tipo` e `componente` são os itens escolhidos na tela. Em cada turma, são procurados
    pelo nome, porque os códigos e as listas podem mudar; sem escolha (a primeira turma da
    lista não tinha opções), vale o padrão. `meses`: códigos ("8", "9") ou ["-1"] para todos."""
    # A página limpa os dependentes ao trocar de turma; o servidor considera os
    # valores que recebe, então os da turma anterior não podem ir junto.
    filtros.definir("IdTurma", turma["id"])
    filtros.definir("IdTipoComponente", "")
    filtros.definir("IdDisciplina", "")
    tipos = filtros.opcoes("TIPO DE FREQUENCIA")
    filtros.definir("IdTipoComponente", _id_pelo_nome(tipos, tipo, TIPO_PADRAO))
    componentes = filtros.opcoes("Componente Curricular")
    filtros.definir("IdDisciplina", _id_pelo_nome(componentes, componente, COMPONENTE_PADRAO))
    registro.info("ficha.filtros", turma=turma["descricao"], id_turma=turma["id"],
                  tipos=len(tipos), componentes=len(componentes),
                  id_tipo=filtros.valor("IdTipoComponente"),
                  id_disciplina=filtros.valor("IdDisciplina"))

    def checar_fila(resposta):
        if _caiu_no_login(resposta):
            raise ErroGier("sessao_expirada")
        try:
            return json.loads(_ler_pagina(resposta) or "{}").get("processaJob")
        except ValueError:
            raise ErroGier("site") from None

    sessao = filtros.sessao
    origem = ORIGEM_RELATORIO.rstrip("/")
    if _chamar_site(lambda: sessao.abrir(
            "{}/relatorio/verificar-processamento?idRelatorio={}".format(origem, ID_RELATORIO),
            etapa="fila"), checar_fila):
        raise ErroGier("fila")

    def ler_pdf(resposta):
        dados = resposta.read()
        if dados[:4] != b"%PDF":
            if _caiu_no_login(resposta):
                raise ErroGier("sessao_expirada")
            tipo_resposta = resposta.headers.get_content_type()
            raise ErroGier("nao_pdf", "veio {}, {} bytes".format(tipo_resposta, len(dados)))
        if b"%%EOF" not in dados[-2048:]:
            raise ErroGier("pdf_incompleto", "{} bytes".format(len(dados)))
        return dados

    # Só os parâmetros sem dados da pessoa: a impressão também leva o nome e o código dela.
    parametros = filtros.parametros_impressao(meses)
    valores = {p["Descricao"]: p["Valor"] for p in parametros}
    registro.info("ficha.pedido", turma=turma["descricao"], mes=valores["Mes"],
                  ano=valores["AnoLetivo"], referencia=valores["DataReferencia"],
                  compensacao=valores["CompensacaoFalta"])
    return _chamar_site(lambda: sessao.enviar_json("/relatorio/imprimir", {
        "id": ID_RELATORIO,
        "nome": "Relatório GIER",
        "parametros": parametros,
        "tipo": "0",
    }, etapa="imprimir"), ler_pdf)


def _simples(texto):
    """Sem acento, sem diferença de maiúsculas e de espaços, para comparar nomes do site."""
    texto = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


def id_padrao(itens, texto):
    """O item com o texto padrão, ou o primeiro da lista ("" se a lista for vazia)."""
    for item in itens:
        if _simples(item["descricao"]) == texto:
            return str(item["id"])
    return str(itens[0]["id"]) if itens else ""


def _id_pelo_nome(itens, escolhido, padrao):
    """O código do item com o mesmo nome; sem ele, esta turma não tem essa opção."""
    if not escolhido and itens:
        return id_padrao(itens, padrao)
    if escolhido:
        for item in itens:
            if _simples(item["descricao"]) == _simples(escolhido["descricao"]):
                return str(item["id"])
    procurado = "precisa de “{}”; ".format(escolhido["descricao"]) if escolhido else ""
    opcoes = ", ".join(str(i["descricao"]) for i in itens[:6]) or "nenhuma"
    raise ErroGier("sem_componente", "{}opções desta turma: {}".format(procurado, opcoes))


def texto_do_erro(excecao):
    """Frase para a pessoa, com o motivo técnico entre parênteses quando houver."""
    frase = mensagem_do_erro({"erro": excecao.codigo}).replace("\n", " ")
    return "{} ({})".format(frase, excecao.detalhe) if excecao.detalhe else frase


def mensagem_do_erro(resposta):
    """Traduz a resposta de entrar() numa frase para o usuário."""
    erro = resposta.get("erro")
    if erro == "senha":
        return resposta.get("mensagem") or "O Gier não aceitou o usuário e a senha."
    if erro == "formulario":
        return ("A tela de login do Gier mudou e o programa não a reconheceu.\n"
                "Avise o responsável pelo programa.")
    if erro == "conexao":
        return ("Não foi possível falar com o Gier.\n"
                "Verifique sua conexão com a internet e tente de novo.")
    if erro == "sessao_expirada":
        return "A sessão do Gier expirou. Feche esta janela e entre no Gier de novo."
    if erro in ("filtros", "site", "nao_pdf"):
        return ("O site do Gier respondeu de um jeito inesperado.\n"
                "Tente de novo; se continuar, avise o responsável pelo programa.")
    if erro == "outra_turma":
        return "O PDF recebido é de outra turma."
    if erro == "outro_mes":
        return "O PDF recebido traz um mês que não foi pedido."
    if erro == "sem_alunos":
        return "O PDF veio sem nenhum aluno que o programa consiga ler."
    if erro == "gravar":
        return "Não foi possível gravar o arquivo na pasta escolhida."
    if erro == "pdf_incompleto":
        return "O PDF chegou cortado."
    if erro == "pdf_invalido":
        return "O PDF chegou, mas não abre."
    if erro == "fila":
        return ("O Gier colocou este relatório na fila de processamento.\n"
                "Gere pelo site e abra o PDF na Configuração.")
    if erro == "sem_turmas":
        return "O Gier não mostrou nenhuma turma para esta escola."
    if erro == "sem_componente":
        return "Esta turma não tem o tipo de frequência ou o componente escolhido."
    if erro in ("sem_dados", "destino", "recusado", "nao_abriu"):
        return ("O Gier não liberou o acesso ao relatório para esta conta.\n"
                "Confira no site se o relatório abre com o seu perfil.")
    return "Não foi possível concluir. Tente novamente."
