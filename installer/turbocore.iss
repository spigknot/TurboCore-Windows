; TurboCore — instalador (Inno Setup 6)
; Gerado pelo tc_release.py com -DAppVersion=<versao>.
#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
AppId={{063d5e0a-2ecb-4788-b797-97354d0911b6}
AppName=TurboCore
AppVersion={#AppVersion}
AppPublisher=TurboCore
DefaultDirName={autopf}\TurboCore
DefaultGroupName=TurboCore
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release\generated\{#AppVersion}
OutputBaseFilename=setup_turbocore_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\TurboCore.exe
SetupLogging=yes

[Files]
; Arvore completa do package validado pelo tc_release.py.
Source: "..\release\generated\{#AppVersion}\package\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Dirs]
; O app e o updater escrevem na pasta em runtime SEM admin.
Name: "{app}"; Permissions: users-modify

[Icons]
Name: "{autodesktop}\TurboCore"; Filename: "{app}\TurboCore.exe"; WorkingDir: "{app}"; Comment: "TurboCore - limitador de cores da CPU"
Name: "{autoprograms}\TurboCore\TurboCore"; Filename: "{app}\TurboCore.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\TurboCoreUpdater"; Filename: "{app}\TurboCoreUpdater.exe"; WorkingDir: "{app}"; Comment: "Atualizar ou reparar o TurboCore"
Name: "{autoprograms}\TurboCore\TurboCoreUpdater"; Filename: "{app}\TurboCoreUpdater.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\TurboCore\Desinstalar TurboCore"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\TurboCore.exe"; Description: "Abrir o TurboCore agora"; Flags: nowait postinstall skipifsilent
