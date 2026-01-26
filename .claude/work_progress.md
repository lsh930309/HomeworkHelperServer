# 작업 진행 상황
**시작일**: 2026-01-27
**최종 업데이트**: 2026-01-27

## 작업 우선순위

### High Priority (즉시 작업)
- [x] Task #1: game_schema_id vs hoyolab_game_id 파라미터명 수정 ✅
- [x] Task #2: 진행률 컬럼 표기 통일 (아이콘 공간 + Progress Bar) ✅
- [x] Task #3: 불필요한 디버깅 코드 정리 및 로깅 표준화 ✅

### Medium Priority (계획 후 작업)
- [ ] Task #4: game_schema_id 저장 문제 조사 및 필요성 검토
- [ ] Task #5: UI 갱신 멈춤 현상 재현 및 수정
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
- **다음 단계**: High Priority 작업 완료, Medium Priority 검토

---

## 주요 발견사항
- main_window.py: 1791줄 (리팩토링 필요)
- 5개의 독립 타이머로 UI 갱신 관리
- game_schema_id와 hoyolab_game_id 역할 구분 필요
- 약 50개 이상의 print() 디버깅 문 산재
- FastAPI CRUD 엔드포인트 미구현
