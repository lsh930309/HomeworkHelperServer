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

[Code]
const
  PrivilegeServiceParameters = 'SYSTEM\CurrentControlSet\Services\HomeworkHelperPrivilege\Parameters';
  WindowsProfileList = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\';
  DataReadAttributes = $80;
  DataDeleteAccess = $10000;
  DataShareRead = 1;
  DataOpenExisting = 3;
  DataOpenPathEntry = $02200000; // BACKUP_SEMANTICS | OPEN_REPARSE_POINT
  DataFileDispositionInfo = 4;
  DataFileAttributeTagInfo = 9;

type
  TLegacyCleanup = (lcDone, lcUnverified, lcFailed);
  TDataPathHandles = array of THandle;
  TDataPathAttributes = record
    Attributes: LongWord;
    ReparseTag: LongWord;
  end;

var
  PostInstallSucceeded: Boolean;
  ServiceWasRunning, ServiceStoppedForUpdate, InstallationStarted: Boolean;
  ApprovedDataCleanupPath: String;

function ConvertOwnerSid(const Value: String; var Sid: THandle): Boolean;
  external 'ConvertStringSidToSidW@advapi32.dll stdcall uninstallonly';
function CheckOwnerToken(Token, Sid: THandle; var IsMember: LongWord): Boolean;
  external 'CheckTokenMembership@advapi32.dll stdcall uninstallonly';
function FreeOwnerSid(Sid: THandle): THandle;
  external 'LocalFree@kernel32.dll stdcall uninstallonly';
function OpenDataPath(const Path: String; Access, Share: LongWord; Security: THandle;
  Creation, Flags: LongWord; Template: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function ReadDataPathAttributes(Handle: THandle; InfoClass: LongWord;
  var Info: TDataPathAttributes; Size: LongWord): Boolean;
  external 'GetFileInformationByHandleEx@kernel32.dll stdcall';
function ReadFinalDataPath(Handle: THandle; Path: String; Size, Flags: LongWord): LongWord;
  external 'GetFinalPathNameByHandleW@kernel32.dll stdcall';
function MarkDataPathForDeletion(Handle: THandle; InfoClass: LongWord;
  var DeleteFile: Byte; Size: LongWord): Boolean;
  external 'SetFileInformationByHandle@kernel32.dll stdcall';
function CloseDataPath(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

procedure CloseAppNormally(); forward;
function RemoveLegacyStartupShortcutForOwner(const OwnerSid: String): TLegacyCleanup; forward;

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
  OwnerSid: String;
begin
  if not RegQueryStringValue(HKLM64, PrivilegeServiceParameters, 'OwnerSid', OwnerSid) then
    RaiseException('이전 자동 실행을 정리할 설치 소유 계정을 확인하지 못했습니다.');
  if RemoveLegacyStartupShortcutForOwner(OwnerSid) = lcFailed then
    RaiseException('확인된 이전 자동 실행 항목을 정리하지 못했습니다.');
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

function IsInstalledOwner(const OwnerSid: String): Boolean;
var
  Sid: THandle;
  IsMember: LongWord;
begin
  Result := False;
  if not ConvertOwnerSid(OwnerSid, Sid) then Exit;
  try
    Result := CheckOwnerToken(0, Sid, IsMember) and (IsMember <> 0);
  finally
    FreeOwnerSid(Sid);
  end;
end;

function InstalledOwnerProfile(const OwnerSid: String): String;
var
  Profile: String;
  Index: Integer;
begin
  Result := '';
  if (Copy(OwnerSid, 1, 4) <> 'S-1-') or (Length(OwnerSid) <= 4) then Exit;
  for Index := 5 to Length(OwnerSid) do
    if Pos(Copy(OwnerSid, Index, 1), '0123456789-') = 0 then Exit;
  if not RegQueryStringValue(HKLM64, WindowsProfileList + OwnerSid, 'ProfileImagePath', Profile) then Exit;
  if SameText(Copy(Profile, 1, 13), '%SystemDrive%') then
    Profile := ExpandConstant('{sd}') + Copy(Profile, 14, Length(Profile));
  if (Length(ExtractFileDrive(Profile)) <> 2) or (Copy(Profile, 3, 1) <> '\') or
    (Pos('%', Profile) <> 0) or not SameText(Profile, ExpandFileName(Profile)) then Exit;
  Result := Profile;
end;

function OwnerAppDataPath(const OwnerSid: String): String;
var
  Profile, Roaming: String;
begin
  Result := '';
  Profile := InstalledOwnerProfile(OwnerSid);
  if (Profile = '') or not IsInstalledOwner(OwnerSid) then Exit;
  Roaming := AddBackslash(Profile) + 'AppData\Roaming';
  if not SameText(Roaming, ExpandConstant('{userappdata}')) or not SameText(Roaming, GetEnv('APPDATA')) then Exit;
  Result := AddBackslash(Roaming) + '{#MyAppName}';
end;

function ConfirmAppDataCleanup(CanDelete: Boolean): Boolean;
var
  Form: TSetupForm;
  Description: TNewStaticText;
  DeleteCheck: TNewCheckBox;
  ContinueButton: TNewButton;
begin
#if Ver >= EncodeVer(6,6,0,0)
  Form := CreateCustomForm(390, 145, True, True);
#else
  Form := CreateCustomForm();
  Form.ClientWidth := ScaleX(390);
  Form.ClientHeight := ScaleY(145);
#endif
  try
    Form.Caption := 'HomeworkHelper 제거 옵션';
    Form.Position := poScreenCenter;
    Description := TNewStaticText.Create(Form);
    Description.Parent := Form;
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.SetBounds(ScaleX(16), ScaleY(16), ScaleX(358), ScaleY(52));
    if CanDelete then
      Description.Caption := '선택하면 앱이 저장한 게임 기록, 설정, 백업이 삭제되며 복구할 수 없습니다.'
    else
      Description.Caption := '설치 소유 계정과 로컬 데이터 경로를 확인할 수 없어 앱 데이터를 보존합니다.';

    DeleteCheck := TNewCheckBox.Create(Form);
    DeleteCheck.Parent := Form;
    DeleteCheck.SetBounds(ScaleX(16), ScaleY(72), ScaleX(358), ScaleY(20));
    DeleteCheck.Caption := '앱 데이터와 백업도 삭제';
    DeleteCheck.Checked := False;
    DeleteCheck.Enabled := CanDelete;

    ContinueButton := TNewButton.Create(Form);
    ContinueButton.Parent := Form;
    ContinueButton.SetBounds(ScaleX(264), ScaleY(108), ScaleX(110), ScaleY(25));
    ContinueButton.Caption := '제거 계속';
    ContinueButton.Default := True;
    ContinueButton.ModalResult := mrOK;
    Result := False;
    if Form.ShowModal = mrOK then Result := DeleteCheck.Checked and CanDelete;
  finally
    Form.Free();
  end;
end;

function OpenPinnedDataPath(const Path: String; Access: LongWord;
  IsDirectory: Boolean; var Missing: Boolean): THandle;
var
  Handle: THandle;
  Info: TDataPathAttributes;
  FinalPath: String;
  Count: LongWord;
begin
  Result := THandle(-1);
  Missing := False;
  // Open the entry itself and refuse any redirect in the final resolved path.
  Handle := OpenDataPath(Path, Access or DataReadAttributes, DataShareRead, 0,
    DataOpenExisting, DataOpenPathEntry, 0);
  if Handle = THandle(-1) then
  begin
    Missing := DLLGetLastError() = 2; // ERROR_FILE_NOT_FOUND, not a missing parent or access denial.
    Exit;
  end;
  try
    if not ReadDataPathAttributes(Handle, DataFileAttributeTagInfo, Info, 8) or
      ((Info.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) or
      (((Info.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) <> IsDirectory) then Exit;
    FinalPath := StringOfChar(#0, Length(Path) + 5);
    Count := ReadFinalDataPath(Handle, FinalPath, Length(FinalPath), 0);
    if (Count = 0) or (Count >= Length(FinalPath)) then Exit;
    SetLength(FinalPath, Count);
    if SameText(FinalPath, '\\?\' + Path) then Result := Handle;
  finally
    if Result = THandle(-1) then CloseDataPath(Handle);
  end;
end;

function PinDataAncestors(const Path: String; var Handles: TDataPathHandles; var Missing: Boolean): Boolean;
var
  DriveRoot, Parent: String;
  Handle: THandle;
  Index: Integer;
begin
  Result := False;
  Missing := False;
  DriveRoot := AddBackslash(ExtractFileDrive(Path));
  if not SameText(Path, DriveRoot) then
  begin
    Parent := ExtractFileDir(Path);
    if (Parent = '') or SameText(Parent, Path) then Exit;
    if not PinDataAncestors(Parent, Handles, Missing) then Exit;
  end;
  Handle := OpenPinnedDataPath(Path, 0, True, Missing);
  if Handle = THandle(-1) then Exit;
  Index := GetArrayLength(Handles);
  SetArrayLength(Handles, Index + 1);
  Handles[Index] := Handle;
  Result := True;
end;

function GameBarSettingRestored(const DataPath: String): Boolean;
var
  IniPath: String;
  IniContents: AnsiString;
  DirectoryHandle, IniHandle: THandle;
  Missing: Boolean;
begin
  Result := False;
  DirectoryHandle := OpenPinnedDataPath(DataPath, 0, True, Missing);
  if DirectoryHandle = THandle(-1) then
  begin
    Result := Missing;
    Exit;
  end;
  try
    IniPath := AddBackslash(DataPath) + 'display_settings.ini';
    IniHandle := OpenPinnedDataPath(IniPath, 0, False, Missing);
    if IniHandle = THandle(-1) then
    begin
      Result := Missing;
      Exit;
    end;
    try
      if not LoadStringFromFile(IniPath, IniContents) then Exit;
      Result := Pos('gamebar_original_value', IniContents) = 0;
    finally
      CloseDataPath(IniHandle);
    end;
  finally
    CloseDataPath(DirectoryHandle);
  end;
end;

function IsAppDataCaptureCandidate(const Path, DataRoot: String): Boolean;
var
  Ext, Stem, Parent, IconSuffix: String;
  IconTag: Integer;
begin
  Result := False;
  if DataRoot = '' then Exit;
  Ext := Lowercase(ExtractFileExt(Path));
  if (Ext = '') or
    (Pos('|' + Ext + '|', '|.png|.jpg|.jpeg|.bmp|.webp|.gif|.tif|.tiff|.mp4|.mkv|.mov|.flv|.ts|.m3u8|.m4v|.avi|.webm|.mpeg|.mpg|.asf|.wmv|') = 0) then Exit;

  // Generated icons are the only known image data owned by these app folders.
  Parent := ExtractFileDir(Path);
  Stem := Lowercase(ChangeFileExt(ExtractFileName(Path), ''));
  if SameText(Parent, AddBackslash(DataRoot) + 'custom_icons') and
    (Pos('|' + Ext + '|', '|.png|.jpg|.jpeg|.webp|') <> 0) and
    (Length(Stem) > 8) and (Copy(Stem, Length(Stem) - 7, 8) = '_stamina') then Exit;
  if (Ext = '.png') and SameText(Parent, AddBackslash(DataRoot) + 'icon_cache') then
  begin
    if (Length(Stem) > 10) and (Copy(Stem, Length(Stem) - 9, 10) = '_v4_native') then Exit;
    IconTag := Pos('_v6_jumbo_', Stem);
    IconSuffix := Copy(Stem, IconTag + Length('_v6_jumbo_'), Length(Stem));
    if IconTag = 0 then
    begin
      IconTag := Pos('_v5_multires_', Stem);
      IconSuffix := Copy(Stem, IconTag + Length('_v5_multires_'), Length(Stem));
    end;
    if (IconTag > 1) and
      (Pos('|' + IconSuffix + '|', '|original|16px|24px|32px|48px|64px|96px|128px|256px|') <> 0) then Exit;
  end;
  Result := True;
end;

function DeleteAppDataTree(const Path, DataRoot: String; IsDirectory, DeleteData: Boolean;
  var Changed: Boolean): Boolean;
var
  Handle: THandle;
  FindRec: TFindRec;
  Missing: Boolean;
  DeleteEntry: Byte;
begin
  Result := False;
  if not IsDirectory and IsAppDataCaptureCandidate(Path, DataRoot) then
  begin
    Log('앱 데이터 폴더에서 캡처로 보이는 파일을 발견해 데이터 삭제를 중단했습니다.');
    Exit;
  end;
  Handle := OpenPinnedDataPath(Path, DataDeleteAccess, IsDirectory, Missing);
  if Handle = THandle(-1) then
  begin
    Result := Missing;
    Exit;
  end;
  try
    if IsDirectory then
    begin
      if not FindFirst(AddBackslash(Path) + '*', FindRec) then Exit;
      try
        repeat
          if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
            if not DeleteAppDataTree(AddBackslash(Path) + FindRec.Name, DataRoot,
              (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0, DeleteData, Changed) then Exit;
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;
    if DeleteData then
    begin
      // Mark the exact verified object, never reopen a mutable path to delete it.
      DeleteEntry := 1;
      if not MarkDataPathForDeletion(Handle, DataFileDispositionInfo, DeleteEntry, 1) then Exit;
      Changed := True;
    end;
    Result := True;
  finally
    CloseDataPath(Handle);
  end;
end;

function DeleteAppData(const DataPath: String; var Changed: Boolean): Boolean;
var
  Handles: TDataPathHandles;
  Index: Integer;
  Remaining: THandle;
  Missing: Boolean;
begin
  Result := False;
  Changed := False;
  if (ExtractFileName(DataPath) <> '{#MyAppName}') or
    (Length(ExtractFileDrive(DataPath)) <> 2) or not SameText(DataPath, ExpandFileName(DataPath)) then Exit;
  SetArrayLength(Handles, 0);
  try
    if not PinDataAncestors(ExtractFileDir(DataPath), Handles, Missing) then Exit;
    // Refuse existing links, locks and potential legacy captures before the first deletion.
    if not DeleteAppDataTree(DataPath, DataPath, True, False, Changed) then Exit;
    if not GameBarSettingRestored(DataPath) then Exit;
    if not DeleteAppDataTree(DataPath, DataPath, True, True, Changed) then Exit;
    Remaining := OpenPinnedDataPath(DataPath, 0, True, Missing);
    if Remaining <> THandle(-1) then CloseDataPath(Remaining);
    Result := Missing;
  finally
    for Index := GetArrayLength(Handles) - 1 downto 0 do
      CloseDataPath(Handles[Index]);
  end;
end;

function RemoveLegacyStartupShortcutForOwner(const OwnerSid: String): TLegacyCleanup;
var
  Profile, Startup, RunKey: String;
  Handles: TDataPathHandles;
  Missing, Changed: Boolean;
  Index: Integer;
begin
  Profile := InstalledOwnerProfile(OwnerSid);
  if Profile = '' then
  begin
    Log('이전 자동 실행 정리: 설치 소유 프로필을 확인할 수 없습니다.');
    Result := lcUnverified;
    Exit;
  end;
  Result := lcDone;
  Startup := AddBackslash(Profile) + 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup';
  SetArrayLength(Handles, 0);
  Changed := False;
  try
    if PinDataAncestors(Startup, Handles, Missing) then
    begin
      if not DeleteAppDataTree(AddBackslash(Startup) + 'GameCycleHelper.lnk', '', False, True, Changed) then
      begin
        Log('이전 자동 실행 정리: 확인된 시작 폴더에서 바로가기를 삭제하지 못했습니다.');
        Result := lcFailed;
      end;
    end
    else if not Missing then
    begin
      Log('이전 자동 실행 정리: 시작 폴더 경로를 확인할 수 없습니다.');
      Result := lcUnverified;
    end;
  finally
    for Index := GetArrayLength(Handles) - 1 downto 0 do CloseDataPath(Handles[Index]);
  end;
  RunKey := OwnerSid + '\Software\Microsoft\Windows\CurrentVersion\Run';
  if not RegKeyExists(HKU, OwnerSid) then
  begin
    Log('이전 자동 실행 정리: 설치 소유 사용자 레지스트리 하이브가 로드되지 않아 Run 값을 확인하지 못했습니다.');
    if Result = lcDone then Result := lcUnverified;
  end
  else if RegValueExists(HKU, RunKey, 'GameCycleHelper') and
    not RegDeleteValue(HKU, RunKey, 'GameCycleHelper') then
  begin
    Log('이전 자동 실행 정리: 확인된 Run 값을 삭제하지 못했습니다.');
    Result := lcFailed;
  end;
end;

function AppProcessStateForDataCleanup(): Integer;
var
  ExpectedExe: String;
begin
  // 0: stopped, 1: only the installed owner's app/API, 2: any other or uncertain instance.
  ExpectedExe := ExpandConstant('{app}\{#MyAppExeName}');
  StringChange(ExpectedExe, '''', '''''');
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "try { $expected = ''' + ExpectedExe + '''; ' +
    '$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value; ' +
    '$session = [Diagnostics.Process]::GetCurrentProcess().SessionId; ' +
    '$apps = @(Get-CimInstance Win32_Process -Filter (''Name={0}homework_helper.exe{0}'' -f [char]39) -ErrorAction Stop); ' +
    'if ($apps.Count -eq 0) { exit 0 }; foreach ($app in $apps) { ' +
    'if ($app.ExecutablePath -ne $expected -or $app.SessionId -ne $session) { exit 2 }; ' +
    '$identity = Invoke-CimMethod -InputObject $app -MethodName GetOwnerSid -ErrorAction Stop; ' +
    'if ($identity.ReturnValue -ne 0 -or $identity.Sid -ne $owner) { exit 2 } }; ' +
    'exit 1 } catch { exit 2 }"',
    '', SW_HIDE, ewWaitUntilTerminated, Result) then Result := 2;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UninstallServiceResult: Integer;
  OwnerSid, DataPath: String;
  Changed: Boolean;
  LegacyResult: TLegacyCleanup;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Service removal clears the persisted SID. Capture it before any cleanup.
    OwnerSid := '';
    RegQueryStringValue(HKLM64, PrivilegeServiceParameters, 'OwnerSid', OwnerSid);
    DataPath := '';
    if not UninstallSilent then
    begin
      DataPath := OwnerAppDataPath(OwnerSid);
      if not ConfirmAppDataCleanup(DataPath <> '') then DataPath := '';
      if DataPath <> '' then
      begin
        if AppProcessStateForDataCleanup() = 1 then CloseAppNormally();
        if AppProcessStateForDataCleanup() <> 0 then
        begin
          MsgBox('앱과 API의 정상 종료를 확인하지 못해 앱 데이터와 백업을 보존합니다.', mbError, MB_OK);
          DataPath := '';
        end;
      end;
    end;

    if not Exec(ExpandConstant('{app}\homework_helper_service.exe'), 'uninstall',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, UninstallServiceResult) then
      RaiseException('권한 서비스를 제거하지 못했습니다.');
    if UninstallServiceResult <> 0 then
      RaiseException('권한 서비스 제거 실패. 종료 코드: ' + IntToStr(UninstallServiceResult));
    DeleteScheduledTasks();
    LegacyResult := RemoveLegacyStartupShortcutForOwner(OwnerSid);
    if (DataPath <> '') and (LegacyResult <> lcDone) then
    begin
      MsgBox('이전 자동 실행 항목의 정리를 확인하지 못해 앱 데이터와 백업을 보존합니다.', mbError, MB_OK);
      DataPath := '';
    end;
    ApprovedDataCleanupPath := DataPath;
  end
  else if (CurUninstallStep = usPostUninstall) and (ApprovedDataCleanupPath <> '') then
  begin
    Changed := False;
    if (AppProcessStateForDataCleanup() = 0) and DeleteAppData(ApprovedDataCleanupPath, Changed) then
      Log('앱 데이터와 백업 삭제 완료')
    else if Changed then
      MsgBox('앱 데이터와 백업 일부를 삭제했지만 정리를 완료하지 못했습니다. 남은 파일을 확인해 주세요.', mbError, MB_OK)
    else
      MsgBox('안전하게 지울 수 있는 상태를 확인하지 못해 앱 데이터와 백업을 보존했습니다. 파일 잠금, 경로, 기존 캡처와 Game Bar 설정을 확인해 주세요.',
        mbError, MB_OK);
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
      if not Exec('sc.exe', 'start HomeworkHelperPrivilege',
        '', SW_HIDE, ewWaitUntilTerminated, RestoreResult) then
        Log('취소 후 기존 서비스 재시작 실행 실패')
      else if RestoreResult <> 0 then
        Log('취소 후 기존 서비스 재시작 실패: ' + IntToStr(RestoreResult));
    end
    else
      Log('설치 실패: 파일 교체 후 서비스 복구는 확인되지 않았습니다. 설치를 다시 실행하세요.');
  end;
end;
