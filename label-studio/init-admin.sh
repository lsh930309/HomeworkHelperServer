#!/bin/bash

# Label Studio 초기화 및 관리자 계정 생성 스크립트

echo "Label Studio 초기화 중..."

# Label Studio 데이터베이스 마이그레이션
label-studio migrate

# 관리자 계정이 없으면 생성
echo "관리자 계정 확인 중..."
label-studio user --username admin > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "관리자 계정 생성 중..."
    label-studio user --username admin --password homework-helper-2025 --user-email admin@localhost
    echo "관리자 계정이 생성되었습니다."
else
    echo "관리자 계정이 이미 존재합니다."
fi

# Label Studio 시작
echo "Label Studio 시작 중..."
exec label-studio --host 0.0.0.0 --port 8080
