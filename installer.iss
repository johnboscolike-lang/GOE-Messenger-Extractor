; GOE메신저 추출기 - Inno Setup 설치 스크립트
; 빌드: ISCC.exe installer.iss

#define MyAppName "GOE메신저 추출기"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "김포과학기술고등학교"
#define MyAppExeName "GOE메신저추출기.exe"

[Setup]
AppId={{8F3B2A1C-D4E5-6F7A-8B9C-0D1E2F3A4B5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GOE메신저추출기
DefaultGroupName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=GOE메신저추출기_Setup_{#MyAppVersion}
SetupIconFile=
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

; 한국어 지원
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "GOE메신저 추출기 실행"; Flags: nowait postinstall skipifsilent

[Code]
// 설치 성공 시 종료 코드 0 반환
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
