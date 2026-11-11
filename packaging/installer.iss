[Setup]
AppId={#ProductName}
AppName=PipeTerminal
AppVersion={#ProductVersion}
DefaultDirName={localappdata}\Programs\{#ProductName}
DisableDirPage=no
AppendDefaultDirName=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\PipeTerminal.exe
Compression=lzma2
SolidCompression=yes

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"; Tasks: desktopicon
