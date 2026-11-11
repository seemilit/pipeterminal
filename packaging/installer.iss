[Setup]
AppId={#ProductName}
AppName=PipeTerminal
AppVersion={#ProductVersion}
DefaultDirName={localappdata}\Programs\{#ProductName}
DisableDirPage=no
AppendDefaultDirName=yes
DisableProgramGroupPage=yes
ShowLanguageDialog=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\PipeTerminal.exe
Compression=lzma2
SolidCompression=yes

; Chinese messages are from jrsoftware/issrc, tag is-6_7_1.
[Languages]
Name: en; MessagesFile: "compiler:Default.isl"
Name: zh_CN; MessagesFile: "installer-languages\ChineseSimplified.isl"
Name: zh_TW; MessagesFile: "installer-languages\ChineseTraditional.isl"
Name: ja; MessagesFile: "compiler:Languages\Japanese.isl"
Name: ko; MessagesFile: "compiler:Languages\Korean.isl"
Name: es; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

#if ProductName == "PipeTerminal-Paid"
[InstallDelete]
Type: files; Name: "{autoprograms}\{#ProductName}.lnk"
#endif

[Icons]
#if ProductName == "PipeTerminal-Paid"
Name: "{autoprograms}\PipeTerminal"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"
#else
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"
#endif
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\PipeTerminal.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,PipeTerminal}"; Flags: postinstall nowait skipifsilent
