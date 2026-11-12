# -*- coding: utf-8 -*-
"""
Acesso ao programa: entrar com e-mail e senha e saber o que cada pessoa pode ver.

As contas ficam numa planilha do Google com um Apps Script (PONTE_ACESSOS_DECLARACOES.gs.txt).
Este módulo só conversa com ela por HTTP (JSON) e guarda, neste computador, uma cópia do último
acesso para o programa abrir mesmo se a internet cair por alguns dias. Só biblioteca padrão.

PERFIS (uma pessoa pode ter mais de um):
    declaracoes  aba Declarações
    estoque      abas Estoque pedagógico e Estoque de limpeza
    admin        cadastra as pessoas (Usuários) e mexe na Configuração; quem é admin vê tudo
"""
import errno
import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import date

# Endereço do aplicativo da Web da ponte (implantação de 12/11/2026 (hoje "Versão 2"), na conta da SEMED, planilha
# "Acessos - Declarações Escolares"). Vazio = o programa abre sem pedir senha, como antes.
# NÃO use "Nova implantação" para atualizar o script: o endereço mudaria (ver LEIA-ME-ACESSOS.txt).
URL_ACESSOS = "https://script.google.com/macros/s/AKfycbzJFqOTE680FliRyvyENrfpQVy0QLK0Y9eA_RAgipBHd24v9ZXSi6nr4go0R2f3sq9tMw/exec"

TEMPO_LIMITE = 20            # segundos esperando o servidor
# Na rede da SEMED, de 35% a 50% das tentativas de abrir conexão com o Google se perdem (medido em 12/11/2026) e o
# Windows fica 21 s esperando antes de desistir (erro 10060); a tentativa seguinte quase sempre abre em menos de 1 s.
# Por isso a abertura da conexão (e só ela) é repetida, com tentativas CURTAS primeiro e mais longas depois (para não
# prejudicar uma rede lenta de verdade). Ver _abrir_com_tentativas. É segura: nessa fase nada foi enviado ao
# servidor, então nenhum pedido se repete.
TEMPOS_ABRIR_CONEXAO = (1.5, 1.5, 2, 3, 3, 5)      # segundos, em cada tentativa (no pior caso, 16 s)
DIAS_SEM_INTERNET = 7        # quantos dias o último acesso vale se não houver internet
SENHA_MINIMA = 8
ITERACOES = 200_000

# Regras para ESCOLHER uma senha: as mesmas do servidor (PONTE_ACESSOS_DECLARACOES.gs.txt). O servidor é quem
# decide; aqui só se avisa a pessoa na hora. Contas antigas com senha mais curta continuam entrando.
SENHAS_COMUNS = frozenset((
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000",
    "12341234", "11223344", "12121212", "password", "password1", "password123", "senha123",
    "senha1234", "senha12345", "senha@123", "mudar123", "mudar@123", "qwertyui", "qwerty123",
    "qwertyuiop", "asdfghjk", "abcd1234", "abc12345", "abc123456", "admin123", "admin1234",
    "admin@123", "semed123", "semed@123", "semed2025", "semed2026", "semed2027", "escola123",
    "escola2026", "manaus123", "manaus2026", "amazonas", "brasil123", "brasil2026", "iloveyou",
    "letmein1", "welcome1", "teste123", "teste1234", "usuario1", "usuario123", "estoque123",
    "declaracao", "declaracoes", "secretaria", "diretora123", "professor1", "professora1"))
TEXTO_SENHA_FRACA = ("Essa senha é fácil de adivinhar (por exemplo 12345678, uma sequência, letras repetidas ou parte do "
                     "seu e-mail). Escolha outra, com pelo menos {} letras ou números, que só você conheça.")

PERFIS = (("declaracoes", "Declarações"), ("estoque", "Estoque"), ("admin", "Administrador"))
NOME_DO_PERFIL = dict(PERFIS)


def configurado():
    return bool(str(URL_ACESSOS or "").strip())


# ---------------------------------------------------------------------------
# O que a pessoa pode ver
# ---------------------------------------------------------------------------

class Sessao:
    """Quem entrou e o que pode usar. Fica só na memória (a senha nunca vai para o disco)."""

    def __init__(self, email="", nome="", perfis=(), validade="", senha="", sem_internet=False, sem_login=False,
                 por_copia=False):
        self.email, self.nome = email, nome
        self.perfis = tuple(p for p, _ in PERFIS if p in set(perfis))
        self.validade, self.senha = validade, senha
        self.sem_internet = sem_internet      # sem internet: entrou pela cópia guardada neste computador
        self.sem_login = sem_login            # o programa está sem login configurado: acesso total
        self.por_copia = por_copia            # entrou NA HORA pela cópia guardada; o servidor ainda vai confirmar

    @classmethod
    def completa(cls):
        return cls(perfis=[p for p, _ in PERFIS], sem_login=True)

    @property
    def admin(self):
        return "admin" in self.perfis

    def pode(self, recurso):
        """recurso: 'declaracoes', 'pedagogico', 'limpeza', 'configuracao' ou 'usuarios'."""
        if self.admin:
            return True
        if recurso == "declaracoes":
            return "declaracoes" in self.perfis
        if recurso in ("pedagogico", "limpeza"):
            return "estoque" in self.perfis
        return False                          # configuração e usuários: só administrador

    def abas(self):
        """Chaves das abas que a pessoa vê, na ordem do programa."""
        return [k for k in ("declaracoes", "pedagogico", "limpeza") if self.pode(k)]

    def texto_perfis(self):
        return ", ".join(NOME_DO_PERFIL[p] for p in self.perfis)


# ---------------------------------------------------------------------------
# Conversa com o servidor
# ---------------------------------------------------------------------------

def _foi_tempo_esgotado(erro):
    """O erro da rede da SEMED: o pacote de abertura se perdeu e ninguém respondeu (10060 / tempo esgotado).
    Só este vale repetir. Sem internet, sem DNS ou servidor recusando o erro é outro e a repetição só atrasaria."""
    return (isinstance(erro, (TimeoutError, socket.timeout))
            or getattr(erro, "winerror", None) == 10060
            or getattr(erro, "errno", None) in (10060, errno.ETIMEDOUT))


def _abrir_com_tentativas(endereco, tempo=None, origem=None):
    """Abre a conexão com o servidor, tentando de novo (até 6 vezes) se o tempo esgotar."""
    tempo = tempo if isinstance(tempo, (int, float)) else TEMPO_LIMITE
    for tentativa, espera in enumerate(TEMPOS_ABRIR_CONEXAO, 1):
        try:
            conexao = socket.create_connection(endereco, min(tempo, espera), origem)
            break
        except OSError as erro:
            if tentativa == len(TEMPOS_ABRIR_CONEXAO) or not _foi_tempo_esgotado(erro):
                raise
    conexao.settimeout(tempo)            # daqui em diante vale o limite normal de espera pela resposta
    return conexao


class _ConexaoHTTP(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _abrir_com_tentativas


class _ConexaoHTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _abrir_com_tentativas


class _AbridorHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_ConexaoHTTP, req)


class _AbridorHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_ConexaoHTTPS, req, context=self._context)


_ABRIDOR = urllib.request.build_opener(_AbridorHTTP, _AbridorHTTPS)      # segue o redirecionamento do Google como antes


def _chamar(payload, timeout=TEMPO_LIMITE):
    """POST JSON. Devolve o dict da resposta ou {"ok": False, "erro": "conexao", "detalhe": ...}."""
    if not configurado():
        return {"ok": False, "erro": "sem_url"}
    try:
        req = urllib.request.Request(
            URL_ACESSOS.strip(), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with _ABRIDOR.open(req, timeout=timeout) as resposta:
            corpo = resposta.read().decode("utf-8")
        dados = json.loads(corpo)
        if not isinstance(dados, dict):
            return {"ok": False, "erro": "conexao", "detalhe": "resposta inesperada"}
        return dados
    except urllib.error.URLError as erro:
        return {"ok": False, "erro": "conexao", "detalhe": str(erro.reason)}
    except Exception as erro:          # tempo esgotado, resposta que não é JSON...
        return {"ok": False, "erro": "conexao", "detalhe": str(erro)}


def _sem_conexao(resp):
    return resp.get("erro") in ("conexao", "ocupado", "falha")


def senha_fraca(senha, email=""):
    """True se a senha é fácil de adivinhar (mesmas regras do servidor)."""
    s = str(senha or "").lower()
    if len(set(s)) < 4:                                       # 11111111, abababab...
        return True
    passos = {ord(b) - ord(a) for a, b in zip(s, s[1:])}
    if passos == {1} or passos == {-1}:                       # 12345678, abcdefgh, 87654321
        return True
    if s in SENHAS_COMUNS:
        return True
    local = str(email or "").lower().split("@")[0]
    return len(local) >= 4 and (local in s or s in local)    # o próprio e-mail


def problema_na_senha(senha, email=""):
    """None se a senha serve para ser ESCOLHIDA; senão, o texto para mostrar à pessoa."""
    if len(senha or "") < SENHA_MINIMA:
        return "A senha precisa ter pelo menos {} caracteres.".format(SENHA_MINIMA)
    if senha_fraca(senha, email):
        return TEXTO_SENHA_FRACA.format(SENHA_MINIMA)
    return None


def mensagem(resp):
    """Texto em português para uma resposta de erro do servidor."""
    motivo = resp.get("motivo") or resp.get("erro") or ""
    if motivo == "nao_cadastrado":
        return "Este e-mail ainda não tem cadastro. Use “Criar minha conta”."
    if motivo == "senha":
        sobra = resp.get("restantes")
        return "Senha incorreta." + (" Restam {} tentativa(s) antes de travar por {} minutos.".format(sobra, 15) if sobra is not None and sobra <= 2 else "")
    if motivo == "muitas_tentativas":
        return "Muitas senhas erradas. Esta conta ficou travada por {} minuto(s). Tente de novo depois.".format(resp.get("minutos", 15))
    if motivo == "pendente":
        return "Seu cadastro ainda não foi liberado. Peça ao administrador para liberar o seu acesso."
    if motivo == "bloqueado":
        return "Seu acesso está bloqueado. Fale com o administrador."
    if motivo == "expirado":
        return "O prazo do seu acesso terminou. Fale com o administrador."
    if motivo == "aguarde":
        return "Uma senha provisória já foi enviada há pouco. Espere {} minutos para pedir outra.".format(resp.get("minutos", 10))
    if motivo == "ja_cadastrado":
        return "Este e-mail já tem cadastro."
    if motivo == "sem_permissao":
        return "Só o administrador pode fazer isso."
    if motivo == "senha_curta":
        return "A senha precisa ter pelo menos {} caracteres.".format(SENHA_MINIMA)
    if motivo == "senha_fraca":
        return TEXTO_SENHA_FRACA.format(SENHA_MINIMA)
    if motivo == "muitos_pendentes":
        return "Há muitos cadastros esperando liberação neste momento. Fale com o administrador do programa."
    if motivo == "email_invalido":
        return "O e-mail não parece certo."
    if motivo == "sem_nome":
        return "Digite o nome."
    if motivo == "voce_mesmo":
        return "Você não pode tirar o seu próprio acesso de administrador, nem remover a sua conta."
    if motivo == "nao_encontrado":
        return "Essa conta não foi encontrada."
    if motivo in ("conexao", "ocupado", "falha", "sem_url"):
        return "Não consegui falar com o servidor de acessos. Confira a internet e tente de novo."
    return "Não foi possível concluir ({}).".format(motivo or "erro desconhecido")


# ---------------------------------------------------------------------------
# Cópia local (para abrir sem internet)
# ---------------------------------------------------------------------------

def _arquivo_local():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    pasta = os.path.join(base, "Declaracoes Escolares")
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, "acesso_local.json")


def _ler_local():
    try:
        with open(_arquivo_local(), encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_local(dados):
    caminho = _arquivo_local()
    try:
        with open(caminho + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        os.replace(caminho + ".tmp", caminho)
    except OSError:
        pass


def _hash_local(senha, sal, iteracoes=ITERACOES):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes).hex()


def _guardar_local(email, senha, nome, perfis, validade):
    dados = _ler_local()
    sal = secrets.token_bytes(16)
    dados.setdefault("usuarios", {})[email] = {
        "nome": nome, "perfis": list(perfis), "validade": validade, "sal": sal.hex(),
        "hash": _hash_local(senha, sal), "iteracoes": ITERACOES, "ok_em": time.time()}
    _gravar_local(dados)


def ultimo_email():
    """O último e-mail que entrou neste computador (a tela de entrada já vem com ele)."""
    return str(_ler_local().get("ultimo_email", ""))


def guardar_ultimo_email(email):
    dados = _ler_local()
    dados["ultimo_email"] = _limpa_email(email)
    _gravar_local(dados)


def _esquecer_local(email):
    dados = _ler_local()
    if dados.get("usuarios", {}).pop(email, None) is not None:
        _gravar_local(dados)


def _entrar_sem_internet(email, senha):
    """Entra com a cópia do último acesso neste computador (vale poucos dias). Devolve Sessao ou None."""
    u = _ler_local().get("usuarios", {}).get(email)
    if not u:
        return None
    try:
        sal = bytes.fromhex(u["sal"])
        confere = hmac.compare_digest(_hash_local(senha, sal, int(u.get("iteracoes", ITERACOES))), u["hash"])
    except (KeyError, ValueError, TypeError):
        return None
    if not confere:
        return None
    if time.time() - float(u.get("ok_em", 0)) > DIAS_SEM_INTERNET * 86400:
        return None
    if u.get("validade") and date.today().isoformat() > u["validade"]:
        return None
    return Sessao(email, u.get("nome", ""), u.get("perfis", []), u.get("validade", ""), senha, sem_internet=True)


# ---------------------------------------------------------------------------
# Ações de quem usa o programa
# ---------------------------------------------------------------------------

def _limpa_email(email):
    return str(email or "").strip().lower()


def entrar(email, senha):
    """Devolve (Sessao, None) se entrou, ou (None, texto) com o que explicar para a pessoa."""
    email = _limpa_email(email)
    if not email or not senha:
        return None, "Digite o e-mail e a senha."
    resp = _chamar({"acao": "entrar", "email": email, "senha": senha})
    if resp.get("ok"):
        perfis = resp.get("perfis") or []
        _guardar_local(email, senha, resp.get("nome", ""), perfis, resp.get("validade", ""))
        return Sessao(email, resp.get("nome", ""), perfis, resp.get("validade", ""), senha), None
    if _sem_conexao(resp):
        sessao = _entrar_sem_internet(email, senha)
        if sessao:
            return sessao, None
        return None, mensagem(resp) + ("" if _ler_local().get("usuarios", {}).get(email)
                                       else " (Sem internet, só entra quem já entrou neste computador nos últimos {} dias.)".format(DIAS_SEM_INTERNET))
    if resp.get("motivo") in ("nao_cadastrado", "bloqueado", "expirado", "pendente"):
        _esquecer_local(email)           # o acesso foi cancelado: a cópia daqui não vale mais
    return None, mensagem(resp)


def entrar_rapido(email, senha):
    """Entra NA HORA com a cópia guardada neste computador, sem esperar o servidor (que na rede da SEMED às vezes
    leva muitos segundos). Só vale se houver cópia, a senha conferir e a cópia tiver menos de 7 dias; senão faz o
    login normal, com o servidor. Quem entra pela cópia deve ser confirmado depois, em segundo plano
    (conferir_acesso), e o programa volta para a tela de entrada se o acesso mudou ou foi cancelado."""
    email = _limpa_email(email)
    if not email or not senha:
        return None, "Digite o e-mail e a senha."
    sessao = _entrar_sem_internet(email, senha)
    if sessao:
        sessao.sem_internet, sessao.por_copia = False, True
        return sessao, None
    return entrar(email, senha)


def conferir_acesso(sessao):
    """Confirma com o servidor o acesso de quem entrou pela cópia guardada. Devolve (estado, texto, sessao_nova):
        "ok"           tudo igual (a cópia é renovada por mais 7 dias)
        "mudou"        o administrador mudou os perfis ou o prazo (a cópia já foi atualizada)
        "cortado"      bloqueado, prazo vencido, conta removida ou senha trocada em outro lugar (a cópia é apagada)
        "sem_resposta" não deu para falar com o servidor agora (nada muda; tenta-se de novo mais tarde)"""
    email = sessao.email
    resp = _chamar({"acao": "entrar", "email": email, "senha": sessao.senha})
    if resp.get("ok"):
        perfis = resp.get("perfis") or []
        nome, validade = resp.get("nome", ""), resp.get("validade", "")
        _guardar_local(email, sessao.senha, nome, perfis, validade)
        nova = Sessao(email, nome, perfis, validade, sessao.senha)
        mudou = nova.perfis != sessao.perfis or (nova.validade or "") != (sessao.validade or "")
        return ("mudou" if mudou else "ok"), "", nova
    if _sem_conexao(resp):
        return "sem_resposta", "", None
    motivo = resp.get("motivo") or resp.get("erro")
    if motivo == "senha":                      # a senha foi trocada em outro computador ou pelo administrador
        _esquecer_local(email)
        return "cortado", "A senha desta conta foi alterada. Entre de novo com a senha nova.", None
    if motivo in ("nao_cadastrado", "bloqueado", "expirado", "pendente"):
        _esquecer_local(email)                 # o acesso foi cancelado: a cópia daqui não vale mais
        return "cortado", mensagem(resp), None
    return "sem_resposta", "", None            # conta travada por tentativas, servidor ocupado etc.: tenta depois


class ConferenciaAcesso:
    """conferir_acesso em segundo plano (a janela não trava). Quem chamou olha .pronta, .estado, .texto e .nova."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.pronta = False
        self.estado, self.texto, self.nova = "sem_resposta", "", None
        threading.Thread(target=self._rodar, daemon=True).start()

    def _rodar(self):
        try:
            self.estado, self.texto, self.nova = conferir_acesso(self.sessao)
        except Exception:
            self.estado, self.texto, self.nova = "sem_resposta", "", None
        finally:
            self.pronta = True


def cadastrar(nome, email, senha):
    """Devolve (True, texto) ou (False, texto)."""
    nome, email = str(nome or "").strip(), _limpa_email(email)
    if not nome:
        return False, "Digite o seu nome."
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, "O e-mail não parece certo."
    problema = problema_na_senha(senha, email)
    if problema:
        return False, problema
    resp = _chamar({"acao": "cadastrar", "nome": nome, "email": email, "senha": senha})
    if resp.get("ok"):
        return True, "Cadastro enviado. Agora é só esperar o administrador liberar o seu acesso."
    if resp.get("erro") == "ja_cadastrado":
        return False, "Este e-mail já tem cadastro" + (" e está aguardando liberação." if resp.get("status") == "pendente" else ".")
    return False, mensagem(resp)


def recuperar(email):
    resp = _chamar({"acao": "recuperar", "email": _limpa_email(email)})
    if resp.get("ok"):
        return True, "Mandei uma senha provisória para o seu e-mail. Entre com ela e depois use “Alterar minha senha”."
    return False, mensagem(resp)


def alterar_senha(email, senha, nova):
    problema = problema_na_senha(nova, email)
    if problema:
        return False, problema
    resp = _chamar({"acao": "alterar_senha", "email": _limpa_email(email), "senha": senha, "nova_senha": nova})
    if resp.get("ok"):
        _esquecer_local(_limpa_email(email))          # a cópia local tinha a senha antiga
        return True, "Senha alterada. Entre com a senha nova."
    return False, mensagem(resp)


# ---------------------------------------------------------------------------
# Ações do administrador (mandam o e-mail e a senha de quem está logado)
# ---------------------------------------------------------------------------

def _admin(sessao, acao, **campos):
    if sessao is None or not sessao.admin or sessao.sem_login:
        return {"ok": False, "erro": "sem_permissao"}
    if sessao.sem_internet:
        return {"ok": False, "erro": "conexao"}
    corpo = {"acao": acao, "email": sessao.email, "senha": sessao.senha}
    corpo.update(campos)
    return _chamar(corpo)


def listar(sessao):
    """Devolve (lista, None) ou (None, texto)."""
    resp = _admin(sessao, "listar")
    if resp.get("ok"):
        return resp.get("lista", []), None
    return None, mensagem(resp)


def atualizar(sessao, alvo, perfis=None, status=None, validade=None):
    """Muda perfis, situação (pendente/autorizado/bloqueado) e/ou prazo (yyyy-mm-dd, '' = sem prazo)."""
    campos = {"alvo": alvo}
    if perfis is not None:
        campos["perfis"] = list(perfis)
    if status is not None:
        campos["status"] = status
    if validade is not None:
        campos["validade"] = validade
    resp = _admin(sessao, "atualizar", **campos)
    return (True, resp) if resp.get("ok") else (False, mensagem(resp))


def definir_senha(sessao, alvo, nova):
    problema = problema_na_senha(nova, alvo)
    if problema:
        return False, problema
    resp = _admin(sessao, "definir_senha", alvo=alvo, nova_senha=nova)
    return (True, "Senha definida.") if resp.get("ok") else (False, mensagem(resp))


def remover(sessao, alvo):
    resp = _admin(sessao, "remover", alvo=alvo)
    return (True, "Conta removida.") if resp.get("ok") else (False, mensagem(resp))
