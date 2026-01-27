# 작업 진행 상황
**시작일**: 2026-01-27
**최종 업데이트**: 2026-01-27

## 작업 우선순위

### High Priority (즉시 작업)
- [x] Task #1: game_schema_id vs hoyolab_game_id 파라미터명 수정 ✅
- [x] Task #2: 진행률 컬럼 표기 통일 (아이콘 공간 + Progress Bar) ✅
- [x] Task #3: 불필요한 디버깅 코드 정리 및 로깅 표준화 ✅

### Medium Priority (계획 후 작업)
- [x] Task #4: game_schema_id 저장 문제 조사 및 필요성 검토 ✅
- [x] Task #5: UI 갱신 멈춤 현상 재현 및 수정 ✅
- [ ] Task #6: 창 위치 기억 및 마그넷 기능 구현

### Low Priority (대규모 작업)
- [ ] Task #7: main_window.py 리팩토링 (기능별 모듈 분리)

---

## 작업 로그

### 2026-01-27
- **13:00**: 코드베이스 탐색 완료
- **13:30**: 분석 보고서 작성 완료
- **13:45**: To-Do List 7개 항목 생성
- **14:00**: Task #1 완료 - HoYoLab Service의 파라미터명을 game_schema_id → hoyolab_game_id로 수정
  - 변경 파일: src/services/hoyolab.py:117-132
  - docstring 및 함수 내부 참조 모두 업데이트
- **14:15**: Task #2 완료 - 진행률 컬럼 표기 통일
  - 변경 파일: src/gui/main_window.py:1476-1540
  - 모든 경우에 동일한 레이아웃 적용: 아이콘 공간(18x18) + 위젯
  - 3가지 케이스 모두 일관성 확보: (1) 기록 없음, (2) 호요버스 게임, (3) 일반 게임
  - 컨테이너 마진/스페이싱 통일: (2,0,2,0), spacing 4
  - stretch factor 1로 Progress Bar가 남은 공간을 균일하게 채움
- **15:00**: Task #3 완료 - 디버깅 코드 정리 및 로깅 표준화
  - 변경 파일:
    * src/gui/main_window.py: 23개 print() 제거/변환
    * src/core/process_monitor.py: 15개 print() → logging 변환
    * src/core/scheduler.py: 7개 print() → logging 변환
    * src/gui/dialogs.py: 8개 print() → logging 변환
  - 총 53개 print() 문 정리 완료
  - logging 모듈 표준화: logger.info(), logger.error(), logger.warning(), logger.debug()
  - 일반 동작 추적용 print() 완전 제거
  - 중요 이벤트는 logging.info()로 변환
  - 에러는 logging.error()로 변환 (exc_info=True 옵션 사용)
- **15:30**: 커밋 완료 (4038c8a)
- **16:00**: Task #5 완료 - UI 갱신 멈춤 현상 수정 및 최적화
  - 변경 파일: src/gui/main_window.py
  - **절전 복귀 문제 해결**:
    * _on_sleep_wake()에서 테이블 전체 다시 채우기 (populate_process_list)
    * viewport 강제 업데이트 (update() + repaint())
    * 절전 복귀 감지 임계값 5초 → 10초로 증가 (오탐 방지)
  - **UI 갱신 최적화**:
    * _refresh_progress_bars(): 값 변경 시에만 업데이트, 색상 구간 변경 시에만 스타일시트 적용
    * _refresh_status_columns(): 상태 변경 시 viewport 강제 갱신
    * run_process_monitor_check(): game mode 체크를 상태 변경 시에만 수행
  - **타이머 성능 모니터링**:
    * 모든 타이머 콜백에 실행 시간 로깅 추가 (100ms 초과 시 경고)
    * monitor_timer, scheduler_timer, progress_bar_refresh_timer, status_column_refresh_timer
- **16:30**: Task #4 완료 - game_schema_id → user_preset_id 재정의 및 MVP 완전 제거
  - 조사 완료: game_schema_id는 사용자 프리셋 관리용, MVP는 미구현
  - **완료된 작업**:
    * DB 모델 변경: game_schema_id → user_preset_id, mvp_enabled 제거
    * DB 마이그레이션: 자동 컬럼 추가 + 데이터 복사 (game_schema_id → user_preset_id)
    * data_models.py: ManagedProcess 파라미터/속성 변경
    * schemas.py: ProcessSchema, ProcessSessionCreate/Schema 변경
    * scheduler.py: game_schema_id → hoyolab_game_id 사용
    * main_window.py: _get_stamina_icon_path 파라미터 변경, ManagedProcess 생성 시 user_preset_id 사용
    * dialogs.py: MVP UI 섹션 완전 제거 + 프리셋 자동 선택 구현
      - MVP import 제거 (SCHEMA_SUPPORT 등)
      - 6개 MVP 메서드 삭제 (_setup_mvp_section, _on_game_schema_changed, _on_monitoring_path_changed, _open_schema_editor, _sync_hoyolab_game_combo, _update_stamina_section_enabled)
      - populate_fields_from_existing_process()에 user_preset_id로 프리셋 자동 선택 기능 추가
      - get_data()에서 user_preset_id 사용
    * preset_editor_dialog.py: MVP 체크박스 및 관련 로직 제거
  - **주요 개선사항**:
    * 프로세스 편집 시 기존 프리셋이 자동으로 선택됨
    * 코드 간소화 (약 100줄 제거)
    * user_preset_id로 일관성 있는 네이밍
- **17:00**: 프로젝트 정리 - 미사용 server/ 폴더 및 Docker 파일 제거
  - **제거된 파일**:
    * server/ 폴더 전체 (PostgreSQL 기반, 미구현 스켈레톤 코드)
    * docker-compose.yml (Docker 배포용 설정, 미사용)
  - **homework_helper.pyw 마이그레이션 수정**:
    * ensure_process_table_schema() 함수 업데이트
    * game_schema_id, mvp_enabled → user_preset_id로 변경
    * stamina_tracking_enabled, hoyolab_game_id 추가
  - **실제 사용 중인 서버**: homework_helper.pyw의 run_server_main() 함수
    * SQLite 로컬 DB (127.0.0.1:8000)
    * multiprocessing으로 GUI와 독립 실행
  - **결과**: 약 360줄의 미사용 코드 제거, 프로젝트 구조 단순화

---

## 주요 발견사항
- main_window.py: 1791줄 (리팩토링 필요)
- 5개의 독립 타이머로 UI 갱신 관리
- game_schema_id와 hoyolab_game_id 역할 구분 필요
- 약 50개 이상의 print() 디버깅 문 산재
- FastAPI CRUD 엔드포인트 미구현
