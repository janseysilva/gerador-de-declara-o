# -*- coding: utf-8 -*-
"""
Gera um PDF que imita uma LISTA DE MATERIAL ESCANEADA (só imagem, sem texto), com produtos inventados.
Serve para provar que o leitor de notas (OCR) funciona de verdade, inclusive dentro do .exe.

    python testes/nota_escaneada_exemplo.py SAIDA.pdf
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

LINHAS = (
    ("1", "DETERGENTE LIQUIDO 500 ML", "UN", "2", "20"),
    ("2", "SABAO EM PO 500 G", "PCT", "1", "12"),
    ("3", "AGUA SANITARIA 1 L", "UN", "2", "24"),
    ("4", "PAPEL HIGIENICO FOLHA SIMPLES", "PCT", "1", "15"),
    ("5", "ESPONJA DUPLA FACE", "UN", "3", "30"),
    ("6", "DESINFETANTE 2 L", "UN", "1", "10"),
)


def _fonte(tamanho, negrito=False):
    for nome in (("arialbd.ttf" if negrito else "arial.ttf"), "DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf"):
        for pasta in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu", "/Library/Fonts"):
            caminho = os.path.join(pasta, nome)
            if os.path.exists(caminho):
                return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()


def gerar(saida):
    img = Image.new("L", (1654, 2339), 255)            # A4 a 200 dpi
    d = ImageDraw.Draw(img)
    d.text((120, 130), "ESCOLA EXEMPLO ESTRELA DO SABER", font=_fonte(44, True), fill=20)
    d.text((120, 200), "LISTA DE MATERIAL DE LIMPEZA - NOVEMBRO", font=_fonte(34), fill=20)
    colunas = (120, 260, 960, 1090, 1400)             # ITEM | DESCRIÇÃO | UND | POR FUNC | QUANT (afastadas para o OCR não colar)
    y = 330
    for x, texto in zip(colunas, ("ITEM", "DESCRIÇÃO", "UND", "POR FUNC", "QUANT")):
        d.text((x, y), texto, font=_fonte(32, True), fill=0)
    d.line((100, y + 55, 1560, y + 55), fill=0, width=3)
    y += 85
    for linha in LINHAS:
        for x, texto in zip(colunas, linha):
            d.text((x, y), texto, font=_fonte(32), fill=10)
        y += 78
    d.line((100, y + 10, 1560, y + 10), fill=0, width=3)
    img.convert("RGB").save(saida, "PDF", resolution=200.0)        # PDF só de imagem, como o do scanner
    return saida


if __name__ == "__main__":
    print(gerar(sys.argv[1] if len(sys.argv) > 1 else "nota_escaneada_exemplo.pdf"))
