# -*- coding: utf-8 -*-
"""
Tela de entrada do programa: e-mail e senha, criar conta, esqueci a senha e alterar a senha.

Abre ANTES da janela principal, numa janela própria (`pedir_acesso`). Quem fala com o servidor é o
módulo `acesso`; aqui só tem a tela. A chamada de rede roda em segundo plano para a janela não travar.
"""
import queue
import threading
import tkinter as tk

import acesso

# Preenchidos por usar(): widgets, cores e funções do arquivo principal.
Botao = Chip = campo = AreaRolavel = None
COR_FUNDO = COR_CARTAO = COR_AZUL = COR_AZUL_ESCURO = COR_AZUL_CLARO = None
COR_TEXTO = COR_TEXTO_FRACO = COR_BORDA = COR_VERDE = COR_LARANJA = None
FONTE = "Arial"
COR_VERMELHO = "#B42318"
_BASE = None


def usar(base):
    """Recebe o arquivo principal (os widgets e as cores dele)."""
    global _BASE
    _BASE = base
    for nome in ("Botao", "Chip", "campo", "COR_FUNDO", "COR_CARTAO", "COR_AZUL", "COR_AZUL_ESCURO",
                 "COR_AZUL_CLARO", "COR_TEXTO", "COR_TEXTO_FRACO", "COR_BORDA", "COR_VERDE", "COR_LARANJA", "FONTE"):
        globals()[nome] = getattr(base, nome)


def desenhar_faixa(faixa, largura, altura, titulo, subtitulo):
    """Faixa azul em degradê com o logo (a mesma do alto do programa)."""
    faixa.delete("all")
    for x in range(0, largura, 4):
        faixa.create_rectangle(x, 0, x + 4, altura, outline="", fill=_BASE._misturar("#17327A", "#2A63C8", x / max(largura, 1)))
    _BASE._retangulo_arredondado(faixa, 22, 16, 72, 66, 13, fill="#FFFFFF", outline="#FFFFFF")
    faixa.create_polygon(35, 25, 52, 25, 59, 32, 59, 57, 35, 57, fill=COR_AZUL, outline=COR_AZUL)
    faixa.create_polygon(52, 25, 52, 32, 59, 32, fill="#9DB6E6", outline="#9DB6E6")
    for yy in (36, 41):
        faixa.create_line(40, yy, 50, yy, fill="#DCE8FF", width=2, capstyle="round")
    faixa.create_line(41, 48, 46, 53, 54, 44, fill="#3DDC84", width=4, capstyle="round", joinstyle="round")
    faixa.create_text(88, 30, anchor="w", text=titulo, fill="white", font=(FONTE, 17, "bold"))
    faixa.create_text(88, 56, anchor="w", text=subtitulo, fill="#D5E1F7", font=(FONTE, 9))


def em_segundo_plano(janela, funcao, depois, intervalo=100):
    """Roda `funcao` (que usa a internet) numa thread e chama `depois(resultado)` na tela, sem travar a janela."""
    fila = queue.Queue()
    threading.Thread(target=lambda: fila.put(funcao()), daemon=True).start()

    def olhar():
        try:
            if not janela.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            resultado = fila.get_nowait()
        except queue.Empty:
            janela.after(intervalo, olhar)
            return
        depois(resultado)
    janela.after(intervalo, olhar)


class JanelaAcesso(tk.Tk):
    """A janela de entrada. Depois de `mainloop()`, `.sessao` é a Sessao de quem entrou (ou None se fechou)."""

    LARGURA = 470

    def __init__(self, aviso=""):
        super().__init__()
        _BASE.aplicar_aumento_de_letra(self)
        self.title(_BASE.NOME_PROGRAMA)
        try:
            self.iconbitmap(default=_BASE.caminho_recurso("icone_declaracoes.ico"))
        except tk.TclError:
            pass
        _BASE.configurar_estilo(self)
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.sessao = None
        self._acao = lambda: None
        self._botao = None
        self._ocupado = False
        self.var_email = tk.StringVar(value=acesso.ultimo_email())
        self.var_mostrar = tk.BooleanVar(value=False)
        self._entradas_senha = []

        self.faixa = tk.Canvas(self, width=self.LARGURA, height=84, highlightthickness=0, bd=0, bg=COR_AZUL_ESCURO)
        self.faixa.pack(fill="x")
        desenhar_faixa(self.faixa, self.LARGURA, 84, _BASE.NOME_PROGRAMA, "Acesso restrito: entre para continuar")
        self.corpo = tk.Frame(self, bg=COR_CARTAO)
        self.corpo.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.bind("<Return>", lambda e: self._acao())
        self.bind("<Escape>", lambda e: self.destroy())
        self.var_mostrar.trace_add("write", lambda *_: self._mostrar_senhas())
        self._mostrar_modo_entrar(aviso, "info")

    # -- peças ---------------------------------------------------------------------------

    def _limpar(self):
        for w in self.corpo.winfo_children():
            w.destroy()
        self._entradas_senha = []
        interno = tk.Frame(self.corpo, bg=COR_CARTAO)
        interno.pack(fill="both", expand=True, padx=30, pady=(18, 22))
        return interno

    def _titulo(self, pai, texto, ajuda=""):
        tk.Label(pai, text=texto, bg=COR_CARTAO, fg=COR_AZUL_ESCURO, font=(FONTE, 14, "bold"), anchor="w").pack(anchor="w")
        if ajuda:
            tk.Label(pai, text=ajuda, bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w", justify="left",
                     wraplength=self.LARGURA - 90).pack(anchor="w", pady=(2, 0))

    def _campo(self, pai, titulo, variavel, senha=False):
        q = campo(pai, titulo, variavel)
        q.pack(fill="x", pady=(10, 0))
        if senha:
            q.entrada.configure(show="•")
            self._entradas_senha.append(q.entrada)
        return q

    def _mensagem(self, pai):
        self.lbl = tk.Label(pai, text="", bg=COR_CARTAO, fg=COR_VERMELHO, font=(FONTE, 9, "bold"), anchor="w",
                            justify="left", wraplength=self.LARGURA - 90)
        self.lbl.pack(fill="x", pady=(10, 0))

    def _avisar(self, texto, tipo="erro"):
        cor = {"erro": COR_VERMELHO, "ok": COR_VERDE, "info": COR_TEXTO_FRACO}.get(tipo, COR_VERMELHO)
        if self.lbl.winfo_exists():
            self.lbl.configure(text=texto, fg=cor)
            self._ajustar_altura()

    def _ajustar_altura(self):
        """A janela cresce ou encolhe com a mensagem, sem mudar de lugar."""
        self.update_idletasks()
        self.geometry("{}x{}".format(self.winfo_reqwidth(), self.winfo_reqheight()))

    def _link(self, pai, texto, comando):
        t = tk.Label(pai, text=texto, bg=COR_CARTAO, fg=COR_AZUL, font=(FONTE, 9, "underline"), cursor="hand2")
        t.bind("<Button-1>", lambda e: comando())
        return t

    def _botao_principal(self, pai, texto, comando):
        self._acao = comando
        self._botao = Botao(pai, texto, comando, estilo="azul", fonte=(FONTE, 11, "bold"), pad_y=9)
        self._botao.pack(fill="x", pady=(14, 0))

    def _mostrar_senhas(self):
        for e in self._entradas_senha:
            try:
                e.configure(show="" if self.var_mostrar.get() else "•")
            except tk.TclError:
                pass

    def _centralizar(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry("{}x{}+{}+{}".format(w, h, max((self.winfo_screenwidth() - w) // 2, 0),
                                           max((self.winfo_screenheight() - h) // 3, 0)))

    def _trabalhar(self, funcao, depois, texto="Conectando ao servidor..."):
        """Roda `funcao` (que usa a internet) em segundo plano e chama `depois(resultado)` aqui na tela."""
        if self._ocupado:
            return
        self._ocupado = True
        self._avisar(texto, "info")
        if self._botao is not None:
            self._botao.definir_ativo(False)
        self.configure(cursor="watch")

        def terminou(resultado):
            self._ocupado = False
            self.configure(cursor="")
            if self._botao is not None and self._botao.winfo_exists():
                self._botao.definir_ativo(True)
            depois(resultado)
        em_segundo_plano(self, funcao, terminou)

    # -- modos ---------------------------------------------------------------------------

    def _mostrar_modo_entrar(self, aviso="", tipo="info"):
        p = self._limpar()
        self._titulo(p, "Entrar")
        q = self._campo(p, "E-mail", self.var_email)
        self._campo(p, "Senha", self._nova_var("senha"), senha=True)
        Chip(p, "Mostrar senha", self.var_mostrar).pack(anchor="w", pady=(10, 0))
        self._mensagem(p)
        self._botao_principal(p, "Entrar", self._entrar)
        links = tk.Frame(p, bg=COR_CARTAO)
        links.pack(fill="x", pady=(14, 0))
        self._link(links, "Criar minha conta", self._mostrar_modo_cadastro).pack(side="left")
        self._link(links, "Alterar minha senha", self._mostrar_modo_alterar).pack(side="right")
        self._link(links, "Esqueci minha senha", self._mostrar_modo_esqueci).pack(side="right", padx=(0, 14))
        if aviso:
            self._avisar(aviso, tipo)
        self._centralizar()
        (self.focus_senha if self.var_email.get() else q.entrada).focus_set()

    def _nova_var(self, nome):
        v = tk.StringVar()
        setattr(self, "v_" + nome, v)
        return v

    @property
    def focus_senha(self):
        return self._entradas_senha[0]

    def _entrar(self):
        email, senha = self.var_email.get(), self.v_senha.get()
        self._trabalhar(lambda: acesso.entrar_rapido(email, senha), self._depois_de_entrar)

    def _depois_de_entrar(self, resultado):
        sessao, erro = resultado
        if sessao is None:
            self._avisar(erro, "erro")
            self.v_senha.set("")
            self.focus_senha.focus_set()
            return
        acesso.guardar_ultimo_email(sessao.email)
        self.sessao = sessao
        self.destroy()

    def _mostrar_modo_cadastro(self):
        p = self._limpar()
        self._titulo(p, "Criar minha conta", "Depois de enviar, o administrador libera o seu acesso e escolhe o que você pode usar.")
        q = self._campo(p, "Nome completo", self._nova_var("nome"))
        self._campo(p, "E-mail", self.var_email)
        self._campo(p, "Senha (mínimo {} caracteres)".format(acesso.SENHA_MINIMA), self._nova_var("senha"), senha=True)
        self._campo(p, "Repita a senha", self._nova_var("senha2"), senha=True)
        Chip(p, "Mostrar senha", self.var_mostrar).pack(anchor="w", pady=(10, 0))
        self._mensagem(p)
        self._botao_principal(p, "Enviar cadastro", self._cadastrar)
        self._link(p, "← Voltar para entrar", self._mostrar_modo_entrar).pack(anchor="w", pady=(14, 0))
        self._centralizar()
        q.entrada.focus_set()

    def _cadastrar(self):
        if self.v_senha.get() != self.v_senha2.get():
            self._avisar("As duas senhas não são iguais.")
            return
        nome, email, senha = self.v_nome.get(), self.var_email.get(), self.v_senha.get()
        self._trabalhar(lambda: acesso.cadastrar(nome, email, senha), self._depois_de_cadastrar)

    def _depois_de_cadastrar(self, resultado):
        ok, texto = resultado
        if ok:
            self._mostrar_modo_entrar(texto, "ok")
        else:
            self._avisar(texto, "erro")

    def _mostrar_modo_esqueci(self):
        p = self._limpar()
        self._titulo(p, "Esqueci minha senha", "Vou mandar uma senha provisória para o seu e-mail. Entre com ela e depois use “Alterar minha senha”.")
        q = self._campo(p, "E-mail", self.var_email)
        self._mensagem(p)
        self._botao_principal(p, "Enviar senha provisória", self._recuperar)
        self._link(p, "← Voltar para entrar", self._mostrar_modo_entrar).pack(anchor="w", pady=(14, 0))
        self._centralizar()
        q.entrada.focus_set()

    def _recuperar(self):
        email = self.var_email.get()
        self._trabalhar(lambda: acesso.recuperar(email), self._depois_de_recuperar)

    def _depois_de_recuperar(self, resultado):
        ok, texto = resultado
        if ok:
            self._mostrar_modo_entrar(texto, "ok")
        else:
            self._avisar(texto, "erro")

    def _mostrar_modo_alterar(self):
        p = self._limpar()
        self._titulo(p, "Alterar minha senha")
        self._campo(p, "E-mail", self.var_email)
        q = self._campo(p, "Senha atual (ou a provisória)", self._nova_var("senha"), senha=True)
        self._campo(p, "Senha nova (mínimo {} caracteres)".format(acesso.SENHA_MINIMA), self._nova_var("nova"), senha=True)
        self._campo(p, "Repita a senha nova", self._nova_var("nova2"), senha=True)
        Chip(p, "Mostrar senha", self.var_mostrar).pack(anchor="w", pady=(10, 0))
        self._mensagem(p)
        self._botao_principal(p, "Alterar senha", self._alterar)
        self._link(p, "← Voltar para entrar", self._mostrar_modo_entrar).pack(anchor="w", pady=(14, 0))
        self._centralizar()
        q.entrada.focus_set()

    def _alterar(self):
        if self.v_nova.get() != self.v_nova2.get():
            self._avisar("As duas senhas novas não são iguais.")
            return
        email, atual, nova = self.var_email.get(), self.v_senha.get(), self.v_nova.get()
        self._trabalhar(lambda: acesso.alterar_senha(email, atual, nova), self._depois_de_alterar)

    def _depois_de_alterar(self, resultado):
        ok, texto = resultado
        if ok:
            self._mostrar_modo_entrar(texto, "ok")
        else:
            self._avisar(texto, "erro")


def pedir_acesso(aviso=""):
    """Mostra a tela de entrada e devolve a Sessao (ou None se a pessoa fechou a janela)."""
    janela = JanelaAcesso(aviso)
    janela.mainloop()
    return janela.sessao
