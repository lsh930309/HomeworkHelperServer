# 스키마 자동 마이그레이션 시스템

**작성일**: 2025-11-14
**버전**: 1.0.0
**관련 모듈**: `src/migration/schema_migrator.py`

---

## 📋 개요

HomeworkHelper MVP의 스키마 구조가 업데이트될 때, 기존 사용자의 데이터를 자동으로 새 구조로 마이그레이션하는 시스템입니다.

### 핵심 특징
- ✅ **투명한 마이그레이션**: 사용자에게 보이지 않음
- ✅ **자동 백업**: 마이그레이션 전 자동 백업 생성
- ✅ **롤백 지원**: 실패 시 자동 롤백
- ✅ **버전 추적**: 마이그레이션 이력 기록

---

## 🔄 동작 방식

### 1. 앱 시작 시 자동 체크

```
앱 시작 (homework_helper.pyw)
    ↓
SchemaMigrator.check_and_migrate()
    ↓
버전 체크
    ├── 최신 버전 → 패스
    ├── 구 버전 → 마이그레이션
    └── 신규 설치 → 기본 구조 생성
    ↓
정상 앱 실행
```

### 2. 버전 감지 로직

| 상태 | 감지 방법 | 처리 |
|-----|---------|------|
| 신규 설치 | schemas/ 없음 | 빈 구조 생성 |
| v1.0.0 (구) | 통합 JSON 파일 존재 | v1→v2 마이그레이션 |
| v2.0.0 (신) | version.json = 2.0.0 | 패스 |
| version.json 누락 | games/ 존재 | version.json 생성 |

---

## 📁 스키마 버전

### v1.0.0 (구 구조)
```
schemas/
├── game_resources.json    (4개 게임 통합)
├── game_contents.json     (4개 게임 통합)
└── ui_elements.json       (4개 게임 통합)
```

### v2.0.0 (신 구조)
```
schemas/
├── version.json           # 버전 정보
├── registry.json          # 게임 목록 + 프로세스 매칭
└── games/
    ├── zenless_zone_zero/
    │   ├── metadata.json
    │   ├── resources.json
    │   ├── contents.json
    │   └── ui_elements.json
    ├── honkai_star_rail/
    ├── wuthering_waves/
    └── nikke/
```

---

## 🛠️ 사용법

### 앱 시작 시 자동 실행

`homework_helper.pyw`에 이미 통합되어 있습니다:

```python
# === 스키마 자동 마이그레이션 ===
try:
    from src.migration import SchemaMigrator
    migrator = SchemaMigrator()
    if not migrator.check_and_migrate():
        print("⚠️ 스키마 마이그레이션 실패")
except Exception as e:
    print(f"스키마 마이그레이션 체크 중 오류: {e}")
```

### 수동 실행 (개발/테스트용)

```python
from src.migration import SchemaMigrator

migrator = SchemaMigrator()
print(f"현재 버전: {migrator.get_current_version()}")
print(f"목표 버전: {migrator.CURRENT_VERSION}")

# 마이그레이션 실행
success = migrator.check_and_migrate()
print(f"결과: {'성공' if success else '실패'}")
```

### 편의 함수

```python
from src.migration.schema_migrator import check_and_migrate_schemas

# 간단한 호출
success = check_and_migrate_schemas()
```

---

## 📂 파일 구조

### version.json

```json
{
  "schema_version": "2.0.0",
  "last_migration": "2025-11-14T12:00:00Z",
  "migration_history": [
    {
      "from": "1.0.0",
      "to": "2.0.0",
      "date": "2025-11-14T12:00:00Z",
      "description": "통합 JSON → 게임별 디렉토리 구조"
    }
  ]
}
```

### 백업 디렉토리

마이그레이션 시 자동 백업:
```
schemas/
├── backup_v1.0.0_20251114_120000/  # 자동 생성
│   ├── game_resources.json
│   ├── game_contents.json
│   └── ui_elements.json
└── games/
    └── ...
```

---

## 🔧 새 마이그레이션 추가하기

### 1. 마이그레이션 함수 작성

```python
# src/migration/schema_migrator.py

def _migrate_v2_to_v3(self) -> bool:
    """v2.0.0 → v3.0.0 마이그레이션"""
    logger.info("v2.0.0 → v3.0.0 마이그레이션 시작...")

    try:
        # 마이그레이션 로직 구현
        # 예: 새 필드 추가, 구조 변경 등

        logger.info("v2.0.0 → v3.0.0 마이그레이션 완료")
        return True

    except Exception as e:
        logger.error(f"v2→v3 마이그레이션 실패: {e}")
        return False
```

### 2. 마이그레이션 경로 등록

```python
def find_migration_path(self, from_version: str, to_version: str):
    migrations = {
        "1.0.0": ["2.0.0"],
        "2.0.0": ["3.0.0"],  # 새 경로 추가
        "3.0.0": [],
    }
    # ...
```

### 3. 실행 함수 등록

```python
def _execute_single_migration(self, from_version: str, to_version: str):
    migrations = {
        ("1.0.0", "2.0.0"): self._migrate_v1_to_v2,
        ("2.0.0", "3.0.0"): self._migrate_v2_to_v3,  # 새 함수 등록
    }
    # ...
```

### 4. 현재 버전 업데이트

```python
class SchemaMigrator:
    CURRENT_VERSION = "3.0.0"  # 업데이트
```

---

## 🔒 안전장치

### 1. 자동 백업
- 마이그레이션 전 전체 schemas 디렉토리 백업
- 타임스탬프 포함 이름: `backup_v1.0.0_20251114_120000`

### 2. 롤백 지원
- 마이그레이션 실패 시 자동 롤백
- `restore_backup()` 메서드로 수동 복원 가능

### 3. 에러 핸들링
- 모든 단계에서 예외 처리
- 실패해도 앱 실행은 계속 (기존 기능 유지)

### 4. 로깅
- 모든 마이그레이션 과정 로깅
- 디버그/문제 해결용

---

## 🎯 사용자 경험

### 사용자 입장에서
1. 앱 업데이트 다운로드
2. 앱 실행 (평소와 동일)
3. 자동으로 데이터 구조 업데이트 (1-2초)
4. 정상 사용

### 보이지 않는 것
- 마이그레이션 진행 상황
- 백업 생성
- 버전 관리

### 선택적 표시
- 마이그레이션 실패 시 콘솔 경고 (개발 모드)
- 심각한 실패 시 QMessageBox (선택적)

---

## 📊 테스트 방법

### 1. 구 버전 시뮬레이션

```bash
# schemas/old/ 에서 구 파일 복원
cp schemas/old/*.json schemas/

# version.json 삭제
rm schemas/version.json

# 앱 실행 → 자동 마이그레이션
python homework_helper.pyw
```

### 2. 단위 테스트

```python
def test_migration_v1_to_v2():
    # 테스트 디렉토리 생성
    test_dir = Path("test_schemas")
    # 구 파일 복사
    # 마이그레이션 실행
    # 결과 검증
    # 정리
```

---

## 🚀 향후 개선 계획

### 1. GUI 알림 (선택적)
```python
if not migrator.check_and_migrate():
    QMessageBox.warning(
        None,
        "데이터 업데이트 알림",
        "스키마 업데이트 중 문제가 발생했습니다.\n"
        "앱이 정상 동작하지 않을 수 있습니다."
    )
```

### 2. 프로그레스 바 (대용량 마이그레이션 시)
- 수천 개 게임 스키마 마이그레이션 시
- QProgressDialog 표시

### 3. 클라우드 백업
- 마이그레이션 전 클라우드에 백업
- 복원 옵션 제공

---

## 🔗 관련 문서

- **[Phase 0 - MVP 통합 설계](phase0-mvp-integration.md)**: 프로세스-스키마 연동
- **[MVP 로드맵](mvp-roadmap.md)**: 전체 개발 계획
- **[스키마 구조 개선](../claude.md)**: 디렉토리 구조 설명

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-11-14
