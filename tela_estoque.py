# -*- coding: utf-8 -*-
"""
Telas do estoque (material pedagógico e material de limpeza) do Declarações Escolares.

As regras ficam em estoque.py. Aqui estão só as telas, no mesmo visual do resto do
programa: a barra de abas, a pesquisa com as opções logo abaixo (como a de aluno), as
páginas Estoque, Entrada, Saída e Histórico, as janelinhas e o relatório em PDF.

Os botões, cores e blocos vêm do arquivo principal (declaracoes_escolares.py). Para não
importar um arquivo no outro em círculo, o principal entrega a si mesmo a `usar()`.
"""

import base64
import io
import math
import os
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk

import estoque as est
import leitor_nota as ln
from estoque import ErroEstoque, texto_quantidade

# Preenchidos por usar(): widgets, cores e funções do arquivo principal.
Botao = Chip = cartao = campo = rotulo = AreaRolavel = None
COR_FUNDO = COR_CARTAO = COR_AZUL = COR_AZUL_ESCURO = COR_AZUL_CLARO = None
COR_TEXTO = COR_TEXTO_FRACO = COR_BORDA = COR_LINHA = COR_VERDE = COR_LARANJA = None
FONTE = "Arial"
COR_VERMELHO = "#B42318"
_BASE = None


def usar(base):
    """Recebe o arquivo principal (os widgets e as cores dele)."""
    global _BASE
    _BASE = base
    for nome in ("Botao", "Chip", "cartao", "campo", "rotulo", "AreaRolavel", "COR_FUNDO", "COR_CARTAO",
                 "COR_AZUL", "COR_AZUL_ESCURO", "COR_AZUL_CLARO", "COR_TEXTO", "COR_TEXTO_FRACO",
                 "COR_BORDA", "COR_LINHA", "COR_VERDE", "COR_LARANJA", "FONTE"):
        globals()[nome] = getattr(base, nome)


# ---------------------------------------------------------------------------
# Abas do programa (Declarações | Estoque pedagógico | Estoque de limpeza)
# ---------------------------------------------------------------------------

class BarraAbas(tk.Canvas):
    """Abas no topo da janela. Cada aba pode ter um selo laranja (ex.: materiais abaixo do mínimo)."""

    def __init__(self, pai, abas, ao_mudar, baixa=False):
        super().__init__(pai, height=40 if baixa else 48, bg=COR_CARTAO, highlightthickness=0, bd=0)
        self._abas = abas
        self._ao_mudar = ao_mudar
        self._ativa = abas[0][0]
        self._sobre = None
        self._selos = {}
        self._areas = []
        self._fonte = tkfont.Font(family=FONTE, size=11, weight="bold")
        self._fonte_selo = tkfont.Font(family=FONTE, size=8, weight="bold")
        self.bind("<Configure>", lambda e: self._desenhar())
        self.bind("<Motion>", self._mover)
        self.bind("<Leave>", lambda e: self._pintar_sobre(None))
        self.bind("<Button-1>", self._clicar)

    @property
    def ativa(self):
        return self._ativa

    def escolher(self, chave, avisar=True):
        if chave == self._ativa:
            return
        self._ativa = chave
        self._desenhar()
        if avisar:
            self._ao_mudar(chave)

    def definir_selo(self, chave, texto):
        """Texto do selo laranja ao lado do nome da aba ('' tira o selo)."""
        if texto:
            self._selos[chave] = texto
        else:
            self._selos.pop(chave, None)
        self._desenhar()

    def _achar(self, x):
        for x1, x2, chave in self._areas:
            if x1 <= x <= x2:
                return chave
        return None

    def _mover(self, evento):
        self._pintar_sobre(self._achar(evento.x))

    def _pintar_sobre(self, chave):
        if chave != self._sobre:
            self._sobre = chave
            self.configure(cursor="hand2" if chave else "")
            self._desenhar()

    def _clicar(self, evento):
        chave = self._achar(evento.x)
        if chave:
            self.escolher(chave)

    def _desenhar(self):
        self.delete("all")
        largura, altura = max(self.winfo_width(), 1), max(self.winfo_height(), int(float(self["height"])))
        self.create_line(0, altura - 1, largura, altura - 1, fill=COR_BORDA)
        self._areas = []
        x = 22
        for chave, texto in self._abas:
            ativa = chave == self._ativa
            cor = COR_AZUL if ativa else (COR_AZUL_ESCURO if chave == self._sobre else COR_TEXTO_FRACO)
            pad = 16
            self.create_text(x + pad, altura / 2 - 1, text=texto, anchor="w", font=self._fonte, fill=cor)
            fim = x + pad + self._fonte.measure(texto)
            selo = self._selos.get(chave)
            if selo:
                larg_selo = self._fonte_selo.measure(selo) + 14
                _BASE._retangulo_arredondado(self, fim + 8, altura / 2 - 10, fim + 8 + larg_selo, altura / 2 + 8,
                                             9, fill=COR_LARANJA, outline=COR_LARANJA)
                self.create_text(fim + 8 + larg_selo / 2, altura / 2 - 1, text=selo, font=self._fonte_selo,
                                 fill="#FFFFFF")
                fim += 8 + larg_selo
            fim += pad
            if ativa:
                self.create_rectangle(x, altura - 4, fim, altura, fill=COR_AZUL, outline=COR_AZUL)
            self._areas.append((x, fim, chave))
            x = fim + 6


# ---------------------------------------------------------------------------
# Cartões grandes de navegação (Estoque | Entrada | Saída | Histórico)
# ---------------------------------------------------------------------------

# Desenho dos ícones, em traços (pontos de um quadrado de 44 x 44). O ícone é pintado junto com o
# fundo do cartão, pixel a pixel, para as pontas ficarem lisas (o Canvas do Tk não suaviza).
_TRAVESSA = [((11, 27), (11, 33)), ((11, 33), (33, 33)), ((33, 33), (33, 27))]
_GLIFOS = {
    "estoque": [((13, 14), (13.01, 14)), ((19, 14), (31, 14)), ((13, 22), (13.01, 22)), ((19, 22), (31, 22)),
                ((13, 30), (13.01, 30)), ((19, 30), (31, 30))],
    "entrada": [((22, 10), (22, 24)), ((15, 18), (22, 25)), ((22, 25), (29, 18))] + _TRAVESSA,
    "saida": [((22, 26), (22, 11)), ((15, 18), (22, 11)), ((22, 11), (29, 18))] + _TRAVESSA,
    "historico": [((22, 15), (22, 22)), ((22, 22), (28, 26))],
}


def _distancia_glifo(icone, x, y):
    """Distância (em unidades do quadrado 44x44) até o traço mais próximo do ícone."""
    d = min(_BASE._dist_segmento(x, y, a[0], a[1], b[0], b[1]) for a, b in _GLIFOS[icone])
    if icone == "historico":
        d = min(d, abs(math.hypot(x - 22, y - 22) - 11))
    return d


class CartaoAcao(tk.Canvas):
    """
    Cartão grande para trocar de página: ícone num quadradinho, o nome e uma linha de resumo
    (ex.: "12 materiais · 2 abaixo do mínimo"). O cartão da página aberta fica com borda azul.
    """

    RAIO = 12

    def __init__(self, pai, texto, icone, variavel, valor, baixa=False):
        self._altura = 66 if baixa else 78
        self._tile = 38 if baixa else 44
        self._texto, self._icone, self._var, self._valor = texto, icone, variavel, valor
        self.resumo, self._alerta = "", False
        self._sobre = False
        self._imagens, self._largura_imagens = {}, 0
        self._f_titulo = tkfont.Font(family=FONTE, size=12, weight="bold")
        self._f_resumo = tkfont.Font(family=FONTE, size=9)
        super().__init__(pai, height=self._altura, bg=pai["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self._desenhar())
        self.bind("<Enter>", lambda e: self._mudar_sobre(True))
        self.bind("<Leave>", lambda e: self._mudar_sobre(False))
        self.bind("<Button-1>", lambda e: self._var.set(self._valor))
        self._trace = variavel.trace_add("write", lambda *_: self._desenhar())
        self.bind("<Destroy>", lambda e: self._soltar())

    def _soltar(self):
        try:
            self._var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass

    def definir_resumo(self, texto, alerta=False):
        if (texto, alerta) != (self.resumo, self._alerta):
            self.resumo, self._alerta = texto, alerta
            self._desenhar()

    def _mudar_sobre(self, sobre):
        self._sobre = sobre
        self._desenhar()

    def _estado(self):
        if self._var.get() == self._valor:
            return "ativo"
        return "sobre" if self._sobre else "normal"

    def _imagem(self, largura, estado):
        if largura != self._largura_imagens:            # a janela mudou de tamanho: refaz os desenhos
            self._imagens.clear()
            self._largura_imagens = largura
        if estado in self._imagens:
            return self._imagens[estado]
        B = _BASE
        ativo = estado == "ativo"
        if ativo:
            fundo, borda, esp = "#EAF1FF", COR_AZUL, 2.0
            cor_tile, cor_glifo = COR_AZUL, "#FFFFFF"
        elif estado == "sobre":
            fundo, borda, esp = "#F6F9FF", "#9DB6E6", 1.0
            cor_tile, cor_glifo = "#D9E5FB", COR_AZUL
        else:
            fundo, borda, esp = "#FFFFFF", COR_BORDA, 1.0
            cor_tile, cor_glifo = "#E6EEFC", COR_AZUL
        fundo, borda, cor_tile, cor_glifo = B._rgb(fundo), B._rgb(borda), B._rgb(cor_tile), B._rgb(cor_glifo)
        altura, raio, tile = self._altura, self.RAIO, self._tile
        tx, ty = 16, (altura - tile) / 2
        esc = tile / 44.0
        cx, cy = largura / 2, altura / 2

        def pixel(px, py):
            x, y = px + 0.5, py + 0.5
            p = (0.0, 0.0, 0.0, 0.0)
            p = B._por_cima(p, borda, B._cobertura(B._dist_retangulo(x, y, cx, cy, cx, cy, raio)))
            p = B._por_cima(p, fundo, B._cobertura(B._dist_retangulo(x, y, cx, cy, cx - esp, cy - esp, raio - esp)))
            if tx - 2 <= x <= tx + tile + 2 and ty - 2 <= y <= ty + tile + 2:
                p = B._por_cima(p, cor_tile, B._cobertura(B._dist_retangulo(
                    x, y, tx + tile / 2, ty + tile / 2, tile / 2, tile / 2, 11 * esc)))
                d = _distancia_glifo(self._icone, (x - tx) / esc, (y - ty) / esc) * esc
                p = B._por_cima(p, cor_glifo, B._cobertura(d - 1.25 * esc))
            r, g, b, a = p
            if a <= 0:
                return b"\x00\x00\x00\x00"
            return bytes((round(r / a), round(g / a), round(b / a), round(a * 255)))

        zona_esq, zona_dir = max(raio + 2, int(tx + tile) + 3), largura - raio - 2
        linhas = bytearray()
        for py in range(altura):
            linhas.append(0)
            meio = None                                  # no miolo o pixel só muda de cima para baixo
            for px in range(largura):
                if zona_esq <= px < zona_dir:
                    if meio is None:
                        meio = pixel(zona_esq, py)
                    linhas += meio
                else:
                    linhas += pixel(px, py)
        self._imagens[estado] = tk.PhotoImage(data=base64.b64encode(B._png_de_pixels(largura, altura, linhas)))
        return self._imagens[estado]

    def _desenhar(self):
        largura = self.winfo_width()
        if largura <= 40:                                # ainda não foi desenhado na tela
            return
        self.delete("all")
        estado = self._estado()
        self.create_image(0, 0, image=self._imagem(largura, estado), anchor="nw")
        x = 16 + self._tile + 14
        meio = self._altura / 2
        cor_titulo = COR_AZUL if estado == "ativo" else COR_AZUL_ESCURO
        self.create_text(x, meio - 10, text=self._texto, anchor="w", font=self._f_titulo, fill=cor_titulo)
        texto, livre = self.resumo, largura - x - 10
        if self._f_resumo.measure(texto) > livre:       # não cabe: corta com reticências
            while texto and self._f_resumo.measure(texto + "…") > livre:
                texto = texto[:-1]
            texto = texto.rstrip(" ·") + "…"
        self.create_text(x, meio + 11, text=texto, anchor="w", font=self._f_resumo,
                         fill=COR_LARANJA if self._alerta else COR_TEXTO_FRACO)


# ---------------------------------------------------------------------------
# Pesquisa com as opções logo abaixo
# ---------------------------------------------------------------------------

class CaixaPesquisa(tk.Frame):
    """Barra de pesquisa com lupa (a mesma da pesquisa de aluno), com frase cinza de dica."""

    def __init__(self, pai, dica):
        super().__init__(pai, bg="#FFFFFF", highlightthickness=1, highlightbackground="#CFD8EA")
        self.var = tk.StringVar()
        lupa = tk.Canvas(self, width=34, height=34, bg="#FFFFFF", highlightthickness=0, bd=0)
        lupa.create_oval(10, 9, 22, 21, outline=COR_AZUL_CLARO, width=2)
        lupa.create_line(20.5, 19.5, 26, 25, fill=COR_AZUL_CLARO, width=2.4, capstyle="round")
        lupa.pack(side="left", padx=(4, 0))
        self.entrada = tk.Entry(self, textvariable=self.var, bd=0, relief="flat", font=(FONTE, 12),
                                bg="#FFFFFF", fg=COR_TEXTO, insertbackground=COR_AZUL_ESCURO, insertwidth=2,
                                insertontime=600, insertofftime=400, highlightthickness=0)
        self.entrada.pack(side="left", fill="x", expand=True, ipady=6, padx=(2, 10))
        self._dica = tk.Label(self, text=dica, bg="#FFFFFF", fg="#9AA5B8", font=(FONTE, 12), cursor="xterm")
        for w in (self, lupa, self._dica):
            w.bind("<Button-1>", lambda e: self.entrada.focus_set())
        self.entrada.bind("<FocusIn>", lambda e: self.configure(highlightbackground=COR_AZUL))
        self.entrada.bind("<FocusOut>", lambda e: self.configure(highlightbackground="#CFD8EA"))
        self.entrada.bind("<Configure>", lambda e: self._ajustar_dica())
        self.var.trace_add("write", lambda *_: self._ajustar_dica())
        self._ajustar_dica()

    def _ajustar_dica(self):
        if self.var.get():
            self._dica.place_forget()
        else:
            x = self.entrada.winfo_x() + 8 if self.entrada.winfo_x() > 0 else 48
            self._dica.place(x=x, rely=0.5, anchor="w")

    def focar(self):
        self.entrada.focus_set()


class CampoBusca(tk.Frame):
    """
    Pesquisa como a de aluno: digitou, as opções aparecem logo abaixo, clicou, escolheu.
    Também dá para usar as setas e o Enter. Se o que se procura não existe, a última opção
    cadastra na hora (quando `cadastrar` foi dado).
    """

    def __init__(self, pai, dica, buscar, descrever, ao_escolher, cadastrar=None, maximo=5):
        super().__init__(pai, bg=pai["bg"])
        self._fundo = pai["bg"]
        self._buscar, self._descrever, self._ao_escolher, self._cadastrar = buscar, descrever, ao_escolher, cadastrar
        self._max = maximo
        self._escolhido = None
        self._mudando = False
        self._linhas = []
        self._acoes = []
        self._indice = -1
        self.caixa = CaixaPesquisa(self, dica)
        self.caixa.pack(fill="x")
        self.var = self.caixa.var
        self.lista = tk.Frame(self, bg=self._fundo)
        self.var.trace_add("write", lambda *_: self._digitou())
        e = self.caixa.entrada
        e.bind("<Down>", lambda ev: self._mover(1))
        e.bind("<Up>", lambda ev: self._mover(-1))
        e.bind("<Return>", lambda ev: self._enter())
        e.bind("<KP_Enter>", lambda ev: self._enter())
        e.bind("<Escape>", lambda ev: self._fechar())

    # -- uso de fora ---------------------------------------------------------------

    @property
    def escolhido(self):
        return self._escolhido

    def focar(self):
        self.caixa.focar()

    def definir(self, item):
        """Escolhe o item sem pesquisar (ex.: carregar o destinatário de uma saída anterior)."""
        self._escolher(item)

    def limpar(self):
        self._mudando = True
        self.var.set("")
        self._mudando = False
        self._escolhido = None
        self._fechar()

    # -- por dentro ---------------------------------------------------------------

    def _digitou(self):
        if self._mudando:
            return
        if self._escolhido is not None:           # a pessoa mexeu no texto: a escolha anterior vale mais
            self._escolhido = None
            self._ao_escolher(None)
        self._mostrar()

    def _fechar(self):
        for w in self.lista.winfo_children():
            w.destroy()
        self._linhas, self._acoes, self._indice = [], [], -1
        self.lista.pack_forget()

    def _mostrar(self):
        self._fechar()
        texto = self.var.get().strip()
        if not texto:
            return
        achados = self._buscar(texto)
        self.lista.pack(fill="x", pady=(8, 0))
        for item in achados[:self._max]:
            self._linha(item)
        if len(achados) > self._max:
            tk.Label(self.lista, text="Mostrando {} de {}. Continue digitando para achar o certo.".format(
                self._max, len(achados)), bg=self._fundo, fg=COR_TEXTO_FRACO, font=(FONTE, 9)).pack(anchor="w", pady=(2, 0))
        exato = any(est.normalizar(self._descrever(i)[0]) == est.normalizar(texto) for i in achados)
        if self._cadastrar and not exato:
            self._linha_cadastrar(texto)
        elif not achados:
            tk.Label(self.lista, text="Nada encontrado com “{}”.".format(texto), bg=self._fundo,
                     fg=COR_TEXTO_FRACO, font=(FONTE, 10)).pack(anchor="w")

    def _montar_linha(self, principal, detalhe, rotulo_seta, cor_seta, acao, cor_detalhe=None):
        linha = tk.Frame(self.lista, bg=COR_LINHA, highlightthickness=1, highlightbackground=COR_BORDA, cursor="hand2")
        linha.pack(fill="x", pady=(0, 4))
        nome = tk.Label(linha, text=principal, bg=COR_LINHA, fg=COR_TEXTO, font=(FONTE, 10, "bold"),
                        anchor="w", cursor="hand2")
        nome.pack(side="left", padx=(12, 10), pady=5)
        info = tk.Label(linha, text=detalhe, bg=COR_LINHA, fg=cor_detalhe or COR_TEXTO_FRACO, font=(FONTE, 9),
                        anchor="w", cursor="hand2")
        info.pack(side="left")
        seta = tk.Label(linha, text=rotulo_seta, bg=COR_LINHA, fg=cor_seta, font=(FONTE, 9, "bold"), cursor="hand2")
        seta.pack(side="right", padx=12)
        n = len(self._linhas)
        partes = (linha, nome, info, seta)
        for w in partes:
            w.bind("<Button-1>", lambda e, n=n: self._acionar(n))
            w.bind("<Enter>", lambda e, n=n: self._pintar(n, True))
            w.bind("<Leave>", lambda e, n=n: self._pintar(n, False))
        self._linhas.append(partes)
        self._acoes.append(acao)

    def _linha(self, item):
        principal, detalhe, *resto = self._descrever(item)
        self._montar_linha(principal, detalhe, "Escolher  ›", COR_AZUL, lambda i=item: self._escolher(i),
                           cor_detalhe=resto[0] if resto else None)

    def _linha_cadastrar(self, texto):
        self._montar_linha("＋  Cadastrar “{}” como novo".format(texto), "", "Cadastrar  ›", COR_VERDE,
                           lambda t=texto: self._novo(t))

    def _pintar(self, n, sobre):
        if n >= len(self._linhas):
            return
        marcado = sobre or n == self._indice
        fundo, borda = ("#EAF1FF", "#9DB6E6") if marcado else (COR_LINHA, COR_BORDA)
        linha, nome, info, seta = self._linhas[n]
        linha.configure(bg=fundo, highlightbackground=borda)
        for w in (nome, info, seta):
            w.configure(bg=fundo)

    def _acionar(self, n):
        if n < len(self._acoes):
            self._acoes[n]()

    def _mover(self, passo):
        if not self._linhas:
            return "break"
        antigo = self._indice
        self._indice = max(0, min(len(self._linhas) - 1, self._indice + passo)) if antigo >= 0 else 0
        for n in (antigo, self._indice):
            if n >= 0:
                self._pintar(n, False)
        return "break"

    def _enter(self):
        if self._indice >= 0:
            self._acionar(self._indice)
        elif self._linhas:                          # primeiro Enter marca a primeira opção; o segundo escolhe
            self._mover(1)
        return "break"

    def _escolher(self, item):
        self._mudando = True
        self.var.set(self._descrever(item)[0])
        self.caixa.entrada.icursor("end")
        self._mudando = False
        self._escolhido = item
        self._fechar()
        self._ao_escolher(item)

    def _novo(self, texto):
        item = self._cadastrar(texto)
        if item:
            self._escolher(item)


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------

def _estilo_tabela(raiz):
    """Tabela do estoque: a linha acompanha o tamanho da letra (que o programa aumenta em 20%)."""
    estilo = ttk.Style(raiz)
    altura = tkfont.Font(family=FONTE, size=10).metrics("linespace") + 12
    estilo.configure("Estoque.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=COR_TEXTO,
                     rowheight=altura, font=(FONTE, 10), bordercolor=COR_BORDA, lightcolor=COR_BORDA,
                     darkcolor=COR_BORDA, borderwidth=1)
    estilo.configure("Estoque.Treeview.Heading", background=COR_LINHA, foreground=COR_AZUL_ESCURO,
                     font=(FONTE, 9, "bold"), relief="flat", bordercolor=COR_BORDA, lightcolor=COR_LINHA,
                     darkcolor=COR_BORDA, padding=(6, 5))
    estilo.map("Estoque.Treeview", background=[("selected", "#DCE8FF")], foreground=[("selected", COR_AZUL_ESCURO)])
    estilo.map("Estoque.Treeview.Heading", background=[("active", "#E6ECF7")])


def _tabela(pai, colunas, linhas=10):
    """Tabela com barra de rolagem. colunas: [(id, título, largura, âncora, estica)]."""
    quadro = tk.Frame(pai, bg=pai["bg"])
    arvore = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings", style="Estoque.Treeview",
                          height=linhas, selectmode="browse")
    barra = ttk.Scrollbar(quadro, orient="vertical", command=arvore.yview)
    arvore.configure(yscrollcommand=barra.set)
    for cid, titulo, largura, ancora, estica in colunas:
        arvore.heading(cid, text=titulo, anchor=ancora)
        arvore.column(cid, width=largura, minwidth=50, anchor=ancora, stretch=estica)
    arvore.tag_configure("baixo", foreground=COR_LARANJA)
    arvore.tag_configure("zerado", foreground=COR_VERMELHO)
    arvore.tag_configure("apagado", foreground="#9AA5B8")
    arvore.pack(side="left", fill="both", expand=True)
    barra.pack(side="right", fill="y")
    return quadro, arvore


def _plural(n, singular, plural):
    """1 material, 2 materiais."""
    return "{} {}".format(n, singular if n == 1 else plural)


def _limpar_tabela(arvore):
    arvore.delete(*arvore.get_children())


# ---------------------------------------------------------------------------
# Janelinhas
# ---------------------------------------------------------------------------

class _Dialogo(tk.Toplevel):
    """Janelinha no estilo do programa. Quem chama usa `wait_window` e lê `.resultado`."""

    def __init__(self, pai, titulo):
        super().__init__(pai)
        self.pai = pai.winfo_toplevel()
        self.title(titulo)
        self.configure(bg=COR_FUNDO)
        self.transient(self.pai)
        self.resizable(False, False)
        self.resultado = None
        self.corpo = tk.Frame(self, bg=COR_CARTAO, highlightthickness=1, highlightbackground=COR_BORDA)
        self.corpo.pack(fill="both", expand=True, padx=14, pady=14)
        self.interno = tk.Frame(self.corpo, bg=COR_CARTAO)
        self.interno.pack(fill="both", expand=True, padx=20, pady=16)
        self.aviso = tk.Label(self.interno, text="", bg=COR_CARTAO, fg=COR_VERMELHO, font=(FONTE, 9, "bold"),
                              anchor="w", justify="left", wraplength=420)
        self.bind("<Escape>", lambda e: self.destroy())

    def botoes(self, texto_ok, comando_ok, estilo="principal"):
        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        Botao(linha, texto_ok, comando_ok, estilo=estilo, pad_x=22, pad_y=8).pack(side="right")
        Botao(linha, "Cancelar", self.destroy, pad_y=8).pack(side="right", padx=(0, 8))

    def erro(self, texto):
        self.aviso.configure(text=texto)
        if not self.aviso.winfo_ismapped():
            self.aviso.pack(fill="x", pady=(8, 0), before=self.interno.winfo_children()[-1])

    def abrir(self, foco=None):
        self.update_idletasks()
        largura, altura = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.pai.winfo_rootx() + max((self.pai.winfo_width() - largura) // 2, 0)
        y = self.pai.winfo_rooty() + max((self.pai.winfo_height() - altura) // 3, 0)
        self.geometry("+{}+{}".format(x, y))
        self.grab_set()
        if foco is not None:
            foco.focus_set()
        self.wait_window(self)
        return self.resultado


class DialogoMaterial(_Dialogo):
    """Material novo ou editar um material (nome, unidade, ocultar)."""

    def __init__(self, pai, livro, material=None, nome_inicial=""):
        super().__init__(pai, "Editar material" if material else "Novo material")
        self.livro, self.material = livro, material
        self.var_nome = tk.StringVar(value=material["nome"] if material else nome_inicial)
        self.var_unidade = tk.StringVar(value=material["unidade"] if material else "unidade")
        self.var_oculto = tk.BooleanVar(value=bool(material and not material["ativo"]))
        tk.Label(self.interno, text="Editar material" if material else "Cadastrar material novo", bg=COR_CARTAO,
                 fg=COR_AZUL_ESCURO, font=(FONTE, 13, "bold")).pack(anchor="w")
        q = campo(self.interno, "Nome do material", self.var_nome)
        q.pack(fill="x", pady=(10, 0))
        q.entrada.configure(width=46)
        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(8, 0))
        campo(linha, "Unidade", self.var_unidade, largura=14, opcoes=est.UNIDADES).pack(side="left")
        if material:
            Chip(self.interno, "Ocultar (não usar mais este material)", self.var_oculto).pack(anchor="w", pady=(10, 0))
        self.botoes("Salvar", self._salvar)
        self.bind("<Return>", lambda e: self._salvar())
        self._foco = q.entrada

    def _salvar(self):
        try:
            if self.material:
                self.livro.editar_material(self.material["id"], nome=self.var_nome.get(), unidade=self.var_unidade.get(),
                                           minimo=self.material["minimo"], ativo=not self.var_oculto.get())
                self.resultado = self.material["id"]
            else:
                self.resultado = self.livro.cadastrar_material(self.var_nome.get(), self.var_unidade.get(), 0)
        except ErroEstoque as erro:
            self.erro(str(erro))
            return
        self.destroy()

    def abrir(self, foco=None):
        return super().abrir(self._foco)


class DialogoDestinatario(_Dialogo):
    """Pessoa ou setor que recebe o material."""

    def __init__(self, pai, livro, nome_inicial=""):
        super().__init__(pai, "Novo destinatário")
        self.livro = livro
        self.var_nome = tk.StringVar(value=nome_inicial)
        self.var_setor = tk.StringVar()
        tk.Label(self.interno, text="Cadastrar quem recebe o material", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        q = campo(self.interno, "Nome", self.var_nome)
        q.pack(fill="x", pady=(10, 0))
        q.entrada.configure(width=46)
        campo(self.interno, "Setor, turma ou cargo (opcional)", self.var_setor,
              opcoes=["Cozinha", "Secretaria", "Direção", "Coordenação pedagógica", "Limpeza"]).pack(fill="x", pady=(8, 0))
        self.botoes("Cadastrar", self._salvar)
        self.bind("<Return>", lambda e: self._salvar())
        self._foco = q.entrada

    def _salvar(self):
        try:
            self.resultado = self.livro.cadastrar_destinatario(self.var_nome.get(), self.var_setor.get())
        except ErroEstoque as erro:
            self.erro(str(erro))
            return
        self.destroy()

    def abrir(self, foco=None):
        return super().abrir(self._foco)


class DialogoEstorno(_Dialogo):
    def __init__(self, pai, mov):
        super().__init__(pai, "Estornar registro")
        self.var_motivo = tk.StringVar()
        tk.Label(self.interno, text="Estornar {} de {}".format("entrada" if mov["tipo"] == "entrada" else "saída",
                                                                est.texto_data_hora(mov["quando"])),
                 bg=COR_CARTAO, fg=COR_AZUL_ESCURO, font=(FONTE, 13, "bold")).pack(anchor="w")
        tk.Label(self.interno, text=mov["resumo"], bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 10), anchor="w",
                 justify="left", wraplength=460).pack(anchor="w", pady=(6, 0))
        tk.Label(self.interno, text="O estoque volta ao que era antes. O registro continua no histórico, marcado como "
                 "estornado.", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w", justify="left",
                 wraplength=460).pack(anchor="w", pady=(6, 0))
        q = campo(self.interno, "Motivo (opcional)", self.var_motivo)
        q.pack(fill="x", pady=(10, 0))
        self.botoes("Estornar", lambda: self._ok(), estilo="azul")
        self.bind("<Return>", lambda e: self._ok())
        self._foco = q.entrada

    def _ok(self):
        self.resultado = self.var_motivo.get().strip()
        self.destroy()

    def abrir(self, foco=None):
        return super().abrir(self._foco)


class DialogoQuantidade(_Dialogo):
    """Muda a quantidade de um material que está na lista (antes de registrar). `maximo` vale na saída."""

    def __init__(self, pai, material, quantidade, maximo=None):
        super().__init__(pai, "Editar quantidade")
        self.material, self.maximo = material, maximo
        self.var = tk.StringVar(value=texto_quantidade(quantidade))
        tk.Label(self.interno, text="Editar quantidade", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        tk.Label(self.interno, text=material["nome"], bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 11, "bold"),
                 anchor="w", justify="left", wraplength=420).pack(anchor="w", pady=(8, 0))
        if maximo is not None:
            tk.Label(self.interno, text="Em estoque: {} {}".format(texto_quantidade(maximo), material["unidade"]),
                     bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9)).pack(anchor="w")
        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(8, 0))
        q = campo(linha, "Quantidade", self.var, largura=12)
        q.pack(side="left")
        tk.Label(linha, text=material["unidade"], bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 10, "bold")).pack(side="left", padx=(8, 0), pady=(18, 0))
        self.botoes("Salvar", self._salvar)
        self.bind("<Return>", lambda e: self._salvar())
        self._foco = q.entrada

    def _salvar(self):
        try:
            valor = est.ler_quantidade(self.var.get())
        except ErroEstoque as erro:
            self.erro(str(erro))
            return
        if self.maximo is not None and valor > self.maximo + 1e-9:
            self.erro("Só há {} {} em estoque.".format(texto_quantidade(self.maximo), self.material["unidade"]))
            return
        self.resultado = valor
        self.destroy()

    def abrir(self, foco=None):
        self._foco.selection_range(0, "end")
        return super().abrir(self._foco)


class DialogoImportarSaida(_Dialogo):
    """Escolhe uma saída anterior para repetir os mesmos materiais."""

    def __init__(self, pai, livro, destinatario=None):
        super().__init__(pai, "Importar saída anterior")
        self.livro, self.destinatario = livro, destinatario
        self.var_so_dele = tk.BooleanVar(value=bool(destinatario))
        tk.Label(self.interno, text="Repetir uma saída anterior", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        tk.Label(self.interno, text="Escolha a saída. Os materiais dela vão para a lista e você confere as quantidades "
                 "antes de registrar.", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w",
                 justify="left", wraplength=640).pack(anchor="w", pady=(4, 8))
        if destinatario:
            Chip(self.interno, "Só as saídas de {}".format(destinatario["nome"]), self.var_so_dele).pack(anchor="w", pady=(0, 8))
            self.var_so_dele.trace_add("write", lambda *_: self._preencher())
        quadro, self.tabela = _tabela(self.interno, [
            ("quando", "Data e hora", 160, "w", False), ("dest", "Para", 200, "w", False),
            ("itens", "Materiais", 560, "w", True)], linhas=9)
        quadro.pack(fill="both", expand=True)
        self.resizable(True, True)                  # dá para alargar a janela e ver a lista inteira
        self.minsize(760, 420)
        self.tabela.bind("<Double-1>", lambda e: self._ok())
        self._movs = {}
        self._preencher()
        self.botoes("Usar estes materiais", self._ok)

    def _preencher(self):
        _limpar_tabela(self.tabela)
        self._movs = {}
        for mov in self.livro.movimentos("saida", incluir_estornados=False):
            if self.var_so_dele.get() and self.destinatario and (mov["destinatario"] or {}).get("id") != self.destinatario["id"]:
                continue
            self._movs[mov["id"]] = mov
            dest = mov["destinatario"]
            self.tabela.insert("", "end", iid=mov["id"], values=(
                est.texto_data_hora(mov["quando"]), dest["nome"] if dest else "", mov["resumo"]))
        filhos = self.tabela.get_children()
        if filhos:
            self.tabela.selection_set(filhos[0])

    def _ok(self):
        sel = self.tabela.selection()
        if not sel:
            self.erro("Escolha uma saída da lista.")
            return
        self.resultado = self._movs[sel[0]]
        self.destroy()


class DialogoLendoNota(_Dialogo):
    """Mostra o andamento enquanto o PDF da nota fiscal é lido (leva 1 a 2 minutos)."""

    def __init__(self, pai, leitor, caminho):
        super().__init__(pai, "Lendo a nota fiscal")
        self.cancelado = False
        self.fila = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.bind("<Escape>", lambda e: self._cancelar())
        tk.Label(self.interno, text="Lendo a nota fiscal…", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        tk.Label(self.interno, text=os.path.basename(caminho), bg=COR_CARTAO, fg=COR_TEXTO_FRACO,
                 font=(FONTE, 9)).pack(anchor="w", pady=(2, 10))
        self.var_texto = tk.StringVar(value="Abrindo o PDF…")
        tk.Label(self.interno, textvariable=self.var_texto, bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 10),
                 anchor="w", justify="left", wraplength=440).pack(anchor="w")
        self.barra = ttk.Progressbar(self.interno, mode="indeterminate", length=440)
        self.barra.pack(fill="x", pady=(10, 0))
        self.barra.start(14)
        tk.Label(self.interno, text="O programa olha a imagem da nota como uma pessoa olharia. Pode levar um ou dois "
                 "minutos; é só esperar.", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w",
                 justify="left", wraplength=440).pack(anchor="w", pady=(10, 0))
        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(12, 0))
        Botao(linha, "Cancelar", self._cancelar, pad_y=8).pack(side="right")
        threading.Thread(target=self._trabalhar, args=(leitor, caminho), daemon=True).start()
        self.after(150, self._olhar)

    def _trabalhar(self, leitor, caminho):
        """Roda em segundo plano (nunca mexe na tela: só põe recados na fila)."""
        try:
            resultado = leitor.ler(caminho, progresso=lambda texto, a, b: self.fila.put(("andamento", texto)),
                                   cancelado=lambda: self.cancelado)
            self.fila.put(("pronto", resultado))
        except ln.ErroLeitura as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:                                  # qualquer falha do leitor vira aviso
            self.fila.put(("erro", "Não foi possível ler a nota: {}".format(erro)))

    def _olhar(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "andamento":
                    self.var_texto.set(dado)
                elif tipo == "pronto":
                    self.resultado = dado
                    self._fechar_leitura()
                    return
                else:
                    self.resultado = {"erro": dado}
                    self._fechar_leitura()
                    return
        except queue.Empty:
            pass
        if not self.cancelado:
            self.after(150, self._olhar)

    def _fechar_leitura(self):
        self.barra.stop()
        self.destroy()

    def _cancelar(self):
        self.cancelado = True
        self.resultado = None
        self.destroy()


class DialogoItemNota(_Dialogo):
    """Corrige um produto lido da nota (nome, quantidade, unidade) antes de ele entrar na lista."""

    def __init__(self, pai, item):
        super().__init__(pai, "Corrigir produto da nota")
        self.item = item
        self.var_nome = tk.StringVar(value=item["descricao"])
        self.var_qtd = tk.StringVar(value=texto_quantidade(item["quantidade"]) if item["quantidade"] else "")
        self.var_unidade = tk.StringVar(value=item["unidade"])
        tk.Label(self.interno, text="Corrigir produto da nota", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        q = campo(self.interno, "Nome do material", self.var_nome)
        q.pack(fill="x", pady=(10, 0))
        q.entrada.configure(width=54)
        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(8, 0))
        self.campo_qtd = campo(linha, "Quantidade", self.var_qtd, largura=12)
        self.campo_qtd.pack(side="left")
        campo(linha, "Unidade", self.var_unidade, largura=14, opcoes=est.UNIDADES).pack(side="left", padx=(12, 0))
        self.botoes("Salvar", self._salvar)
        self.bind("<Return>", lambda e: self._salvar())
        self._foco = self.campo_qtd.entrada if not item["quantidade"] else q.entrada

    def _salvar(self):
        nome = est.limpar_nome(self.var_nome.get())
        if not nome:
            self.erro("Digite o nome do material.")
            return
        try:
            quantidade = est.ler_quantidade(self.var_qtd.get())
        except ErroEstoque as erro:
            self.erro(str(erro))
            return
        self.item.update(descricao=nome, quantidade=quantidade, avisos=[], conferido=True,
                         unidade=est.limpar_nome(self.var_unidade.get()) or "unidade")
        self.resultado = True
        self.destroy()

    def abrir(self, foco=None):
        return super().abrir(self._foco)


class DialogoNotaLida(_Dialogo):
    """
    A lista lida da nota fiscal, para a pessoa CONFERIR antes de entrar no estoque: o leitor de texto
    erra de vez em quando, então embaixo aparece a imagem da linha da nota do produto escolhido.
    """

    def __init__(self, pai, livro, resultado):
        super().__init__(pai, "Conferir a nota lida")
        self.livro, self.itens, self.nota = livro, resultado["itens"], resultado["nota"]
        self._existentes = livro.materiais(incluir_ocultos=True)
        for item in self.itens:
            item["incluir"] = bool(item["descricao"]) and item["quantidade"] is not None
        self.resizable(True, True)
        self.minsize(900, 520)
        tela_baixa = self.winfo_screenheight() < 900

        tk.Label(self.interno, text="Conferir a nota lida", bg=COR_CARTAO, fg=COR_AZUL_ESCURO,
                 font=(FONTE, 13, "bold")).pack(anchor="w")
        partes = [p for p in (self.nota.get("fornecedor"), "Nota " + self.nota["numero"] if self.nota.get("numero") else "",
                              self.nota.get("emissao")) if p]
        self.lbl_resumo = tk.Label(self.interno, text="", bg=COR_CARTAO, fg=COR_TEXTO, font=(FONTE, 10, "bold"),
                                   anchor="w", justify="left")
        self.lbl_resumo.pack(anchor="w", pady=(4, 0))
        self._cabecalho = "  ·  ".join(partes)
        tk.Label(self.interno, text="O leitor pode errar. Clique num produto para ver a linha da nota logo abaixo e "
                 "compare. Corrija o que estiver errado (dois cliques) e tire o que não deve entrar no estoque.",
                 bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9), anchor="w", justify="left",
                 wraplength=1000).pack(anchor="w", pady=(2, 8))
        quadro, self.tabela = _tabela(self.interno, [
            ("entra", "Entra?", 70, "center", False), ("nome", "Material", 430, "w", True),
            ("unidade", "Unidade", 90, "w", False), ("qtd", "Quantidade", 100, "center", False),
            ("obs", "Observação", 420, "w", False)], linhas=8 if tela_baixa else 11)
        quadro.pack(fill="both", expand=True)
        tk.Label(self.interno, text="Como está na nota (linha do produto escolhido):", bg=COR_CARTAO,
                 fg=COR_TEXTO_FRACO, font=(FONTE, 9, "bold"), anchor="w").pack(anchor="w", pady=(8, 2))
        self.tela = tk.Canvas(self.interno, height=50, bg="#FFFFFF", highlightthickness=1,
                              highlightbackground=COR_BORDA)
        self.tela.pack(fill="x")
        self._foto = None

        linha = tk.Frame(self.interno, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        Botao(linha, "Corrigir", self._editar, estilo="azul", pad_y=7, pad_x=16, raio=8,
              fonte=(FONTE, 10, "bold")).pack(side="left")
        Botao(linha, "Entra / não entra", self._alternar, estilo="suave", pad_y=7, pad_x=16, raio=8,
              fonte=(FONTE, 10, "bold")).pack(side="left", padx=(8, 0))
        self.botao_ok = Botao(linha, "Adicionar à lista de entrada", self._ok, estilo="principal", pad_x=22, pad_y=8)
        self.botao_ok.pack(side="right")
        Botao(linha, "Cancelar", self.destroy, pad_y=8).pack(side="right", padx=(0, 8))

        self.tabela.bind("<<TreeviewSelect>>", lambda e: self._mostrar_linha())
        self.tabela.bind("<Double-1>", lambda e: self._editar())
        self.tabela.bind("<space>", lambda e: (self._alternar(), "break")[1])
        self._preencher()
        filhos = self.tabela.get_children()
        if filhos:
            self.tabela.selection_set(filhos[0])
        self.bind("<Escape>", lambda e: self.destroy())

    # -- a lista ---------------------------------------------------------------------

    def _situacao(self, item):
        existente = ln.achar_igual(item["descricao"], self._existentes)
        partes = []
        if existente:
            partes.append("já cadastrado" + (" (oculto)" if not existente.get("ativo", True) else ""))
            if existente["unidade"] != item["unidade"]:
                partes.append("no estoque a unidade é " + existente["unidade"])
        else:
            partes.append("material novo")
        if item["avisos"]:
            partes.append("CONFERIR: " + ", ".join(item["avisos"]))
        return " · ".join(partes)

    def _valores(self, item):
        qtd = texto_quantidade(item["quantidade"]) if item["quantidade"] else "?"
        return ("Sim" if item["incluir"] else "Não", item["descricao"] or "(sem nome)", item["unidade"], qtd,
                self._situacao(item))

    def _tags(self, item):
        if not item["incluir"]:
            return ("apagado",)
        return ("baixo",) if item["avisos"] else ()

    def _preencher(self):
        _limpar_tabela(self.tabela)
        for n, item in enumerate(self.itens):
            self.tabela.insert("", "end", iid=str(n), values=self._valores(item), tags=self._tags(item))
        self._atualizar_resumo()

    def _atualizar_linha(self, n):
        item = self.itens[n]
        self.tabela.item(str(n), values=self._valores(item), tags=self._tags(item))
        self._atualizar_resumo()

    def _atualizar_resumo(self):
        entram = sum(1 for i in self.itens if i["incluir"])
        conferir = sum(1 for i in self.itens if i["incluir"] and i["avisos"])
        texto = _plural(len(self.itens), "produto lido", "produtos lidos")
        if conferir:
            texto += " · {} para conferir (em laranja)".format(conferir)
        self.lbl_resumo.configure(text=(self._cabecalho + "   —   " if self._cabecalho else "") + texto)
        self.botao_ok.definir_texto("Adicionar {} à lista de entrada".format(entram) if entram else
                                    "Adicionar à lista de entrada")
        self.botao_ok.definir_ativo(entram > 0)

    def _selecionado(self):
        sel = self.tabela.selection()
        return int(sel[0]) if sel else None

    # -- a imagem da linha da nota -----------------------------------------------------

    def _mostrar_linha(self):
        n = self._selecionado()
        self.tela.delete("all")
        if n is None or self.itens[n].get("imagem") is None:
            return
        from PIL import Image
        imagem = self.itens[n]["imagem"]
        largura = max(self.tela.winfo_width() - 10, 600)
        if imagem.width > largura:
            imagem = imagem.resize((largura, max(1, round(imagem.height * largura / imagem.width))), Image.LANCZOS)
        buf = io.BytesIO()
        imagem.convert("L").save(buf, "PNG")
        self._foto = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.tela.configure(height=imagem.height + 10)
        self.tela.create_image(5, 5, image=self._foto, anchor="nw")

    # -- ações -------------------------------------------------------------------------

    def _alternar(self):
        n = self._selecionado()
        if n is None:
            return
        item = self.itens[n]
        if not item["incluir"] and (item["quantidade"] is None or not item["descricao"]):
            self.erro("Corrija o produto (nome e quantidade) antes de colocá-lo na lista.")
            return
        item["incluir"] = not item["incluir"]
        self._atualizar_linha(n)

    def _editar(self):
        n = self._selecionado()
        if n is None:
            return
        item = self.itens[n]
        if DialogoItemNota(self, item).abrir():
            item["incluir"] = True
            self._atualizar_linha(n)
            self.tabela.selection_set(str(n))
            self.tabela.see(str(n))

    def _ok(self):
        escolhidos = [i for i in self.itens if i["incluir"]]
        if not escolhidos:
            self.erro("Nenhum produto marcado para entrar.")
            return
        self.resultado = escolhidos
        self.destroy()

    def abrir(self, foco=None):
        # janela grande, centralizada na tela (a lista é comprida)
        self.update_idletasks()
        largura = min(max(self.winfo_reqwidth(), 1100), self.winfo_screenwidth() - 60)
        altura = min(self.winfo_reqheight() + 10, self.winfo_screenheight() - 90)
        x = max((self.winfo_screenwidth() - largura) // 2, 0)
        y = max((self.winfo_screenheight() - altura) // 3, 0)
        self.geometry("{}x{}+{}+{}".format(largura, altura, x, y))
        self.grab_set()
        self.tabela.focus_set()
        self.wait_window(self)
        return self.resultado


# ---------------------------------------------------------------------------
# O painel de um estoque (uma aba)
# ---------------------------------------------------------------------------

class PainelEstoque(tk.Frame):
    """Uma aba de estoque: Estoque (relatório), Entrada, Saída e Histórico."""

    def __init__(self, pai, app, livro, titulo, chave, baixa=False, ao_mudar=None):
        super().__init__(pai, bg=COR_FUNDO)
        self.app, self.livro, self.titulo, self.chave = app, livro, titulo, chave
        self.baixa = baixa
        self._ao_mudar = ao_mudar or (lambda: None)
        _estilo_tabela(app)
        self.area = AreaRolavel(self, COR_FUNDO)
        self.area.pack(fill="both", expand=True)
        self.corpo = tk.Frame(self.area.miolo, bg=COR_FUNDO)
        self.corpo.pack(fill="both", expand=True, padx=26, pady=(12, 8) if baixa else (16, 12))

        self.var_pagina = tk.StringVar(value="estoque")
        self.var_status = tk.StringVar()
        self.ent_itens, self.sai_itens = [], []
        self.mov_atual = None

        # Quatro cartões grandes no alto: o da página aberta fica com borda azul e cada um mostra um resumo.
        topo = tk.Frame(self.corpo, bg=COR_FUNDO)
        topo.pack(fill="x", pady=(0, 10 if baixa else 14))
        self.cartoes = {}
        for col, (chave, texto, icone) in enumerate((("estoque", "Estoque", "estoque"),
                                                     ("entrada", "Entrada de material", "entrada"),
                                                     ("saida", "Saída de material", "saida"),
                                                     ("historico", "Histórico", "historico"))):
            topo.columnconfigure(col, weight=1, uniform="cartoes")
            cartao_acao = CartaoAcao(topo, texto, icone, self.var_pagina, chave, baixa=baixa)
            cartao_acao.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
            self.cartoes[chave] = cartao_acao

        self.paginas = {}
        self.paginas["estoque"] = self._montar_estoque()
        self.paginas["entrada"] = self._montar_entrada()
        self.paginas["saida"] = self._montar_saida()
        self.paginas["historico"] = self._montar_historico()
        self.rodape = tk.Frame(self.corpo, bg=COR_FUNDO)
        self.rodape.pack(fill="x", pady=(8, 0))
        Botao(self.rodape, "Atualizar", self.atualizar, estilo="suave", fonte=(FONTE, 9, "bold"), pad_y=4, pad_x=12,
              raio=8).pack(side="right", padx=(12, 0))
        self.lbl_status = tk.Label(self.rodape, textvariable=self.var_status, bg=COR_FUNDO, fg=COR_TEXTO_FRACO,
                                   font=(FONTE, 10), anchor="w", justify="left", wraplength=1000)
        self.lbl_status.pack(side="left", fill="x", expand=True)
        self.var_pagina.trace_add("write", lambda *_: self._mostrar_pagina())
        self._mostrar_pagina()

    # -- ligação com a janela principal ---------------------------------------------

    def ao_mostrar(self):
        """A aba apareceu: lê de novo o que os outros computadores registraram."""
        self.livro.recarregar()
        self._atualizar_tudo()
        self._focar_pagina()

    def atualizar(self):
        self.livro.recarregar()
        self._atualizar_tudo()
        self._aviso("Estoque atualizado.", "ok")

    def pendentes(self):
        """Materiais já colocados numa lista de entrada ou saída que ainda não foi registrada."""
        return len(self.ent_itens) + len(self.sai_itens)

    def _atualizar_resumo(self):
        """Linha de resumo de cada cartão do alto: o que está pendente e como está o estoque."""
        resumo = self.livro.resumo()
        # Sem aviso laranja aqui: o que está zerado ou abaixo do mínimo já aparece colorido na lista da página.
        self.cartoes["estoque"].definir_resumo(_plural(resumo["materiais"], "material", "materiais"))
        if self.ent_itens:
            self.cartoes["entrada"].definir_resumo(
                _plural(len(self.ent_itens), "material", "materiais") + " esperando entrada", alerta=True)
        else:
            self.cartoes["entrada"].definir_resumo("Registrar o que chegou")
        if self.sai_itens:
            self.cartoes["saida"].definir_resumo(
                _plural(len(self.sai_itens), "material", "materiais") + " esperando saída", alerta=True)
        else:
            self.cartoes["saida"].definir_resumo("Dar baixa no estoque")
        self.cartoes["historico"].definir_resumo(_plural(len(self.livro.movimentos()), "registro", "registros"))
        self._ao_mudar()                      # o selo da aba acompanha o que está pendente

    def _atualizar_tudo(self):
        self._preencher_estoque()
        self._preencher_historico()
        self._atualizar_lista_entrada()
        self._atualizar_lista_saida()
        self._atualizar_resumo()

    def _aviso(self, texto, tipo="info"):
        cor = {"ok": COR_VERDE, "erro": COR_LARANJA}.get(tipo, COR_TEXTO_FRACO)
        self.lbl_status.configure(fg=cor)
        self.var_status.set(texto)

    def _mostrar_pagina(self):
        chave = self.var_pagina.get()
        for k, f in self.paginas.items():
            f.pack_forget()
        self.paginas[chave].pack(fill="x", before=self.rodape)
        self.var_status.set("")
        self._atualizar_tudo()
        self._focar_pagina()

    def _focar_pagina(self):
        alvo = {"estoque": getattr(self, "pesq_estoque", None), "entrada": getattr(self, "busca_ent", None),
                "saida": getattr(self, "busca_dest", None), "historico": getattr(self, "pesq_hist", None)}.get(self.var_pagina.get())
        if alvo is not None:
            self.after(60, alvo.focar)

    # -- página: Estoque (o relatório) ---------------------------------------------

    def _montar_estoque(self):
        f = tk.Frame(self.corpo, bg=COR_FUNDO)
        externo, c, canto = cartao(f, "Materiais em estoque", 1)
        externo.pack(fill="x")
        self.var_ocultos = tk.BooleanVar(value=False)
        Chip(canto, "Mostrar ocultos", self.var_ocultos).pack(side="right")
        self.var_ocultos.trace_add("write", lambda *_: self._preencher_estoque())
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 8))
        self.pesq_estoque = CaixaPesquisa(linha, "Filtrar a lista pelo nome do material")
        self.pesq_estoque.pack(side="left", fill="x", expand=True)
        self.pesq_estoque.var.trace_add("write", lambda *_: self._preencher_estoque())
        Botao(linha, "＋  Novo material", self._novo_material_estoque, estilo="tracejado", pad_y=8).pack(side="left", padx=(10, 0))
        Botao(linha, "Relatório em PDF", self._relatorio_pdf, estilo="azul", pad_y=8).pack(side="left", padx=(8, 0))
        quadro, self.tab_estoque = _tabela(c, [
            ("nome", "Material", 520, "w", True), ("unidade", "Unidade", 140, "w", False),
            ("saldo", "Em estoque", 160, "center", False)], linhas=7 if self.baixa else 10)
        quadro.pack(fill="x")
        self.tab_estoque.bind("<Double-1>", lambda e: self._editar_material())
        rodape = tk.Frame(c, bg=COR_CARTAO)
        rodape.pack(fill="x", pady=(8, 0))
        tk.Label(rodape, text="Clique duas vezes num material para editar o nome ou a unidade.",
                 bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9)).pack(side="left")
        Botao(rodape, "Editar material", self._editar_material, estilo="suave", pad_y=5, pad_x=14, raio=8,
              fonte=(FONTE, 9, "bold")).pack(side="right")
        return f

    def _preencher_estoque(self):
        _limpar_tabela(self.tab_estoque)
        filtro = est.normalizar(self.pesq_estoque.var.get())
        n = 0
        for m in self.livro.materiais(incluir_ocultos=self.var_ocultos.get()):
            if filtro and not all(t in est.normalizar(m["nome"]) for t in filtro.split()):
                continue
            nome, tags = (m["nome"], ()) if m["ativo"] else (m["nome"] + "  (oculto)", ("apagado",))
            self.tab_estoque.insert("", "end", iid=m["id"], values=(
                nome, m["unidade"], texto_quantidade(m["saldo"])), tags=tags)
            n += 1
        if not n and not filtro:
            self.tab_estoque.insert("", "end", values=("Nenhum material cadastrado ainda. Use “Novo material” ou "
                                                       "faça uma entrada.", "", ""), tags=("apagado",))

    def _novo_material_estoque(self):
        novo = DialogoMaterial(self, self.livro).abrir()
        if novo:
            self._atualizar_tudo()
            self._aviso("Material cadastrado. Faça uma entrada para colocar a quantidade no estoque.", "ok")

    def _editar_material(self):
        sel = self.tab_estoque.selection()
        if not sel or not self.livro.material(sel[0]):
            self._aviso("Clique num material da lista para editar.", "erro")
            return
        if DialogoMaterial(self, self.livro, material=self.livro.material(sel[0])).abrir():
            self._atualizar_tudo()
            self._aviso("Material atualizado.", "ok")

    def _relatorio_pdf(self):
        linhas = self.livro.materiais()
        if not linhas:
            self._aviso("Ainda não há materiais para o relatório.", "erro")
            return
        agora = datetime.now()
        cfg = self.app.cfg
        pasta = os.path.join(cfg.get("pasta_saida") or os.path.join(_BASE.pasta_documentos(), "Declarações Escolares"),
                             "Estoque")
        logo = os.path.join(_BASE.pasta_dados(), _BASE.ARQ_LOGO)
        logo = logo if os.path.exists(logo) else ""
        caminho = os.path.join(pasta, _BASE.nome_arquivo_seguro("Relatório de estoque - {} - {}.pdf".format(
            self.titulo.replace("Estoque ", "").replace("de ", ""), agora.strftime("%Y-%m-%d %H%M"))))
        try:
            os.makedirs(pasta, exist_ok=True)
            gerar_relatorio_pdf(caminho, cfg, "RELATÓRIO DE ESTOQUE", self.titulo, linhas, logo, agora)
        except PermissionError:
            self._aviso("O arquivo está aberto em outro programa. Feche-o e tente de novo.", "erro")
            return
        except Exception as erro:
            self._aviso("Não foi possível gerar o relatório: {}".format(erro), "erro")
            return
        _BASE.abrir_arquivo(caminho)
        self.app.ultimo_arquivo = caminho
        self._aviso("Relatório gerado e aberto para imprimir: {}".format(os.path.basename(caminho)), "ok")

    # -- pesquisa de material e de destinatário (comuns às páginas) ---------------------

    def _descrever_material(self, m):
        saldo = "em estoque: {} {}".format(texto_quantidade(m["saldo"]), m["unidade"])
        cor = {"zerado": COR_VERMELHO, "baixo": COR_LARANJA}.get(m["situacao"])
        return m["nome"], "{}  ·  {}".format(m["unidade"], saldo), cor

    def _descrever_destinatario(self, d):
        return d["nome"], d["setor"]

    def _cadastrar_material_pelo_campo(self, texto):
        mid = DialogoMaterial(self, self.livro, nome_inicial=texto.strip()).abrir()
        return self.livro.material(mid) if mid else None

    def _cadastrar_destinatario_pelo_campo(self, texto):
        did = DialogoDestinatario(self, self.livro, nome_inicial=texto.strip()).abrir()
        return self.livro.destinatario(did) if did else None

    def _campo_quantidade(self, pai, variavel, ao_enter):
        q = campo(pai, "Quantidade", variavel, largura=10)
        q.entrada.bind("<Return>", lambda e: ao_enter())
        return q

    # -- página: Entrada ---------------------------------------------------------------

    def _montar_entrada(self):
        f = tk.Frame(self.corpo, bg=COR_FUNDO)
        f.columnconfigure(0, weight=5, uniform="e")
        f.columnconfigure(1, weight=6, uniform="e")
        externo, c1, _ = cartao(f, "Material que chegou", 1)
        externo.grid(row=0, column=0, sticky="new", padx=(0, 8))
        self.ent_material = None
        self.busca_ent = CampoBusca(c1, "Digite o nome do material (ou parte dele)",
                                    self.livro_buscar_materiais, self._descrever_material, self._ent_escolheu,
                                    cadastrar=self._cadastrar_material_pelo_campo)
        self.busca_ent.pack(fill="x", pady=(4, 0))
        linha = tk.Frame(c1, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        self.var_ent_qtd = tk.StringVar()
        q = self._campo_quantidade(linha, self.var_ent_qtd, self._ent_adicionar)
        q.pack(side="left")
        self.ent_qtd_entrada = q.entrada
        self.lbl_ent_unidade = tk.Label(linha, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 10, "bold"))
        self.lbl_ent_unidade.pack(side="left", padx=(8, 0), pady=(18, 0))
        self.var_ent_obs = tk.StringVar()
        q = campo(c1, "Observação (fornecedor, nota fiscal...) – opcional", self.var_ent_obs)
        q.pack(fill="x", pady=(8, 0))
        botoes = tk.Frame(c1, bg=COR_CARTAO)
        botoes.pack(fill="x", pady=(12, 0))
        Botao(botoes, "Adicionar à lista  ›", self._ent_adicionar, estilo="azul", pad_y=8).pack(side="left")
        Botao(botoes, "Ler nota fiscal (PDF)", self._ent_ler_pdf, estilo="tracejado", pad_y=8).pack(side="left", padx=(10, 0))

        externo, c2, canto = cartao(f, "Lista desta entrada", 2)
        externo.grid(row=0, column=1, sticky="new", padx=(8, 0))
        quadro, self.tab_ent = _tabela(c2, [
            ("nome", "Material", 300, "w", True), ("qtd", "Quantidade", 100, "center", False),
            ("unidade", "Unidade", 90, "w", False)], linhas=5 if self.baixa else 6)
        quadro.pack(fill="x", pady=(4, 8))
        linha = tk.Frame(c2, bg=COR_CARTAO)
        linha.pack(fill="x")
        self.tab_ent.bind("<Double-1>", lambda e: self._editar_quantidade("entrada"))
        Botao(linha, "Editar quantidade", lambda: self._editar_quantidade("entrada"), estilo="azul", pad_y=5,
              pad_x=14, raio=8, fonte=(FONTE, 9, "bold")).pack(side="left", padx=(0, 8))
        Botao(linha, "Tirar da lista", lambda: self._tirar(self.tab_ent, self.ent_itens, self._atualizar_lista_entrada),
              estilo="suave", pad_y=5, pad_x=14, raio=8, fonte=(FONTE, 9, "bold")).pack(side="left")
        Botao(linha, "Limpar a lista", lambda: self._limpar_lista("entrada"), estilo="tracejado", pad_y=5, pad_x=14,
              raio=8, fonte=(FONTE, 9, "bold")).pack(side="left", padx=(8, 0))
        self.lbl_ent_total = tk.Label(linha, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9))
        self.lbl_ent_total.pack(side="right")
        Botao(c2, "▶   Registrar entrada", self._ent_registrar, estilo="principal", fonte=(FONTE, 13, "bold"),
              pad_y=10, raio=12).pack(fill="x", pady=(10, 0))
        return f

    def livro_buscar_materiais(self, texto):
        return self.livro.buscar_materiais(texto)

    def _ent_ler_pdf(self):
        """Lê o PDF (escaneado ou não) de uma nota fiscal e põe os produtos na lista de entrada."""
        ok, motivo = ln.disponivel()
        if not ok:
            self._aviso("Não dá para ler nota fiscal neste computador: {}.".format(motivo), "erro")
            return
        from tkinter import filedialog
        caminho = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Escolha o PDF da nota fiscal",
                                             filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        leitor = getattr(self.app, "leitor_nota", None)
        if leitor is None:
            leitor = self.app.leitor_nota = ln.LeitorNota()          # o mesmo para todas as notas (carregar demora)
        lido = DialogoLendoNota(self, leitor, caminho).abrir()
        if not lido:
            self._aviso("Leitura da nota cancelada.", "info")
            return
        if "erro" in lido:
            self._aviso(lido["erro"], "erro")
            return
        escolhidos = DialogoNotaLida(self, self.livro, lido).abrir()
        if not escolhidos:
            self._aviso("Nada foi colocado na lista.", "info")
            return
        self._ent_receber_da_nota(escolhidos, lido["nota"])

    def _ent_receber_da_nota(self, itens, nota):
        """Cadastra o que ainda não existe e põe tudo na lista de entrada (ainda falta Registrar entrada)."""
        materiais = self.livro.materiais(incluir_ocultos=True)
        novos = reativados = 0
        for item in itens:
            existente = ln.achar_igual(item["descricao"], materiais)
            if existente is None:
                try:
                    mid = self.livro.cadastrar_material(item["descricao"], item["unidade"], 0)
                except ErroEstoque as erro:
                    self._aviso(str(erro), "erro")
                    continue
                materiais.append(self.livro.material(mid))
                novos += 1
            else:
                mid = existente["id"]
                if not existente.get("ativo", True):
                    self.livro.editar_material(mid, ativo=True)
                    reativados += 1
            self._somar(self.ent_itens, mid, item["quantidade"])
        partes = [p for p in (nota.get("fornecedor"), "NF " + nota["numero"] if nota.get("numero") else "",
                              nota.get("emissao")) if p]
        if partes and not self.var_ent_obs.get().strip():
            self.var_ent_obs.set(" – ".join(partes))
        self._atualizar_lista_entrada()
        extra = "{} cadastrado(s) agora".format(novos) if novos else "todos já estavam cadastrados"
        if reativados:
            extra += ", {} voltou(aram) a ser usado(s)".format(reativados)
        self._aviso("Nota lida: {} entraram na lista ({}). Confira as quantidades e clique em Registrar entrada."
                    .format(_plural(len(itens), "produto", "produtos"), extra), "ok")

    def _ent_escolheu(self, material):
        self.ent_material = material
        self.lbl_ent_unidade.configure(text=material["unidade"] if material else "")
        if material:                                   # depois de escolher, o cursor vai para a quantidade
            self.after(40, self.ent_qtd_entrada.focus_set)

    def _ent_adicionar(self):
        if not self.ent_material:
            self._aviso("Escolha o material primeiro: digite o nome e clique na opção certa.", "erro")
            self.busca_ent.focar()
            return
        try:
            qtd = est.ler_quantidade(self.var_ent_qtd.get())
        except ErroEstoque as erro:
            self._aviso(str(erro), "erro")
            self.ent_qtd_entrada.focus_set()
            return
        self._somar(self.ent_itens, self.ent_material["id"], qtd)
        nome = self.ent_material["nome"]
        self.busca_ent.limpar()
        self.ent_material = None
        self.var_ent_qtd.set("")
        self.lbl_ent_unidade.configure(text="")
        self._atualizar_lista_entrada()
        self._aviso("“{}” entrou na lista. Escolha o próximo material ou clique em Registrar entrada.".format(nome), "ok")
        self.busca_ent.focar()

    def _atualizar_lista_entrada(self):
        self._preencher_lista(self.tab_ent, self.ent_itens, self.lbl_ent_total, saida=False)
        self._atualizar_resumo()

    def _ent_registrar(self):
        if not self.ent_itens:
            self._aviso("A lista está vazia. Adicione ao menos um material.", "erro")
            return
        try:
            self.livro.registrar_entrada(self.ent_itens, self.var_ent_obs.get())
        except ErroEstoque as erro:
            self._aviso(str(erro), "erro")
            return
        n = len(self.ent_itens)
        self.ent_itens.clear()
        self.var_ent_obs.set("")
        self._atualizar_tudo()
        self._aviso("Entrada registrada: {} material(is) somado(s) ao estoque.".format(n), "ok")
        self.busca_ent.focar()

    # -- listas de itens (entrada e saída) ----------------------------------------------

    @staticmethod
    def _somar(itens, material_id, quantidade):
        for item in itens:
            if item["material"] == material_id:
                item["quantidade"] = round(item["quantidade"] + quantidade, 3)
                return
        itens.append({"material": material_id, "quantidade": quantidade})

    def _preencher_lista(self, tabela, itens, rotulo_total, saida):
        _limpar_tabela(tabela)
        for item in itens:
            m = self.livro.material(item["material"])
            if not m:
                continue
            valores = [m["nome"], texto_quantidade(item["quantidade"]), m["unidade"]]
            tags = ()
            if saida:
                resta = round(m["saldo"] - item["quantidade"], 3)
                valores.append(texto_quantidade(resta))
                tags = ("zerado",) if resta < 0 else (("baixo",) if resta == 0 else ())
            tabela.insert("", "end", iid=item["material"], values=valores, tags=tags)
        rotulo_total.configure(text="{} material(is) na lista".format(len(itens)) if itens else "Lista vazia")

    def _tirar(self, tabela, itens, depois):
        sel = tabela.selection()
        if not sel:
            self._aviso("Clique num material da lista para tirar.", "erro")
            return
        itens[:] = [i for i in itens if i["material"] != sel[0]]
        depois()

    def _editar_quantidade(self, qual):
        """Muda a quantidade de um item da lista, antes de registrar (na saída, até o que há em estoque)."""
        saida = qual == "saida"
        tabela, itens = (self.tab_sai, self.sai_itens) if saida else (self.tab_ent, self.ent_itens)
        sel = tabela.selection()
        item = next((i for i in itens if sel and i["material"] == sel[0]), None)
        m = self.livro.material(sel[0]) if sel else None
        if not item or not m:
            self._aviso("Clique num material da lista para mudar a quantidade.", "erro")
            return
        nova = DialogoQuantidade(self, m, item["quantidade"], m["saldo"] if saida else None).abrir()
        if nova is None:
            return
        item["quantidade"] = nova
        (self._atualizar_lista_saida if saida else self._atualizar_lista_entrada)()
        tabela.selection_set(m["id"])
        self._aviso("Quantidade de “{}” alterada para {} {}.".format(m["nome"], texto_quantidade(nova), m["unidade"]), "ok")

    def _limpar_lista(self, qual):
        if qual == "entrada":
            self.ent_itens.clear()
            self._atualizar_lista_entrada()
        else:
            self.sai_itens.clear()
            self._atualizar_lista_saida()
        self._aviso("Lista limpa.", "info")

    # -- página: Saída ---------------------------------------------------------------

    def _montar_saida(self):
        f = tk.Frame(self.corpo, bg=COR_FUNDO)
        f.columnconfigure(0, weight=5, uniform="s")
        f.columnconfigure(1, weight=6, uniform="s")
        esquerda = tk.Frame(f, bg=COR_FUNDO)
        esquerda.grid(row=0, column=0, sticky="new", padx=(0, 8))
        externo, c1, _ = cartao(esquerda, "Quem recebe", 1)
        externo.pack(fill="x", pady=(0, 10))
        self.sai_dest = None
        self.busca_dest = CampoBusca(c1, "Digite o nome de quem recebe (ou parte dele)",
                                     lambda t: self.livro.buscar_destinatarios(t), self._descrever_destinatario,
                                     self._sai_dest_escolhido, cadastrar=self._cadastrar_destinatario_pelo_campo)
        self.busca_dest.pack(fill="x", pady=(4, 0))
        externo, c2, _ = cartao(esquerda, "Material que sai", 2)
        externo.pack(fill="x")
        self.sai_material = None
        self.busca_sai = CampoBusca(c2, "Digite o nome do material (ou parte dele)",
                                    self.livro_buscar_materiais, self._descrever_material, self._sai_escolheu)
        self.busca_sai.pack(fill="x", pady=(4, 0))
        linha = tk.Frame(c2, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(10, 0))
        self.var_sai_qtd = tk.StringVar()
        q = self._campo_quantidade(linha, self.var_sai_qtd, self._sai_adicionar)
        q.pack(side="left")
        self.sai_qtd_entrada = q.entrada
        self.lbl_sai_unidade = tk.Label(linha, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 10, "bold"))
        self.lbl_sai_unidade.pack(side="left", padx=(8, 0), pady=(18, 0))
        Botao(c2, "Adicionar à lista  ›", self._sai_adicionar, estilo="azul", pad_y=8).pack(anchor="w", pady=(12, 0))

        externo, c3, _ = cartao(f, "Materiais desta saída", 3)
        externo.grid(row=0, column=1, sticky="new", padx=(8, 0))
        topo = tk.Frame(c3, bg=COR_CARTAO)
        topo.pack(fill="x", pady=(2, 6))
        Botao(topo, "Importar saída anterior", self._sai_importar, estilo="tracejado", pad_y=6, pad_x=14, raio=8,
              fonte=(FONTE, 9, "bold")).pack(side="left")
        quadro, self.tab_sai = _tabela(c3, [
            ("nome", "Material", 260, "w", True), ("qtd", "Quantidade", 110, "center", False),
            ("unidade", "Unidade", 80, "w", False), ("resta", "Fica em estoque", 140, "center", False)],
            linhas=5 if self.baixa else 6)
        quadro.pack(fill="x", pady=(0, 8))
        linha = tk.Frame(c3, bg=COR_CARTAO)
        linha.pack(fill="x")
        self.tab_sai.bind("<Double-1>", lambda e: self._editar_quantidade("saida"))
        Botao(linha, "Editar quantidade", lambda: self._editar_quantidade("saida"), estilo="azul", pad_y=5,
              pad_x=14, raio=8, fonte=(FONTE, 9, "bold")).pack(side="left", padx=(0, 8))
        Botao(linha, "Tirar da lista", lambda: self._tirar(self.tab_sai, self.sai_itens, self._atualizar_lista_saida),
              estilo="suave", pad_y=5, pad_x=14, raio=8, fonte=(FONTE, 9, "bold")).pack(side="left")
        Botao(linha, "Limpar a lista", lambda: self._limpar_lista("saida"), estilo="tracejado", pad_y=5, pad_x=14,
              raio=8, fonte=(FONTE, 9, "bold")).pack(side="left", padx=(8, 0))
        self.lbl_sai_total = tk.Label(linha, text="", bg=COR_CARTAO, fg=COR_TEXTO_FRACO, font=(FONTE, 9))
        self.lbl_sai_total.pack(side="right")
        self.var_sai_obs = tk.StringVar()
        campo(c3, "Observação (opcional)", self.var_sai_obs).pack(fill="x", pady=(8, 0))
        Botao(c3, "▶   Registrar saída", self._sai_registrar, estilo="principal", fonte=(FONTE, 13, "bold"),
              pad_y=10, raio=12).pack(fill="x", pady=(10, 0))
        return f

    def _sai_dest_escolhido(self, dest):
        self.sai_dest = dest
        if dest:
            self.winfo_toplevel().after(40, self.busca_sai.focar)

    def _sai_escolheu(self, material):
        self.sai_material = material
        self.lbl_sai_unidade.configure(text=material["unidade"] if material else "")
        if material:
            self.after(40, self.sai_qtd_entrada.focus_set)

    def _sai_adicionar(self):
        m = self.sai_material
        if not m:
            self._aviso("Escolha o material primeiro: digite o nome e clique na opção certa.", "erro")
            self.busca_sai.focar()
            return
        try:
            qtd = est.ler_quantidade(self.var_sai_qtd.get())
        except ErroEstoque as erro:
            self._aviso(str(erro), "erro")
            return
        atual = self.livro.material(m["id"])
        ja = sum(i["quantidade"] for i in self.sai_itens if i["material"] == m["id"])
        if ja + qtd > atual["saldo"] + 1e-9:
            self._aviso("Só há {} {} de “{}” em estoque{}.".format(
                texto_quantidade(atual["saldo"]), atual["unidade"], atual["nome"],
                " (e {} já estão na lista)".format(texto_quantidade(ja)) if ja else ""), "erro")
            return
        self._somar(self.sai_itens, m["id"], qtd)
        self.busca_sai.limpar()
        self.sai_material = None
        self.var_sai_qtd.set("")
        self.lbl_sai_unidade.configure(text="")
        self._atualizar_lista_saida()
        self._aviso("“{}” entrou na lista.".format(m["nome"]), "ok")
        self.busca_sai.focar()

    def _atualizar_lista_saida(self):
        self._preencher_lista(self.tab_sai, self.sai_itens, self.lbl_sai_total, saida=True)
        self._atualizar_resumo()

    def _sai_importar(self):
        mov = DialogoImportarSaida(self, self.livro, self.sai_dest).abrir()
        if mov:
            self._carregar_saida(mov)

    def _carregar_saida(self, mov):
        """Põe na lista os materiais de uma saída anterior (e o destinatário, se ainda não há um)."""
        for i in mov["itens"]:
            if self.livro.material(i["material"]) and self.livro.material(i["material"])["ativo"]:
                self._somar(self.sai_itens, i["material"], i["quantidade"])
        if mov["destinatario"] and not self.sai_dest:
            self.busca_dest.definir(mov["destinatario"])
        self._atualizar_lista_saida()
        self._aviso("Materiais da saída de {} colocados na lista. Confira as quantidades e clique em Registrar saída."
                    .format(est.texto_data_hora(mov["quando"])), "ok")

    def _sai_registrar(self):
        if not self.sai_dest:
            self._aviso("Escolha quem recebe o material (digite o nome e clique na opção certa).", "erro")
            self.busca_dest.focar()
            return
        if not self.sai_itens:
            self._aviso("A lista está vazia. Adicione ao menos um material.", "erro")
            return
        try:
            self.livro.registrar_saida(self.sai_dest["id"], self.sai_itens, self.var_sai_obs.get())
        except ErroEstoque as erro:
            self._atualizar_tudo()
            self._aviso(str(erro), "erro")
            return
        nome, n = self.sai_dest["nome"], len(self.sai_itens)
        self.sai_itens.clear()
        self.var_sai_obs.set("")
        self.busca_dest.limpar()
        self.sai_dest = None
        self._atualizar_tudo()
        self._aviso("Saída registrada para {}: {} material(is) baixado(s) do estoque.".format(nome, n), "ok")
        self.busca_dest.focar()

    # -- página: Histórico ---------------------------------------------------------------

    def _montar_historico(self):
        f = tk.Frame(self.corpo, bg=COR_FUNDO)
        externo, c, _ = cartao(f, "Entradas e saídas registradas", 1)
        externo.pack(fill="x")
        linha = tk.Frame(c, bg=COR_CARTAO)
        linha.pack(fill="x", pady=(4, 8))
        self.var_hist_tipo = tk.StringVar(value="todos")
        for texto, valor in (("Todas", "todos"), ("Entradas", "entrada"), ("Saídas", "saida")):
            Chip(linha, texto, self.var_hist_tipo, valor).pack(side="left", padx=(0, 6))
        self.pesq_hist = CaixaPesquisa(linha, "Filtrar por material, destinatário ou observação")
        self.pesq_hist.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.var_hist_tipo.trace_add("write", lambda *_: self._preencher_historico())
        self.pesq_hist.var.trace_add("write", lambda *_: self._preencher_historico())
        quadro, self.tab_hist = _tabela(c, [
            ("quando", "Data e hora", 160, "w", False), ("tipo", "Tipo", 80, "w", False),
            ("dest", "Destinatário", 210, "w", False), ("itens", "Materiais", 360, "w", True),
            ("sit", "Situação", 170, "w", False)], linhas=7 if self.baixa else 10)
        quadro.pack(fill="x")
        self.tab_hist.bind("<<TreeviewSelect>>", lambda e: self._ao_selecionar_historico())
        self.tab_hist.bind("<Double-1>", lambda e: self._ver_detalhes())
        rodape = tk.Frame(c, bg=COR_CARTAO)
        rodape.pack(fill="x", pady=(8, 0))
        Botao(rodape, "Ver detalhes", self._ver_detalhes, estilo="suave", pad_y=6, pad_x=16, raio=8,
              fonte=(FONTE, 10, "bold")).pack(side="left")
        self.botao_repetir = Botao(rodape, "Repetir esta saída", self._repetir_saida, estilo="azul", pad_y=6,
                                   pad_x=16, raio=8, fonte=(FONTE, 10, "bold"))
        self.botao_repetir.pack(side="left", padx=(8, 0))
        Botao(rodape, "Estornar", self._estornar, estilo="tracejado", pad_y=6, pad_x=16, raio=8,
              fonte=(FONTE, 10, "bold")).pack(side="right")
        self.botao_repetir.definir_ativo(False)
        return f

    def _preencher_historico(self):
        _limpar_tabela(self.tab_hist)
        tipo = self.var_hist_tipo.get()
        n = 0
        for mov in self.livro.movimentos(None if tipo == "todos" else tipo, self.pesq_hist.var.get()):
            dest = mov["destinatario"]
            situacao = ""
            if mov["estornado"]:
                situacao = "Estornada em " + mov["estornado_em"].strftime("%d/%m %H:%M")
            self.tab_hist.insert("", "end", iid=mov["id"], values=(
                est.texto_data_hora(mov["quando"]), "Entrada" if mov["tipo"] == "entrada" else "Saída",
                dest["nome"] if dest else "–", mov["resumo"], situacao), tags=("apagado",) if mov["estornado"] else ())
            n += 1
        if not n:
            self.tab_hist.insert("", "end", values=("Nenhum registro ainda.", "", "", "", ""), tags=("apagado",))
        self._ao_selecionar_historico()

    def _selecionado_historico(self):
        sel = self.tab_hist.selection()
        return self.livro.movimento(sel[0]) if sel else None

    def _ao_selecionar_historico(self):
        mov = self._selecionado_historico()
        self.botao_repetir.definir_ativo(bool(mov and mov["tipo"] == "saida"))

    def _ver_detalhes(self):
        mov = self._selecionado_historico()
        if not mov:
            self._aviso("Clique num registro da lista.", "erro")
            return
        linhas = ["{} de {}".format("Entrada" if mov["tipo"] == "entrada" else "Saída", est.texto_data_hora(mov["quando"]))]
        if mov["destinatario"]:
            d = mov["destinatario"]
            linhas.append("Para: {}{}".format(d["nome"], " ({})".format(d["setor"]) if d["setor"] else ""))
        linhas.append("")
        linhas += ["•  {}:  {} {}".format(i["nome"], texto_quantidade(i["quantidade"]), i["unidade"]) for i in mov["itens"]]
        if mov["obs"]:
            linhas += ["", "Observação: " + mov["obs"]]
        if mov["estornado"]:
            linhas += ["", "ESTORNADO em {}{}".format(est.texto_data_hora(mov["estornado_em"]),
                                                       ": " + mov["motivo_estorno"] if mov["motivo_estorno"] else "")]
        from tkinter import messagebox
        messagebox.showinfo(_BASE.NOME_PROGRAMA, "\n".join(linhas), parent=self.winfo_toplevel())

    def _repetir_saida(self):
        mov = self._selecionado_historico()
        if not mov or mov["tipo"] != "saida":
            self._aviso("Clique numa saída da lista para repetir.", "erro")
            return
        self.var_pagina.set("saida")
        self.sai_itens.clear()
        self.busca_dest.limpar()
        self.sai_dest = None
        self._carregar_saida(mov)

    def _estornar(self):
        mov = self._selecionado_historico()
        if not mov:
            self._aviso("Clique no registro que quer estornar.", "erro")
            return
        if mov["estornado"]:
            self._aviso("Esse registro já foi estornado.", "erro")
            return
        motivo = DialogoEstorno(self, mov).abrir()
        if motivo is None:
            return
        try:
            self.livro.estornar(mov["id"], motivo)
        except ErroEstoque as erro:
            self._aviso(str(erro), "erro")
            return
        self._atualizar_tudo()
        self._aviso("Registro estornado. O estoque voltou ao que era antes.", "ok")


# ---------------------------------------------------------------------------
# Relatório de estoque em PDF
# ---------------------------------------------------------------------------

def _fontes_pdf():
    """
    Fontes que VÃO DENTRO do PDF (Arial e Times New Roman do Windows). Com as fontes-padrão do PDF
    (Helvetica/Times), o leitor tem de procurar uma fonte parecida no computador; no Adobe Acrobat
    isso chamava o "Font Capture", que deu erro numa máquina da escola. Se o Windows não tiver as
    fontes, volta para as padrão e o PDF sai igual a antes.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pasta = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    pedido = {"Helvetica": ("arial.ttf", "DE-Arial"), "Helvetica-Bold": ("arialbd.ttf", "DE-Arial-Bold"),
              "Times-Roman": ("times.ttf", "DE-Times"), "Times-Bold": ("timesbd.ttf", "DE-Times-Bold")}
    mapa = {}
    for padrao, (arquivo, nome) in pedido.items():
        try:
            if nome not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(nome, os.path.join(pasta, arquivo)))
            mapa[padrao] = nome
        except Exception:
            mapa[padrao] = padrao
    return mapa


def gerar_relatorio_pdf(caminho, cfg, titulo, subtitulo, linhas, logo, agora):
    """PDF com o saldo de cada material (cabeçalho da escola igual ao das declarações)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas  # noqa: F401  (garante o reportlab completo no .exe)
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    F = _fontes_pdf()
    azul = _BASE.AZUL_DOC
    largura, altura = A4
    esq = dir_ = 16 * mm
    cab = _BASE._linhas_cabecalho(cfg)
    alturas = [t * 1.32 for _, _, t, _, _ in cab]
    topo_pagina = 18 * mm
    fim_cabecalho = topo_pagina + sum(alturas) + 4 * mm + 8 * mm + 15 * mm      # até o resumo, na 1ª página
    margem_topo = 22 * mm

    def rodape(c, doc):
        c.saveState()
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.setLineWidth(0.6)
        c.line(esq, 14 * mm, largura - dir_, 14 * mm)
        c.setFont(F["Helvetica"], 8.5)
        c.setFillColorRGB(0.27, 0.27, 0.27)
        c.drawString(esq, 9.5 * mm, "{} – {}".format(cfg.get("escola") or "", subtitulo))
        c.drawRightString(largura - dir_, 9.5 * mm, "Página {}".format(doc.page))
        c.restoreState()

    def primeira(c, doc):
        c.saveState()
        topo = altura - topo_pagina
        if logo and os.path.exists(logo):
            try:
                lado = 20 * mm
                c.drawImage(logo, esq, topo - max(sum(alturas), lado) / 2 - lado / 2, width=lado, height=lado,
                            preserveAspectRatio=True, anchor="c", mask="auto")
            except Exception:
                pass
        y = topo
        for (texto, fonte, tam, _n, cor), alt in zip(cab, alturas):
            y -= alt
            c.setFont(F.get(fonte, fonte), tam)
            c.setFillColorRGB(*(azul if cor == "azul" else (0.27, 0.27, 0.27) if cor == "cinza" else (0.07, 0.07, 0.07)))
            c.drawCentredString(largura / 2, y, texto)
        y -= 4 * mm
        c.setStrokeColorRGB(*azul)
        c.setLineWidth(1.2)
        c.line(esq, y, largura - dir_, y)
        y -= 11 * mm
        c.setFillColorRGB(0.07, 0.07, 0.07)
        c.setFont(F["Times-Bold"], 15)
        c.drawCentredString(largura / 2, y, titulo)
        y -= 6.5 * mm
        c.setFont(F["Times-Roman"], 11.5)
        c.drawCentredString(largura / 2, y, subtitulo.upper())
        c.restoreState()
        rodape(c, doc)

    def seguintes(c, doc):
        c.saveState()
        c.setFont(F["Helvetica-Bold"], 9)
        c.setFillColorRGB(*azul)
        c.drawString(esq, altura - 14 * mm, "{} – {}".format(titulo.capitalize(), subtitulo))
        c.setStrokeColorRGB(*azul)
        c.setLineWidth(0.8)
        c.line(esq, altura - 16 * mm, largura - dir_, altura - 16 * mm)
        c.restoreState()
        rodape(c, doc)

    nome_st = ParagraphStyle("nome", fontName=F["Helvetica"], fontSize=9.5, leading=11.5)
    dados = [["Material", "Unidade", "Em estoque"]]
    estilos = [("BACKGROUND", (0, 0), (-1, 0), colors.Color(*azul)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONTNAME", (0, 0), (-1, 0), F["Helvetica-Bold"]), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
               ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.Color(0.8, 0.82, 0.87)),
               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for n, m in enumerate(linhas, start=1):
        dados.append([Paragraph(m["nome"].replace("&", "&amp;").replace("<", "&lt;"), nome_st), m["unidade"],
                      texto_quantidade(m["saldo"])])
        if n % 2 == 0:
            estilos.append(("BACKGROUND", (0, n), (-1, n), colors.Color(0.95, 0.96, 0.98)))
    util = largura - esq - dir_
    tabela = Table(dados, colWidths=[util - 34 * mm - 36 * mm, 34 * mm, 36 * mm], repeatRows=1)
    tabela.setStyle(TableStyle(estilos))

    resumo = "Emitido em {}  ·  {}".format(agora.strftime("%d/%m/%Y às %H:%M"), _plural(len(linhas), "material", "materiais"))
    est_resumo = ParagraphStyle("resumo", fontName=F["Helvetica"], fontSize=9, leading=11, textColor=colors.Color(0.27, 0.27, 0.27),
                                alignment=1)
    doc = SimpleDocTemplate(caminho, pagesize=A4, leftMargin=esq, rightMargin=dir_, topMargin=margem_topo,
                            bottomMargin=20 * mm, title="{} – {}".format(titulo.capitalize(), subtitulo),
                            author=cfg.get("escola") or _BASE.NOME_PROGRAMA, creator=_BASE.NOME_PROGRAMA)
    historia = [Spacer(1, max(fim_cabecalho - margem_topo, 0) + 2 * mm), Paragraph(resumo, est_resumo),
                Spacer(1, 4 * mm), tabela]
    # A biblioteca de PDF começa cada página com a fonte-padrão dela (Helvetica, que não vai dentro do
    # arquivo); trocando por uma embutida, o PDF não depende de nenhuma fonte do computador.
    from reportlab import rl_config
    fonte_inicial = rl_config.canvas_basefontname
    rl_config.canvas_basefontname = F["Helvetica"]
    try:
        doc.build(historia, onFirstPage=primeira, onLaterPages=seguintes)
    finally:
        rl_config.canvas_basefontname = fonte_inicial
