; ProjectionAI Windows installer script (Inno Setup 6).
;
; The portable zip (dist/ProjectionAI-<ver>-win64.zip, built by
; scripts/build_package.ps1) is the primary distribution artifact on
; machines without Inno Setup. This script produces a proper MSI-style
; installer when ISCC.exe is available.
;
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/ProjectionAI.iss

#define MyAppName "ProjectionAI"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "ProjectionAI Team"
#define MyAppExeName "ProjectionAI.exe"

[Setup]
AppId={{8F3E2A1C-5B4D-4E6F-9A0B-ProjectionAI}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ProjectionAI-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ProjectionAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent