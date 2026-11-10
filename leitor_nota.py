# -*- coding: utf-8 -*-
"""
Leitor de nota fiscal (DANFE) em PDF para a ENTRADA do estoque.

O PDF da nota costuma ser ESCANEADO (só imagem). Então o arquivo é aberto página por página,
a imagem é endireitada e lida por um OCR (reconhecimento de texto, o RapidOCR, que roda no
próprio computador, sem internet). Depois o texto é arrumado em linhas da tabela de produtos:
descrição, unidade (UN, CX, PCT...) e quantidade.

O que está aqui:
  - a parte que entende a tabela (`extrair_itens`, `ler_dinheiro`...): só Python puro, testada
    sem precisar do OCR (`testes/teste_leitor_nota.py`);
  - a parte que usa o OCR (`LeitorNota`): abre o PDF, endireita a imagem, chama o OCR.

O OCR erra (letras e números), então o programa NUNCA registra sozinho: ele mostra a lista lida,
com a imagem de cada linha da nota ao lado, para a pessoa conferir antes de entrar no estoque.
"""

import math
import os
import re
import sys
import unicodedata

# Unidades que aparecem na nota -> como ficam no estoque (ver estoque.UNIDADES).
UNIDADES_NOTA = {
    "UN": "unidade", "UND": "unidade", "UNID": "unidade", "U": "unidade", "PC": "unidade", "PÇ": "unidade",
    "CX": "caixa", "CXA": "caixa", "PCT": "pacote", "PT": "pacote", "PCTE": "pacote",
    "RS": "resma", "RESMA": "resma", "RL": "rolo", "ROL": "rolo", "PAR": "par", "PR": "par",
    "KG": "kg", "LT": "litro", "L": "litro", "DZ": "dúzia", "FD": "fardo", "MT": "metro", "M": "metro",
    "FL": "folha", "FLS": "folha", "GL": "galão", "BD": "balde", "JG": "jogo", "KIT": "kit",
    "FR": "frasco", "TB": "tubo", "SC": "saco", "BL": "bloco", "CT": "cartela", "ET": "caixa",
}
# Leituras erradas comuns do OCR para as unidades (o "UN" quase sempre vira "NN" ou "Nn").
CORRECOES_UNIDADE = {"NN": "UN", "N": "UN", "UM": "UN", "LN": "UN", "IN": "UN", "VN": "UN", "UH": "UN",
                     "CK": "CX", "CXX": "CX", "OX": "CX", "PCI": "PCT", "PGT": "PCT", "PC1": "PCT", "P0T": "PCT"}


# ---------------------------------------------------------------------------
# Pedacinhos de texto
# ---------------------------------------------------------------------------

class Palavra:
    """Um trecho de texto lido pelo OCR, com a posição na página (x, y = canto de cima à esquerda)."""

    __slots__ = ("t", "x", "y", "w", "h")

    def __init__(self, t, x, y, w, h):
        self.t, self.x, self.y, self.w, self.h = t, float(x), float(y), float(w), float(h)

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def __repr__(self):
        return "Palavra({!r}, x={:.0f}, y={:.0f})".format(self.t, self.x, self.y)


def sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c))


def _chave(texto):
    """Só letras e números em maiúsculas, para comparar títulos de coluna lidos pelo OCR."""
    return re.sub(r"[^A-Z0-9]", "", sem_acento(texto).upper())


def ler_dinheiro(texto):
    """'1.264,00' -> 1264.0 ; devolve None se não parece um valor (o OCR às vezes embaralha)."""
    t = (texto or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", t):
        return None
    return float(t.replace(".", "").replace(",", "."))


def ler_quantidade_nota(texto):
    """
    Quantidade da coluna QUANT.: '10' -> 10.0, '2,5' -> 2.5. Aceita as trocas comuns do OCR em um
    token curto (I/l/| no lugar do 1, O no lugar do 0, símbolo sobrando depois do número).
    """
    t = (texto or "").strip()
    if not t or len(t) > 7:
        return None
    if t in ("I", "l", "|", "!", "i"):
        return 1.0
    t = t.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"}))
    m = re.fullmatch(r"(\d{1,5})(?:,(\d{1,3}))?\D{0,2}", t)
    if not m:
        return None
    numero = float(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
    return numero if numero > 0 else None


def normalizar_unidade_nota(texto):
    """'Nn' -> ('UN', 'unidade'); devolve (None, None) se não reconhece."""
    t = re.sub(r"[^A-Za-zÇç]", "", texto or "").upper()
    t = CORRECOES_UNIDADE.get(t, t)
    if t in UNIDADES_NOTA:
        return t, UNIDADES_NOTA[t]
    return None, None


# ---------------------------------------------------------------------------
# Da lista de palavras da página para as linhas da tabela
# ---------------------------------------------------------------------------

class ColunasTabela:
    """Onde ficam as colunas da tabela de produtos desta página (a partir dos títulos)."""

    def __init__(self, esq_codigo, esq_unid, esq_valor_unit, esq_total, dir_total, fim_descricao, topo):
        self.esq_codigo, self.esq_unid, self.esq_valor_unit = esq_codigo, esq_unid, esq_valor_unit
        self.esq_total, self.dir_total, self.fim_descricao, self.topo = esq_total, dir_total, fim_descricao, topo

    @property
    def inicio_descricao(self):
        return self.esq_codigo + 95

    @property
    def inicio_qtd(self):
        return self.esq_unid + 40

    @property
    def fim_qtd(self):
        return self.esq_valor_unit - 20


def achar_colunas(palavras):
    """
    Procura os títulos "UNID." / "V. UNIT." / "V. TOTAL" / "NCM" / "CÓD." e devolve as colunas,
    ou None se a página não tem a tabela de produtos.
    """
    unid = [p for p in palavras if _chave(p.t).startswith("UNID")]
    if not unid:
        return None
    u = min(unid, key=lambda p: p.y)
    mesma = [p for p in palavras if abs(p.cy - u.cy) < 14]
    esq_codigo = next((p.x for p in mesma if _chave(p.t).startswith("COD")), None)
    if esq_codigo is None:
        esq_codigo = min([p.x for p in mesma] or [u.x - 760])
    ncm = next((p for p in mesma if _chave(p.t).startswith("NCM")), None)
    unit = next((p for p in mesma if "UNIT" in _chave(p.t)), None)
    total = next((p for p in mesma if _chave(p.t).endswith("TOTAL")), None)
    esq_unit = unit.x if unit else u.x + 125
    esq_total = total.x if total else esq_unit + 80
    return ColunasTabela(
        esq_codigo=esq_codigo, esq_unid=u.x, esq_valor_unit=esq_unit,
        esq_total=esq_total, dir_total=esq_total + 70,
        fim_descricao=(ncm.x - 15) if ncm else u.x - 215, topo=u.y + u.h + 6)


# Se a linha tem um destes trechos, a tabela de produtos já acabou (o OCR pode lê-los em pedaços ou juntos).
FIM_TABELA = ("CALCULODOISSQN", "ISSQN", "DADOSADICIONAIS", "INFORMACOESCOMPLEMENTARES", "RESERVADOAOFISCO")


def agrupar_linhas(palavras, tolerancia=13):
    """Junta as palavras que estão na mesma altura (mesma linha da tabela)."""
    grupos = []
    for p in sorted(palavras, key=lambda p: p.cy):
        if grupos and abs(p.cy - grupos[-1]["cy"]) <= max(tolerancia, p.h * 0.55):
            g = grupos[-1]
            g["palavras"].append(p)
            g["cy"] = sum(q.cy for q in g["palavras"]) / len(g["palavras"])
        else:
            grupos.append({"cy": p.cy, "palavras": [p]})
    for g in grupos:
        g["palavras"].sort(key=lambda p: p.x)
    return grupos


def _juntar(palavras):
    return " ".join(p.t.strip() for p in palavras if p.t.strip()).strip()


def limpar_descricao(texto):
    t = re.sub(r"\s+", " ", texto or "").strip(" |.,;:-")
    t = re.sub(r"(?<=\d)F[1l]s\b|\bF1s\b", "Fls", t)            # 'c/20F1s' -> 'c/20Fls'
    t = re.sub(r"(?<=\d)O(?=[mMgGlL]\b)", "0", t)               # '5Om' -> '50m'
    return t


def extrair_itens(palavras, colunas=None):
    """
    Linhas de produto de UMA página. Cada item: dict com descricao, unidade_nota ('UN'),
    unidade (estoque), quantidade (ou None), valor_unitario, valor_total, codigo, y (altura da
    linha na página) e avisos (o que precisa de conferência).
    """
    colunas = colunas or achar_colunas(palavras)
    if colunas is None:
        return [], None
    itens = []
    for g in agrupar_linhas([p for p in palavras if p.cy > colunas.topo]):
        chave = _chave(_juntar(g["palavras"]))
        if any(marca in chave for marca in FIM_TABELA):
            break
        item = _ler_linha(g["palavras"], colunas)
        if item:
            item["y"] = g["cy"]
            itens.append(item)
    return itens, colunas


def _ler_linha(pals, c):
    codigo = [p for p in pals if p.x < c.inicio_descricao - 5]
    desc = [p for p in pals if c.inicio_descricao - 5 <= p.x < c.fim_descricao]
    unid = [p for p in pals if c.esq_unid - 25 <= p.x < c.inicio_qtd]
    qtd = [p for p in pals if c.inicio_qtd <= p.x < c.fim_qtd]
    unit = [p for p in pals if c.fim_qtd <= p.x < c.esq_total - 25]
    total = [p for p in pals if c.esq_total - 25 <= p.x < c.dir_total + 40]

    cod = _juntar(codigo)
    cod = cod if re.fullmatch(r"\d{2,7}", cod) else ""
    descricao = limpar_descricao(_juntar(desc))
    unidade_nota, unidade = normalizar_unidade_nota(_juntar(unid))
    quantidade = next((q for q in (ler_quantidade_nota(p.t) for p in qtd) if q), None)
    valor_unit = next((v for v in (ler_dinheiro(p.t) for p in unit) if v is not None), None)
    valor_total = next((v for v in (ler_dinheiro(p.t) for p in total) if v is not None), None)

    # Não é linha de produto (título, linha solta do OCR): sem descrição, sem código e sem números da tabela.
    if not (cod or descricao) and quantidade is None and valor_unit is None and valor_total is None:
        return None
    if not descricao and not cod and quantidade is None:
        return None

    avisos = []
    if not descricao:
        avisos.append("descrição não foi lida")
    if quantidade is None and valor_unit and valor_total:      # a conta fecha: quantidade = total / unitário
        q = valor_total / valor_unit
        if abs(q - round(q)) < 0.02 and 0 < round(q) < 100000:
            quantidade = float(round(q))
            avisos.append("quantidade calculada pelo valor")
    if quantidade is None:
        avisos.append("quantidade não foi lida")
    elif valor_unit and valor_total and abs(quantidade * valor_unit - valor_total) > max(0.05, valor_total * 0.01):
        avisos.append("quantidade não bate com o valor da nota")
    if unidade_nota is None:
        avisos.append("unidade não foi lida")
    return {"codigo": cod, "descricao": descricao, "unidade_nota": unidade_nota, "unidade": unidade or "unidade",
            "quantidade": quantidade, "valor_unitario": valor_unit, "valor_total": valor_total, "avisos": avisos,
            "caixa": (c.esq_codigo - 8, c.dir_total + 20)}


# ---------------------------------------------------------------------------
# Dados da nota (número, fornecedor, data)
# ---------------------------------------------------------------------------

def dados_da_nota(palavras):
    """Número da nota, nome do fornecedor e data de emissão, quando o OCR conseguiu ler."""
    topo = sorted([p for p in palavras if p.y < 420], key=lambda p: (round(p.cy / 14), p.x))
    texto = " ".join(p.t for p in topo)
    numero = re.search(r"\b(\d{3}\.\d{3}\.\d{3})\b", texto)
    emissao = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
    fornecedor = ""
    linhas = agrupar_linhas([p for p in palavras if p.y < 130 and p.x < 700 and p.w < 500], 12)
    for g in linhas:                               # a 1ª linha do alto, à esquerda, é o nome do emitente
        t = limpar_descricao(_juntar(g["palavras"]))
        if len(t) >= 4 and not re.search(r"DANFE|DOCUMENTO|AUXILIAR|FISCAL|ENTRADA", sem_acento(t).upper()):
            fornecedor = t
            break
    return {"numero": numero.group(1) if numero else "", "emissao": emissao.group(1) if emissao else "",
            "fornecedor": fornecedor}


# ---------------------------------------------------------------------------
# Comparar com os materiais que já existem
# ---------------------------------------------------------------------------

def _chave_nome(texto):
    """Só letras e números, minúsculos e sem acento: 'Cola branca 90 g' e 'COLA BRANCA 90g' ficam iguais."""
    return re.sub(r"[^a-z0-9]+", "", sem_acento(texto).lower())


def achar_igual(descricao, materiais):
    """
    O material já cadastrado com O MESMO nome (sem contar maiúsculas, acentos, espaços e pontuação).
    Só nome igual de propósito: "Papel Cartão Rosa" e "Papel Cartão Preto" são parecidíssimos, mas são
    produtos diferentes e NÃO podem ser somados no mesmo material.
    """
    alvo = _chave_nome(descricao)
    if not alvo:
        return None
    return next((m for m in materiais if _chave_nome(m["nome"]) == alvo), None)


# ---------------------------------------------------------------------------
# A parte que usa o OCR (precisa do rapidocr, do onnxruntime e do pypdfium2)
# ---------------------------------------------------------------------------

class ErroLeitura(Exception):
    pass


def _pasta_modelos():
    """Onde estão os arquivos do OCR quando o programa é um .exe (PyInstaller) ou roda do código."""
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "modelos_ocr")):
        return os.path.join(base, "modelos_ocr")
    aqui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos_ocr")
    return aqui if os.path.isdir(aqui) else None


def disponivel():
    """(True, '') se este computador consegue ler notas escaneadas; senão (False, motivo)."""
    try:
        import numpy  # noqa: F401
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as erro:
        return False, "falta um componente do programa ({})".format(erro)
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception as erro:
        return False, "o leitor de notas (OCR) não está instalado neste computador ({})".format(erro)
    return True, ""


def endireitar(imagem):
    """
    Corrige a inclinação de uma página escaneada: acha o ângulo em que as linhas de texto ficam
    mais "marcadas" (o escaneamento torto borra as linhas). Devolve (imagem_endireitada, ângulo).
    """
    import numpy as np
    from PIL import Image

    cinza = imagem.convert("L")
    pequena = cinza.resize((800, max(1, round(800 * cinza.height / cinza.width))), Image.BILINEAR)

    def nitidez(angulo):
        r = pequena.rotate(angulo, resample=Image.BILINEAR, fillcolor=255)
        escuro = (np.asarray(r) < 140).sum(axis=1).astype(float)
        return float(np.var(np.diff(escuro)))

    melhor = max((a / 4.0 for a in range(-16, 17)), key=nitidez)            # -4° a +4°, passo de 0,25°
    refino = max((melhor + a / 20.0 for a in range(-5, 6)), key=nitidez)    # passo de 0,05°
    if abs(refino) < 0.08:
        return cinza, 0.0
    return cinza.rotate(refino, resample=Image.BICUBIC, fillcolor=255), refino


class LeitorNota:
    """Lê um PDF de nota fiscal e devolve os itens. Crie um só e reaproveite (carregar o OCR demora)."""

    def __init__(self):
        self._motor = None

    def _ocr(self):
        if self._motor is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            params = {"Rec.lang_type": LangRec.LATIN, "Rec.model_type": ModelType.MOBILE,
                      "Rec.ocr_version": OCRVersion.PPOCRV5, "Global.use_cls": False,
                      "Global.log_level": "critical"}
            pasta = _pasta_modelos()
            if pasta:                                           # modelos que vão junto com o programa
                for nome, chave in (("det.onnx", "Det.model_path"), ("rec.onnx", "Rec.model_path")):
                    caminho = os.path.join(pasta, nome)
                    if os.path.exists(caminho):
                        params[chave] = caminho
            self._motor = RapidOCR(params=params)
        return self._motor

    def _palavras(self, imagem, deslocamento=(0, 0), escala=1.0):
        import numpy as np
        r = self._ocr()(np.asarray(imagem.convert("RGB")))
        if r is None or getattr(r, "boxes", None) is None:
            return []
        saida = []
        for caixa, texto, _nota in zip(r.boxes, r.txts, r.scores):
            xs, ys = [p[0] for p in caixa], [p[1] for p in caixa]
            saida.append(Palavra(texto, min(xs) / escala + deslocamento[0], min(ys) / escala + deslocamento[1],
                                 (max(xs) - min(xs)) / escala, (max(ys) - min(ys)) / escala))
        return saida

    def ler(self, caminho_pdf, progresso=None, cancelado=None):
        """
        Devolve {"itens": [...], "nota": {...}, "paginas": n}. `progresso(texto, parte, total)` é
        chamado a cada passo; `cancelado()` devolve True se a pessoa desistiu.
        """
        ok, motivo = disponivel()
        if not ok:
            raise ErroLeitura("Não foi possível ler a nota: " + motivo + ".")
        import pypdfium2 as pdfium

        def avisar(texto, parte, total):
            if progresso:
                progresso(texto, parte, total)

        try:
            pdf = pdfium.PdfDocument(caminho_pdf)
        except Exception as erro:
            raise ErroLeitura("Não consegui abrir o PDF ({}).".format(erro))
        n = min(len(pdf), 12)
        itens, nota = [], {"numero": "", "emissao": "", "fornecedor": ""}
        passos = n * 2
        for i in range(n):
            if cancelado and cancelado():
                raise ErroLeitura("Leitura cancelada.")
            avisar("Preparando a página {} de {}…".format(i + 1, n), i * 2, passos)
            imagem = pdf[i].render(scale=200 / 72).to_pil()
            imagem, _angulo = endireitar(imagem)
            avisar("Lendo a página {} de {} (leva cerca de 1 minuto)…".format(i + 1, n), i * 2 + 1, passos)
            palavras = self._palavras(imagem)
            achados, colunas = extrair_itens(palavras)
            if colunas is None:
                continue
            if not nota["numero"]:
                nota = {k: nota[k] or v for k, v in dados_da_nota(palavras).items()}
            for it in achados:
                it["pagina"] = i + 1
                self._completar(imagem, colunas, it)
                x1, x2 = it["caixa"]
                it["imagem"] = imagem.crop((max(0, int(x1)), max(0, int(it["y"] - 19)),
                                            min(imagem.width, int(x2)), min(imagem.height, int(it["y"] + 19))))
            itens += achados
        avisar("Pronto.", passos, passos)
        if not itens:
            raise ErroLeitura("Não encontrei a tabela de produtos neste PDF. Ele é uma nota fiscal (DANFE)? "
                              "Se a página está de cabeça para baixo ou muito escura, escaneie de novo.")
        return {"itens": itens, "nota": nota, "paginas": n}

    def _completar(self, imagem, colunas, item):
        """Linha com descrição/unidade/quantidade em falta: lê só aquela faixa da nota, ampliada."""
        faltam_desc = not item["descricao"]
        faltam_unid = item["unidade_nota"] is None
        faltam_qtd = item["quantidade"] is None
        if not (faltam_desc or faltam_unid or faltam_qtd):
            return
        y = item["y"]
        if faltam_desc:
            faixa = (colunas.inicio_descricao - 10, y - 20, colunas.fim_descricao + 5, y + 20)
            ps = self._palavras(self._ampliar(imagem.crop([int(v) for v in faixa])),
                                (faixa[0] - 40 / 2.0, faixa[1] - 40 / 2.0), 2.0)
            texto = limpar_descricao(_juntar(sorted(ps, key=lambda p: p.x)))
            if len(texto) >= 4:
                item["descricao"] = texto
                item["avisos"] = [a for a in item["avisos"] if "descrição" not in a] + ["descrição lida de novo, confira"]
        if faltam_unid or faltam_qtd:
            faixa = (colunas.esq_unid - 30, y - 20, colunas.esq_valor_unit - 6, y + 20)
            ps = self._palavras(self._ampliar(imagem.crop([int(v) for v in faixa]), 3),
                                (faixa[0] - 40 / 3.0, faixa[1] - 40 / 3.0), 3.0)
            if faltam_unid:
                for p in sorted(ps, key=lambda p: p.x):
                    u, nome = normalizar_unidade_nota(p.t)
                    if u and p.x < colunas.inicio_qtd:
                        item["unidade_nota"], item["unidade"] = u, nome
                        item["avisos"] = [a for a in item["avisos"] if "unidade" not in a]
                        break
            if faltam_qtd:
                for p in sorted(ps, key=lambda p: p.x):
                    q = ler_quantidade_nota(p.t)
                    if q and p.x >= colunas.inicio_qtd - 5:
                        item["quantidade"] = q
                        item["avisos"] = [a for a in item["avisos"] if "quantidade não foi lida" not in a]
                        break
        valor_u, valor_t, q = item["valor_unitario"], item["valor_total"], item["quantidade"]
        if q and valor_u and valor_t and abs(q * valor_u - valor_t) > max(0.05, valor_t * 0.01):
            if "quantidade não bate com o valor da nota" not in item["avisos"]:
                item["avisos"].append("quantidade não bate com o valor da nota")

    @staticmethod
    def _ampliar(img, fator=2):
        from PIL import Image
        g = img.convert("L").resize((img.width * fator, img.height * fator), Image.LANCZOS)
        fundo = Image.new("L", (g.width + 80, g.height + 80), 255)          # margem branca: o OCR precisa de respiro
        fundo.paste(g, (40, 40))
        return fundo
