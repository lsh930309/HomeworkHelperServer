param(
    [ValidateSet('inspect','logs','prepare-source','build','release-preflight','release-build','release-asset','install','desktop','verify','media-qa')][string]$Command,
    [string]$Repo, [string]$Owner, [string]$ExpectedComputer,
    [string]$Commit, [string]$Branch, [string]$VersionSnapshot, [string]$ArchivedRelease,
    [string]$ReleaseTag, [string]$ReleaseRepo, [string]$ReleaseFile, [long]$ReleaseSize, [string]$ReleaseDigest,
    [string]$ProbeSource, [string]$SessionSource, [string]$VerifySource,
    [int]$LogLines = 80, [string]$Contains = '',
    [int]$Duration = 0, [string]$Scenario = 'observe', [switch]$PrepareRuntime, [switch]$AllowProtectedTime,
    [switch]$RepairWuwaLink, [switch]$ReuseRelease
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Install = 'C:\Program Files\HomeworkHelper'
if ($env:COMPUTERNAME -ne $ExpectedComputer) { throw '대상 Windows 컴퓨터 불일치' }
if (![IO.Path]::IsPathRooted($Repo) -or !(Test-Path (Join-Path $Repo '.git'))) { throw 'Windows 작업 checkout을 확인하세요' }
$Sid = ([Security.Principal.NTAccount]::new($env:COMPUTERNAME,$Owner)).Translate([Security.Principal.SecurityIdentifier]).Value
$Profile = (Get-ItemProperty ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$Sid)).ProfileImagePath
$AppData = Join-Path ([Environment]::ExpandEnvironmentVariables($Profile)) 'AppData\Roaming'
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$VersionFile = Join-Path $Repo 'build.version.json'
if (!(Test-Path $Python)) { throw 'Windows 작업 checkout의 Python 환경이 없습니다' }
Set-Location $Repo
if ($RepairWuwaLink -and ($Command -ne 'install' -or $ArchivedRelease)) { throw '명조 오프라인 복구는 새 수정본 설치에서만 사용합니다' }

function Decode-Source([string]$Payload) {
    $Buffer = [IO.MemoryStream]::new([Convert]::FromBase64String($Payload))
    $Gzip = [IO.Compression.GZipStream]::new($Buffer,[IO.Compression.CompressionMode]::Decompress)
    $Reader = [IO.StreamReader]::new($Gzip,[Text.UTF8Encoding]::new($false,$true))
    try { return $Reader.ReadToEnd() } finally { $Reader.Dispose(); $Gzip.Dispose(); $Buffer.Dispose() }
}

function Git-Checked([string[]]$Arguments) {
    $Output = & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Windows Git 명령 실패' }
    return ($Output -join "`n").Trim()
}
function Require-Source {
    if ((Git-Checked @('status','--porcelain'))) { throw 'Windows 작업 checkout에 변경 사항이 있습니다' }
    $Head = Git-Checked @('rev-parse','HEAD')
    if ($Head -ne $Commit) { throw 'Windows 소스 커밋 불일치' }
}
function Read-RequestedVersion {
    if (!$VersionSnapshot) { throw '맥에서 확정한 호스트 빌드 버전이 없습니다' }
    $Version = $VersionSnapshot | ConvertFrom-Json
    if ($Version.product -cne 'host' -or $Version.commit -cne $Commit -or !$Version.version -or !$Version.base_version) {
        throw '맥에서 확정한 호스트 버전 또는 소스 커밋 불일치'
    }
    return $Version
}
function Require-SyncedVersion {
    $Version = Read-RequestedVersion
    if (!(Test-Path -LiteralPath $VersionFile -PathType Leaf)) { throw '맥에서 먼저 Windows 소스를 준비하세요' }
    $Saved = Get-Content -LiteralPath $VersionFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Saved.product -cne $Version.product -or $Saved.commit -cne $Version.commit -or
        $Saved.version -cne $Version.version -or $Saved.base_version -cne $Version.base_version) {
        throw 'Windows 빌드 버전이 맥의 버전과 다릅니다. 소스를 다시 준비하세요'
    }
}
function Prepare-PublishedSource([switch]$ReleaseBuild) {
    if ((Git-Checked @('status','--porcelain'))) { throw 'Windows 작업 checkout에 변경 사항이 있습니다' }
    $null = Read-RequestedVersion
    $null = Git-Checked @('fetch','origin',('refs/heads/'+$Branch))
    if ($ReleaseBuild) {
        if ($Branch -cne 'main' -or (Git-Checked @('rev-list','--first-parent','FETCH_HEAD')).Split("`n") -cnotcontains $Commit) {
            throw '릴리즈 커밋이 공개 main 이력에 없습니다'
        }
    } elseif ((Git-Checked @('rev-parse','FETCH_HEAD')) -cne $Commit) {
        throw 'Windows origin에서 가져온 커밋이 배포 대상과 다릅니다'
    }
    $Temporary = Join-Path $Repo ('.build.version.'+[Guid]::NewGuid().ToString('N')+'.tmp')
    try {
        [IO.File]::WriteAllText($Temporary,$VersionSnapshot,[Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $VersionFile) {
            [IO.File]::Replace($Temporary,$VersionFile,[NullString]::Value)
        } else {
            [IO.File]::Move($Temporary,$VersionFile)
        }
    } finally {
        if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force }
    }
    $null = Git-Checked @('checkout','--detach',$Commit)
    Require-Source
}
function Test-ReleaseRepository {
    if ($ReleaseRepo -cnotmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\z') { return $false }
    $Origin = Git-Checked @('remote','get-url','origin')
    $Repository = [regex]::Match($Origin,'^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)(?<name>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?\z')
    return ($Repository.Success -and $Repository.Groups['name'].Value -ieq $ReleaseRepo)
}
function Get-ReleasePreflight {
    if (!(Test-ReleaseRepository)) { return @{ok=$false;reason='repository-mismatch'} }
    if ((Git-Checked @('status','--porcelain'))) { return @{ok=$false;reason='source-dirty'} }
    $env:GIT_TERMINAL_PROMPT = '0'
    try {
        $null = Git-Checked @('ls-remote','--exit-code','--heads','origin','refs/heads/main')
    } catch {
        return @{ok=$false;reason='repository-access'}
    }
    return @{ok=$true}
}
function Require-ReleaseTarget {
    $Version = Read-RequestedVersion
    if ($Branch -cne 'main' -or $ReleaseTag -cne ('H/v'+$Version.version) -or
        $ReleaseTag -cnotmatch '^H/v[0-9]+\.[0-9]+\.0\z') {
        throw 'Windows 릴리즈 대상, 버전 또는 태그 불일치'
    }
    if (!(Test-ReleaseRepository)) { throw 'Windows origin과 GitHub 릴리즈 저장소가 다릅니다' }
}
function Require-PublishedReleaseTag {
    Require-ReleaseTarget
    $Ref = 'refs/tags/'+$ReleaseTag
    $Peeled = $Ref+'^{}'
    $DirectCommit = $null
    $PeeledCommit = $null
    foreach ($Line in (Git-Checked @('ls-remote','--tags','origin',$Ref,$Peeled)).Split("`n")) {
        if ($Line -cmatch '^([a-f0-9]{40})\s+(.+)\z') {
            if ($Matches[2] -ceq $Ref) { $DirectCommit = $Matches[1] }
            if ($Matches[2] -ceq $Peeled) { $PeeledCommit = $Matches[1] }
        }
    }
    $TagCommit = if ($PeeledCommit) { $PeeledCommit } else { $DirectCommit }
    if (!$DirectCommit -or $TagCommit -cne $Commit) { throw 'GitHub 릴리즈 태그와 빌드 커밋이 다릅니다' }
}
function Invoke-HostBuild {
    Require-Source
    Require-SyncedVersion
    $Signature = Get-AuthenticodeSignature (Join-Path $Install 'homework_helper.exe')
    if ($Signature.Status -ne 'Valid') { throw '기존 설치본의 서명 인증서를 확인할 수 없습니다' }
    $env:HH_CERT_THUMBPRINT = $Signature.SignerCertificate.Thumbprint
    $null = Invoke-Probe 'build'
    Require-Source
    Require-SyncedVersion
}
function Get-CheckedReleaseFiles {
    $Files = Invoke-Probe 'release'
    Require-Source
    Require-SyncedVersion
    if ((Get-AuthenticodeSignature -LiteralPath $Files.setup).Status -ne 'Valid') { throw 'Setup 서명 오류' }
    $null = Invoke-Probe 'payload' $Files.portable
    return $Files
}
function Open-ReleasePackage([string]$Path) {
    if ((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw '릴리즈 패키지 경로가 원본 파일이 아닙니다'
    }
    return [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
}
function Get-PackageDigest([IO.Stream]$Stream) {
    $Hash = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($Hash.ComputeHash($Stream)).Replace('-','').ToLowerInvariant()
    } finally { $Hash.Dispose() }
}
function Require-ProductionEnvironment {
    foreach ($Name in @('HH_TEST_APPDATA_DIR','HH_API_PORT','HH_SERVER_MUTEX_NAME','HH_TESTBENCH_SESSION_ID')) {
        if ([Environment]::GetEnvironmentVariable($Name)) { throw '테스트 환경변수가 설정된 셸에서 운영 설치할 수 없습니다' }
    }
}
function Require-InstallTime {
    $Kst = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow,'Korea Standard Time')
    $Minute = $Kst.Hour * 60 + $Kst.Minute
    if ($Minute -ge 705 -and $Minute -lt 780 -and !$AllowProtectedTime) { throw '11:45~13:00 보호 시간: 설치 유예' }
}
function Invoke-Probe([string]$Kind, [string]$Portable = '') {
    $Code = Decode-Source $ProbeSource
    $Arguments = @('-', $Kind, '--repo',$Repo,'--appdata',$AppData,'--install',$Install,'--log-lines',$LogLines)
    if ($Contains) { $Arguments += @('--contains',$Contains) }
    if ($Portable) { $Arguments += @('--portable',$Portable) }
    if ($Kind -eq 'release') {
        $Version = Read-RequestedVersion
        $Arguments += @('--expected-commit',$Version.commit,'--expected-version',$Version.version)
    }
    $Output = $Code | & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Windows 검사 실패: '+$Kind) }
    return ($Output -join "`n") | ConvertFrom-Json
}
function Service-Status {
    $Output = & (Join-Path $Install 'homework_helper_service.exe') --control status
    if ($LASTEXITCODE -ne 0) { throw '권한 서비스 상태 확인 실패' }
    $Status = ($Output -join "`n") | ConvertFrom-Json
    if ($Status.owner_sid -ne $Sid) { throw '설치 사용자 SID 불일치' }
    return $Status
}
function User-Session($Status) {
    $Sessions = @($Status.user_sessions | Where-Object { $_.owner_sid -eq $Sid })
    if (!$Status.user_session_ready -or $Sessions.Count -ne 1) { throw '지정 사용자 로그인 세션 미준비 또는 모호함' }
    return $Sessions[0].session_id
}
function Register-OneTime($Scheduler, [string]$Executable, [string]$Arguments, [string]$Directory, [int]$Level, [string]$Limit) {
    $Task = $Scheduler.NewTask(0)
    $Task.Principal.UserId = $Sid
    $Task.Principal.LogonType = 3
    $Task.Principal.RunLevel = $Level
    $Task.Settings.ExecutionTimeLimit = $Limit
    $Task.Settings.AllowHardTerminate = $false
    $Action = $Task.Actions.Create(0)
    $Action.Path = $Executable
    $Action.Arguments = $Arguments
    $Action.WorkingDirectory = $Directory
    return $Task
}
function Invoke-Session([string]$Kind, $Status, $Obs = $null) {
    $Session = User-Session $Status
    $Root = Join-Path $env:TEMP ('HHHostOperations\'+[Guid]::NewGuid().ToString('N'))
    $null = New-Item $Root -ItemType Directory -Force
    $CodeFile = Join-Path $Root 'windows_session_probe.py'
    $ResultFile = Join-Path $Root 'result.json'
    [IO.File]::WriteAllText($CodeFile,(Decode-Source $SessionSource),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $Root 'windows_host_probe.py'),(Decode-Source $ProbeSource),[Text.UTF8Encoding]::new($false))
    $Arguments = '"'+$CodeFile+'" '+$Kind+' --repo "'+$Repo+'" --appdata "'+$AppData+'" --result "'+$ResultFile+'" --sid '+$Sid+' --session '+$Session+' --duration '+$Duration
    if ($Kind -eq 'media-qa') { $Arguments += ' --scenario '+$Scenario }
    if ($Obs) { $Arguments += ' --pid '+$Obs.pid+' --created '+([double]$Obs.created).ToString('R',[Globalization.CultureInfo]::InvariantCulture) }
    $Scheduler = New-Object -ComObject 'Schedule.Service'
    $Scheduler.Connect()
    $Folder = $Scheduler.GetFolder('\')
    $Name = 'HHHostOperations-'+[Guid]::NewGuid().ToString('N')
    $Level = if ($Kind -eq 'close-obs') {1} else {0}
    $Task = Register-OneTime $Scheduler ($Python -replace 'python.exe$','pythonw.exe') $Arguments $Repo $Level 'PT3M'
    $Completed = $false
    $Registered = $null
    try {
        $Registered = $Folder.RegisterTaskDefinition($Name,$Task,6,$Sid,$null,3)
        $null = $Registered.Run($null)
        $WaitSeconds = if ($Kind -eq 'media-qa' -and $Scenario -eq 'focus-lifecycle') {170} elseif ($Kind -eq 'media-qa') {120} else {[Math]::Max($Duration+15,40)}
        $Deadline = (Get-Date).AddSeconds($WaitSeconds)
        while (!(Test-Path $ResultFile) -and (Get-Date) -lt $Deadline) { Start-Sleep -Milliseconds 200 }
        if (!(Test-Path $ResultFile)) { throw ('사용자 세션 작업 결과 없음. 자동 재시도하지 않음: '+$Root) }
        $Result = Get-Content $ResultFile -Raw -Encoding UTF8 | ConvertFrom-Json
        # native 검수 실패에는 미종료 fixture가 있을 수 있어 진단 root를 보존한다.
        $Completed = $Result.ok -and ($Kind -ne 'media-qa' -or $Result.result.ok)
        if (!$Result.ok) { throw ('사용자 세션 작업 실패: '+$Result.error) }
        return $Result.result
    } finally {
        if ($Registered) { $Folder.DeleteTask($Name,0) }
        if ($Completed) { Remove-Item $Root -Recurse -Force }
    }
}
function Start-UserApp($Status) {
    $null = User-Session $Status
    $Scheduler = New-Object -ComObject 'Schedule.Service'
    $Scheduler.Connect()
    $Folder = $Scheduler.GetFolder('\')
    $Name = 'HHHostStart-'+[Guid]::NewGuid().ToString('N')
    $Task = Register-OneTime $Scheduler (Join-Path $Install 'homework_helper.exe') '' $Install 0 'PT0S'
    $Registered = $null
    try {
        $Registered = $Folder.RegisterTaskDefinition($Name,$Task,6,$Sid,$null,3)
        $null = $Registered.Run($null)
    } finally { if ($Registered) { $Folder.DeleteTask($Name,0) } }
}

switch ($Command) {
    'logs' { (Invoke-Probe 'logs') | ConvertTo-Json -Depth 4 }
    'verify' {
        $Root = Join-Path $env:TEMP ('HHOperationsTests-'+[Guid]::NewGuid().ToString('N'))
        $null = New-Item $Root -ItemType Directory
        $Files = (Decode-Source $VerifySource) | ConvertFrom-Json
        foreach ($File in $Files.PSObject.Properties) {
            $Destination = Join-Path $Root $File.Name
            $null = New-Item (Split-Path $Destination) -ItemType Directory -Force
            [IO.File]::WriteAllText($Destination,$File.Value,[Text.UTF8Encoding]::new($false))
        }
        $Log = Join-Path $Repo 'artifacts/host-operations-tests.log'
        $null = New-Item (Split-Path $Log) -ItemType Directory -Force
        $Variables = @('APPDATA','LOCALAPPDATA','HH_TEST_APPDATA_DIR')
        $Previous = @{}
        foreach ($Name in $Variables) { $Previous[$Name]=[Environment]::GetEnvironmentVariable($Name); [Environment]::SetEnvironmentVariable($Name,(Join-Path $Root 'isolated-appdata')) }
        try {
            Push-Location $Root
            $env:HH_OPERATIONS_TEST_LOG = $Log
            # Python owns subprocess output collection; no PowerShell native-stderr misclassification.
            $Code = "import os,subprocess,sys; f=open(os.environ['HH_OPERATIONS_TEST_LOG'],'wb'); r=subprocess.run([sys.executable,'-m','pytest','tests/test_host_operations.py','-q','--basetemp=pytest-temp','--junitxml=results.xml'],stdout=f,stderr=subprocess.STDOUT); f.close(); sys.exit(r.returncode)"
            & $Python -c $Code
            if ($LASTEXITCODE -ne 0) { throw ('Windows 격리 검사 실패: '+$Log) }
            [xml]$Results = Get-Content (Join-Path $Root 'results.xml') -Raw
            @{ok=$true; platform='Windows'; tests=$Results.testsuites.testsuite.tests; failures=$Results.testsuites.testsuite.failures; skipped=$Results.testsuites.testsuite.skipped; log=$Log} | ConvertTo-Json
        } finally {
            Pop-Location
            foreach ($Name in $Variables) { [Environment]::SetEnvironmentVariable($Name,$Previous[$Name]) }
            Remove-Item $Root -Recurse -Force
        }
    }
    'inspect' {
        $State = Invoke-Probe 'inspect'
        $State | Add-Member source @{head=(Git-Checked @('rev-parse','HEAD')); branch=(Git-Checked @('branch','--show-current')); dirty=[bool](Git-Checked @('status','--porcelain'))}
        $State | Add-Member computer $env:COMPUTERNAME
        $State | Add-Member owner_sid $Sid
        $Service = Get-CimInstance Win32_Service -Filter "Name='HomeworkHelperPrivilege'"
        $State | Add-Member service @{state=$Service.State; account=$Service.StartName; pid=$Service.ProcessId; start_mode=$Service.StartMode}
        $State | Add-Member build_version $(if (Test-Path -LiteralPath $VersionFile) { Get-Content -LiteralPath $VersionFile -Raw -Encoding UTF8 | ConvertFrom-Json })
        $State | ConvertTo-Json -Depth 12
    }
    'prepare-source' {
        Prepare-PublishedSource
        @{ok=$true; head=$Commit; branch=$Branch; version=(Read-RequestedVersion)} | ConvertTo-Json -Depth 5
    }
    'build' {
        Invoke-HostBuild
        @{ok=$true; source=$Commit; version=(Read-RequestedVersion); release=(Join-Path $Repo 'release')} | ConvertTo-Json -Depth 5
    }
    'release-preflight' {
        Get-ReleasePreflight | ConvertTo-Json -Compress
    }
    'release-build' {
        Require-ReleaseTarget
        $Files = $null
        try { $Files = Get-CheckedReleaseFiles } catch {
            if ($ReuseRelease) {
                throw ('초안의 기존 자산과 대조할 원본 패키지가 없습니다. 원본을 복구하거나 해당 초안의 자산을 직접 정리한 뒤 다시 실행하세요. '+$_.Exception.Message)
            }
        }
        if (!$Files) {
            Prepare-PublishedSource -ReleaseBuild
            Invoke-HostBuild
            $Files = Get-CheckedReleaseFiles
        }
        Require-Source
        Require-SyncedVersion
        $Assets = @{}
        foreach ($File in @($Files.setup,$Files.portable)) {
            $Name = [IO.Path]::GetFileName($File)
            $Stream = Open-ReleasePackage $File
            try { $Assets[$Name] = @{sha256=(Get-PackageDigest $Stream); size=$Stream.Length} }
            finally { $Stream.Dispose() }
        }
        @{ok=$true; source=$Commit; version=(Read-RequestedVersion); assets=$Assets} | ConvertTo-Json -Depth 5
    }
    'release-asset' {
        Require-PublishedReleaseTag
        $Files = Get-CheckedReleaseFiles
        $File = @($Files.setup,$Files.portable) | Where-Object {
            [IO.Path]::GetFileName($_) -ceq $ReleaseFile
        }
        if (!$File -or $ReleaseSize -le 0 -or $ReleaseDigest -cnotmatch '^[0-9a-f]{64}\z') {
            throw '발급된 호스트 릴리즈의 패키지 정보가 아닙니다'
        }
        $Stream = Open-ReleasePackage $File
        try {
            if ($Stream.Length -ne $ReleaseSize -or (Get-PackageDigest $Stream) -cne $ReleaseDigest) {
                throw '전송할 Windows 패키지의 크기 또는 SHA-256이 달라졌습니다'
            }
            $Stream.Position = 0
            $Output = [Console]::OpenStandardOutput()
            $Stream.CopyTo($Output)
            $Output.Flush()
        } finally { $Stream.Dispose() }
    }
    'desktop' {
        $Result = Invoke-Session 'desktop' (Service-Status)
        $Result | ConvertTo-Json -Depth 14
    }
    'media-qa' {
        Require-Source
        if ($PrepareRuntime) {
            # pip 하위 프로세스를 만드는 준비는 stdin 코드 파이프가 아닌 고정 소스 파일로 실행한다.
            $null = & $Python (Join-Path $Repo 'tools/windows_host_probe.py') prepare-runtime --repo $Repo --appdata $AppData --install $Install
            if ($LASTEXITCODE -ne 0) { throw 'Windows 미디어 검수 의존성 준비 실패' }
        }
        $Result = Invoke-Session 'media-qa' (Service-Status)
        $Result | ConvertTo-Json -Depth 20
    }
    'install' {
        if (!$ArchivedRelease) { Require-Source; Require-SyncedVersion }
        Require-ProductionEnvironment
        Require-InstallTime
        if ($ArchivedRelease) {
            if ($ArchivedRelease -cnotmatch '^(?:v[0-9]+\.[0-9]+\.[0-9]+(?:_b[1-9][0-9]*_g[0-9a-f]{4,40})?|dev\.[1-9][0-9]*)\z') { throw '보관 릴리스 ID 형식 오류' }
            $Release = $ArchivedRelease
            $Archive = Join-Path $Repo 'release\archives\windows-host'
            $SetupName = 'HomeworkHelper_'+$Release+'_Setup.exe'
            $PortableName = 'HomeworkHelper_'+$Release+'_Portable.zip'
            $Pair = Join-Path (Join-Path $Archive 'by-version') $Release
            if (Test-Path -LiteralPath $Pair) {
                $Setup = Join-Path $Pair $SetupName
                $Portable = Join-Path $Pair $PortableName
                if (!(Test-Path -LiteralPath $Setup -PathType Leaf) -or !(Test-Path -LiteralPath $Portable -PathType Leaf)) {
                    throw '보관 패키지 쌍이 불완전함: '+$Release
                }
            } else {
                $Setups = @(Get-ChildItem -LiteralPath $Archive -File -Recurse -Filter $SetupName)
                $Portables = @(Get-ChildItem -LiteralPath $Archive -File -Recurse -Filter $PortableName)
                if ($Setups.Count -ne 1 -or $Portables.Count -ne 1) { throw '보관 패키지가 없거나 중복됨: '+$Release }
                $Setup = $Setups[0].FullName
                $Portable = $Portables[0].FullName
            }
        } else {
            $Files = Invoke-Probe 'release'
            $Release = $Files.release_id
            $Setup = $Files.setup
            $Portable = $Files.portable
            Require-Source
            Require-SyncedVersion
        }
        if ((Get-AuthenticodeSignature $Setup).Status -ne 'Valid') { throw 'Setup 서명 오류' }
        $Expected = Invoke-Probe 'payload' $Portable
        $Before = Invoke-Probe 'preflight'
        $Status = Service-Status
        $Session = User-Session $Status
        $Backup = Invoke-Probe 'backup'
        Require-InstallTime
        $Obs = @($Before.processes | Where-Object {$_.name -eq 'obs64.exe'})
        if ($Obs.Count -gt 1) { throw 'OBS 인스턴스 모호함' }
        if ($Obs.Count -eq 1) {
            if ($Obs[0].sid -ne $Sid -or $Obs[0].session -ne $Session) { throw 'OBS 사용자/세션 불일치' }
            $Locked = @((Get-Process -Id $Obs[0].pid).Modules | Where-Object {$_.FileName.StartsWith($Install+'\',[StringComparison]::OrdinalIgnoreCase)})
            if ($Locked.Count) { $null = Invoke-Session 'close-obs' $Status $Obs[0] }
        }
        # Recheck current game/output state immediately before normal app shutdown.
        $null = Invoke-Probe 'preflight'
        Require-InstallTime
        $Quit = Start-Process (Join-Path $Install 'homework_helper.exe') -ArgumentList '--quit-application' -Wait -PassThru
        if ($Quit.ExitCode -ne 0) { throw '호스트 앱 정상 종료 실패' }
        $Deadline = (Get-Date).AddSeconds(20)
        do {
            $Remaining = @(Get-CimInstance Win32_Process -Filter "Name='homework_helper.exe'" | Where-Object {$_.ExecutablePath -eq (Join-Path $Install 'homework_helper.exe')})
            if (!$Remaining.Count) { break }
            Start-Sleep -Milliseconds 250
        } while ((Get-Date) -lt $Deadline)
        if ($Remaining.Count) { throw '설치본 GUI/API가 종료되지 않음' }
        $Log = Join-Path $Repo ('artifacts\host-operations-install-'+$Release+'.log')
        $Installer = Start-Process $Setup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/HostUser='+$Owner),('/LOG="'+$Log+'"')) -Wait -PassThru
        if ($Installer.ExitCode -ne 0) { throw ('Setup 실패: '+$Installer.ExitCode+'; '+$Log) }
        foreach ($File in @('homework_helper.exe','homework_helper_service.exe')) {
            if ((Get-AuthenticodeSignature (Join-Path $Install $File)).Status -ne 'Valid') { throw '설치된 실행파일 서명 오류' }
            if ((Get-FileHash (Join-Path $Install $File) -Algorithm SHA256).Hash.ToLower() -ne $Expected.$File) { throw '설치 payload와 패키지 불일치' }
        }
        if ((Get-Service HomeworkHelperPrivilege).Status -ne 'Running') { throw '설치된 서비스 미실행' }
        if ((Get-CimInstance Win32_Service -Filter "Name='HomeworkHelperPrivilege'").StartName -ne 'LocalSystem') { throw '서비스 SYSTEM 실행 확인 실패' }
        $Status = Service-Status
        if ((User-Session $Status) -ne $Session) { throw '설치 중 지정 사용자 세션 변경' }
        $Repair = $null
        if ($RepairWuwaLink) {
            Require-Source
            Require-SyncedVersion
            $Repair = Invoke-Probe 'repair-wuwa-link'
            if (!$Repair.ok) { throw '명조 오프라인 데이터 복구 실패: 앱을 시작하지 않습니다' }
        }
        Start-UserApp $Status
        $Deadline = (Get-Date).AddSeconds(30)
        $Ready = $false
        while ((Get-Date) -lt $Deadline) {
            try {
                $Health = Invoke-RestMethod 'http://127.0.0.1:8000/api/gui/health' -TimeoutSec 2
                if ($Health.ok -and $Health.db_ready -and $Health.database_access.mode -eq 'normal') {$Ready=$true; break}
            } catch {}
            Start-Sleep -Milliseconds 500
        }
        if (!$Ready) { throw '설치된 API/DB 미준비' }
        $After = Invoke-Probe 'inspect'
        $Apps = @($After.processes | Where-Object {$_.path -eq (Join-Path $Install 'homework_helper.exe')})
        if (!$Apps.Count -or @($Apps | Where-Object {$_.sid -ne $Sid -or $_.session -ne $Session -or $_.elevated -ne $false}).Count) { throw '호스트 앱 사용자/세션/일반 권한 확인 실패' }
        if (($Before.database.settings | ConvertTo-Json -Compress) -ne ($After.database.settings | ConvertTo-Json -Compress)) { throw '설치 전후 사용자 설정이 변경됨' }
        @{ok=$true; release=$Release; backup=$Backup; repair=$Repair; log=$Log; runtime=$After; user_acceptance='pending'} | ConvertTo-Json -Depth 12
    }
}
