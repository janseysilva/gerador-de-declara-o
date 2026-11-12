# -*- coding: utf-8 -*-
"""
Tela "Usuários" (só para o administrador): quem pediu acesso, o que cada pessoa pode usar e até quando.

Cada pedido ao servidor roda em segundo plano (a janela não trava). Quem fala com o servidor é `acesso`.
"""
import tkinter as tk
from datetime import date

import acesso
import estoque as est
import tela_estoque
import tela_login

# Preenchidos por usar(): widgets, cores e funções do arquivo principal.
Botao = Chip = cartao = campo = AreaRolavel = None
COR_FUNDO = COR_CARTAO = COR_AZUL = COR_AZUL_ESCURO = COR_TEXTO = COR_TEXTO_FRACO = COR_BORDA = None
COR_VERDE = COR_LARANJA = None
FONTE = "Arial"
COR_VERMELHO = "#B42318"
_BASE = None

SITUACAO = {"pendente": "Aguardando liberação", "autorizado": "Liberado", "bloqueado": "Bloqueado"}


def usar(base):
    global _BASE
    _BASE = base
    for nome in ("Botao", "Chip", "cartao", "campo", "AreaRolavel", "COR_FUNDO", "COR_CARTAO", "COR_AZUL",
                 "COR_AZUL_ESCURO", "COR_TEXTO", "COR_TEXTO_FRACO", "COR_BORDA", "COR_VERDE", "COR_LARANJA", "FONTE"):
        globals()[nome] = getattr(base, nome)


def texto_data(iso):
    """'2026-11-30' -> '30/11/2026' ('' fica vazio)."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return d.strftime("%d/%m/%Y")


def texto_perfis(perfis):
    if "admin" in (perfis or []):
        return "Administrador (tudo)"
    return ", ".join(acesso.NOME_DO_PERFIL[p] for p, _ in acesso.PERFIS if p in (perfis or [])) or "—"


class DialogoSenha(tela_estoque._Dialogo):
    """Define a senha de outra pessoa (para quando o e-mail com a senha provisória não chega)."""

    def __init__(self, pai, nome, email=""):
        super().__init__(pai, "Definir senha")
        self.email = email
        self.v1, self.v2 = tk.StringVar(), tk.StringVar()
        tk.Label(self.interno, text="Definir senha de {}".format(nome), bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold"), wraplength=420, justify="left").pack(anchor="w")
        q = campo(self.interno, "Senha nova (mínimo {} caracteres)".format(acesso.SENHA_MINIMA), self.v1)
        q.pack(fill="x", pady=(10, 0))
        q.entrada.configure(show="•", width=36)
        q2 = campo(self.interno, "Repita a senha", self.v2)
        q2.pack(fill="x", pady=(8, 0))
        q2.entrada.configure(show="•")
        tk.Label(self.interno, text="Passe a senha para a pessoa. Ela pode trocar depois em “Alterar minha senha”.",
                 bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), wraplength=420, justify="left").pack(anchor="w", pady=(8, 0))
        self.botoes("Definir senha", self._ok)
        self.bind("<Return>", lambda e: self._ok())
        self._foco = q.entrada

    def _ok(self):
        if self.v1.get() != self.v2.get():
            self.erro("As duas senhas não são iguais.")
            return
        problema = acesso.problema_na_senha(self.v1.get(), self.email)
        if problema:
            self.erro(problema)
            return
        self.resultado = self.v1.get()
        self.destroy()

    def abrir(self, foco=None):
        return super().abrir(self._foco)


class JanelaUsuarios(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app)
        self.app, self.sessao = app, app.sessao
        self.title("Usuários – " + _BASE.NOME_PROGRAMA)
        self.configure(bg=COR_FUNDO)
        self.transient(app)
        largura, altura = min(1040, app.winfo_screenwidth() - 40), min(760, app.winfo_screenheight() - 80)
        self.geometry("{}x{}+{}+{}".format(largura, altura, max(app.winfo_rootx() + 30, 0), max(app.winfo_rooty() - 10, 0)))
        self.minsize(860, 520)
        self.usuarios = {}                       # e-mail -> dados da lista
        self.escolhido = None                    # e-mail da pessoa selecionada
        self._ocupado = False
        self.v_declaracoes, self.v_estoque, self.v_admin = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        self.v_prazo = tk.StringVar()
        self.v_status = tk.StringVar()
        tela_estoque._estilo_tabela(app)

        self.area = AreaRolavel(self, COR_FUNDO)
        self.area.pack(fill="both", expand=True)
        corpo = tk.Frame(self.area.miolo, bg=COR_FUNDO)
        corpo.pack(fill="both", expand=True, padx=22, pady=16)

        # 1 - lista
        externo, c, canto = cartao(corpo, "Pessoas com acesso", 1)
        externo.pack(fill="x")
        Botao(canto, "Atualizar lista", self._carregar, estilo="suave", pad_y=4, pad_x=12, raio=8,
              fonte=(FONTE, 9, "bold")).pack(side="right")
        tk.Label(c, text="Quem se cadastra no programa aparece aqui como “Aguardando liberação”. Escolha a pessoa, marque o que "
                 "ela pode usar e clique em “Liberar / salvar”.", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9),
                 anchor="w", justify="left", wraplength=900).pack(anchor="w", pady=(0, 6))
        quadro, self.tab = tela_estoque._tabela(c, [
            ("nome", "Nome", 220, "w", False), ("email", "E-mail", 260, "w", True), ("perfis", "Pode usar", 230, "w", False),
            ("sit", "Situação", 170, "w", False), ("prazo", "Acesso até", 100, "w", False)], linhas=6)
        quadro.pack(fill="x")
        self.tab.tag_configure("pendente", foreground=COR_LARANJA)
        self.tab.tag_configure("bloqueado", foreground="#9AA5B8")
        self.tab.bind("<<TreeviewSelect>>", lambda e: self._ao_selecionar())
        self.lbl_conta = tk.Label(c, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9, "bold"), anchor="w")
        self.lbl_conta.pack(anchor="w", pady=(6, 0))

        # 2 - pessoa selecionada
        externo2, c2, _ = cartao(corpo, "Pessoa selecionada", 2)
        externo2.pack(fill="x", pady=(12, 0))
        self.lbl_pessoa = tk.Label(c2, text="Clique numa pessoa da lista.", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                                   font=(FONTE, 11, "bold"), anchor="w")
        self.lbl_pessoa.pack(anchor="w")
        tk.Label(c2, text="O que ela pode usar (marque mais de um se for o caso):", bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9, "bold"), anchor="w").pack(anchor="w", pady=(8, 4))
        chips = tk.Frame(c2, bg=COR_CARTAO)
        chips.pack(fill="x")
        for texto, var in (("Declarações", self.v_declaracoes), ("Estoque (pedagógico e limpeza)", self.v_estoque),
                           ("Administrador", self.v_admin)):
            Chip(chips, texto, var).pack(side="left", padx=(0, 8))
        tk.Label(c2, text="Administrador vê tudo, cadastra as pessoas (esta tela) e mexe na Configuração.", bg=COR_CARTAO,
                 fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w").pack(anchor="w", pady=(4, 0))
        for v in (self.v_declaracoes, self.v_estoque, self.v_admin):
            v.trace_add("write", lambda *_: self._ajustar_marcas())
        linha = tk.Frame(c2, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        self.campo_prazo = campo(linha, "Acesso até (dia/mês/ano) — deixe vazio para não ter prazo", self.v_prazo, largura=14)
        self.campo_prazo.pack(side="left")
        botoes = tk.Frame(c2, bg=COR_CARTAO)
        botoes.pack(fill="x", pady=(12, 0))
        self.b_salvar = Botao(botoes, "Liberar / salvar", self._salvar, estilo="azul", pad_y=7, pad_x=18, raio=8, fonte=(FONTE, 10, "bold"))
        self.b_salvar.pack(side="left")
        self.b_bloquear = Botao(botoes, "Bloquear acesso", self._bloquear, estilo="suave", pad_y=7, pad_x=14, raio=8, fonte=(FONTE, 10, "bold"))
        self.b_bloquear.pack(side="left", padx=(8, 0))
        self.b_senha = Botao(botoes, "Definir senha...", self._definir_senha, estilo="suave", pad_y=7, pad_x=14, raio=8, fonte=(FONTE, 10, "bold"))
        self.b_senha.pack(side="left", padx=(8, 0))
        self.b_remover = Botao(botoes, "Remover conta", self._remover, estilo="tracejado", pad_y=7, pad_x=14, raio=8, fonte=(FONTE, 10, "bold"))
        self.b_remover.pack(side="right")
        self.lbl_status = tk.Label(corpo, textvariable=self.v_status, bg=COR_FUNDO, fg=COR_TEXTO_FRACO, font=(FONTE, 10),
                                   anchor="w", justify="left", wraplength=900)
        self.lbl_status.pack(fill="x", pady=(10, 0))
        self._botoes_da_pessoa = (self.b_salvar, self.b_bloquear, self.b_senha, self.b_remover)
        self._ao_selecionar()
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(50, self._carregar)

    # -- apoio ----------------------------------------------------------------------------

    def _aviso(self, texto, tipo="info"):
        self.lbl_status.configure(fg={"ok": COR_VERDE, "erro": COR_VERMELHO}.get(tipo, COR_TEXTO_FRACO))
        self.v_status.set(texto)

    def _trabalhar(self, funcao, depois, texto="Falando com o servidor..."):
        if self._ocupado:
            return
        self._ocupado = True
        self._aviso(texto)
        self.configure(cursor="watch")

        def terminou(resultado):
            self._ocupado = False
            self.configure(cursor="")
            depois(resultado)
        tela_login.em_segundo_plano(self, funcao, terminou)

    def _ajustar_marcas(self):
        if self.v_admin.get():                    # administrador vê tudo
            for v in (self.v_declaracoes, self.v_estoque):
                if not v.get():
                    v.set(True)

    # -- lista ----------------------------------------------------------------------------

    def _carregar(self):
        self._trabalhar(lambda: acesso.listar(self.sessao), self._depois_de_carregar, "Buscando a lista de pessoas...")

    def _depois_de_carregar(self, resultado, manter=None):
        lista, erro = resultado
        if lista is None:
            self._aviso(erro, "erro")
            return
        manter = manter or self.escolhido
        self.usuarios = {u["email"]: u for u in lista}
        ordem = {"pendente": 0, "autorizado": 1, "bloqueado": 2}
        lista = sorted(lista, key=lambda u: (ordem.get(u["status"], 3), u["nome"].lower()))
        tela_estoque._limpar_tabela(self.tab)
        for u in lista:
            sit = SITUACAO.get(u["status"], u["status"]) + ("  ·  pediu senha nova" if u.get("pediu_senha") else "")
            self.tab.insert("", "end", iid=u["email"], values=(
                u["nome"], u["email"], texto_perfis(u.get("perfis")) if u["status"] != "pendente" else "—", sit,
                texto_data(u.get("validade"))), tags=(u["status"],) if u["status"] in ("pendente", "bloqueado") else ())
        pend = sum(1 for u in lista if u["status"] == "pendente")
        self.lbl_conta.configure(text="{} pessoa(s)".format(len(lista)) + ("  ·  {} aguardando liberação".format(pend) if pend else ""),
                                 fg=COR_LARANJA if pend else COR_TEXTO_FRACO)
        if manter and manter in self.usuarios:
            self.tab.selection_set(manter)
        else:
            self.escolhido = None
            self._ao_selecionar()
        self._aviso("")

    def _ao_selecionar(self):
        sel = self.tab.selection()
        self.escolhido = sel[0] if sel else None
        u = self.usuarios.get(self.escolhido)
        for b in self._botoes_da_pessoa:
            b.definir_ativo(bool(u))
        if not u:
            self.lbl_pessoa.configure(text="Clique numa pessoa da lista.")
            for v in (self.v_declaracoes, self.v_estoque, self.v_admin):
                v.set(False)
            self.v_prazo.set("")
            return
        self.lbl_pessoa.configure(text="{}  ·  {}".format(u["nome"], u["email"]))
        perfis = set(u.get("perfis") or [])
        self.v_admin.set("admin" in perfis)
        self.v_declaracoes.set("declaracoes" in perfis)
        self.v_estoque.set("estoque" in perfis)
        self.v_prazo.set(texto_data(u.get("validade")))
        self.b_salvar.definir_texto("Liberar acesso" if u["status"] != "autorizado" else "Salvar")
        self.b_bloquear.definir_ativo(u["status"] != "bloqueado")

    # -- ações ----------------------------------------------------------------------------

    def _perfis_marcados(self):
        return [p for p, v in (("declaracoes", self.v_declaracoes), ("estoque", self.v_estoque), ("admin", self.v_admin)) if v.get()]

    def _depois_da_acao(self, resultado, sucesso):
        ok, resp = resultado
        if not ok:
            self._aviso(resp if isinstance(resp, str) else "Não foi possível concluir.", "erro")
            return
        self._aviso(sucesso, "ok")
        self._trabalhar(lambda: acesso.listar(self.sessao), lambda r: (self._depois_de_carregar(r), self._aviso(sucesso, "ok")),
                        sucesso)

    def _salvar(self):
        u = self.usuarios.get(self.escolhido)
        if not u:
            return
        perfis = self._perfis_marcados()
        if not perfis:
            self._aviso("Marque pelo menos um perfil (Declarações, Estoque ou Administrador).", "erro")
            return
        try:
            prazo = est.ler_data(self.v_prazo.get())
        except est.ErroEstoque as erro:
            self._aviso(str(erro), "erro")
            return
        if prazo and prazo < date.today():
            self._aviso("O prazo já passou. Digite uma data de hoje em diante (ou deixe vazio).", "erro")
            return
        nome, email = u["nome"], u["email"]
        self._trabalhar(lambda: acesso.atualizar(self.sessao, email, perfis=perfis, status="autorizado",
                                                 validade=prazo.isoformat() if prazo else ""),
                        lambda r: self._depois_da_acao(r, "Acesso de {} salvo: {}.".format(nome, texto_perfis(perfis))))

    def _bloquear(self):
        u = self.usuarios.get(self.escolhido)
        if not u:
            return
        from tkinter import messagebox
        if not messagebox.askyesno(_BASE.NOME_PROGRAMA, "Bloquear o acesso de {}?\n\nEla não vai mais conseguir entrar no programa "
                                   "(você pode liberar de novo quando quiser).".format(u["nome"]), parent=self):
            return
        nome, email = u["nome"], u["email"]
        self._trabalhar(lambda: acesso.atualizar(self.sessao, email, status="bloqueado"),
                        lambda r: self._depois_da_acao(r, "Acesso de {} bloqueado.".format(nome)))

    def _definir_senha(self):
        u = self.usuarios.get(self.escolhido)
        if not u:
            return
        nova = DialogoSenha(self, u["nome"], u["email"]).abrir()
        if not nova:
            return
        nome, email = u["nome"], u["email"]
        self._trabalhar(lambda: acesso.definir_senha(self.sessao, email, nova),
                        lambda r: self._depois_da_acao(r, "Senha de {} definida. Passe a senha para a pessoa.".format(nome)))

    def _remover(self):
        u = self.usuarios.get(self.escolhido)
        if not u:
            return
        from tkinter import messagebox
        if not messagebox.askyesno(_BASE.NOME_PROGRAMA, "Remover a conta de {} ({})?\n\nA conta é apagada de vez. Se a pessoa "
                                   "precisar de acesso de novo, ela terá de se cadastrar outra vez.".format(u["nome"], u["email"]),
                                   icon="warning", parent=self):
            return
        nome, email = u["nome"], u["email"]
        self.escolhido = None
        self._trabalhar(lambda: acesso.remover(self.sessao, email),
                        lambda r: self._depois_da_acao(r, "Conta de {} removida.".format(nome)))
