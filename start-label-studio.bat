@echo off
chcp 65001 >nul
title HomeworkHelper - Label Studio 시작

echo ================================
echo HomeworkHelper Label Studio 시작
echo ================================
echo.

REM Docker가 실행 중인지 확인
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker가 실행되지 않았습니다!
    echo.
    echo Docker Desktop을 먼저 실행해주세요.
    echo.
    pause
    exit /b 1
)

echo ✅ Docker 실행 확인 완료
echo.

REM label-studio 디렉토리로 이동
cd /d "%~dp0label-studio"
if %errorlevel% neq 0 (
    echo ❌ label-studio 디렉토리를 찾을 수 없습니다!
    pause
    exit /b 1
)

echo 📦 Label Studio 컨테이너 시작 중...
echo.

REM Docker Compose로 Label Studio 시작
docker-compose up -d

if %errorlevel% neq 0 (
    echo.
    echo ❌ Label Studio 시작 실패!
    echo.
    pause
    exit /b 1
)

echo.
echo ✅ Label Studio가 시작되었습니다!
echo.
echo 📊 컨테이너 상태:
docker-compose ps

echo.
echo ================================
echo 🌐 Label Studio 접속 정보
echo ================================
echo URL: http://localhost:8080
echo.
echo ℹ️  처음 접속 시:
echo    - Sign Up 페이지에서 계정 생성
echo    - 첫 가입자가 자동으로 관리자가 됩니다
echo.
echo 💡 권장 계정 정보:
echo    Email: admin@localhost
echo    Password: homework-helper-2025
echo ================================
echo.

REM 5초 대기 후 브라우저 열기
echo 5초 후 브라우저가 자동으로 열립니다...
timeout /t 5 /nobreak >nul

start http://localhost:8080

echo.
echo ✅ 완료! 브라우저에서 Label Studio를 확인하세요.
echo.
echo 종료하려면 'stop-label-studio.bat'를 실행하세요.
echo.
pause
