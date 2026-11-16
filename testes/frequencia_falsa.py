"""Parte do Gier de mentira (gier_falso.py): Pedagógico / Frequência e o relatório
"Relação de Pendências de Lançamento de Aula", com nomes INVENTADOS.

Imita o que o programa usa: Frequencia.aspx (turmas no oculto hdfFiltroGeral + Pesquisar
na mesma página), a caixa "Imprimir Relatórios" (postback assíncrono) e o PDF em
RelatorioVisualizar.aspx (o mesmo de avaliacao_falsa: guarda o último relatório pedido).
"""
import html
import io
import json
import urllib.parse

from avaliacao_falsa import ESTADO

P = "ctl00$cphContent$CabecalhoFiltro$"
TURMAS = [
    {"id": 701, "codigo": "PE I-TURMA-A", "ciclo": 5, "profs": [(9001, "PROFESSORA EXEMPLO UM")]},
    {"id": 702, "codigo": "PE II -TURMA-F", "ciclo": 6,
     "profs": [(9002, "PROFESSORA EXEMPLO DOIS"), (9003, "PROFESSORA EXEMPLO TRES")]},
    {"id": 703, "codigo": "PE II -TURMA-L (com erro)", "ciclo": 6, "profs": [(9004, "PROFESSORA EXEMPLO QUATRO")]},
]
FREQ = {"turma": None, "pesquisas": [], "relatorios": []}


def _oculto(nome, valor):
    return '<input type="hidden" name="{}{}" id="{}" value="{}">'.format(P, nome, nome, html.escape(valor, quote=True))


def _pagina(turma=None):
    geral = [{"AnoLetivo": 2025, "IdModalidade": 1, "IdTurma": 98, "CodigoTurma": "TURMA DE 2025", "IdCursosCiclos": 5,
              "IdDisciplina": 549, "IdTipoComponenteDisciplina": 1, "IdProfessor": 1}]
    for t in TURMAS:
        for prof, nome in t["profs"]:
            geral.append({"AnoLetivo": 2026, "IdModalidade": 1, "Modalidade": "Educação Infantil", "IdTurma": t["id"],
                          "CodigoTurma": t["codigo"], "IdCursosCiclos": t["ciclo"], "IdDisciplina": 549,
                          "Disciplina": "AULA DIA", "IdProfessor": prof, "ProfessorNome": nome,
                          "IdTipoComponenteDisciplina": 1})
    lista = ""
    if turma:
        lista = ("<div>Turma {}</div><select name='ctl00$cphContent$ddlImprimir'>"
                 "<option value='0'>Imprimir Relatórios</option>"
                 "<option value='348'>Relatório de Frequência Diária</option>"
                 "<option value='524'>Relação de Pendências de Lançamento de Aula</option></select>").format(turma["codigo"])
    return ("<html><body><form method='post' action='./Frequencia.aspx'>"
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="{vs}">'
            '<input type="hidden" name="__LASTFOCUS" id="__LASTFOCUS" value="">'
            + _oculto("hdfFiltroGeral", json.dumps(geral, ensure_ascii=False)) + _oculto("hdfAnoLetivo", "2026")
            + _oculto("hdfModalidade", "") + _oculto("hdfCiclo", "") + _oculto("hdfTurma", "")
            + _oculto("hdfDisciplina", "0") + _oculto("hdfTipoComponenteDisciplina", "0") + _oculto("hdfProfessor", "0")
            + _oculto("hdfDataReferencia", "2026-11-16")
            + '<input type="submit" name="{p}btnPesquisar" value="Pesquisar" disabled="">'
              '<input type="submit" name="{p}btnLimpar" value="Limpar">{lista}</form></body></html>').replace(
        "{vs}", "FV1" if turma else "FV0").replace("{p}", P).replace("{lista}", lista)


def _pdf(turma):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    saida = io.BytesIO()
    c = canvas.Canvas(saida, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(40, 800, "Relação de Pendências de Lançamentos")
    c.drawString(40, 780, "Turma: {} - POLIVALENTE".format(turma["codigo"]))
    c.drawString(40, 760, "{}   01/02/2026   Turno   NÃO   NÃO".format(turma["profs"][0][1]))
    c.showPage()
    c.save()
    return saida.getvalue()


def tratar_get(h):
    if urllib.parse.urlsplit(h.path).path != "/Paginas/Pedagogico/Frequencia.aspx":
        return False
    if not h._tem(".ASPXAUTH"):
        h._enviar("", status=302, extra={"Location": "/Login.aspx?ReturnUrl=x"})
    else:
        FREQ["turma"] = None
        h._enviar(_pagina())
    return True


def tratar_post(h, corpo):
    if urllib.parse.urlsplit(h.path).path != "/Paginas/Pedagogico/Frequencia.aspx":
        return False
    if not h._tem(".ASPXAUTH"):
        h._enviar("", status=302, extra={"Location": "/Login.aspx"})
        return True
    f = {k: v[0] for k, v in urllib.parse.parse_qs(corpo.decode("utf-8"), keep_blank_values=True).items()}
    if f.get("__ASYNCPOST") != "true":                       # Pesquisar
        assert f.get(P + "btnPesquisar") == "Pesquisar" and P + "btnLimpar" not in f, list(f)[:5]
        assert f["__VIEWSTATE"] == "FV0" and f[P + "hdfAnoLetivo"] == "2026" and f[P + "hdfModalidade"] == "1"
        turma = next(t for t in TURMAS if str(t["id"]) == f[P + "hdfTurma"])
        assert f[P + "hdfCiclo"] == str(turma["ciclo"]) and f[P + "hdfDisciplina"] == "549"
        assert f[P + "hdfTipoComponenteDisciplina"] == "1"
        assert f[P + "hdfProfessor"] in [str(p) for p, _n in turma["profs"]]
        FREQ["turma"] = turma
        FREQ["pesquisas"].append(turma["codigo"])
        h._enviar(_pagina(turma))
        return True
    # Imprimir Relatórios → Pendências
    assert h.headers.get("X-MicrosoftAjax") == "Delta=true"
    assert f["ctl00$cphHeader$ScriptManager1"] == "ctl00$cphContent$UpdatePanel1|ctl00$cphContent$ddlImprimir"
    assert f["__EVENTTARGET"] == "ctl00$cphContent$ddlImprimir" and f["ctl00$cphContent$ddlImprimir"] == "524"
    assert f["__VIEWSTATE"] == "FV1" and FREQ["turma"] is not None
    turma = FREQ["turma"]
    FREQ["relatorios"].append(turma["codigo"])
    if turma["codigo"].endswith("(com erro)"):
        ESTADO["relatorio"] = None
    else:
        ESTADO["relatorio"] = lambda t=turma: _pdf(t)
    script = "abreRelatorio();"
    h._enviar("3|hiddenField|__VIEWSTATE|FV2|{}|scriptStartupBlock|ScriptContentNoTags|{}|".format(len(script), script),
              "text/plain; charset=utf-8")
    return True
