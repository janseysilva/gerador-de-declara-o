@echo off
rem Gera o DeclaracoesEscolares.exe (pasta dist) e o instalador (pasta de cima).
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto erro
%PY% -m PyInstaller --noconfirm DeclaracoesEscolares.spec || goto erro
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% instalador_declaracoes.iss || goto erro
  echo.
  echo Pronto: Instalador_DeclaracoesEscolares.exe esta na pasta de cima.
) else (
  echo.
  echo Pronto: dist\DeclaracoesEscolares.exe
  echo (Inno Setup nao encontrado; o instalador nao foi gerado.)
)
pause
exit /b 0
:erro
echo.
echo Deu erro. Copie a mensagem acima e mande para o Claude.
pause
exit /b 1
