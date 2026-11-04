"""Gera um PDF parecido com o "Acompanhamento Diário" do Gier, com nomes INVENTADOS.

Uso: python testes/pdf_gier_exemplo.py saida.pdf
Serve para testar a leitura da frequência (inclusive no .exe montado no GitHub).
"""
import random
import sys

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

NOMES = ["ANA BEATRIZ SOUZA LIMA", "ANA CLARA MENDES", "ARTHUR MIGUEL COSTA",
         "BERNARDO ALVES PEREIRA", "CECILIA RAMOS DUARTE", "DAVI LUCCA FERREIRA"]


def gerar(caminho):
    random.seed(3)
    c = canvas.Canvas(caminho, pagesize=landscape(A4))
    for mes, dias in (("Agosto", 20), ("Setembro", 19), ("Outubro", 9)):
        y = [560]

        def linha(texto, tam=8):
            c.setFont("Helvetica", tam)
            c.drawString(30, y[0], texto)
            y[0] -= 14
        linha("Secretaria Municipal de Educação - Semed")
        linha("CMEI EXEMPLO - INEP: 00000000")
        linha("Acompanhamento Diário - Mês: " + mes, 11)
        linha("Escola: CMEI EXEMPLO Ano Letivo: 2026 Turma: PE II -TURMA-E Componente Curricular: "
              "AULA DIA Professor: PROFESSORA EXEMPLO")
        linha("Nº Estudante Sit. Entr. Saída 01 02 03 Total Total")
        for i, nome in enumerate(NOMES, 1):
            f = random.choice([0, 1, 2, 3])
            simb = ["F"] * f + ["•"] * (dias - f)
            random.shuffle(simb)
            linha("{} {} MA 22/12 {} {} 0".format(i, nome, " ".join(simb), f))
        linha("Legenda:")
        linha("Página 1 de 1")
        c.showPage()
    c.save()


if __name__ == "__main__":
    gerar(sys.argv[1] if len(sys.argv) > 1 else "gier_exemplo.pdf")
