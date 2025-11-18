@echo off
chcp 65001 >nul
title HomeworkHelper - Label Studio 로그

echo ================================
echo HomeworkHelper Label Studio 로그
echo ================================
echo.

REM label-studio 디렉토리로 이동
cd /d "%~dp0label-studio"
if %errorlevel% neq 0 (
    echo ❌ label-studio 디렉토리를 찾을 수 없습니다!
    pause
    exit /b 1
)

echo 📋 Label Studio 로그 출력 중...
echo (Ctrl+C로 종료)
echo.

REM 로그 실시간 출력
docker-compose logs -f

pause
