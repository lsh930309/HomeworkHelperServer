; HomeworkHelper Inno Setup Installer Script
; Inno Setup 6.x 이상 필요 (https://jrsoftware.org/isinfo.php)

#define MyAppName "HomeworkHelper"
#define MyAppVersion "1.0.8"
#define MyAppPublisher "lsh930309"
#define MyAppURL "https://github.com/lsh930309/HomeworkHelper"
#define MyAppExeName "homework_helper.exe"

[Setup]
; 기본 정보
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 설치 경로
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 출력 설정
OutputDir=installer_output
OutputBaseFilename=HomeworkHelper_Setup_v{#MyAppVersion}
SetupIconFile=img\app_icon.ico

; 압축
Compression=lzma2
SolidCompression=yes

; Windows 버전 요구사항
MinVersion=10.0

; 관리자 권한 (Program Files 설치를 위해 필요)
PrivilegesRequired=admin

; 아키텍처 (64비트)
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

; UI 설정
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir 결과물 전체 복사
Source: "dist\homework_helper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: recursesubdirs 플래그로 _internal 폴더 및 모든 하위 폴더 포함

[Icons]
; 시작 메뉴
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; 바탕화면 바로가기 (사용자 선택 시)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 설치 완료 후 프로그램 실행 옵션
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 앱이 생성한 데이터는 사용자 AppData에 있으므로 여기서는 삭제하지 않음
; 필요 시 사용자에게 안내 메시지만 표시

[Code]
// 이전 버전 확인 및 제거
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  UninstallString: String;
begin
  Result := True;

  // 레지스트리에서 이전 버전 확인
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1',
    'UninstallString', UninstallString) then
  begin
    if MsgBox('HomeworkHelper가 이미 설치되어 있습니다. 이전 버전을 제거하시겠습니까?',
      mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec(UninstallString, '/SILENT', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end
    else
    begin
      Result := False;
    end;
  end;
end;
