"""Parte do Gier de mentira (gier_falso.py): Pedagógico / Avaliação e os pareceres, com nomes INVENTADOS.

Imita o que o programa usa: Avaliacao.aspx (listas nos campos ocultos + Pesquisar),
AvaliacaoQuestionario.aspx (um aluno por linha, impressora = postback assíncrono) e
RelatorioVisualizar.aspx (o PDF do último aluno pedido nesta sessão).
O __VIEWSTATE muda a cada clique e o servidor só aceita o último, como o ASP.NET faria
se o programa não guardasse o novo.
"""
import html
import io
import json
import urllib.parse

TURMAS = [
    {"id": 601, "codigo": "PE I-TURMA-A", "ciclo": 5, "nome_ciclo": "1º Período",
     "alunos": [("ALICE EXEMPLO ROCHA", "Lançamento Completo"), ("BENTO EXEMPLO DIAS", "Sem lançamentos"),
                ("CAIO EXEMPLO NUNES", "Lançamento Parcial")]},
    {"id": 602, "codigo": "PE II -TURMA-B", "ciclo": 6, "nome_ciclo": "2º Período",
     "alunos": [("DORA EXEMPLO LIMA", "Lançamento Completo"), ("ENZO EXEMPLO PRADO", "Lançamento Completo")]},
    {"id": 603, "codigo": "PE II -TURMA-C (com erro)", "ciclo": 6, "nome_ciclo": "2º Período",
     "alunos": [("FABIO EXEMPLO REIS", "Lançamento Completo"), ("GABI EXEMPLO SALES", "Lançamento Completo")]},
]
SEMESTRES = [(8, "1º Semestre"), (9, "2º Semestre")]
ESTADO = {"viewstate": "VS0", "relatorio": None, "pedidos": []}


def _pagina_avaliacao():
    geral = [{"AnoLetivo": 2025, "IdModalidade": 1, "Modalidade": "Educação Infantil", "IdTurma": 99,
              "CodigoTurma": "TURMA DE 2025", "NomeCiclo": "1º Período", "IdCursosCiclos": 5}]
    geral += [{"AnoLetivo": 2026, "IdModalidade": 1, "Modalidade": "Educação Infantil", "IdTurma": t["id"],
               "CodigoTurma": t["codigo"], "NomeCiclo": t["nome_ciclo"], "IdCursosCiclos": t["ciclo"]}
              for t in TURMAS]
    unidades = [{"AnoLetivo": 2026, "Idtiposensino": 1, "IdUnidadeLetiva": i, "Descricao": d} for i, d in SEMESTRES]
    unidades += [{"AnoLetivo": 2026, "Idtiposensino": 5, "IdUnidadeLetiva": 8, "Descricao": "1º Semestre"},
                 {"AnoLetivo": 2026, "Idtiposensino": 4, "IdUnidadeLetiva": 1, "Descricao": "1º Bimestre"}]
    oculto = lambda i, n, v: '<input type="hidden" name="ctl00$cphContent${}" id="{}" value="{}">'.format(
        n, i, html.escape(v, quote=True))
    return ("<html><body><form method='post' action='./Avaliacao.aspx'>"
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="AV">'
            '<input type="submit" name="ctl00$btnMasterFavorito" value="">'
            + oculto("hdfFiltroGeral", "hdfFiltroGeral", json.dumps(geral, ensure_ascii=False))
            + oculto("hdfFiltroUnidadeLetiva", "hdfFiltroUnidadeLetiva", json.dumps(unidades, ensure_ascii=False))
            + oculto("hdfAnoLetivo", "hdfAnoLetivo", "2026") + oculto("hdfModalidade", "hdfModalidade", "")
            + oculto("hdfCiclo", "hdfCiclo", "") + oculto("hdfTurma", "hdfTurma", "")
            + oculto("hdfUnidadeLetiva", "hdfUnidadeLetiva", "") + oculto("hdfDisciplina", "hdfDisciplina", "0")
            + "<select id='ComboAnoLetivo'><option value='2026'>2026</option></select>"
            '<input type="submit" name="ctl00$cphContent$btnPesquisar" value="Pesquisar" disabled="">'
            '<input type="submit" name="ctl00$cphContent$btnLimpar" value="Limpar">'
            "</form></body></html>")


def _pagina_alunos(turma, semestre):
    linhas = []
    for n, (nome, situacao) in enumerate(turma["alunos"]):
        linhas.append(
            '<div class="cls-linha-resultado"><span id="cphContent_dtlAlunos_lblNomeAluno_{n}">{nome}</span>'
            '<div id="cphContent_dtlAlunos_divSituacaoQuestionario_{n}"><span id="cphContent_dtlAlunos_lblSituacao_{n}">'
            '{sit}</span></div><input type="submit" name="ctl00$cphContent$dtlAlunos$ctl{n:02d}$btnImprimirQuestionario"'
            ' value="" class="jsn-ico-imprimir"></div>'.format(n=n, nome=nome, sit=situacao))
    sem = dict(SEMESTRES)[semestre].upper()
    return ("<html><body><form method='post'>"
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="{vs}">'
            '<input type="hidden" name="__LASTFOCUS" id="__LASTFOCUS" value="">'
            "<span>2026 / {sem} / {ciclo} / {turma}</span>"
            "<select name='ctl00$cphContent$ddlImprimir'><option value='0'>Imprimir Relatórios</option>"
            "<option value='47'>Ficha</option></select>{linhas}</form></body></html>").format(
        vs=ESTADO["viewstate"], sem=sem, ciclo=turma["nome_ciclo"].upper(), turma=turma["codigo"],
        linhas="".join(linhas))


def _pdf(turma, nome, semestre):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    saida = io.BytesIO()
    c = canvas.Canvas(saida, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(40, 800, "Avaliação do processo de aprendizagem e desenvolvimento infantil")
    c.drawString(40, 780, "{} - {}".format(dict(SEMESTRES)[semestre], turma["codigo"]))
    c.drawString(40, 760, "Criança: " + nome)
    c.showPage()
    c.save()
    return saida.getvalue()


def tratar_get(h):
    caminho = urllib.parse.urlsplit(h.path)
    if caminho.path == "/Paginas/Pedagogico/Avaliacao.aspx":
        if not h._tem(".ASPXAUTH"):
            h._enviar("", status=302, extra={"Location": "/Login.aspx?ReturnUrl=x"})
        else:
            h._enviar(_pagina_avaliacao())
        return True
    if caminho.path == "/Paginas/Pedagogico/AvaliacaoQuestionario.aspx":
        c = urllib.parse.parse_qs(caminho.query).get("c", [""])[0]
        turma_id, semestre = (int(x) for x in c.split("-"))
        turma = next(t for t in TURMAS if t["id"] == turma_id)
        ESTADO["viewstate"] = "VS0"
        ESTADO["contexto"] = (turma, semestre)
        h._enviar(_pagina_alunos(turma, semestre))
        return True
    if caminho.path == "/RelatorioVisualizar.aspx":
        if not ESTADO["relatorio"]:
            h._enviar("<html>Desculpe</html>", status=200)
        else:
            h._enviar(_pdf(*ESTADO["relatorio"]), "application/pdf")
        return True
    return False


def tratar_post(h, corpo):
    caminho = urllib.parse.urlsplit(h.path).path
    if caminho not in ("/Paginas/Pedagogico/Avaliacao.aspx", "/Paginas/Pedagogico/AvaliacaoQuestionario.aspx"):
        return False
    if not h._tem(".ASPXAUTH"):
        h._enviar("", status=302, extra={"Location": "/Login.aspx"})
        return True
    f = {k: v[0] for k, v in urllib.parse.parse_qs(corpo.decode("utf-8"), keep_blank_values=True).items()}
    if caminho.endswith("/Avaliacao.aspx"):
        assert f.get("ctl00$cphContent$btnPesquisar") == "Pesquisar", f.keys()
        assert "ctl00$cphContent$btnLimpar" not in f and f["__VIEWSTATE"] == "AV"
        assert f["ctl00$cphContent$hdfAnoLetivo"] == "2026" and f["ctl00$cphContent$hdfModalidade"] == "1"
        turma = next(t for t in TURMAS if str(t["id"]) == f["ctl00$cphContent$hdfTurma"])
        assert f["ctl00$cphContent$hdfCiclo"] == str(turma["ciclo"]), f["ctl00$cphContent$hdfCiclo"]
        semestre = int(f["ctl00$cphContent$hdfUnidadeLetiva"])
        h._enviar("", status=302, extra={
            "Location": "/Paginas/Pedagogico/AvaliacaoQuestionario.aspx?c={}-{}".format(turma["id"], semestre)})
        return True
    # impressora: postback assíncrono
    assert h.headers.get("X-MicrosoftAjax") == "Delta=true" and f.get("__ASYNCPOST") == "true"
    turma, semestre = ESTADO["contexto"]
    botao = [k for k in f if k.endswith("$btnImprimirQuestionario")]
    assert len(botao) == 1 and f["ctl00$cphHeader$ScriptManager1"] == "ctl00$cphContent$UpdatePanel1|" + botao[0]
    if f.get("__VIEWSTATE") != ESTADO["viewstate"]:
        msg = "viewstate desatualizado"
        h._enviar("{}|error|500|{}|".format(len(msg), msg), "text/plain; charset=utf-8")
        return True
    n = int(botao[0].split("$ctl")[1].split("$")[0])
    nome, _sit = turma["alunos"][n]
    ESTADO["pedidos"].append(nome)
    novo = "VS{}".format(len(ESTADO["pedidos"]))
    ESTADO["viewstate"] = novo
    if turma["codigo"].endswith("(com erro)") and n == 1:
        ESTADO["relatorio"] = None
        resposta = "{}|hiddenField|__VIEWSTATE|{}|".format(len(novo), novo)
    else:
        ESTADO["relatorio"] = (turma, nome, semestre)
        script = "window.open('/RelatorioVisualizarImpressao.aspx','blank','scrollbars=1');"
        resposta = "{}|hiddenField|__VIEWSTATE|{}|{}|scriptStartupBlock|ScriptContentNoTags|{}|".format(
            len(novo), novo, len(script), script)
    h._enviar(resposta, "text/plain; charset=utf-8")
    return True
