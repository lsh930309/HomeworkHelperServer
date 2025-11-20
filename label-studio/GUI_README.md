# 🎯 Label Studio Manager

Label Studio 서버 제어 및 데이터 전처리를 위한 통합 GUI 툴

## ✨ 주요 기능

### 1️⃣ 서버 제어
- ✅ Docker 상태 실시간 모니터링
- ✅ Label Studio 서버 원클릭 시작/중지
- ✅ 실시간 로그 뷰어 (에러 필터링)
- ✅ 브라우저 자동 열기

### 2️⃣ 데이터 전처리
- ✅ SSIM 기반 스마트 비디오 샘플링
- ✅ 프리셋 지원 (빠른/표준/정밀)
- ✅ 진행률 표시 및 예상 시간
- ✅ 취소 기능

### 3️⃣ 상태 모니터링
- ✅ Docker 및 Label Studio 상태 표시
- ✅ 에러/경고 카운트
- ✅ 마지막 업데이트 시간

## 📦 설치 및 실행

### 독립 실행

```bash
# label-studio 디렉토리로 이동
cd label-studio

# GUI 툴 실행
python label_studio_launcher.pyw
```

### Homework Helper에서 실행

Homework Helper 메인 앱에서 메뉴를 통해 실행 가능합니다.

## 🏗 프로젝트 구조

```
label-studio/
├── gui/
│   ├── core/                    # 핵심 모듈
│   │   ├── config_manager.py    # 설정 관리
│   │   ├── docker_manager.py    # Docker 제어
│   │   ├── schema_manager.py    # 스키마 CRUD
│   │   ├── sampler_manager.py   # SSIM 샘플러
│   │   └── dataset_analyzer.py  # 데이터셋 통계
│   │
│   ├── widgets/                 # 재사용 위젯
│   │   ├── log_viewer.py        # 로그 뷰어
│   │   ├── progress_widget.py   # 진행률 위젯
│   │   └── status_indicator.py  # 상태 표시기
│   │
│   ├── tabs/                    # 탭 화면
│   │   ├── server_control_tab.py   # 서버 제어
│   │   └── preprocessing_tab.py    # 전처리
│   │
│   └── label_studio_manager.py  # 메인 윈도우
│
├── label_studio_launcher.pyw    # 진입점
├── config.json                  # 사용자 설정 (자동 생성)
└── GUI_README.md                # 이 파일
```

## ⚙️ 설정

설정은 `label-studio/gui/config.json`에 자동으로 저장됩니다.

### 기본 설정

```json
{
  "config": {
    "last_raw_data_path": "",
    "last_output_path": "",
    "auto_open_browser": true,
    "label_studio_port": 8080,
    "current_preset": "standard",
    "window_width": 1200,
    "window_height": 800
  },
  "presets": {
    "quick": {
      "name": "빠른 샘플링",
      "ssim_high": 0.95,
      "ssim_low": 0.80,
      "interval": 3.0,
      "quality": 90
    },
    "standard": {
      "name": "표준 샘플링",
      "ssim_high": 0.98,
      "ssim_low": 0.85,
      "interval": 5.0,
      "quality": 95
    },
    "precise": {
      "name": "정밀 샘플링",
      "ssim_high": 0.99,
      "ssim_low": 0.90,
      "interval": 8.0,
      "quality": 98
    }
  }
}
```

## 📝 사용 방법

### 서버 시작하기

1. **서버 제어** 탭 클릭
2. Docker 상태 확인 (✅ 실행 중이어야 함)
3. **🚀 서버 시작** 버튼 클릭
4. 로그에서 시작 과정 확인
5. Label Studio 상태가 "✅ 실행 중"이 되면 **🌐 브라우저 열기** 클릭

### 비디오 샘플링하기

1. **전처리** 탭 클릭
2. **입력 비디오** 선택 (찾아보기 버튼)
3. **출력 폴더** 선택
4. **프리셋** 선택 (빠른/표준/정밀)
5. **🎬 샘플링 시작** 버튼 클릭
6. 진행률 바에서 진행 상황 확인
7. 완료 후 출력 폴더에서 결과 확인

## 🔧 개발

### 새 탭 추가하기

1. `gui/tabs/` 폴더에 새 탭 파일 생성
2. `QWidget`을 상속받는 클래스 작성
3. `gui/tabs/__init__.py`에 export 추가
4. `label_studio_manager.py`에서 탭 등록

예시:

```python
# gui/tabs/my_new_tab.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class MyNewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("새 탭입니다!"))
        self.setLayout(layout)
```

### 새 위젯 추가하기

`gui/widgets/` 폴더에 재사용 가능한 위젯 작성

## 🐛 문제 해결

### Docker가 실행되지 않습니다

- Docker Desktop이 실행 중인지 확인하세요
- Windows: 작업 관리자에서 "Docker Desktop" 프로세스 확인
- 재시작 후 다시 시도하세요

### Label Studio가 시작되지 않습니다

1. 로그 확인 (서버 제어 탭)
2. 포트 8080이 이미 사용 중인지 확인
3. `docker-compose.yml` 파일 위치 확인
4. `docker-compose down`으로 기존 컨테이너 제거 후 재시작

### 샘플링이 느립니다

- **빠른 샘플링** 프리셋 사용
- 비디오 해상도 낮추기
- SSD에서 작업하기

## 🎨 향후 추가 예정 기능

- [ ] 스키마 관리 탭 (클래스 CRUD)
- [ ] 데이터셋 통계 대시보드
- [ ] YOLO 변환 원클릭
- [ ] 백업/복원 기능
- [ ] Label Studio 프로젝트 자동 생성
- [ ] 데이터셋 시각화
- [ ] 환경 체크 기능
- [ ] 비디오 세그멘테이션 UI

## 📄 라이선스

MIT License

## 👥 개발자

HomeworkHelper Development Team

---

**버전**: 1.0.0
**최종 업데이트**: 2025-11-20
