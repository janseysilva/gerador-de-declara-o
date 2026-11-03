# Declarações Escolares

Programa para Windows (Python + tkinter), com o mesmo visual do Frequência Inteligente, que gera as declarações escolares da SEMED Manaus.

O programa lê o arquivo de alunos exportado do sistema da SEMED (`TXTALUNO_xxxxx.txt`) e guarda os alunos como banco de dados no computador. Na tela, você pesquisa o aluno pelo nome ou pelo código, escolhe o tipo e clica em **Gerar declaração**. O PDF (ou Word) abre pronto para imprimir.

Tipos: Matrícula, Frequência, Transferência, Conclusão, Vaga e Comparecimento. A data vem do relógio do computador, e o número da declaração (Nº 001/2026) sobe sozinho.

## Baixar o instalador
Na aba **Releases** deste repositório, baixe `Instalador_DeclaracoesEscolares.exe` e dê dois cliques. O instalador é montado num Windows do GitHub só quando alguém pede (aba **Actions** → *Instalador Declarações Escolares* → **Run workflow**); a receita está em `.github/workflows/instalador.yml`.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `declaracoes_escolares.py` | O programa: leitura do TXT, textos, PDF/Word e a janela |
| `DeclaracoesEscolares.spec` | Receita do PyInstaller (gera o `.exe`) |
| `instalador_declaracoes.iss` | Receita do Inno Setup (gera o instalador) |
| `TESTAR.bat` | Abre o programa direto do código, para testar |
| `GERAR_INSTALADOR.bat` | Gera o `.exe` e o instalador no próprio PC |
| `LEIA-ME.txt` | Guia de uso (vai junto no instalador) |
| `versao-navegador/` | Primeira versão, como página HTML (não é mais usada) |

## Gerar no próprio PC
```
pip install -r requirements.txt
python -m PyInstaller DeclaracoesEscolares.spec
ISCC.exe instalador_declaracoes.iss
```
A versão fica em `VERSAO_PROGRAMA` (arquivo `.py`) e em `MeuAppVersao` (arquivo `.iss`). Mantenha as duas iguais.

## Privacidade
Este repositório não contém dados de alunos (o `.gitignore` bloqueia `TXTALUNO*.txt`). Os dados ficam só em `%APPDATA%\Declaracoes Escolares` no computador de quem usa.
