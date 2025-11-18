@echo off
chcp 65001 >nul
title HomeworkHelper - Label Studio 중지

echo ================================
echo HomeworkHelper Label Studio 중지
echo ================================
echo.

REM label-studio 디렉토리로 이동
cd /d "%~dp0label-studio"
if %errorlevel% neq 0 (
    echo ❌ label-studio 디렉토리를 찾을 수 없습니다!
    pause
    exit /b 1
)

echo 📦 Label Studio 컨테이너 중지 중...
echo.

REM Docker Compose로 Label Studio 중지
docker-compose down

if %errorlevel% neq 0 (
    echo.
    echo ❌ Label Studio 중지 실패!
    echo.
    pause
    exit /b 1
)

echo.
echo ✅ Label Studio가 중지되었습니다!
echo.
pause
