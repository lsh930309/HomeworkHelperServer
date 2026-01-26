# 코드베이스 분석 보고서
**날짜**: 2026-01-27
**작성자**: Claude Code

## 발견된 문제 및 개선사항

### 1. UI 지속 갱신이 멈추는 현상

#### 현재 구조
- **5개의 독립 타이머**: monitor_timer (1초), scheduler_timer (1초), web_button_refresh_timer (60초), status_column_refresh_timer (30초), progress_bar_refresh_timer (1초)
- **절전 복귀 감지**: `_on_monitor_timer_tick()`에서 5초 이상 경과 시 절전 복귀로 판단
- **타이머 재시작**: `_ensure_timers_running()`으로 중단된 타이머 재시작

#### 잠재적 문제
- 타이머 충돌 가능성: 여러 타이머가 동시에 UI를 업데이트하면 경합 상태(race condition) 발생 가능
- Qt 이벤트 루프 블로킹: 장시간 작업이 메인 스레드를 점유하면 타이머 틱이 누락될 수 있음
- 절전 복귀 감지 오차: 5초 임계값이 시스템 부하가 높을 때 오탐할 수 있음

#### 재현 조건 파악 필요
- 특정 상황이 무엇인지 로그를 통해 파악
- 타이머가 멈추는 순간의 이벤트 추적

---

### 2. 진행률 컬럼 표기 통일

#### 현재 상태
- **호요버스 게임**: 아이콘 + Progress Bar (라인 1485-1515, main_window.py)
- **일반 게임**: Progress Bar만 표시 (라인 1516-1523)

#### 개선 방안
- 모든 게임에 대해 동일한 아이콘 공간 + Progress Bar 레이아웃 적용
- 호요버스가 아닌 게임은 아이콘 공간을 비워두고 Progress Bar만 표시
- 시각적 일관성 확보

#### 수정 대상
- `_create_progress_bar_widget()` 메서드 (라인 1476-1523)
- Progress Bar 생성 로직 통일

---

### 3. game_schema_id 저장 문제

#### 현재 상황
- **데이터베이스**: `ProcessSession.game_schema_id` 컬럼 존재 (nullable=True)
- **FastAPI 서버**: 기본 엔드포인트만 있고 CRUD 라우터가 주석 처리됨
- **저장 로직**: `create_session()`과 `end_session()`에서 game_schema_id 전달 가능

#### 문제
- FastAPI `/sessions` 엔드포인트가 구현되지 않아서 웹으로 조회 불가
- game_schema_id가 실제로 저장되고 있는지 확인 필요

#### 필요성 검토
- **MVP 연동 용도**: 현재는 사용되지 않는 것으로 보임
- **hoyolab_game_id와의 혼동**: 스태미나 추적에는 hoyolab_game_id를 사용
- **제거 고려**: MVP 기능이 활성화되지 않으면 불필요할 수 있음

---

### 4. game_schema_id vs hoyolab_game_id 혼용 점검

#### 명확한 구분

| 필드명 | 목적 | 값 예시 | 사용 위치 |
|--------|------|--------|---------|
| **game_schema_id** | MVP 연동 (범용) | "zenless_zone_zero" | Process 모델, Session 모델, MVP 토글 |
| **hoyolab_game_id** | HoYoLab API 조회용 | "honkai_starrail", "zenless_zone_zero" | 스태미나 조회 전용 |

#### 혼동 사례
- **HoYoLab Service** (라인 117, `/src/services/hoyolab.py`)
  ```python
  def get_stamina(self, game_schema_id: str) -> Optional[StaminaInfo]:
  ```
  - 파라미터명이 `game_schema_id`이지만 실제로는 `hoyolab_game_id`를 받아야 함
  - 호출 시점: `process_monitor.py` 라인 170, 201

#### 수정 필요
- HoYoLab Service의 파라미터명을 `hoyolab_game_id`로 변경
- 일관성 있는 네이밍 유지

---

### 5. 창 위치 기억 + 마그넷 기능

#### 현재 구현
- **메모리 기반 임시 저장**: `_saved_geometry`, `_saved_size`
- **저장 시점**: 불명확 (라인 1414-1415에서 설정)
- **복원 시점**: 절전 복귀 시, 창 활성화 시

#### 부재 기능
- **영구 저장**: 앱 재시작 후에도 마지막 창 위치 기억
- **마그넷 스냅**: 모니터 가장자리에 창이 자동으로 붙는 기능

#### 구현 방안
1. **창 위치 저장**
   - `closeEvent()` 또는 `moveEvent()`에서 창 위치 저장
   - Settings 파일에 `window_geometry` 저장 (QByteArray)
   - 앱 시작 시 복원

2. **마그넷 기능**
   - `moveEvent()` 오버라이드
   - 창이 화면 가장자리 근처 (예: 10px 이내)에 있으면 자동 정렬
   - 멀티 모니터 환경 고려

---

### 6. main_window.py 리팩토링

#### 현재 상태
- **파일 크기**: 1791줄
- **클래스 구조**: MainWindow + IconDownloader
- **메서드 수**: 약 50개

#### 문제점
- 단일 파일에 모든 UI 로직이 집중
- 메서드별 역할은 명확하지만 응집도가 낮음
- 유지보수 어려움

#### 리팩토링 전략

##### Option 1: 기능별 모듈 분리
```
gui/
├── main_window.py (핵심 창 관리만)
├── widgets/
│   ├── progress_widget.py (Progress Bar 관련)
│   ├── web_button_panel.py (웹 바로가기 패널)
│   └── process_table.py (프로세스 테이블)
├── managers/
│   ├── timer_manager.py (타이머 관리)
│   └── window_state_manager.py (창 상태 관리)
└── dialogs.py (기존)
```

##### Option 2: MVC 패턴 적용
```
gui/
├── views/
│   ├── main_window_view.py
│   └── widgets/
├── controllers/
│   ├── main_window_controller.py
│   └── process_controller.py
└── models/ (기존 data/ 활용)
```

**추천**: Option 1 (점진적 리팩토링 가능)

---

### 7. 불필요한 디버깅 코드 정리

#### print() 문 위치
- **main_window.py**: 약 30개 (절전 복귀, 창 상태, 타이머 등)
- **process_monitor.py**: 약 20개 (프로세스 시작/종료, 스태미나)
- **scheduler.py**: 2개 (스태미나 알림)
- **dialogs.py**: 2개 (프리셋 자동 감지)

#### 파일 기반 디버그 로그
- `~/.HomeworkHelper/logs/stamina_debug.log`
- `_debug_log()` 함수 사용

#### 정리 전략
1. **제거 대상**
   - 일반 동작 추적용 print() (예: "절전 복귀 UI 갱신 시작")
   - 창 크기 조절 관련 주석 처리된 print()

2. **유지 대상**
   - 에러 처리 시 print() → logging.error()로 변경
   - 중요 이벤트 로그 → logging.info()로 변경

3. **로깅 표준화**
   - 모든 모듈에 `logger = logging.getLogger(__name__)` 추가
   - 로그 레벨 설정: DEBUG, INFO, WARNING, ERROR
   - 설정 파일에서 로그 레벨 토글 가능하도록

---

## 우선순위 제안

### High Priority (즉시 작업)
1. **#4**: game_schema_id vs hoyolab_game_id 파라미터명 수정 (간단, 버그 방지)
2. **#2**: 진행률 컬럼 표기 통일 (UI 개선, 사용자 경험)
3. **#7**: 디버깅 코드 정리 (코드 품질, 리팩토링 준비)

### Medium Priority (계획 후 작업)
4. **#3**: game_schema_id 저장 문제 조사 및 필요성 검토
5. **#1**: UI 갱신 멈춤 현상 재현 및 수정 (로그 추가 필요)
6. **#5**: 창 위치 기억 + 마그넷 기능 (사용자 편의)

### Low Priority (대규모 작업)
7. **#6**: main_window.py 리팩토링 (시간 소요, 점진적 진행)

---

## 다음 단계
1. To-Do List 생성 (TaskCreate)
2. High Priority 항목부터 작업 시작
3. 각 작업 완료 후 이 파일에 진행 상황 업데이트
