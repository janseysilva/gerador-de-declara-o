@echo off
rem Abre o Declaracoes Escolares direto do codigo (para testar, sem instalar).
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py
echo Preparando (so demora na primeira vez)...
%PY% -m pip install --quiet --disable-pip-version-check reportlab python-docx pillow
if errorlevel 1 (
  echo.
  echo Nao consegui instalar os componentes. Confira se o Python esta instalado.
  pause
  exit /b 1
)
start "" %PY%w declaracoes_escolares.py 2>nul || %PY% declaracoes_escolares.py
