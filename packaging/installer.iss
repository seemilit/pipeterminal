[Setup]
AppId={#ProductName}
AppName=PipeTerminal
AppVersion={#ProductVersion}
DefaultDirName={localappdata}\Programs\{#ProductName}
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\PipeTerminal.exe
Compression=lzma2
SolidCompression=yes

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"
