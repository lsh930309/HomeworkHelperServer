; HomeworkHelper Inno Setup Installer Script
; Inno Setup 6.x 이상 필요 (https://jrsoftware.org/isinfo.php)

#define MyAppName "HomeworkHelper"
#ifndef MyAppVersion
#define MyAppVersion "1.1.9"
#endif
#ifndef MyAppOutputBaseFilename
#define MyAppOutputBaseFilename "HomeworkHelper_Setup_v" + MyAppVersion
#endif
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
DisableDirPage=yes
UsePreviousAppDir=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 출력 설정
OutputDir=release
OutputBaseFilename={#MyAppOutputBaseFilename}
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
Name: "tailscalebootstrap"; Description: "Tailscale 기반환경 자동 설치/실행 확인"; GroupDescription: "원격 연결 필수 구성요소:"

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
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[InstallDelete]
; PyInstaller onedir 업데이트 시 이전 _internal 잔여 모듈이 새 exe와 섞이면
; 런타임 entrypoint/모듈 버전이 불일치할 수 있으므로 새 파일 복사 전에 제거합니다.
Type: files; Name: "{app}\{#MyAppExeName}"
Type: files; Name: "{app}\homework_helper_service.exe"
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; 앱이 생성한 데이터는 사용자 AppData에 있으므로 여기서는 삭제하지 않음
; 필요 시 사용자에게 안내 메시지만 표시

[Code]
var
  PostInstallSucceeded: Boolean;
  ServiceWasRunning, ServiceStoppedForUpdate, InstallationStarted: Boolean;

// ============================================================
// 권한 서비스 설치/해제. 운영 호스트 적용은 사용자 설치 실행 시에만 수행합니다.
// ============================================================

procedure InstallPrivilegeService();
var
  ServiceExe, Owner: String;
  ResultCode: Integer;
begin
  ServiceExe := ExpandConstant('{app}\homework_helper_service.exe');
  Owner := ExpandConstant('{param:HostUser|lsh93}');
  // User/SID syntax cannot include a quote. Account resolution is owned by the service CLI.
  if (Pos('"', Owner) > 0) or (Owner = '') then
    RaiseException('호스트 사용자 이름이 올바르지 않습니다.');
  if not Exec(ServiceExe, 'install --owner "' + Owner + '"',
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('권한 서비스 설치 프로그램을 실행하지 못했습니다.');
  if ResultCode <> 0 then
    RaiseException('권한 서비스 설치 실패. 종료 코드: ' + IntToStr(ResultCode));
  Log('권한 서비스 설치 완료: ' + Owner);
end;

procedure RemoveLegacyStartupShortcut();
var
  ScriptPath, Script, Owner: String;
  ResultCode: Integer;
begin
  Owner := ExpandConstant('{param:HostUser|lsh93}');
  if (Pos('''', Owner) > 0) or (Pos('"', Owner) > 0) then
    RaiseException('호스트 사용자 이름이 올바르지 않습니다.');
  ScriptPath := ExpandConstant('{tmp}\hh_remove_legacy_startup.ps1');
  Script := '$ErrorActionPreference = "Stop"' + #13#10 +
    '$sid = ([Security.Principal.NTAccount]''' + Owner + ''').Translate([Security.Principal.SecurityIdentifier]).Value' + #13#10 +
    '$profile = (Get-ItemProperty ("HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\" + $sid)).ProfileImagePath' + #13#10 +
    '$link = Join-Path ([Environment]::ExpandEnvironmentVariables($profile)) "AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\GameCycleHelper.lnk"' + #13#10 +
    'if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }' + #13#10 +
    '$run = "Registry::HKEY_USERS\" + $sid + "\Software\Microsoft\Windows\CurrentVersion\Run"' + #13#10 +
    'if (Test-Path $run) { Remove-ItemProperty -Path $run -Name GameCycleHelper -ErrorAction SilentlyContinue }';
  SaveStringToFile(ScriptPath, Script, False);
  if not Exec('powershell.exe', '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('이전 자동 실행 경로를 정리하지 못했습니다.');
  if ResultCode <> 0 then
    RaiseException('이전 자동 실행 경로 정리 실패. 종료 코드: ' + IntToStr(ResultCode));
end;

function TailscaleExePath(): String;
var
  Candidate: String;
begin
  Result := '';

  Candidate := ExpandConstant('{autopf}\Tailscale\tailscale.exe');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{pf32}\Tailscale\tailscale.exe');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{localappdata}\Tailscale\tailscale.exe');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;
end;

procedure TryBootstrapTailscalePrerequisite();
var
  ScriptPath, Script: String;
  ResultCode: Integer;
begin
  if TailscaleExePath() <> '' then
  begin
    Log('Tailscale already installed: ' + TailscaleExePath());
  end;

  ScriptPath := ExpandConstant('{tmp}\hh_bootstrap_tailscale.ps1');
  Script :=
    '$ErrorActionPreference = "Stop"' + #13#10 +
    '$candidates = @(' + #13#10 +
    '  (Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"),' + #13#10 +
    '  (Join-Path ${env:ProgramFiles(x86)} "Tailscale\tailscale.exe"),' + #13#10 +
    '  (Join-Path $env:LocalAppData "Tailscale\tailscale.exe")' + #13#10 +
    ') | Where-Object { $_ -and (Test-Path $_) }' + #13#10 +
    'if (-not $candidates) {' + #13#10 +
    '  $listing = (Invoke-WebRequest -Uri "https://pkgs.tailscale.com/stable/?v=latest" -UseBasicParsing).Content' + #13#10 +
    '  $match = [regex]::Match($listing, "tailscale-setup-[0-9.]+-amd64\.msi")' + #13#10 +
    '  if (-not $match.Success) { throw "Tailscale MSI download URL not found" }' + #13#10 +
    '  $msi = Join-Path $env:TEMP $match.Value' + #13#10 +
    '  Invoke-WebRequest -Uri ("https://pkgs.tailscale.com/stable/" + $match.Value) -OutFile $msi -UseBasicParsing' + #13#10 +
    '  $install = Start-Process msiexec.exe -ArgumentList @("/i", $msi, "/qn", "/norestart") -Wait -PassThru' + #13#10 +
    '  if ($install.ExitCode -ne 0 -and $install.ExitCode -ne 3010) { throw "Tailscale MSI install failed: $($install.ExitCode)" }' + #13#10 +
    '}' + #13#10 +
    '$exe = @(' + #13#10 +
    '  (Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"),' + #13#10 +
    '  (Join-Path ${env:ProgramFiles(x86)} "Tailscale\tailscale.exe"),' + #13#10 +
    '  (Join-Path $env:LocalAppData "Tailscale\tailscale.exe")' + #13#10 +
    ') | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1' + #13#10 +
    'if (-not $exe) { throw "Tailscale executable was not found after installation" }' + #13#10 +
    'function Invoke-Tailscale([string[]]$Arguments) {' + #13#10 +
    '  $stdout = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + ".out")' + #13#10 +
    '  $stderr = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + ".err")' + #13#10 +
    '  try {' + #13#10 +
    '    $p = Start-Process -FilePath $exe -ArgumentList $Arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr' + #13#10 +
    '    # Retain the native handle so Windows PowerShell 5.1 preserves ExitCode after exit.' + #13#10 +
    '    $null = $p.Handle' + #13#10 +
    '    if (-not $p.WaitForExit(15000)) { $p.Kill(); $p.WaitForExit(); throw "Tailscale command timed out" }' + #13#10 +
    '    $p.WaitForExit()' + #13#10 +
    '    if ($p.ExitCode -ne 0) { throw ("Tailscale command failed: " + $p.ExitCode + " " + [IO.File]::ReadAllText($stderr)) }' + #13#10 +
    '    return [IO.File]::ReadAllText($stdout)' + #13#10 +
    '  } finally {' + #13#10 +
    '    Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10 +
    '$null = Invoke-Tailscale @("set", "--unattended=true")' + #13#10 +
    '$applied = (Invoke-Tailscale @("get", "--json", "unattended")) | ConvertFrom-Json' + #13#10 +
    'if ($applied.unattended -ne $true) { throw "Tailscale unattended setting was not applied" }';

  SaveStringToFile(ScriptPath, Script, False);

  if not Exec('powershell.exe',
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + ScriptPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Tailscale 설정 프로그램을 실행하지 못했습니다.');

  if ResultCode <> 0 then
  begin
    Log('Tailscale unattended setup failed. ResultCode=' + IntToStr(ResultCode));
    RaiseException('Tailscale 무인 실행 설정을 완료하지 못했습니다. 종료 코드: ' + IntToStr(ResultCode));
  end;
  Log('Tailscale unattended setting applied and verified');
end;

procedure DeleteScheduledTasks();
var
  RC1, RC2, QueryAdmin, QueryNormal: Integer;
begin
  Exec('schtasks.exe', '/delete /tn "HomeworkHelper_Admin" /f',
    '', SW_HIDE, ewWaitUntilTerminated, RC1);
  Exec('schtasks.exe', '/delete /tn "HomeworkHelper_Normal" /f',
    '', SW_HIDE, ewWaitUntilTerminated, RC2);
  Exec('schtasks.exe', '/query /tn "HomeworkHelper_Admin"',
    '', SW_HIDE, ewWaitUntilTerminated, QueryAdmin);
  Exec('schtasks.exe', '/query /tn "HomeworkHelper_Normal"',
    '', SW_HIDE, ewWaitUntilTerminated, QueryNormal);
  if (QueryAdmin = 0) or (QueryNormal = 0) then
    RaiseException('이전 자동 실행 예약 작업이 남아 있습니다. 서비스 전환을 완료하지 못했습니다.');
  if (RC1 = 0) and (RC2 = 0) then
    Log('예약 작업 삭제 완료 (HomeworkHelper_Admin, HomeworkHelper_Normal)')
  else
    Log('예약 작업 삭제 일부 실패. RC1=' + IntToStr(RC1) + ', RC2=' + IntToStr(RC2));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then InstallationStarted := True;
  if CurStep = ssPostInstall then
  begin
    InstallPrivilegeService();
    ServiceStoppedForUpdate := False;
    DeleteScheduledTasks();
    RemoveLegacyStartupShortcut();
    PostInstallSucceeded := True;
  end;
end;

function GetCustomSetupExitCode(): Integer;
begin
  // Inno can return 0 after a suppressed ssPostInstall exception. Success
  // requires the service registration and startup cleanup to finish together.
  if PostInstallSucceeded then
    Result := 0
  else
    Result := 1;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UninstallServiceResult: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if not Exec(ExpandConstant('{app}\homework_helper_service.exe'), 'uninstall',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, UninstallServiceResult) then
      RaiseException('권한 서비스를 제거하지 못했습니다.');
    if UninstallServiceResult <> 0 then
      RaiseException('권한 서비스 제거 실패. 종료 코드: ' + IntToStr(UninstallServiceResult));
    DeleteScheduledTasks();
  end;
end;

// ============================================================
// 실행 중인 프로세스 확인 함수
function IsProcessRunning(ProcessName: String): Boolean;
var
  ResultCode: Integer;
begin
  // cmd /c를 사용하여 파이프 명령 실행
  // tasklist | find로 프로세스 존재 여부 확인 (ERRORLEVEL 0 = 프로세스 존재)
  Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq ' + ProcessName + '" 2>NUL | find /I "' + ProcessName + '" >NUL',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

// 설치 이미지의 정상 종료 요청. 시간 초과 후 강제 종료하지 않습니다.
procedure CloseAppNormally();
var
  ResultCode, Attempt: Integer;
begin
  if not Exec(ExpandConstant('{app}\homework_helper.exe'), '--quit-application',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  if ResultCode <> 0 then Exit;
  for Attempt := 1 to 15 do
  begin
    if not IsProcessRunning('homework_helper.exe') then Exit;
    Sleep(1000);
  end;
end;

// HomeworkHelper 관련 프로세스가 실행 중인지 확인
function IsAppRunning(): Boolean;
begin
  Result := IsProcessRunning('homework_helper.exe');
end;

// 설치 전 실행 중인 프로세스 종료
function CloseRunningApp(): Boolean;
begin
  Result := True;

  // === 실행 중인 HomeworkHelper 프로세스 종료 ===
  // 이전 버전을 삭제하지 않고, 실행 중인 프로세스만 종료합니다.
  // Inno Setup은 동일한 AppId를 감지하면 자동으로 in-place 업그레이드를 수행하며,
  // 이 방식을 사용하면 작업 표시줄에 고정된 아이콘이 유지됩니다.

  if IsAppRunning() then
  begin
    if WizardSilent then
    begin
      // 자동 업데이트에서는 사용자 입력을 기다리지 않고 같은 종료 경로를 사용합니다.
      CloseAppNormally();
      Sleep(1000);

      if IsAppRunning() then
      begin
        Log('무인 설치 중 HomeworkHelper 프로세스를 종료하지 못했습니다.');
        Result := False;
        Exit;
      end;
    end
    else if MsgBox('HomeworkHelper가 현재 실행 중입니다.' + #13#10 + #13#10 +
              '설치를 계속하려면 프로그램을 종료해야 합니다.' + #13#10 +
              '자동으로 종료하고 계속 진행하시겠습니까?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      // 프로세스 종료
      CloseAppNormally();

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
var
  ServiceExe: String;
  ServiceResult: Integer;
begin
  Result := '';
  NeedsRestart := False;

  if WizardIsTaskSelected('tailscalebootstrap') then
  begin
    TryBootstrapTailscalePrerequisite();
  end;

  if not CloseRunningApp() then
  begin
    Result := 'HomeworkHelper를 정상 종료한 뒤 설치를 다시 시도해주세요.';
    Exit;
  end;
  ServiceExe := ExpandConstant('{app}\homework_helper_service.exe');
  Exec('cmd.exe', '/c sc query HomeworkHelperPrivilege | find "RUNNING" >NUL',
    '', SW_HIDE, ewWaitUntilTerminated, ServiceResult);
  ServiceWasRunning := ServiceResult = 0;
  if FileExists(ServiceExe) then
  begin
    if not Exec(ServiceExe, 'stop', ExpandConstant('{app}'), SW_HIDE,
      ewWaitUntilTerminated, ServiceResult) then
    begin
      Result := '업데이트 전에 권한 서비스를 정지하지 못했습니다.';
      Exit;
    end;
    if ServiceResult <> 0 then
    begin
      Result := '권한 서비스 정지 실패. 종료 코드: ' + IntToStr(ServiceResult);
      Exit;
    end;
    ServiceStoppedForUpdate := True;
  end;


end;

procedure DeinitializeSetup();
var
  RestoreResult: Integer;
begin
  if ServiceStoppedForUpdate and ServiceWasRunning and not PostInstallSucceeded then
  begin
    if not InstallationStarted then
    begin
      if not Exec(ExpandConstant('{app}\homework_helper_service.exe'), 'start',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RestoreResult) then
        Log('취소 후 기존 서비스 재시작 실행 실패')
      else if RestoreResult <> 0 then
        Log('취소 후 기존 서비스 재시작 실패: ' + IntToStr(RestoreResult));
    end
    else
      Log('설치 실패: 파일 교체 후 서비스 복구는 확인되지 않았습니다. 설치를 다시 실행하세요.');
  end;
end;
