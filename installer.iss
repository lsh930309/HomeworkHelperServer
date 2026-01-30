; HomeworkHelper Inno Setup Installer Script
; Inno Setup 6.x 이상 필요 (https://jrsoftware.org/isinfo.php)

#define MyAppName "HomeworkHelper"
#define MyAppVersion "1.1.5"
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
OutputDir=release
OutputBaseFilename=HomeworkHelper_Setup_v{#MyAppVersion}
SetupIconFile=assets\icons\app\app_icon.ico

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
// 실행 중인 프로세스 확인 함수
function IsProcessRunning(ProcessName: String): Boolean;
var
  ResultCode: Integer;
begin
  // tasklist로 프로세스 확인 (ERRORLEVEL 0 = 프로세스 존재)
  Result := Exec('tasklist', '/FI "IMAGENAME eq ' + ProcessName + '" /NH | find /I "' + ProcessName + '"', 
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  
  // 위 방법이 동작하지 않을 경우를 대비한 대체 방식
  // cmd /c 를 사용하여 파이프 명령 실행
  Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq ' + ProcessName + '" 2>NUL | find /I "' + ProcessName + '" >NUL',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

// 프로세스 종료 함수
function KillProcess(ProcessName: String): Boolean;
var
  ResultCode: Integer;
begin
  // taskkill로 프로세스 종료 (/F = 강제, /IM = 이미지 이름)
  Exec('taskkill', '/F /IM ' + ProcessName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0) or (ResultCode = 128); // 128 = 프로세스 없음
end;

// 모든 HomeworkHelper 관련 프로세스 종료
procedure KillAllAppProcesses();
var
  ResultCode: Integer;
begin
  // 메인 GUI 프로세스 종료
  Exec('taskkill', '/F /IM homework_helper.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  
  // 잠시 대기 (프로세스 종료 완료 대기)
  Sleep(500);
  
  // 혹시 남아있을 수 있는 Python 서버 프로세스 종료 (같은 경로에서 실행된 경우)
  // 참고: API 서버는 homework_helper.exe의 자식 프로세스로 실행되므로 부모 종료 시 함께 종료됨
end;

// HomeworkHelper 관련 프로세스가 실행 중인지 확인
function IsAppRunning(): Boolean;
begin
  Result := IsProcessRunning('homework_helper.exe');
end;

// 설치 전 실행 중인 프로세스 종료
function InitializeSetup(): Boolean;
begin
  Result := True;

  // === 실행 중인 HomeworkHelper 프로세스 종료 ===
  // 이전 버전을 삭제하지 않고, 실행 중인 프로세스만 종료합니다.
  // Inno Setup은 동일한 AppId를 감지하면 자동으로 in-place 업그레이드를 수행하며,
  // 이 방식을 사용하면 작업 표시줄에 고정된 아이콘이 유지됩니다.

  if IsAppRunning() then
  begin
    if MsgBox('HomeworkHelper가 현재 실행 중입니다.' + #13#10 + #13#10 +
              '설치를 계속하려면 프로그램을 종료해야 합니다.' + #13#10 +
              '자동으로 종료하고 계속 진행하시겠습니까?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      // 프로세스 종료
      KillAllAppProcesses();

      // 종료 확인을 위해 잠시 대기
      Sleep(1000);

      // 아직도 실행 중인지 확인
      if IsAppRunning() then
      begin
        MsgBox('프로그램을 종료하지 못했습니다.' + #13#10 +
               '수동으로 HomeworkHelper를 종료한 후 설치를 다시 시도해주세요.',
               mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end
    else
    begin
      MsgBox('설치가 취소되었습니다.' + #13#10 +
             'HomeworkHelper를 종료한 후 다시 시도해주세요.',
             mbInformation, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  // 참고: 이전 버전은 자동으로 삭제하지 않습니다.
  // Inno Setup이 동일한 AppId를 감지하면 파일을 덮어쓰는 방식으로 자동 업그레이드됩니다.
  // 이 방식은 작업 표시줄 고정 아이콘을 유지하는 가장 안정적인 방법입니다.
end;

// 설치 전 준비 단계에서 추가 확인 (PrepareToInstall)
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  NeedsRestart := False;
  
  // 마지막으로 프로세스가 종료되었는지 확인
  if IsAppRunning() then
  begin
    // 한 번 더 종료 시도
    KillAllAppProcesses();
    Sleep(1000);
    
    if IsAppRunning() then
    begin
      Result := 'HomeworkHelper가 아직 실행 중입니다. 프로그램을 종료한 후 다시 시도해주세요.';
    end;
  end;
end;
