#define AppName "Oni Thermal LCD Control"
#define AppVersion "0.1.0"
#define AppPublisher "Oni Thermal LCD contributors"
#define AppExeName "Oni Thermal LCD Control.exe"

[Setup]
AppId={{8A71E29B-7E5B-4A61-9E2E-B79A7F6EF5A1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\Oni Thermal LCD Control
DefaultGroupName=Oni Thermal LCD Control
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=Oni-Thermal-LCD-Control-Setup
SetupIconFile=..\assets\oni-thermal-lcd.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Oni Thermal LCD Control"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Oni Thermal LCD Control"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; User settings and profiles live outside {app}. The standard uninstaller removes
; installed application files and shortcuts but deliberately leaves user data intact.
