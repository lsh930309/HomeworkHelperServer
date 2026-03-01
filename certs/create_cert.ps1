# HomeworkHelper 코드 서명용 자체 서명 인증서 생성 스크립트
# 관리자 권한으로 PowerShell에서 1회 실행
# 사용법: powershell -ExecutionPolicy Bypass -File create_cert.ps1

param(
    [string]$CertName = "HomeworkHelper Code Signing",
    [string]$Publisher = "CN=lsh930309",
    [int]$ValidYears = 5,
    [switch]$TrustRoot
)

$ErrorActionPreference = "Stop"
$CertsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PfxPath = Join-Path $CertsDir "HomeworkHelper.pfx"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HomeworkHelper 코드 서명 인증서 생성기" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 이미 PFX가 존재하는지 확인
if (Test-Path $PfxPath) {
    Write-Host "[!] 이미 인증서 파일이 존재합니다: $PfxPath" -ForegroundColor Yellow
    $overwrite = Read-Host "덮어쓰시겠습니까? (y/N)"
    if ($overwrite -ne 'y' -and $overwrite -ne 'Y') {
        Write-Host "[취소] 기존 인증서를 유지합니다." -ForegroundColor Yellow
        exit 0
    }
}

# PFX 비밀번호 입력
Write-Host "[1/4] PFX 파일 보호용 비밀번호를 설정합니다."
$password = Read-Host "비밀번호 입력" -AsSecureString
$confirmPassword = Read-Host "비밀번호 확인" -AsSecureString

# 비밀번호 일치 확인
$bstr1 = [IntPtr]::Zero
$bstr2 = [IntPtr]::Zero
$passwordMatch = $false
try {
    $bstr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $bstr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirmPassword)
    $pw1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr1)
    $pw2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr2)

    if ($pw1 -ne $pw2) {
        Write-Host "[오류] 비밀번호가 일치하지 않습니다." -ForegroundColor Red
    } else {
        $passwordMatch = $true
    }
} finally {
    if ($bstr1 -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1) }
    if ($bstr2 -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2) }
    Remove-Variable pw1, pw2, bstr1, bstr2 -ErrorAction SilentlyContinue
}
if (-not $passwordMatch) { exit 1 }

# 인증서 생성
Write-Host ""
Write-Host "[2/4] 자체 서명 인증서 생성 중..." -ForegroundColor Green
$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Publisher `
    -FriendlyName $CertName `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears($ValidYears) `
    -KeyUsage DigitalSignature `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -HashAlgorithm SHA256

Write-Host "  인증서 Thumbprint: $($cert.Thumbprint)"
Write-Host "  유효기간: $(Get-Date -Format 'yyyy-MM-dd') ~ $((Get-Date).AddYears($ValidYears).ToString('yyyy-MM-dd'))"

# PFX로 내보내기
Write-Host ""
Write-Host "[3/4] PFX 파일로 내보내는 중..." -ForegroundColor Green
Export-PfxCertificate `
    -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" `
    -FilePath $PfxPath `
    -Password $password | Out-Null

Write-Host "  저장 위치: $PfxPath"

# Thumbprint 파일 저장 (build.py에서 참조)
$ThumbprintFile = Join-Path $CertsDir ".thumbprint"
$cert.Thumbprint | Out-File -FilePath $ThumbprintFile -Encoding ascii -NoNewline
Write-Host "  썸프린트 저장: $ThumbprintFile"

# 신뢰할 수 있는 루트 인증 기관에 등록 (선택: -TrustRoot 스위치 필요)
Write-Host ""
if ($TrustRoot) {
    Write-Host "[4/4] 로컬 신뢰 저장소에 등록 중..." -ForegroundColor Green
    $rootStore = $null
    try {
        $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
        $rootStore.Open("ReadWrite")
        $rootStore.Add($cert)
        Write-Host "  신뢰할 수 있는 루트 인증 기관에 등록 완료" -ForegroundColor Green
    } catch {
        Write-Host "  [경고] 루트 저장소 등록 실패: $_" -ForegroundColor Yellow
        Write-Host "  (서명은 가능하지만, Windows가 인증서를 신뢰하지 않을 수 있습니다)"
    } finally {
        if ($rootStore) {
            $rootStore.Close()
            $rootStore.Dispose()
        }
    }
} else {
    Write-Host "[4/4] 루트 저장소 등록 건너뜀 (-TrustRoot 스위치로 활성화 가능)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  인증서 생성 완료!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "다음 단계:" -ForegroundColor Cyan
Write-Host "  1. build.py 실행 시 자동으로 서명됩니다 (Windows 인증서 저장소 기반)."
Write-Host "  2. PFX 비밀번호와 .thumbprint 파일을 안전하게 보관하세요."
Write-Host "  3. PFX 파일과 .thumbprint 파일을 Git에 커밋하지 마세요!"
Write-Host ""
