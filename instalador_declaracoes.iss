; ============================================================
;  Instalador do "Declarações Escolares"
;  Compilar com:  ISCC.exe instalador_declaracoes.iss
;  (antes: python -m PyInstaller DeclaracoesEscolares.spec)
; ============================================================

#define MeuApp        "Declarações Escolares"
#define MeuAppVersao  "2.11"
#define MeuAutor      "Jansey Felix Silva"
#define MeuExe        "DeclaracoesEscolares.exe"

[Setup]
; O AppId NAO muda entre versoes: e ele que faz o instalador novo substituir o antigo.
AppId={{AB69085C-D528-447F-BE53-1E8A0F6B5A01}
AppName={#MeuApp}
AppVersion={#MeuAppVersao}
AppVerName={#MeuApp} {#MeuAppVersao}
AppPublisher={#MeuAutor}
DefaultDirName={autopf}\Declaracoes Escolares
DefaultGroupName={#MeuApp}
DisableProgramGroupPage=yes
OutputDir=..\
OutputBaseFilename=Instalador_DeclaracoesEscolares
SetupIconFile=icone_declaracoes.ico
UninstallDisplayIcon={app}\{#MeuExe}
UninstallDisplayName={#MeuApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Instala so para o usuario atual: nao pede senha de administrador
; (evita travar nos computadores da rede da escola).
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Se o programa estiver aberto, o instalador fecha antes de trocar o arquivo
; (senão dá "DeleteFile falhou; código 5. Acesso negado").
CloseApplications=force

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; \
    GroupDescription: "Atalhos:"

[Files]
Source: "dist\{#MeuExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIA-ME.txt";    DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MeuApp}";              Filename: "{app}\{#MeuExe}"
Name: "{group}\Como usar (Leia-me)";    Filename: "{app}\LEIA-ME.txt"
Name: "{group}\Desinstalar {#MeuApp}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MeuApp}";        Filename: "{app}\{#MeuExe}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MeuExe}"; \
    Description: "Abrir o {#MeuApp} agora"; \
    Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MeuExe}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Sleep(800);
  Result := '';
end;
