# Declarações Escolares: regras e andamento (leia antes de tudo)

Programa do Windows (Python + tkinter) feito para o Jansey, do CMEI Argentina Barros (SEMED Manaus). Gera declarações escolares a partir do arquivo de alunos do sistema da SEMED. Tem o visual do **Frequência Inteligente** (repositório `janseysilva/frequencia-inteligente`), de onde vieram cores, faixa azul, quadros numerados, pílulas (`Chip`) e botões (`Botao`).

## Regras do Jansey
1. Responder sempre em **português (pt-BR)**.
2. **Só montar o instalador quando ele mandar** ("gera o instalador"). A receita do GitHub (`.github/workflows/instalador.yml`) roda **só por `workflow_dispatch`**: enviar código para o `main` não monta nada. Para montar, use `actions_run_trigger` → `run_workflow`, `workflow_id: instalador.yml`, `ref: main`. O release sai como `v<versão>-build<n>`, e o link direto para mandar é
   `https://github.com/janseysilva/gerador-de-declara-o/releases/download/<tag>/Instalador_DeclaracoesEscolares.exe`
3. Antes de propor um instalador, mostrar como ficou (fotos ou página de revisão). Ele testa no Windows e manda print.
4. Ele não preenche nada à mão: o que está no banco de dados sai sozinho, e o que não está ele preenche **no próprio programa**.
5. Dados reais de alunos **nunca** vão para o GitHub nem para páginas publicadas. Use o arquivo de exemplo inventado (ver "Testes").

## Como o programa funciona (versão 2.3)
- **Configuração:** "Abrir arquivo de alunos" lê o `TXTALUNO_xxxxx.txt` da SEMED (ANSI, colunas separadas por `;`) e **substitui** o banco (`%APPDATA%\Declaracoes Escolares\alunos.json`). Lá também ficam os dados da escola, o gestor(a) e o secretário(a) (nome, cargo, matrícula), a numeração, PDF/Word, a pasta de saída e o logotipo.
- **Tela principal:**
  1. **Pesquisar aluno:** campo + botão Pesquisar (ou Enter). As opções aparecem embaixo. Ao clicar num aluno, o nome vai para o campo e a lista some. Com um só resultado, ele é escolhido sozinho.
  2. **Aluno:** turma, turno, nascimento (com idade), código, sexo, mãe, pai, responsável da matrícula, endereço (com bairro e CEP) e telefones. Tem o botão "Corrigir", que vale só para a declaração.
  3. **Tipo:** Matrícula, Frequência, Transferência, Conclusão, Comparecimento, **Justificativa de falta** e **Termo de compromisso** (CEMASP). A opção Vaga foi removida a pedido dele.
  - **Quem assina:** Gestor(a) ou Secretário(a), ao lado do botão Gerar.
- A data e o ano letivo vêm do relógio do PC. A numeração "Nº 001/2026" sobe sozinha, mas não vale para os termos.
- **Matrícula:** sai sem o nome da mãe e do pai (`SEM_FILIACAO`).
- **Comparecimento:** pílulas com os responsáveis do arquivo, e "Outra pessoa" para digitar. Entrada e saída no formato 00:00, com máscara.
- **Justificativa de falta:** no quadro 3 se preenchem data e quantidade de faltas, Bolsa Família, motivo (com "Outro" e o campo "Qual?") e o responsável. O responsável é escolhido em pílulas Mãe/Pai/Responsável/Outro; "Outro" abre o campo Nome. O WhatsApp vem do arquivo.
- **Termo de compromisso (CEMASP):** responsável em pílulas (como acima), CPF ao lado com máscara (vem do arquivo quando o escolhido é quem fez a matrícula; ao trocar de pessoa, é apagado), profissão e horário. Endereço, bairro, telefone, série, turma e turno saem do arquivo. "pai/mãe/responsável" é marcado conforme o nome.
- **Frequência do Gier (2.3):** o Gier (site da SEMED, Relatório de Frequência Diária, filtro 348) exporta o PDF "Acompanhamento Diário - Mês: X" (Reporting Services), o mesmo que o Frequência Inteligente lê. `frequencia_gier.py` é cópia do leitor do FI (pypdfium2 rápido, pdfplumber de reserva). Configuração → "Abrir frequência do Gier (PDF)..." (vários PDFs de uma vez) grava `frequencia.json` (`meses → nome normalizado → dias/faltas/fj/pct`; um mês reaberto é atualizado). O aluno é casado pelo nome (igual ou difflib 0,87). Quadro 2 mostra "X% de presença · N falta(s) (Ago a Out)". Na declaração de Frequência: combobox "Período" (Todos os meses / cada mês) preenche a %; o texto diz "no mês de outubro" / "no período de agosto a outubro"; % digitada à mão volta a "até a presente data". Com o PDF real (PE II Turma A, outubro, 20 linhas): 18 casaram; 1 transferida (TR) não está no TXT e 1 tem sobrenome diferente no Gier e no TXTALUNO (o programa avisa e deixa digitar).
- Busca automática no site do Gier (com login do Jansey): adiada; ele não conseguiu salvar a página de download (Ctrl+S), e o PDF resolve por enquanto.
- O instalador (Inno Setup) fecha o programa aberto antes de atualizar (`taskkill` no `[Code]`).
- **Fonte Arial, 20% maior** (`FONTE`, `AUMENTO_LETRA = 1.2`, aplicado no `tk scaling`), escolhida pelo Jansey a partir das imagens de revisão. O programa **abre maximizado** (`_maximizar`), e o texto do quadro 2 quebra conforme a largura (`_ajustar_quebras`).
- **Telas baixas (altura < 900, ex.: 1366x768 do outro PC da escola):** faixa azul mais baixa (66 em vez de 92). O espaço das opções da pesquisa só aparece quando há resultado. A tela principal e a Configuração ficam dentro de `AreaRolavel`, que ganha barra de rolagem sozinha quando falta espaço (a rodinha do mouse rola). Quando o conteúdo muda de altura, `_reajustar()` acerta a barra na hora.

## Arquivo da SEMED (TXTALUNO)
- Formato atual com 40 colunas, entre elas: `Ano da Matrícula` (2026, **não** é código), `Nome Resp. Matrícula` → responsavel, `CPF do responsável` (sem os zeros da frente: `formatar_cpf` completa), `Codigo do Aluno`, `Nome do Aluno`, `Nome Social`, `Data de Nascimento`, `Nome da Mãe`, `Nome do Pai`, `Sexo`, `Bairro do Aluno`, `Endereço do Aluno`, `CEP do Aluno`, `Telefone`, `Telefone Altern`, `Fase` (1 PERIODO / 2 PERIODO), `Turma`, `Turno`.
- `_escolher_colunas` decide entre colunas parecidas pelo conteúdo: valores distintos, "cara" do dado e preferência por títulos com "aluno".
- O CMEI tem 368 alunos, só da Educação Infantil. Ensino Fundamental e EJA funcionam no texto ("no 5º ano do Ensino Fundamental – Anos Iniciais", "na 1ª etapa da EJA"), mas **não foram testados com arquivo real**.

## Testes (no contêiner Linux)
- Python com tkinter: `/usr/bin/python3.12`. Instalar com `--break-system-packages`: reportlab, python-docx, pillow. Rodar a janela com `xvfb-run -a -s "-screen 0 1920x1080x24"`. Para fotografar, usar `PIL.ImageGrab.grab(bbox=..., xdisplay=os.environ["DISPLAY"])`.
- Para simular o Windows, usar `tk scaling 1.3333` (96 dpi) antes de criar a janela; o programa multiplica por 1,2 → 1,6. Como o Xvfb não maximiza, usar `app.geometry("LxA+0+0")`.
- **Teste de todas as telas** (o Jansey pediu): os 7 tipos, as variações com "Outro", a janela Corrigir e a Configuração, em 1920×1080, 1600×900, 1366×768 (maximizada e restaurada 960×688), 1280×720 e 1024×768. Ele procura qualquer Label/Entry/Combobox/Canvas mais estreito ou mais baixo que o pedido, ou fora da janela. Na versão 2.1, não houve nenhum problema.
- Arquivo de exemplo inventado (mesmas 40 colunas): gerar de novo a partir do cabeçalho do TXTALUNO real, com nomes, CPFs e telefones inventados. **Não commitar.**

## Pendências / ideias
- **Versão atual em uso: v2.1-build14** (04/11/2026). O Jansey instalou e aprovou ("deu certo"), nos dois PCs da escola: o dele (1920x1080) e o de tela menor (1366x768). Ela corrigiu os cortes que a v1.9 tinha no PC de tela menor.
- **Versão 2.3 no `main`, sem instalador ainda:** frequência do Gier (ver acima). Teste de todas as telas sem problemas (a Configuração em janela < 1000 de largura usa margem 10 em vez de 22, porque os itens novos fazem a barra de rolagem aparecer).
- **Versão 2.2** (incluída na 2.3) (ele pediu para não montar): o cursor da barra de pesquisa ficava escondido atrás da frase cinza. Agora a frase começa depois do cursor (`_x_dica`), o cursor é mais grosso e pisca (`insertontime/insertofftime`), e o campo recebe o foco ao abrir (`_focar_pesquisa`) e ao clicar na barra ou na lupa. Montar o instalador só quando ele pedir.
- O release **v1.8-build12** foi montado sem querer, porque ele pediu para não montar logo depois. Ele pode apagá-lo em Releases.
- Página de revisão com fotos e documentos (artifact): https://claude.ai/artifact/GeF7noaEdUPEtnX5biJv1k (mostra a 1.6; atualizar quando for revisar de novo).
- `versao-navegador/` tem a primeira versão em HTML, que não é mais usada.
