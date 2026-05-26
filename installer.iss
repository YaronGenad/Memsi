; installer.iss — Inno Setup script for Memsi Interface
; Compile with Inno Setup Compiler (F9 inside Inno Setup IDE)
;
; Expects: dist\PriorityInterface\ to exist (built by `pyinstaller priority_interface.spec`)
; and to contain the bundled app + .env with the production DB credentials.

#define MyAppName "Memsi Interface"
#define MyAppVersion "0.13.5"
#define MyAppPublisher "Newcinema"
#define MyAppExeName "PriorityInterface.exe"

[Setup]
AppId={{A3F7C2E1-9B45-4D8E-A2F1-1C5E8A6D7B0F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MemsiInterface
DefaultGroupName=Memsi Interface
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=Output
OutputBaseFilename=MemsiInterface_Setup_v{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=
SetupIconFile=

; שפה: עברית + אנגלית
[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; כל התיקיה של PyInstaller bundle, כולל ה-.env
Source: "dist\PriorityInterface\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Sprint C7.4: ה-.env מכיל credentials לסביבת-ייצור. מבטיחים שהוא נמחק
; ב-uninstall כדי שלא יישאר על הדיסק אחרי הסרת התקנה.
[UninstallDelete]
Type: files; Name: "{app}\.env"
