; Inno Setup script for the Windows installer (VL-Setup-x86_64.exe).
;   iscc /DAppVersion=0.1.0 packaging\vl.iss
; Installs dist\VL (PyInstaller) for the current user; no admin rights needed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=Visual Language
AppVersion={#AppVersion}
AppPublisher=mostodont01
DefaultDirName={autopf}\Visual Language
DefaultGroupName=Visual Language
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VL-Setup-x86_64
SetupIconFile=vl.ico
UninstallDisplayIcon={app}\VL.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\VL\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Visual Language"; Filename: "{app}\VL.exe"
Name: "{autodesktop}\Visual Language"; Filename: "{app}\VL.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VL.exe"; Description: "Start Visual Language"; Flags: nowait postinstall skipifsilent
