# 🚀 프로젝트: 스크린 인식을 통한 게임 데이터 자동 수집 시스템

## 1. 프로젝트 목표

주기적인 화면 캡처, OCR, 템플릿 매칭을 통해 게임 내 특정 UI 요소의 정보를 자동으로 인식하고, 이를 바탕으로 사용자의 게임 플레이 데이터를 수집 및 로깅한다.

**주요 수집 대상:**
1.  **반복성 콘텐츠:** 일일/주간 임무 수행 여부 (템플릿 매칭)
2.  **콘텐츠 시간:** 특정 콘텐츠(전투, 시뮬레이션 등)의 시작/종료 시간 및 소요 시간 (상태 추적)
3.  **게임 내 자원:** 개척력, 배터리 등 자동 충전 자원 트래킹 (OCR)
4.  **재화:** 성옥, 원석 등 현금성 재화 트래킹 (OCR)

## 2. 핵심 아키텍처

본 시스템은 **"데이터셋 구축"** 단계와 **"라이브 서비스"** 단계로 분리된다.

* **1단계 (개발): 데이터셋 구축 및 파라미터 최적화**
    * `Label Studio`를 사용해 사전 녹화된 게임 영상(`gameplay.mp4`)에서 라벨링을 수행한다.
    * 라벨링 결과(`labels.json`)를 '정답지'로 삼아, `optimizer.py` 스크립트가 최적의 OCR 전처리 파라미터를 탐색한다.
    * 탐색된 최적의 파라미터와 BBox 좌표를 `config.json`에 저장한다.

* **2단계 (운영): 라이브 데이터 수집**
    * `main_collector.py`가 `config.json`을 로드한다.
    * `mss`를 사용해 실시간 게임 화면을 캡처한다.
    * 설정값에 따라 이미지를 전처리하고 OCR/템플릿 매칭을 수행한다.
    * 인식된 데이터를 (예: `logs.db` 또는 `data.csv`)에 기록한다.

## 3. 개발 워크플로우 (핵심)

가장 큰 난관인 'OCR 파라미터 튜닝'을 자동화하는 것이 핵심이다.

### Phase 1: 데이터셋 구축 (Label Studio)

1.  **도구:** `Label Studio`
2.  **입력:** `dataset/gameplay.mp4` (미리 녹화한 전체 화면 영상)
3.  **작업:**
    * 영상에서 인식할 대상(예: '개척력')의 BBox를 그린다.
    * 해당 BBox에 `stamina` (개척력) 같은 `key`를 할당한다.
    * 해당 BBox가 유효한 '시간 구간'을 지정한다.
    * 해당 구간에서 OCR이 읽어야 할 '정답 텍스트'(예: `"180 / 240"`)를 입력한다.
    * 다른 모든 수집 대상(재화, 임무 완료 체크)에 대해 반복한다.
4.  **출력:** `dataset/labels.json` (BBox 좌표, Key, 시간 구간, 정답 텍스트가 포함된 구조화된 데이터)

### Phase 2: OCR 파라미터 최적화 (자동화 스크립트)

1.  **스크립트:** `optimizer.py`
2.  **입력:** `dataset/gameplay.mp4` + `dataset/labels.json`
3.  **로직 (Grid Search):**
    * 테스트할 전처리 파라미터 후보군을 정의한다. (예: `threshold_values = [100, 120, 140]`, `blur_kernels = [(3,3), (5,5)]`)
    * 모든 파라미터 조합을 순회한다.
    * 각 조합으로 `labels.json`에 명시된 모든 '유효 구간'의 프레임을 처리(BBox 자르기 -> 전처리 -> OCR)한다.
    * OCR 결과와 `labels.json`의 '정답 텍스트'를 비교하여 정확도(Score)를 계산한다.
4.  **출력:** 가장 높은 정확도를 보인 파라미터 조합 (예: `{'threshold': 140, 'blur_kernel': (3,3)}`)

### Phase 3: 설정 파일 완료

1.  **파일:** `config.json`
2.  **작업:**
    * Phase 1에서 정의한 BBox 좌표와 Key를 저장한다.
    * Phase 2에서 찾은 최적의 OCR 파라미터를 저장한다.
    * 템플릿 매칭에 사용할 이미지 경로(예: `templates/quest_done.png`)를 저장한다.

### Phase 4: 라이브 서비스 실행

1.  **스크립트:** `main_collector.py`
2.  **작업:**
    * `config.json`을 로드한다.
    * 무한 루프를 돌며 `mss`로 실시간 화면의 BBox 영역만 캡처한다.
    * `config.json`에 저장된 최적의 파라미터로 전처리 및 인식을 수행한다.
    * 이전 상태와 비교하여 변화(예: 자원 소모, 임무 완료)를 감지한다.
    * 감지된 이벤트를 타임스탬프와 함께 로깅한다.

## 4. 예상 디렉터리 구조

/game-data-collector/ | |-- main_collector.py # 4단계: 라이브 수집기 |-- optimizer.py # 2단계: OCR 파라미터 자동 튜닝 스크립트 | |-- config.json # 3단계: BBox 좌표 및 최적 파라미터가 저장된 설정 파일 |-- requirements.txt # (mss, opencv-python, pytesseract, numpy) | |-- /dataset/ | |-- gameplay.mp4 # 1단계: 라벨링을 위한 원본 게임 영상 | |-- labels.json # 1단계: Label Studio에서 Export한 정답지 | |-- /templates/ | |-- quest_complete.png # 템플릿 매칭용 '임무 완료' V체크 아이콘 | |-- combat_icon.png # '전투 상태' 감지용 템플릿 | |-- /logs/ |-- events.log # 수집된 데이터가 저장될 파일 (또는 .db, .csv)


## 5. 핵심 라이브러리

* **`mss`:** 실시간 화면 캡처 (BBox 영역만 빠르게 캡처하는 데 최적화됨)
* **`opencv-python` (`cv2`)**: 이미지 전처리(흑백, 이진화), 템플릿 매칭, 비디오 파일 읽기
* **`pytesseract`:** OCR 수행 (Tesseract 엔진 연동)
* **`numpy`:** OpenCV 이미지 데이터(배열) 처리
* **`label-studio`:** (설치형 도구) 데이터셋 구축용