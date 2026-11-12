# -*- coding: utf-8 -*-
"""
Testa o login: o código REAL da ponte (PONTE_ACESSOS_DECLARACOES.gs.txt) roda no Node, com serviços do
Google de mentira (testes/ponte_de_mentira.js), e o programa fala com ela por HTTP. Nomes inventados.

    python testes/teste_acesso.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))
import acesso  # noqa: E402

NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Ponte:
    """Liga a ponte de mentira e aponta o programa para ela (e para uma pasta de dados vazia)."""

    def __init__(self, isolar=True):
        self.isolar = isolar          # True: pasta de dados vazia e temporária (testes); False: a que já estiver em uso

    def __enter__(self):
        self.porta = porta_livre()
        self.proc = subprocess.Popen([NODE, os.path.join(AQUI, "ponte_de_mentira.js"), str(self.porta)],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     creationflags=0x08000000 if os.name == "nt" else 0)     # sem janela preta
        for _ in range(100):
            linha = self.proc.stdout.readline()
            if "pronto" in linha:
                break
            if not linha and self.proc.poll() is not None:
                raise RuntimeError("a ponte de mentira não ligou")
        self.pasta = tempfile.mkdtemp() if self.isolar else None
        self._appdata = os.environ.get("APPDATA")
        if self.isolar:
            os.environ["APPDATA"] = self.pasta
        self._url_anterior = acesso.URL_ACESSOS
        acesso.URL_ACESSOS = "http://127.0.0.1:{}".format(self.porta)
        return self

    def __exit__(self, *a):
        self.proc.kill()
        self.proc.wait()
        acesso.URL_ACESSOS = self._url_anterior
        if self.isolar:
            if self._appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = self._appdata
            shutil.rmtree(self.pasta, ignore_errors=True)

    def pegar(self, rota):
        with urllib.request.urlopen("http://127.0.0.1:{}/{}".format(self.porta, rota), timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def avancar(self, minutos):
        self.pegar("_avancar?minutos={}".format(minutos))

    def emails(self):
        return self.pegar("_emails")

    def senha_provisoria_de(self, email):
        """Lê a senha provisória do último e-mail mandado para `email` (como a pessoa leria na caixa dela)."""
        for e in reversed(self.emails()):
            if e["para"] == email and "senha provisória" in e["assunto"]:
                return [l.strip() for l in e["corpo"].splitlines() if re.fullmatch(r"[A-Z2-9]{8}", l.strip())][0]
        raise AssertionError("nenhum e-mail de senha para " + email)


ADMIN = "admin@exemplo.com"


def entrar_admin(p):
    s, erro = acesso.entrar(ADMIN, p.senha_provisoria_de(ADMIN))
    assert s is not None, erro
    return s


def liberar(admin, email, perfis, validade=""):
    ok, resp = acesso.atualizar(admin, email, perfis=perfis, status="autorizado", validade=validade)
    assert ok, resp


def teste_primeiro_administrador():
    with Ponte() as p:
        # a ponte mandou a senha provisória para o e-mail do administrador, e ela não está escrita na planilha
        prov = p.senha_provisoria_de(ADMIN)
        assert len(prov) == 8
        assert prov not in json.dumps(p.pegar("_planilha"))
        s, erro = acesso.entrar(ADMIN, prov)
        assert s and s.admin and s.perfis == ("declaracoes", "estoque", "admin"), erro
        assert s.abas() == ["declaracoes", "pedagogico", "limpeza"] and s.pode("configuracao") and s.pode("usuarios")
        assert s.nome == "Administrador" and not s.sem_internet and s.senha == prov
        s2, erro = acesso.entrar(ADMIN.upper(), prov)                 # maiúsculas no e-mail
        assert s2 is not None
        s3, erro = acesso.entrar(ADMIN, "senha errada")
        assert s3 is None and "incorreta" in erro


def teste_cadastro_e_liberacao():
    with Ponte() as p:
        admin = entrar_admin(p)
        # validações antes de falar com o servidor
        assert not acesso.cadastrar("", "ana@exemplo.com", "123456")[0]
        assert not acesso.cadastrar("Ana Exemplo", "ana-sem-arroba", "123456")[0]
        assert "pelo menos 8" in acesso.cadastrar("Ana Exemplo", "ana@exemplo.com", "123")[1]
        assert "pelo menos 8" in acesso.cadastrar("Ana Exemplo", "ana@exemplo.com", "segredo")[1]      # 7 letras
        ok, texto = acesso.cadastrar("Ana Exemplo", "Ana@Exemplo.com", "segredo1")
        assert ok and "administrador" in texto
        ok, texto = acesso.cadastrar("Ana Exemplo", "ana@exemplo.com", "segredo1")
        assert not ok and "aguardando" in texto                            # já cadastrada, pendente
        assert any(e["para"] == ADMIN and "novo cadastro" in e["assunto"] for e in p.emails())   # avisou o administrador
        assert "segredo1" not in json.dumps(p.pegar("_planilha"))          # a senha não fica escrita na planilha
        # pendente não entra
        s, erro = acesso.entrar("ana@exemplo.com", "segredo1")
        assert s is None and "ainda não foi liberado" in erro
        # aparece na lista do administrador, pendente e sem perfis
        lista, erro = acesso.listar(admin)
        ana = [u for u in lista if u["email"] == "ana@exemplo.com"][0]
        assert ana["status"] == "pendente" and ana["perfis"] == [] and ana["nome"] == "Ana Exemplo"
        # libera só com Declarações
        liberar(admin, "ana@exemplo.com", ["declaracoes"])
        assert any(e["para"] == "ana@exemplo.com" and "acesso liberado" in e["assunto"] for e in p.emails())
        s, erro = acesso.entrar("ana@exemplo.com", "segredo1")
        assert s and s.perfis == ("declaracoes",) and not s.admin, erro
        assert s.abas() == ["declaracoes"] and s.pode("declaracoes")
        assert not s.pode("pedagogico") and not s.pode("limpeza") and not s.pode("configuracao") and not s.pode("usuarios")
        assert s.texto_perfis() == "Declarações"


def teste_perfis_combinados():
    with Ponte() as p:
        admin = entrar_admin(p)
        for email in ("so.estoque@exemplo.com", "decl.e.estoque@exemplo.com", "so.admin@exemplo.com", "sem.perfil@exemplo.com"):
            assert acesso.cadastrar("Pessoa " + email.split("@")[0], email, "segredo1")[0]
        liberar(admin, "so.estoque@exemplo.com", ["estoque"])
        liberar(admin, "decl.e.estoque@exemplo.com", ["declaracoes", "estoque"])
        liberar(admin, "so.admin@exemplo.com", ["admin"])                  # só marcou Administrador
        liberar(admin, "sem.perfil@exemplo.com", [])                        # liberada, mas sem nenhum perfil
        e = acesso.entrar("so.estoque@exemplo.com", "segredo1")[0]
        assert e.abas() == ["pedagogico", "limpeza"] and not e.pode("declaracoes") and not e.admin
        c = acesso.entrar("decl.e.estoque@exemplo.com", "segredo1")[0]
        assert c.abas() == ["declaracoes", "pedagogico", "limpeza"] and not c.admin and not c.pode("configuracao")
        a = acesso.entrar("so.admin@exemplo.com", "segredo1")[0]
        assert a.admin and a.abas() == ["declaracoes", "pedagogico", "limpeza"] and a.pode("usuarios")   # administrador vê tudo
        assert a.perfis == ("declaracoes", "estoque", "admin")
        n = acesso.entrar("sem.perfil@exemplo.com", "segredo1")[0]
        assert n is not None and n.abas() == []                             # entra, mas não vê nada
        # perfil inventado é ignorado
        ok, resp = acesso.atualizar(admin, "sem.perfil@exemplo.com", perfis=["declaracoes", "voar"])
        assert ok and resp["perfis"] == ["declaracoes"]


def teste_travas_do_administrador():
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Beto Exemplo", "beto@exemplo.com", "segredo1")[0]
        liberar(admin, "beto@exemplo.com", ["declaracoes"])
        beto = acesso.entrar("beto@exemplo.com", "segredo1")[0]
        # quem não é administrador não consegue as ações de administrador (nem pelo servidor)
        assert acesso.listar(beto) == (None, "Só o administrador pode fazer isso.")
        resp = acesso._chamar({"acao": "listar", "email": "beto@exemplo.com", "senha": "segredo1"})
        assert resp["erro"] == "sem_permissao"
        resp = acesso._chamar({"acao": "atualizar", "email": "beto@exemplo.com", "senha": "segredo1",
                               "alvo": "beto@exemplo.com", "perfis": ["admin"]})
        assert resp["erro"] == "sem_permissao"                              # não dá para se promover
        resp = acesso._chamar({"acao": "listar", "email": ADMIN, "senha": "errada"})
        assert resp["motivo"] == "senha"                                    # senha de administrador errada
        # o administrador não tira o próprio acesso nem apaga a própria conta
        assert "próprio acesso" in acesso.atualizar(admin, ADMIN, perfis=["declaracoes"])[1]
        assert "próprio acesso" in acesso.atualizar(admin, ADMIN, status="bloqueado")[1]
        assert "próprio acesso" in acesso.remover(admin, ADMIN)[1]
        assert acesso.atualizar(admin, ADMIN, perfis=["declaracoes", "estoque", "admin"])[0]      # mesmo perfil: pode
        # mudar a situação e o prazo; remover
        assert acesso.atualizar(admin, "beto@exemplo.com", status="bloqueado")[0]
        s, erro = acesso.entrar("beto@exemplo.com", "segredo1")
        assert s is None and "bloqueado" in erro
        assert acesso.atualizar(admin, "beto@exemplo.com", status="autorizado")[0]
        assert acesso.entrar("beto@exemplo.com", "segredo1")[0] is not None
        resp = acesso._chamar({"acao": "atualizar", "email": ADMIN, "senha": admin.senha, "alvo": "beto@exemplo.com", "status": "voando"})
        assert resp["erro"] == "status_invalido"
        assert acesso.remover(admin, "beto@exemplo.com") == (True, "Conta removida.")
        assert "não tem cadastro" in acesso.entrar("beto@exemplo.com", "segredo1")[1]
        assert "não foi encontrada" in acesso.remover(admin, "beto@exemplo.com")[1]
        assert "pelo menos 8" in acesso.definir_senha(admin, "beto@exemplo.com", "123")[1]


def teste_prazo_do_acesso():
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Carla Exemplo", "carla@exemplo.com", "segredo1")[0]
        amanha = (date.today() + timedelta(days=1)).isoformat()
        liberar(admin, "carla@exemplo.com", ["declaracoes"], validade=amanha)
        s = acesso.entrar("carla@exemplo.com", "segredo1")[0]
        assert s and s.validade == amanha
        p.avancar(60 * 24 * 2)                                              # passam 2 dias
        s, erro = acesso.entrar("carla@exemplo.com", "segredo1")
        assert s is None and "prazo" in erro
        # sem prazo (vazio) nunca vence
        liberar(admin, "carla@exemplo.com", ["declaracoes"], validade="")
        assert acesso.entrar("carla@exemplo.com", "segredo1")[0] is not None
        ok, resp = acesso.atualizar(admin, "carla@exemplo.com", validade="31/12/2026")
        assert not ok                                                       # formato errado é recusado


def teste_senha_errada_trava_a_conta():
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Davi Exemplo", "davi@exemplo.com", "segredo1")[0]
        liberar(admin, "davi@exemplo.com", ["declaracoes"])
        for i in range(4):
            s, erro = acesso.entrar("davi@exemplo.com", "errada{}".format(i))
            assert s is None and "incorreta" in erro
        assert "Restam 1" in erro                                            # avisa quando falta pouco
        s, erro = acesso.entrar("davi@exemplo.com", "errada5")              # 5ª errada: trava
        assert s is None and "travada" in erro
        s, erro = acesso.entrar("davi@exemplo.com", "segredo1")             # nem a senha certa entra enquanto está travada
        assert s is None and "travada" in erro
        p.avancar(16)
        assert acesso.entrar("davi@exemplo.com", "segredo1")[0] is not None  # passou o tempo: volta
        # entrar certo zera a contagem: 4 erradas, 1 certa, 4 erradas e ainda não travou
        for i in range(4):
            acesso.entrar("davi@exemplo.com", "x{}".format(i))
        assert acesso.entrar("davi@exemplo.com", "segredo1")[0] is not None
        for i in range(4):
            s, erro = acesso.entrar("davi@exemplo.com", "y{}".format(i))
            assert "travada" not in erro


def teste_esqueci_e_alterar_a_senha():
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Eva Exemplo", "eva@exemplo.com", "segredo1")[0]
        liberar(admin, "eva@exemplo.com", ["estoque"])
        assert "não tem cadastro" in acesso.recuperar("naoexiste@exemplo.com")[1]
        ok, texto = acesso.recuperar("eva@exemplo.com")
        assert ok and "provisória" in texto
        assert acesso.entrar("eva@exemplo.com", "segredo1")[0] is None      # a senha antiga deixou de valer
        prov = p.senha_provisoria_de("eva@exemplo.com")
        ok, texto = acesso.recuperar("eva@exemplo.com")                     # pedir de novo logo em seguida
        assert not ok and "Espere" in texto
        s = acesso.entrar("eva@exemplo.com", prov)[0]
        assert s and s.perfis == ("estoque",)
        assert "pelo menos 8" in acesso.alterar_senha("eva@exemplo.com", prov, "123")[1]
        assert "incorreta" in acesso.alterar_senha("eva@exemplo.com", "errada", "novasenha")[1]
        assert acesso.alterar_senha("eva@exemplo.com", prov, "novasenha")[0]
        assert acesso.entrar("eva@exemplo.com", prov)[0] is None
        assert acesso.entrar("eva@exemplo.com", "novasenha")[0] is not None
        # o administrador define uma senha quando o e-mail não chega
        assert acesso.definir_senha(admin, "eva@exemplo.com", "outrasenha") == (True, "Senha definida.")
        assert acesso.entrar("eva@exemplo.com", "outrasenha")[0] is not None


def teste_sem_internet():
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Fábio Exemplo", "fabio@exemplo.com", "segredo1")[0]
        liberar(admin, "fabio@exemplo.com", ["declaracoes"])
        assert acesso.entrar("fabio@exemplo.com", "segredo1")[0] is not None     # entrou com internet: fica a cópia
        guardado = open(acesso._arquivo_local(), encoding="utf-8").read()
        assert "segredo1" not in guardado and "fabio@exemplo.com" in guardado    # só o código da senha, nunca a senha
        url_boa = acesso.URL_ACESSOS
        acesso.URL_ACESSOS = "http://127.0.0.1:{}".format(porta_livre())         # ninguém responde aqui
        try:
            s, erro = acesso.entrar("fabio@exemplo.com", "segredo1")
            assert s and s.sem_internet and s.abas() == ["declaracoes"]
            s, erro = acesso.entrar("fabio@exemplo.com", "errada")
            assert s is None and "servidor" in erro                              # senha errada não passa
            s, erro = acesso.entrar("gente.nova@exemplo.com", "segredo1")
            assert s is None and "servidor" in erro and "nos últimos 7 dias" in erro   # quem nunca entrou aqui não passa
            # administrador sem internet não mexe nos usuários
            assert acesso.listar(Sessao_sem_internet_admin()) == (None, "Não consegui falar com o servidor de acessos. Confira a internet e tente de novo.")
            # a cópia vence depois de 7 dias
            dados = acesso._ler_local()
            dados["usuarios"]["fabio@exemplo.com"]["ok_em"] = time.time() - 8 * 86400
            acesso._gravar_local(dados)
            assert acesso.entrar("fabio@exemplo.com", "segredo1")[0] is None
        finally:
            acesso.URL_ACESSOS = url_boa
        # voltou a internet: entra normalmente e a cópia é renovada
        assert acesso.entrar("fabio@exemplo.com", "segredo1")[0] is not None
        assert acesso._entrar_sem_internet("fabio@exemplo.com", "segredo1") is not None
        # acesso bloqueado com internet apaga a cópia: sem internet também não entra mais
        acesso.atualizar(admin, "fabio@exemplo.com", status="bloqueado")
        assert acesso.entrar("fabio@exemplo.com", "segredo1")[0] is None
        assert acesso._entrar_sem_internet("fabio@exemplo.com", "segredo1") is None
        # trocar a senha também apaga a cópia (que tinha a senha antiga)
        acesso.atualizar(admin, "fabio@exemplo.com", status="autorizado")
        assert acesso.entrar("fabio@exemplo.com", "segredo1")[0] is not None
        assert acesso.alterar_senha("fabio@exemplo.com", "segredo1", "segredo2")[0]
        assert acesso._entrar_sem_internet("fabio@exemplo.com", "segredo1") is None


def Sessao_sem_internet_admin():
    return acesso.Sessao("admin@exemplo.com", "Administrador", ["admin"], senha="x", sem_internet=True)


def teste_sessao_sem_login_e_sem_servidor():
    # sem endereço configurado o programa abre como antes: acesso total
    url_real = acesso.URL_ACESSOS
    acesso.URL_ACESSOS = ""
    try:
        assert not acesso.configurado()
    finally:
        acesso.URL_ACESSOS = url_real
    s = acesso.Sessao.completa()
    assert s.sem_login and s.abas() == ["declaracoes", "pedagogico", "limpeza"] and s.pode("usuarios")
    assert acesso.listar(s) == (None, "Só o administrador pode fazer isso.")             # sem login, nada de administração online
    # servidor fora do ar: mensagem clara, sem travar
    with Ponte() as p:
        acesso.URL_ACESSOS = "http://127.0.0.1:{}".format(porta_livre())
        t0 = time.time()
        s, erro = acesso.entrar("alguem@exemplo.com", "segredo1")
        assert s is None and "servidor de acessos" in erro and time.time() - t0 < 10
        assert "Digite" in acesso.entrar("", "x")[1] and "Digite" in acesso.entrar("a@b.com", "")[1]
        assert not acesso.cadastrar("Fulano", "fulano@exemplo.com", "segredo1")[0]


def _servidor_fora_do_ar():
    return "http://127.0.0.1:{}".format(porta_livre())              # ninguém responde aqui


def teste_entrada_rapida_com_a_copia_guardada():
    """Opção A: com a cópia guardada neste computador, a pessoa entra NA HORA, sem esperar o servidor."""
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Ana Exemplo", "ana@exemplo.com", "segredo1")[0]
        liberar(admin, "ana@exemplo.com", ["declaracoes"])
        # 1º acesso neste computador: não há cópia, então fala com o servidor (e a cópia passa a existir)
        s, erro = acesso.entrar_rapido("ana@exemplo.com", "segredo1")
        assert s and not s.por_copia and not s.sem_internet and s.perfis == ("declaracoes",), erro
        url_boa = acesso.URL_ACESSOS
        acesso.URL_ACESSOS = _servidor_fora_do_ar()
        try:
            # a partir daí entra sem nem tentar o servidor: aqui o servidor está fora do ar e mesmo assim é imediato
            t0 = time.time()
            s, erro = acesso.entrar_rapido("ANA@exemplo.com ", "segredo1")
            assert s and s.por_copia and not s.sem_internet and s.perfis == ("declaracoes",) and s.nome == "Ana Exemplo", erro
            assert s.email == "ana@exemplo.com" and s.senha == "segredo1" and s.abas() == ["declaracoes"]
            assert time.time() - t0 < 5, "a entrada pela cópia não pode esperar o servidor"
            # senha errada não entra pela cópia (cai no servidor, que está fora do ar)
            s, erro = acesso.entrar_rapido("ana@exemplo.com", "outra-senha-9")
            assert s is None and "servidor" in erro
            # cópia com mais de 7 dias não vale: volta a exigir o servidor
            dados = acesso._ler_local()
            dados["usuarios"]["ana@exemplo.com"]["ok_em"] = time.time() - 8 * 86400
            acesso._gravar_local(dados)
            s, erro = acesso.entrar_rapido("ana@exemplo.com", "segredo1")
            assert s is None and "servidor" in erro
        finally:
            acesso.URL_ACESSOS = url_boa
        # com o servidor de volta, entra pelo caminho normal e a cópia é renovada
        s, erro = acesso.entrar_rapido("ana@exemplo.com", "segredo1")
        assert s and not s.por_copia, erro
        # prazo vencido na cópia: não entra pela cópia
        dados = acesso._ler_local()
        dados["usuarios"]["ana@exemplo.com"]["validade"] = "2020-01-01"
        acesso._gravar_local(dados)
        acesso.URL_ACESSOS = _servidor_fora_do_ar()
        try:
            assert acesso.entrar_rapido("ana@exemplo.com", "segredo1")[0] is None
        finally:
            acesso.URL_ACESSOS = url_boa
        # sem nada digitado
        assert "Digite" in acesso.entrar_rapido("", "x")[1] and "Digite" in acesso.entrar_rapido("a@b.com", "")[1]


def teste_confirmacao_do_acesso_em_segundo_plano():
    """Quem entrou pela cópia é confirmado depois: igual, mudou, cortado ou sem resposta."""
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.cadastrar("Beto Exemplo", "beto@exemplo.com", "segredo1")[0]
        liberar(admin, "beto@exemplo.com", ["estoque"])
        assert acesso.entrar_rapido("beto@exemplo.com", "segredo1")[0]                    # cria a cópia
        entra = lambda: acesso.entrar_rapido("beto@exemplo.com", "segredo1")[0]
        copia = lambda: acesso._ler_local().get("usuarios", {}).get("beto@exemplo.com")

        # 1) tudo igual
        s = entra()
        assert s.por_copia
        antes = copia()["ok_em"]
        time.sleep(0.05)
        estado, texto, nova = acesso.conferir_acesso(s)
        assert estado == "ok" and texto == "" and nova.perfis == ("estoque",) and copia()["ok_em"] > antes

        # 2) o administrador muda os perfis: "mudou", e a cópia já fica com os perfis novos
        liberar(admin, "beto@exemplo.com", ["declaracoes", "estoque"])
        estado, texto, nova = acesso.conferir_acesso(s)
        assert estado == "mudou" and nova.perfis == ("declaracoes", "estoque") and copia()["perfis"] == ["declaracoes", "estoque"]
        s2 = entra()
        assert s2.por_copia and s2.perfis == ("declaracoes", "estoque")                      # a próxima entrada já vem certa
        # também "mudou" se só o prazo mudar
        liberar(admin, "beto@exemplo.com", ["declaracoes", "estoque"], validade=(date.today() + timedelta(days=30)).isoformat())
        assert acesso.conferir_acesso(s2)[0] == "mudou"

        # 3) sem resposta do servidor: nada muda, a cópia continua
        s3 = entra()
        url_boa = acesso.URL_ACESSOS
        acesso.URL_ACESSOS = _servidor_fora_do_ar()
        try:
            estado, texto, nova = acesso.conferir_acesso(s3)
            assert (estado, texto, nova) == ("sem_resposta", "", None) and copia() is not None
        finally:
            acesso.URL_ACESSOS = url_boa

        # 4) bloqueado: "cortado", a cópia é apagada e a pessoa não entra mais (nem pela cópia)
        assert acesso.atualizar(admin, "beto@exemplo.com", status="bloqueado")[0]
        estado, texto, nova = acesso.conferir_acesso(s3)
        assert estado == "cortado" and "bloqueado" in texto and nova is None and copia() is None
        s4, erro = acesso.entrar_rapido("beto@exemplo.com", "segredo1")
        assert s4 is None and "bloqueado" in erro

        # 5) senha trocada pelo administrador: a cópia (com a senha antiga) deixa de valer
        assert acesso.atualizar(admin, "beto@exemplo.com", status="autorizado")[0]
        s5 = acesso.entrar_rapido("beto@exemplo.com", "segredo1")[0]
        assert s5 and not s5.por_copia                                                      # a cópia foi apagada: foi ao servidor
        s5 = entra()
        assert s5.por_copia
        assert acesso.definir_senha(admin, "beto@exemplo.com", "Boa-Senha-77")[0]
        estado, texto, nova = acesso.conferir_acesso(s5)
        assert estado == "cortado" and "senha" in texto and copia() is None

        # 6) conta removida
        assert acesso.entrar_rapido("beto@exemplo.com", "Boa-Senha-77")[0]                  # cria a cópia (senha nova)
        s6 = acesso.entrar_rapido("beto@exemplo.com", "Boa-Senha-77")[0]
        assert s6.por_copia
        assert acesso.remover(admin, "beto@exemplo.com")[0]
        estado, texto, nova = acesso.conferir_acesso(s6)
        assert estado == "cortado" and "cadastro" in texto and copia() is None

        # a conferência em segundo plano devolve o mesmo resultado, sem travar quem chamou
        acesso.cadastrar("Beto Exemplo", "beto@exemplo.com", "segredo1")
        liberar(admin, "beto@exemplo.com", ["estoque"])
        s7 = acesso.entrar_rapido("beto@exemplo.com", "segredo1")[0]
        s7 = entra()
        c = acesso.ConferenciaAcesso(s7)
        t0 = time.time()
        while not c.pronta and time.time() - t0 < 30:
            time.sleep(0.05)
        assert c.pronta and c.estado == "ok" and c.nova.perfis == ("estoque",)


def teste_senha_guardada_neste_computador():
    """"Salvar a senha neste computador": criptografada (DPAPI), só vale para a mesma pessoa e some quando fica velha."""
    if not acesso.pode_guardar_senha():
        return                                                          # só no Windows
    with Ponte() as p:
        admin = entrar_admin(p)
        assert acesso.guardar_senha(" Ana@Exemplo.com", "Boa-Senha-77")
        bruto = open(acesso._arquivo_senha(), "rb").read()
        assert b"Boa-Senha-77" not in bruto and b"ana@exemplo.com" not in bruto and len(bruto) > 40, "não pode estar em texto puro"
        assert acesso.senha_guardada("ANA@exemplo.com ") == "Boa-Senha-77"
        assert acesso.senha_guardada("beto@exemplo.com") == ""            # é da Ana, não do Beto
        assert not acesso.guardar_senha("ana@exemplo.com", "")            # sem senha, nada a guardar
        # apagar a senha de outra pessoa não mexe na da Ana; apagar a da Ana apaga
        acesso.esquecer_senha("beto@exemplo.com")
        assert acesso.senha_guardada("ana@exemplo.com") == "Boa-Senha-77"
        acesso.esquecer_senha("ana@exemplo.com")
        assert acesso.senha_guardada("ana@exemplo.com") == "" and not os.path.exists(acesso._arquivo_senha())
        # só uma senha por computador: a da última pessoa que salvou
        assert acesso.guardar_senha("ana@exemplo.com", "Boa-Senha-77") and acesso.guardar_senha("beto@exemplo.com", "outra-Senha-55")
        assert acesso.senha_guardada("ana@exemplo.com") == "" and acesso.senha_guardada("beto@exemplo.com") == "outra-Senha-55"
        acesso.esquecer_senha()                                           # sem e-mail: apaga a de quem for
        assert not os.path.exists(acesso._arquivo_senha())
        # arquivo estragado ou de outra conta do Windows: não dá erro, só não preenche; e pode ser apagado
        with open(acesso._arquivo_senha(), "wb") as f:
            f.write(b"lixo que nao e do DPAPI")
        assert acesso.senha_guardada("ana@exemplo.com") == ""
        acesso.esquecer_senha("ana@exemplo.com")
        assert not os.path.exists(acesso._arquivo_senha())

        # trocar a senha (Alterar minha senha) apaga a guardada, que ficou velha; senha fraca recusada não apaga
        assert acesso.cadastrar("Ana Exemplo", "ana@exemplo.com", "segredo1")[0]
        liberar(admin, "ana@exemplo.com", ["declaracoes"])
        assert acesso.guardar_senha("ana@exemplo.com", "segredo1")
        assert not acesso.alterar_senha("ana@exemplo.com", "segredo1", "12345678")[0]
        assert acesso.senha_guardada("ana@exemplo.com") == "segredo1"
        assert acesso.alterar_senha("ana@exemplo.com", "segredo1", "Boa-Senha-77")[0]
        assert acesso.senha_guardada("ana@exemplo.com") == ""

        # o administrador troca a senha em outro lugar: a conferência em segundo plano apaga a guardada
        assert acesso.entrar_rapido("ana@exemplo.com", "Boa-Senha-77")[0]
        sessao = acesso.entrar_rapido("ana@exemplo.com", "Boa-Senha-77")[0]
        assert sessao.por_copia and acesso.guardar_senha("ana@exemplo.com", "Boa-Senha-77")
        assert acesso.definir_senha(admin, "ana@exemplo.com", "tomate azul 42")[0]
        estado, texto, nova = acesso.conferir_acesso(sessao)
        assert estado == "cortado" and acesso.senha_guardada("ana@exemplo.com") == ""
        assert acesso.INICIO_SENHA_INCORRETA in acesso.mensagem({"motivo": "senha"})


def teste_conexao_que_nao_abre_e_tentada_de_novo():
    """Rede da SEMED: às vezes a conexão não abre (erro 10060, 21 s). O programa tenta de novo logo (até 6 vezes)."""
    with Ponte() as p:
        real = socket.create_connection
        contagem = {"falhas_restantes": 2, "tentativas": 0}

        def instavel(*args, **kwargs):
            contagem["tentativas"] += 1
            if contagem["falhas_restantes"] > 0:
                contagem["falhas_restantes"] -= 1
                raise OSError(10060, "a conexão não abriu")
            return real(*args, **kwargs)

        socket.create_connection = instavel
        try:
            # falha 2 vezes e abre na 3ª: o pedido passa normalmente
            r = acesso._chamar({"acao": "entrar", "email": "ninguem@exemplo.com", "senha": "qualquer coisa"})
            assert r.get("motivo") == "nao_cadastrado", r
            assert contagem["tentativas"] == 3 and contagem["falhas_restantes"] == 0, contagem
            # nunca abre: desiste depois de 3 tentativas e devolve erro de conexão (sem travar)
            contagem.update(falhas_restantes=999, tentativas=0)
            r = acesso._chamar({"acao": "entrar", "email": "ninguem@exemplo.com", "senha": "qualquer coisa"})
            assert r.get("erro") == "conexao", r
            assert contagem["tentativas"] == len(acesso.TEMPOS_ABRIR_CONEXAO) == 6, contagem
            # sem internet, sem DNS ou servidor recusando: NÃO repete (senão quem está sem internet esperaria à toa)
            for erro in (ConnectionRefusedError(10061, "recusada"), socket.gaierror(11001, "sem DNS"),
                         OSError(10051, "rede inacessível")):
                contagem.update(falhas_restantes=0, tentativas=0)

                def uma_falha(*args, _e=erro, **kwargs):
                    contagem["tentativas"] += 1
                    raise _e
                socket.create_connection = uma_falha
                t0 = time.time()
                r = acesso._chamar({"acao": "entrar", "email": "ninguem@exemplo.com", "senha": "qualquer coisa"})
                assert r.get("erro") == "conexao" and contagem["tentativas"] == 1, (erro, r, contagem)
                assert time.time() - t0 < 2
        finally:
            socket.create_connection = real
        assert sum(acesso.TEMPOS_ABRIR_CONEXAO) <= 16 and acesso.TEMPOS_ABRIR_CONEXAO[0] <= 2      # curtas primeiro, pior caso 16 s
        # com a conexão boa, o tempo de espera da resposta volta ao normal (20 s), não fica nos 5 s da abertura
        sock = acesso._abrir_com_tentativas(("127.0.0.1", p.porta), 20)
        try:
            assert sock.gettimeout() == 20
        finally:
            sock.close()


# Senhas que o programa e o servidor têm de recusar, e senhas que têm de servir (e-mail de teste: carla.exemplo@exemplo.com)
FRACAS = ["11111111", "aaaaaaaa", "abababab", "12341234", "12345678", "87654321", "abcdefgh", "hgfedcba",
          "123456789", "1234567890", "Senha123", "PASSWORD", "qwertyui", "semed2026", "SEMED2026", "Admin123",
          "carla.exemplo", "carla.exemplo2026", "minhacarla.exemplo", "CARLA.EXEMPLO"]
BOAS = ["segredo1", "Boa-Senha-77", "tomate azul 42", "cadeira#roxa9", "x9k2m4q7", "SenhaBoa#77", "carla2026",
        "12345679", "abcdefgi", "aaaaaabc1"]


def teste_regras_de_senha_no_programa():
    email = "carla.exemplo@exemplo.com"
    assert acesso.SENHA_MINIMA == 8
    for s in FRACAS:
        assert acesso.senha_fraca(s, email), s
        assert acesso.problema_na_senha(s, email), s
    for s in BOAS:
        assert not acesso.senha_fraca(s, email), s
        assert acesso.problema_na_senha(s, email) is None, s
    assert "pelo menos 8" in acesso.problema_na_senha("abc", email)
    assert "fácil de adivinhar" in acesso.problema_na_senha("12345678", email)
    assert acesso.problema_na_senha("", "") and acesso.problema_na_senha(None, None)
    assert "fácil de adivinhar" in acesso.mensagem({"erro": "senha_fraca"})
    assert "muitos cadastros" in acesso.mensagem({"erro": "muitos_pendentes"})


def teste_servidor_recusa_senhas_fracas_e_concorda_com_o_programa():
    """O servidor decide sozinho (mesmo que alguém pule a verificação do programa) e dá a mesma resposta."""
    email = "carla.exemplo@exemplo.com"
    with Ponte() as p:
        admin = entrar_admin(p)
        for s in FRACAS + BOAS + ["curta", "1234567"]:
            resp = acesso._chamar({"acao": "cadastrar", "nome": "Carla Exemplo", "email": email, "senha": s})
            esperado_fraca = acesso.problema_na_senha(s, email) is not None
            if esperado_fraca:
                assert resp.get("erro") in ("senha_curta", "senha_fraca"), (s, resp)
            else:
                assert resp.get("ok") is True, (s, resp)
                acesso.remover(admin, email)               # libera o e-mail para a próxima tentativa
        # trocar a própria senha e o administrador definir a senha de outra pessoa passam pelas mesmas regras
        assert acesso.cadastrar("Carla Exemplo", email, "segredo1")[0]
        liberar(admin, email, ["declaracoes"])
        for fraca in ("12345678", "carla.exemplo1"):
            r = acesso._chamar({"acao": "alterar_senha", "email": email, "senha": "segredo1", "nova_senha": fraca})
            assert r.get("erro") == "senha_fraca", (fraca, r)
            r = acesso._chamar({"acao": "definir_senha", "email": ADMIN, "senha": admin.senha, "alvo": email, "nova_senha": fraca})
            assert r.get("erro") == "senha_fraca", (fraca, r)
        assert acesso.entrar(email, "segredo1")[0] is not None                  # a senha antiga continua valendo
        assert acesso.alterar_senha(email, "segredo1", "Boa-Senha-77")[0]
        assert acesso.definir_senha(admin, email, "tomate azul 42")[0]
        assert acesso.entrar(email, "tomate azul 42")[0] is not None            # entra com a senha que o administrador definiu


def teste_limite_de_cadastros_aguardando_liberacao():
    with Ponte() as p:
        admin = entrar_admin(p)
        limite = 20
        for n in range(limite):
            r = acesso._chamar({"acao": "cadastrar", "nome": "Pessoa Exemplo %d" % n, "email": "pessoa%d@exemplo.com" % n, "senha": "segredo1"})
            assert r.get("ok") is True, (n, r)
        avisos = [e for e in p.emails() if e["para"] == ADMIN and "novo cadastro" in e["assunto"]]
        assert len(avisos) == limite
        # o 21º é recusado, sem e-mail de aviso e sem entrar na planilha
        r = acesso._chamar({"acao": "cadastrar", "nome": "Fake", "email": "fake@exemplo.com", "senha": "segredo1"})
        assert r.get("erro") == "muitos_pendentes", r
        assert "muitos cadastros" in acesso.cadastrar("Fake", "fake@exemplo.com", "segredo1")[1]
        assert len([e for e in p.emails() if e["para"] == ADMIN and "novo cadastro" in e["assunto"]]) == limite
        assert "fake@exemplo.com" not in json.dumps(p.pegar("_planilha"))
        # quem já está cadastrado continua recebendo a resposta de sempre
        assert "aguardando" in acesso.cadastrar("Pessoa 0", "pessoa0@exemplo.com", "segredo1")[1]
        # o administrador libera uma pessoa: abre uma vaga
        liberar(admin, "pessoa0@exemplo.com", ["declaracoes"])
        assert acesso.cadastrar("Fake", "fake@exemplo.com", "segredo1")[0]
        # e a lista do administrador mostra tudo (21 cadastros novos + o administrador)
        lista, _ = acesso.listar(admin)
        assert len(lista) == limite + 2


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("teste_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print("ok  ", nome)
    print("\n{} testes passaram.".format(len(testes)))
