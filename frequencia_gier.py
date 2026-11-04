"""Leitura do PDF "Acompanhamento Diario" exportado do Gier (SEMED Manaus).

Codigo copiado do Frequencia Inteligente (janseysilva/frequencia-inteligente,
gerar_relatorio_presenca_GUI.py), que ja le esse mesmo relatorio.
"""
import re
import unicodedata

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None
try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

SITUACOES = {"MA", "TR", "TF", "NC"}

# Dia sem aula para o aluno (antes da matricula / apos transferencia).
# Nao conta como dia letivo. Varios tracos Unicode aparecem em PDFs.
TRACOS = {"-", "‐", "‑", "‒", "–", "—", "−"}

RE_DATA = re.compile(r"^\d{2}/\d{2}$")
RE_INICIO_ALUNO = re.compile(r"^\d+\s")
RE_TURMA = re.compile(r"Turma:\s*(.+?)\s+Componente\s+Curricular:", re.IGNORECASE)
RE_TURMA_SIMPLES = re.compile(r"Turma:\s*(\S+)")

# Algumas escolas (ex. CMEI Ismail Aziz) imprimem só uma coluna de total
# ("Faltas", combinando justificadas e normais) e listam as faltas
# justificadas à parte, numa tabela "Faltas Justificadas" no fim do PDF.
RE_TITULO_FALTAS_JUST = re.compile(
    r"Faltas\s+Justificadas\s*-\s*M[eê]s:?\s*([A-Za-zÀ-ú]*)", re.IGNORECASE)
# Titulo de cada pagina-mes do Acompanhamento Diario. Um mesmo PDF pode trazer
# VARIOS meses (ex.: Janeiro a Agosto, uma pagina por mes).
RE_TITULO_DIARIO = re.compile(
    r"Acompanhamento\s+Di[aá]rio\s*-\s*M[eê]s:\s*([A-Za-zÀ-ú]+)", re.IGNORECASE)
RE_LINHA_FALTA_JUST = re.compile(r"^\d+\s+(.+?)\s+\d{2}/\d{2}\s+.+$")
RE_ESCOLA = re.compile(r"Escola:\s*(.+?)\s+Ano\s+Letivo:", re.IGNORECASE)
RE_ANO = re.compile(r"Ano\s+Letivo:\s*(\d{4})", re.IGNORECASE)
RE_MES = re.compile(r"M[\wê\xad]*s:\s*([A-Za-zÀ-ú]+)")

RE_FORMULARIO_MEC = re.compile(
    r"Acompanhamento\s+de\s+Frequ[êe]ncia\s+Escolar", re.IGNORECASE
)



def normalizar(nome):
    """Maiusculas, sem acentos, sem pontuacao, espacos colapsados."""
    if not nome:
        return ""
    txt = unicodedata.normalize("NFKD", nome)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.upper()
    txt = re.sub(r"[^A-Z ]", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def eh_continuacao_de_nome(tokens):
    """
    Nomes longos quebram em duas linhas no PDF. A linha seguinte e continuacao
    do nome se for so texto em maiusculas, sem token de situacao e sem data.
    """
    if not tokens:
        return False
    for t in tokens:
        if t in SITUACOES:
            return False
        if RE_DATA.match(t):
            return False
        if not re.fullmatch(r"[A-ZÀ-Ú'\.]+", t):
            return False
        # A regua de dias da semana ("S T Q Q S S D S T ...") repetida no
        # cabecalho de cada pagina passaria em todos os testes acima.
        # Sobrenomes tem 2+ letras; letras isoladas nunca sao continuacao.
        if len(t) < 2:
            return False
    return any(len(t) >= 3 for t in tokens)


def parsear_linha_aluno(linha, turma):
    """
    Converte uma linha de aluno em dict, ou devolve None se nao for linha de aluno.

    Formato:
      Nº | Estudante | Sit. | Entr. | Saida | 01..30 | Total Falta | Total Falta Comp.
    Ex.:
      19 SAYLON GAMA DOS SANTOS MA 22/12 F F F FJ FJ • F F 8 5
    """
    tokens = linha.split()
    if len(tokens) < 5:
        return None
    if not tokens[0].isdigit():
        return None

    # Localiza a situacao para saber onde o nome termina.
    idx_sit = None
    for i, t in enumerate(tokens):
        if t in SITUACOES:
            idx_sit = i
            break
    if idx_sit is None or idx_sit < 2:
        return None

    nome = " ".join(tokens[1:idx_sit])
    situacao = tokens[idx_sit]

    if not tokens[-1].isdigit():
        return None
    # A maioria das escolas imprime 2 colunas de total no fim da linha
    # (Faltas e Faltas Comp./Justificadas). Algumas (ex. CMEI Ismail Aziz)
    # só têm 1 coluna combinada - nesse caso as justificadas vêm de uma
    # tabela separada "Faltas Justificadas", somadas depois em
    # extrair_dados_pdf.
    if tokens[-2].isdigit():
        n_totais = 2
        total_falta = int(tokens[-2])
        total_falta_comp = int(tokens[-1])
    else:
        n_totais = 1
        total_falta = int(tokens[-1])
        total_falta_comp = 0

    # Depois da situacao vem 1 ou 2 datas DD/MM (entrada e, opcionalmente, saida).
    i = idx_sit + 1
    datas = 0
    while i < len(tokens) - n_totais and datas < 2 and RE_DATA.match(tokens[i]):
        i += 1
        datas += 1

    simbolos = tokens[i:len(tokens) - n_totais]

    # Dias letivos = quantidade de simbolos, ignorando os tracos.
    # Contagem agnostica de glifo: o bullet de presenca pode ser extraido
    # como •, ·, ● etc. dependendo da fonte do PDF.
    dias_letivos = sum(1 for s in simbolos if s not in TRACOS)

    return {
        "numero": int(tokens[0]),
        "nome": nome,
        "situacao": situacao,
        "turma": turma,
        "dias_letivos": dias_letivos,
        "faltas": total_falta,
        "faltas_justificadas": total_falta_comp,
        # True quando a ficha so traz UMA coluna de total (faltas + justificadas
        # juntas); so essas linhas usam a tabela "Faltas Justificadas".
        "total_unico": n_totais == 1,
        "simbolos": simbolos,
        # Recontagem dos simbolos, usada apenas para detectar divergencia
        # com os totais impressos (o calculo usa os totais impressos).
        "faltas_contadas": sum(1 for s in simbolos if s == "F"),
        "fj_contadas": sum(1 for s in simbolos if s == "FJ"),
    }


def extrair_cabecalho(texto):
    """Escola, mes e ano letivo, lidos do proprio PDF."""
    escola = RE_ESCOLA.search(texto)
    ano = RE_ANO.search(texto)
    mes = RE_MES.search(texto)
    return {
        "escola": escola.group(1).strip() if escola else "",
        "ano": ano.group(1).strip() if ano else "",
        "mes": mes.group(1).strip().capitalize() if mes else "",
    }


def _textos_pdf_rapido(caminho_pdf, max_paginas=None):
    """
    Texto de cada pagina lido pelo PDFium, que e dezenas de vezes mais rapido
    que o pdfplumber nessas fichas cheias de celulas (um ano inteiro de uma
    escola levava ~8 min). Devolve None se o PDFium nao estiver disponivel ou
    falhar - ai quem chama usa o pdfplumber. `max_paginas` limita quantas
    paginas ler (ex.: 1, so pra descobrir o tipo da ficha).
    """
    try:
        import pypdfium2 as pdfium
        documento = pdfium.PdfDocument(caminho_pdf)
    except Exception:
        return None
    try:
        textos = []
        total_paginas = len(documento)
        if max_paginas:
            total_paginas = min(total_paginas, max_paginas)
        for i in range(total_paginas):
            pagina = documento[i]
            try:
                textpage = pagina.get_textpage()
                try:
                    textos.append(_texto_pagina_pdfium(textpage))
                finally:
                    textpage.close()
            finally:
                pagina.close()
        return textos
    except Exception:
        return None
    finally:
        documento.close()


def _texto_pagina_pdfium(textpage, tol_y=3.0, tol_x=3.0):
    """
    Remonta as linhas de uma pagina do PDFium pela POSICAO dos caracteres
    (mesma ideia do pdfplumber: mesma altura = mesma linha, da esquerda para a
    direita). O texto "bruto" do PDFium sai na ordem do arquivo e separa os
    dados de um aluno quando o nome quebra em duas linhas.
    """
    import pypdfium2.raw as pdfium_c

    total = textpage.count_chars()
    if total <= 0:
        return ""

    itens = []                  # (altura, esq, dir, caractere, espaco_antes)
    espaco_antes = False
    for i in range(total):
        # O codigo de cada caractere vem direto do indice (get_text_range pode
        # devolver menos caracteres que count_chars e desalinharia as caixas).
        ch = chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i))
        if ch.isspace() or ch in "\x00￾￿":
            espaco_antes = True
            continue
        esq, base, dire, topo = textpage.get_charbox(i)
        if dire <= esq and topo <= base:
            continue
        itens.append(((base + topo) / 2.0, esq, dire, ch, espaco_antes))
        espaco_antes = False

    itens.sort(key=lambda x: -x[0])
    linhas, atual, ultimo = [], [], None
    for item in itens:
        if ultimo is not None and ultimo - item[0] > tol_y:
            linhas.append(atual)
            atual = []
        atual.append(item)
        ultimo = item[0]
    if atual:
        linhas.append(atual)

    saida = []
    for linha in linhas:
        linha.sort(key=lambda x: x[1])
        partes, fim_anterior = [], None
        for _, esq, dire, ch, antes in linha:
            if fim_anterior is not None and (antes or esq - fim_anterior > tol_x):
                partes.append(" ")
            partes.append(ch)
            fim_anterior = dire if fim_anterior is None else max(fim_anterior, dire)
        saida.append("".join(partes))
    return "\n".join(saida)


def _textos_pdf_pdfplumber(caminho_pdf):
    """Texto de cada pagina lido pelo pdfplumber (mais lento, uma por vez)."""
    if pdfplumber is None:
        return []
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            yield pagina.extract_text() or ""


def extrair_dados_pdf(caminho_pdf):
    """
    Le um PDF de Acompanhamento Diario. Devolve (alunos, info_cabecalho).
    Tenta primeiro a leitura rapida (PDFium); se ela nao achar nenhum aluno,
    refaz com o pdfplumber.
    """
    textos = _textos_pdf_rapido(caminho_pdf)
    if textos:
        alunos, info = _extrair_dados_textos(textos)
        if alunos or info["formulario_mec"]:
            return alunos, info
    return _extrair_dados_textos(_textos_pdf_pdfplumber(caminho_pdf))


def _extrair_dados_textos(paginas_texto):
    """
    Interpreta o texto das paginas (iteravel) de um Acompanhamento Diario.

    O PDF pode trazer varios meses (uma pagina-mes depois da outra). Cada aluno
    sai com o campo "mes" do bloco em que apareceu; `info["meses"]` lista os
    meses encontrados, na ordem do arquivo.
    """
    alunos = []
    turma_atual = "?"
    info = {"escola": "", "ano": "", "mes": "", "meses": [],
            "formulario_mec": False}
    faltas_just = {}            # (mes, nome) -> quantas faltas justificadas
    mes_atual = ""
    mes_just = ""
    em_faltas_justificadas = False

    for numero, texto in enumerate(paginas_texto):
        # Uma copia do formulario do MEC guardada junto das fichas nao e
        # uma turma: tem 60+ paginas e nenhuma linha de aluno.
        if numero == 0 and RE_FORMULARIO_MEC.search(texto):
            info["formulario_mec"] = True
            return [], info

        if not info["escola"]:
            info.update(extrair_cabecalho(texto))

        for linha in texto.split("\n"):
            linha = linha.strip()
            if not linha:
                continue

            # Comeca um novo mes (nova pagina-mes do mesmo PDF).
            m_mes = RE_TITULO_DIARIO.search(linha)
            if m_mes:
                mes_atual = m_mes.group(1).strip().capitalize()
                em_faltas_justificadas = False
                if mes_atual not in info["meses"]:
                    info["meses"].append(mes_atual)
                continue

            m_fj_titulo = RE_TITULO_FALTAS_JUST.search(linha)
            if m_fj_titulo:
                em_faltas_justificadas = True
                mes_just = (m_fj_titulo.group(1).strip().capitalize()
                            or mes_atual)
                continue

            # Tabela "Faltas Justificadas" (Nº, Estudante, Data, Motivo):
            # conta quantas faltas justificadas cada aluno teve NAQUELE
            # mes, para somar depois nas fichas de coluna de total unica.
            if em_faltas_justificadas:
                m_fj = RE_LINHA_FALTA_JUST.match(linha)
                if m_fj:
                    chave = (mes_just, m_fj.group(1).strip())
                    faltas_just[chave] = faltas_just.get(chave, 0) + 1
                continue

            m = RE_TURMA.search(linha) or RE_TURMA_SIMPLES.search(linha)
            if m:
                turma_atual = " ".join(m.group(1).strip().split())
                continue

            aluno = parsear_linha_aluno(linha, turma_atual)
            if aluno:
                aluno["mes"] = mes_atual
                alunos.append(aluno)
                continue

            # Possivel continuacao do nome do aluno anterior.
            if alunos and not RE_INICIO_ALUNO.match(linha):
                if eh_continuacao_de_nome(linha.split()):
                    alunos[-1]["nome"] += " " + linha.strip()

    # PDF sem titulo de mes reconhecivel: usa o mes do cabecalho.
    for aluno in alunos:
        if not aluno["mes"]:
            aluno["mes"] = info["mes"]
    if not info["meses"] and info["mes"]:
        info["meses"].append(info["mes"])

    # Fichas de coluna de total unica (ex.: CMEI Ismail Aziz): a coluna
    # "Faltas" do quadro principal e o total combinado (justificadas +
    # normais). Usa a tabela "Faltas Justificadas" pra separar os dois
    # numeros. Fichas de DUAS colunas ja trazem os dois totais prontos
    # (fonte da verdade) e nao sao mexidas.
    if faltas_just:
        for aluno in alunos:
            if not aluno.get("total_unico"):
                continue
            qtd_just = faltas_just.get((aluno["mes"], aluno["nome"]))
            if qtd_just and aluno["faltas_justificadas"] == 0:
                aluno["faltas_justificadas"] = qtd_just
                aluno["faltas"] = max(0, aluno["faltas"] - qtd_just)
                # Os simbolos do quadro principal nao distinguem falta
                # normal de justificada nessas fichas (so marcam "F" pra
                # ambas) - a recontagem de conferencia tem que acompanhar
                # o ajuste, senao acusaria divergencia por engano.
                aluno["faltas_contadas"] = aluno["faltas"]
                aluno["fj_contadas"] = aluno["faltas_justificadas"]

    return alunos, info


def calcular_presenca(aluno):
    """Aplica as regras de calculo e devolve (presencas, percentual, observacao)."""
    dias = aluno["dias_letivos"]
    faltas = aluno["faltas"]
    fj = aluno["faltas_justificadas"]

    # Aluno matriculado no fim do mes: sem simbolo nenhum.
    if dias == 0:
        return None, None, "Sem dias letivos registrados no mes"

    presencas = dias - faltas - fj

    # Inconsistencia do PDF de origem (ocorre em transferidos no meio do mes):
    # o total impresso nao bate com os simbolos da linha.
    if presencas < 0:
        return (
            presencas,
            None,
            "CONFERIR MANUALMENTE: total de faltas impresso no PDF ({} + {}) "
            "maior que os {} dias letivos da linha".format(faltas, fj, dias),
        )

    percentual = round(presencas / dias * 100, 2)

    # Mesma inconsistencia, porem sem estourar para negativo: o percentual sai
    # plausivel e passaria despercebido. Calculo segue pelo total impresso
    # (fonte da verdade), mas a linha e sinalizada para conferencia.
    f_contadas = aluno.get("faltas_contadas")
    fj_contadas = aluno.get("fj_contadas")
    if f_contadas is not None and (f_contadas != faltas or fj_contadas != fj):
        return (
            presencas,
            percentual,
            "CONFERIR MANUALMENTE: o PDF imprime {} falta(s) e {} falta(s) "
            "justificada(s), mas a linha tem {} e {}. Confira na ficha "
            "original".format(faltas, fj, f_contadas, fj_contadas),
        )

    return presencas, percentual, ""


