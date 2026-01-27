# game_schema_id 조사 보고서
**날짜**: 2026-01-27
**작성자**: Claude Code

## 조사 결과 요약

**결론**: game_schema_id는 **DB에 저장되지 않고 있음**. MVP 기능도 실제로는 사용되지 않고 있음.

---

## 1. game_schema_id 필드 존재 위치

### ManagedProcess 모델 (src/data/models.py:27-28)
```python
game_schema_id = Column(String, nullable=True)  # 게임 스키마 ID
mvp_enabled = Column(Boolean, default=False)    # MVP 기능 플래그
```

### ProcessSession 모델 (src/data/models.py:83)
```python
game_schema_id = Column(String, nullable=True)  # 게임 스키마 ID
```

---

## 2. 세션 생성 시 game_schema_id 전달 여부

### process_monitor.py에서 세션 시작 (라인 97-101)
```python
session = self.data_manager.start_session(
    process_id=managed_proc.id,
    process_name=managed_proc.name,
    start_timestamp=start_timestamp
)
```
**문제**: `game_schema_id`를 전달하지 않음!

### ApiClient의 start_session (src/api/client.py:189-202)
```python
def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Optional[ProcessSession]:
    """새로운 프로세스 세션 시작"""
    try:
        data = {
            "process_id": process_id,
            "process_name": process_name,
            "start_timestamp": start_timestamp
        }
        response = requests.post(f"{self.base_url}/sessions", json=data)
        # ...
```
**문제**: `game_schema_id`를 포함하지 않음!

### ProcessSessionCreate 스키마 (src/data/schemas.py:83-90)
```python
class ProcessSessionCreate(BaseModel):
    process_id: str
    process_name: str
    start_timestamp: float
    game_schema_id: Optional[str] = None  # 포함되어 있지만 전달되지 않음
```

---

## 3. game_schema_id 실제 사용처

### scheduler.py (라인 344)
```python
stamina_name = "개척력" if process.game_schema_id == "honkai_starrail" else "배터리"
```
**용도**: 스태미나 이름 표시용 (호요버스 게임 구분)

**문제**: 이 기능은 이미 `hoyolab_game_id`로 대체 가능!

### dialogs.py (라인 824-841)
```python
# MVP 기능 토글
self.game_schema_combo = QComboBox()
self.mvp_enabled_check = QCheckBox("MVP 기능 활성화")
```
**용도**: MVP 연동 UI (게임 스키마 선택)

**문제**: 실제로 MVP 기능을 사용하는 코드가 없음!

---

## 4. FastAPI 엔드포인트 상태

### server/app/main.py
```python
# 주석 처리된 라우터들:
# app.include_router(sessions_router, prefix="/api/v1/sessions", tags=["sessions"])
# app.include_router(events_router, prefix="/api/v1/events", tags=["events"])
```

**문제**: `/sessions` 엔드포인트가 구현되지 않음! 주석 처리되어 있음.

---

## 5. hoyolab_game_id와의 관계

### 역할 구분

| 필드명 | 목적 | 실제 사용 여부 |
|--------|------|---------------|
| **game_schema_id** | MVP 연동 (범용) | ❌ 사용되지 않음 |
| **hoyolab_game_id** | HoYoLab API 조회용 | ✅ 실제로 사용 중 |

**중요**: `game_schema_id`의 역할은 `hoyolab_game_id`로 완전히 대체 가능!

scheduler.py에서의 유일한 사용처:
```python
# 현재
stamina_name = "개척력" if process.game_schema_id == "honkai_starrail" else "배터리"

# hoyolab_game_id로 변경 가능
stamina_name = "개척력" if process.hoyolab_game_id == "honkai_starrail" else "배터리"
```

---

## 6. MVP 기능 상태

### MVP 관련 코드 위치
- `src/data/models.py:28` - mvp_enabled 플래그
- `src/gui/dialogs.py:824-841` - MVP 토글 UI
- MVP 스키마 연동 import (dialogs.py:20-24) - 선택적 import

### 실제 사용 여부
**전혀 사용되지 않음!**

MVP 기능을 실제로 활용하는 로직이 코드베이스에 존재하지 않습니다.

---

## 결론 및 제안

### 현재 상황
1. `game_schema_id`는 DB 컬럼에만 존재하고 실제로 저장되지 않음
2. FastAPI 엔드포인트가 구현되지 않아 웹으로 조회 불가
3. MVP 기능은 UI만 있고 실제 기능은 미구현
4. `game_schema_id`의 유일한 사용처는 `hoyolab_game_id`로 대체 가능

### 제안 1: 완전 제거 (추천)
**이유**:
- 실제로 사용되지 않음
- hoyolab_game_id로 대체 가능
- 코드 복잡도 감소
- DB 마이그레이션 필요 없음 (nullable=True)

**제거할 항목**:
- ManagedProcess.game_schema_id, mvp_enabled
- ProcessSession.game_schema_id
- dialogs.py의 MVP UI
- scheduler.py에서 game_schema_id → hoyolab_game_id로 변경

### 제안 2: 제대로 구현 (미추천)
**필요 작업**:
- process_monitor.py에서 start_session 호출 시 game_schema_id 전달
- ApiClient.start_session에 game_schema_id 파라미터 추가
- MVP 기능 실제 구현
- FastAPI 엔드포인트 활성화

**문제**: MVP 기능의 목적이 불명확하고, 현재 필요성이 없음

---

## 최종 권장사항

**game_schema_id와 mvp_enabled를 완전히 제거하는 것을 권장합니다.**

현재 이 필드들은:
- 실제로 저장되지 않음
- 사용되지 않음
- hoyolab_game_id로 충분히 대체 가능
- 코드 복잡도만 증가시킴

제거 작업은 위험도가 낮습니다:
- DB 컬럼은 nullable=True이므로 기존 데이터에 영향 없음
- 실제 사용처가 1곳(scheduler.py)뿐이고, 쉽게 대체 가능
