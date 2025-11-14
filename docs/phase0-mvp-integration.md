# Phase 0 - MVP 스키마 통합 설계 문서

**작성일**: 2025-11-14
**대상**: HomeworkHelper Phase 0 (PC 클라이언트) + MVP (YOLO + OCR)
**목적**: 프로세스별 게임 스키마 연동 및 편집 기능 추가

---

## 📋 목차

1. [개요](#개요)
2. [설계 목표](#설계-목표)
3. [데이터 모델 확장](#데이터-모델-확장)
4. [UI 변경사항](#ui-변경사항)
5. [SchemaEditorDialog 설계](#schemaEditordialog-설계)
6. [데이터 플로우](#데이터-플로우)
7. [구현 우선순위](#구현-우선순위)

---

## 개요

Phase 0의 프로세스 관리 기능에 MVP의 게임 스키마 연동 기능을 추가하여, 사용자가 프로세스별로 게임 데이터(재화, 콘텐츠, UI 요소)를 관리할 수 있도록 합니다.

### 핵심 아이디어
- 프로세스 우클릭 → 설정 다이얼로그에서 **[Set Schema]** 버튼 추가
- 게임 스키마 선택 및 편집 다이얼로그 팝업
- 기존 Phase 0 기능과 독립적으로 동작 (MVP 비활성화 상태에서도 사용 가능)

---

## 설계 목표

### 1. 사용자 경험
- ✅ 기존 워크플로우 유지 (프로세스 추가/수정 과정 변경 최소화)
- ✅ 직관적인 스키마 연동 (자동 매칭 + 수동 선택)
- ✅ 스키마 편집 GUI 제공 (한국어 명칭 수정, 항목 추가/삭제)

### 2. 확장성
- ✅ MVP 기능 비활성화 상태에서도 동작
- ✅ 향후 YOLO 모델 학습 후 자동 활성화 가능
- ✅ 새 게임 스키마 추가 시 자동 인식

### 3. 데이터 무결성
- ✅ 기존 프로세스 데이터 호환성 유지
- ✅ 스키마 파일과 프로세스 연결 느슨한 결합 (선택 사항)
- ✅ 스키마 변경 시 프로세스 데이터 영향 없음

---

## 데이터 모델 확장

### 1. ManagedProcess 클래스 확장

**파일**: `src/data/data_models.py`

```python
class ManagedProcess:
    def __init__(self,
                 name: str,
                 monitoring_path: str,
                 launch_path: str,
                 id: Optional[str] = None,
                 server_reset_time_str: Optional[str] = None,
                 user_cycle_hours: Optional[int] = 24,
                 mandatory_times_str: Optional[List[str]] = None,
                 is_mandatory_time_enabled: bool = False,
                 last_played_timestamp: Optional[float] = None,
                 original_launch_path: Optional[str] = None,

                 # 🆕 MVP 연동 필드
                 game_schema_id: Optional[str] = None,  # "zenless_zone_zero" or None
                 mvp_enabled: bool = False):            # MVP 기능 활성화 여부

        # 기존 필드 초기화...

        # 🆕 새 필드 초기화
        self.game_schema_id = game_schema_id
        self.mvp_enabled = mvp_enabled
```

**필드 설명**:
- `game_schema_id`: schemas/games/{game_id}/ 디렉토리 이름
  - 예: `"zenless_zone_zero"`, `"honkai_star_rail"`, `None` (미연동)
- `mvp_enabled`: MVP 기능 사용 여부
  - `False`: 기존 Phase 0 기능만 사용 (기본값)
  - `True`: YOLO + OCR 기능 활성화 (Week 6 이후)

### 2. 하위 호환성 보장

**from_dict() 메서드 수정**:
```python
@classmethod
def from_dict(cls, data: Dict) -> 'ManagedProcess':
    """딕셔너리에서 객체를 생성 (하위 호환성 유지)"""
    # 🆕 새 필드가 없으면 기본값 설정
    if 'game_schema_id' not in data:
        data['game_schema_id'] = None
    if 'mvp_enabled' not in data:
        data['mvp_enabled'] = False

    # 기존 호환성 로직...
    if 'original_launch_path' not in data and 'launch_path' in data:
        data['original_launch_path'] = data['launch_path']

    return cls(**data)
```

---

## UI 변경사항

### 1. ProcessDialog 수정

**파일**: `src/gui/dialogs.py`

#### 추가할 UI 요소

```python
class ProcessDialog(QDialog):
    def __init__(self, parent=None, existing_process=None):
        super().__init__(parent)
        # 기존 초기화...

        # 🆕 MVP 연동 섹션
        self.mvp_group_box = QGroupBox("MVP 기능 (게임 스키마 연동)")
        mvp_layout = QVBoxLayout()

        # 게임 선택 드롭다운
        game_select_layout = QHBoxLayout()
        game_select_layout.addWidget(QLabel("게임:"))
        self.game_schema_combo = QComboBox()
        self.game_schema_combo.addItem("없음 (기본 모드)", None)
        # registry.json에서 게임 목록 로드하여 추가
        game_select_layout.addWidget(self.game_schema_combo)
        game_select_layout.addStretch()
        mvp_layout.addLayout(game_select_layout)

        # MVP 활성화 체크박스
        self.mvp_enabled_checkbox = QCheckBox("MVP 기능 활성화 (Week 6 이후)")
        self.mvp_enabled_checkbox.setEnabled(False)  # 초기에는 비활성화
        self.mvp_enabled_checkbox.setToolTip("YOLO 모델 학습 후 활성화됩니다")
        mvp_layout.addWidget(self.mvp_enabled_checkbox)

        # 스키마 편집 버튼
        self.edit_schema_button = QPushButton("📝 스키마 편집...")
        self.edit_schema_button.setEnabled(False)  # 게임 선택 시 활성화
        self.edit_schema_button.clicked.connect(self.open_schema_editor)
        mvp_layout.addWidget(self.edit_schema_button)

        self.mvp_group_box.setLayout(mvp_layout)
        self.form_layout.addRow(self.mvp_group_box)

        # 연결
        self.game_schema_combo.currentIndexChanged.connect(self.on_game_schema_changed)
```

#### UI 배치 (최종 모습)

```
┌─────────────────────────────────────────────────┐
│ 프로세스 편집                                    │
├─────────────────────────────────────────────────┤
│ [실행 중인 프로세스에서 자동 완성...]            │
│                                                 │
│ 이름:                [젠레스 존 제로          ] │
│ 모니터링 경로:       [C:\...\ZZZ.exe  ] [찾기] │
│ 실행 경로:           [C:\...\launcher.exe][찾기] │
│ 서버 초기화 시각:    [04:00                   ] │
│ 사용자 실행 주기:    [24                      ] │
│ 특정 접속 시각:      [21:00                   ] │
│ ☑ 특정 접속 시간 알림 활성화                    │
│                                                 │
│ ┌─ MVP 기능 (게임 스키마 연동) ───────────────┐ │
│ │ 게임: [젠레스 존 제로 (MVP 지원) ▼]         │ │
│ │ ☐ MVP 기능 활성화 (Week 6 이후)             │ │
│ │ [📝 스키마 편집...]                          │ │
│ └────────────────────────────────────────────┘ │
│                                                 │
│                              [확인]  [취소]    │
└─────────────────────────────────────────────────┘
```

### 2. 자동 게임 감지 로직

**프로세스 경로 입력 시 자동 매칭**:

```python
def on_monitoring_path_changed(self, path: str):
    """모니터링 경로 변경 시 자동으로 게임 감지"""
    detected_game_id = self.detect_game_from_path(path)
    if detected_game_id:
        # 콤보박스에서 해당 게임 선택
        index = self.game_schema_combo.findData(detected_game_id)
        if index >= 0:
            self.game_schema_combo.setCurrentIndex(index)

def detect_game_from_path(self, exe_path: str) -> Optional[str]:
    """프로세스 경로에서 게임 스키마 자동 감지"""
    registry = load_registry()  # schemas/registry.json

    for game in registry['games']:
        for pattern in game['process_patterns']:
            if fnmatch.fnmatch(exe_path.lower(), pattern.lower()):
                return game['game_id']  # "zenless_zone_zero"

    return None
```

### 3. 스키마 편집 버튼 상태 관리

```python
def on_game_schema_changed(self, index: int):
    """게임 선택 변경 시"""
    game_id = self.game_schema_combo.currentData()

    # 스키마 편집 버튼 활성화/비활성화
    self.edit_schema_button.setEnabled(game_id is not None)

    if game_id:
        # 스키마 파일 존재 확인
        schema_exists = self.check_schema_exists(game_id)
        if not schema_exists:
            QMessageBox.warning(
                self,
                "경고",
                f"게임 '{game_id}'의 스키마 파일을 찾을 수 없습니다."
            )

def check_schema_exists(self, game_id: str) -> bool:
    """스키마 파일 존재 확인"""
    schema_dir = Path("schemas/games") / game_id
    required_files = ["metadata.json", "resources.json", "contents.json", "ui_elements.json"]

    return all((schema_dir / f).exists() for f in required_files)
```

---

## SchemaEditorDialog 설계

### 1. 다이얼로그 구조

**파일**: `src/gui/schema_editor_dialog.py` (새 파일)

```python
class SchemaEditorDialog(QDialog):
    """게임 스키마 편집 다이얼로그"""

    def __init__(self, game_id: str, parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self.schema_data = {}
        self.modified = False

        self.setWindowTitle(f"스키마 편집 - {self.get_game_name_kr()}")
        self.setMinimumSize(900, 600)

        self.setup_ui()
        self.load_all_schemas()

    def setup_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)

        # 탭 위젯 (재화 / 콘텐츠 / UI 요소)
        self.tab_widget = QTabWidget()

        # 1. 재화 탭
        self.resources_widget = SchemaItemsWidget("resources", self)
        self.tab_widget.addTab(self.resources_widget, "💰 재화 (Resources)")

        # 2. 콘텐츠 탭
        self.contents_widget = SchemaItemsWidget("contents", self)
        self.tab_widget.addTab(self.contents_widget, "🎮 콘텐츠 (Contents)")

        # 3. UI 요소 탭
        self.ui_elements_widget = SchemaItemsWidget("ui_elements", self)
        self.tab_widget.addTab(self.ui_elements_widget, "🖼️ UI 요소 (UI Elements)")

        layout.addWidget(self.tab_widget)

        # 하단 버튼
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("💾 저장")
        save_btn.clicked.connect(self.save_all_schemas)
        button_layout.addWidget(save_btn)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)
```

### 2. SchemaItemsWidget (탭별 위젯)

```python
class SchemaItemsWidget(QWidget):
    """스키마 항목 목록 및 편집 위젯"""

    def __init__(self, schema_type: str, parent=None):
        super().__init__(parent)
        self.schema_type = schema_type  # "resources", "contents", "ui_elements"
        self.items = []

        self.setup_ui()

    def setup_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)

        # 상단 툴바
        toolbar_layout = QHBoxLayout()

        add_btn = QPushButton("➕ 항목 추가")
        add_btn.clicked.connect(self.add_item)
        toolbar_layout.addWidget(add_btn)

        toolbar_layout.addStretch()

        # 검증 통계
        self.stats_label = QLabel("총 0개 | 검증 완료: 0개")
        toolbar_layout.addWidget(self.stats_label)

        layout.addLayout(toolbar_layout)

        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "영어명", "한국어명", "검증", "메모", "편집"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

    def populate_table(self, items: List[Dict]):
        """테이블에 데이터 채우기"""
        self.items = items
        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            # ID
            id_item = QTableWidgetItem(item.get('id', ''))
            self.table.setItem(row, 0, id_item)

            # 영어명
            name_item = QTableWidgetItem(item.get('name', ''))
            self.table.setItem(row, 1, name_item)

            # 한국어명
            kr_name_item = QTableWidgetItem(item.get('name_kr', ''))
            self.table.setItem(row, 2, kr_name_item)

            # 검증 완료
            verified = item.get('name_kr_verified', False)
            verified_item = QTableWidgetItem("✅" if verified else "❌")
            self.table.setItem(row, 3, verified_item)

            # 메모
            note_item = QTableWidgetItem(item.get('verification_note', ''))
            self.table.setItem(row, 4, note_item)

            # 편집 버튼
            edit_btn = QPushButton("✏️")
            edit_btn.clicked.connect(lambda _, r=row: self.edit_item(r))
            self.table.setCellWidget(row, 5, edit_btn)

        self.update_stats()

    def edit_item(self, row: int):
        """항목 편집"""
        if row >= len(self.items):
            return

        item = self.items[row]
        dialog = SchemaItemEditDialog(item, self.schema_type, self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_item = dialog.get_updated_data()
            self.items[row] = updated_item
            self.populate_table(self.items)
            self.parent().modified = True  # 부모 다이얼로그에 수정 플래그 설정
```

### 3. SchemaItemEditDialog (개별 항목 편집)

```python
class SchemaItemEditDialog(QDialog):
    """개별 스키마 항목 편집 다이얼로그"""

    def __init__(self, item_data: dict, schema_type: str, parent=None):
        super().__init__(parent)
        self.item_data = item_data.copy()
        self.schema_type = schema_type

        self.setWindowTitle("항목 편집")
        self.setMinimumWidth(500)

        self.setup_ui()

    def setup_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # ID (읽기 전용)
        id_label = QLabel(self.item_data.get('id', ''))
        id_label.setStyleSheet("font-weight: bold;")
        form_layout.addRow("ID:", id_label)

        # 영어명 (읽기 전용)
        name_label = QLabel(self.item_data.get('name', ''))
        form_layout.addRow("영어명:", name_label)

        # 한국어명 (편집 가능)
        self.kr_name_edit = QLineEdit(self.item_data.get('name_kr', ''))
        form_layout.addRow("한국어명:", self.kr_name_edit)

        # 검증 완료 체크박스
        self.verified_checkbox = QCheckBox("검증 완료")
        self.verified_checkbox.setChecked(self.item_data.get('name_kr_verified', False))
        form_layout.addRow(self.verified_checkbox)

        # 메모
        self.note_edit = QTextEdit(self.item_data.get('verification_note', ''))
        self.note_edit.setMaximumHeight(80)
        form_layout.addRow("메모:", self.note_edit)

        layout.addLayout(form_layout)

        # 버튼
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_updated_data(self) -> dict:
        """수정된 데이터 반환"""
        self.item_data['name_kr'] = self.kr_name_edit.text().strip()
        self.item_data['name_kr_verified'] = self.verified_checkbox.isChecked()
        self.item_data['verification_note'] = self.note_edit.toPlainText().strip()
        return self.item_data
```

---

## 데이터 플로우

### 1. 프로세스 추가/수정 시

```
사용자 입력
   ↓
모니터링 경로 입력 → [자동 게임 감지]
   ↓
게임 스키마 콤보박스 자동 선택
   ↓
사용자 확인 또는 수동 변경
   ↓
[스키마 편집...] 버튼 클릭 (선택)
   ↓
SchemaEditorDialog 팝업
   ↓
재화/콘텐츠/UI 요소 편집
   ↓
저장 → JSON 파일 업데이트
   ↓
ProcessDialog 확인 클릭
   ↓
ManagedProcess 객체 생성 (game_schema_id 포함)
   ↓
API 서버에 저장 (POST /processes 또는 PUT /processes/{id})
```

### 2. 스키마 로딩

```python
def load_registry() -> dict:
    """schemas/registry.json 로드"""
    with open("schemas/registry.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_game_schema(game_id: str, schema_type: str) -> dict:
    """
    게임별 스키마 파일 로드

    Args:
        game_id: "zenless_zone_zero"
        schema_type: "resources", "contents", "ui_elements"
    """
    schema_file = Path(f"schemas/games/{game_id}/{schema_type}.json")
    with open(schema_file, "r", encoding="utf-8") as f:
        return json.load(f)
```

### 3. 스키마 저장

```python
def save_game_schema(game_id: str, schema_type: str, data: dict):
    """게임별 스키마 파일 저장"""
    schema_file = Path(f"schemas/games/{game_id}/{schema_type}.json")

    # 백업 (선택)
    if schema_file.exists():
        backup_file = schema_file.with_suffix(".json.bak")
        shutil.copy2(schema_file, backup_file)

    # 저장
    with open(schema_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

---

## 구현 우선순위

### Phase 1: 기본 연동 (즉시 구현 가능)
- [x] ManagedProcess에 game_schema_id, mvp_enabled 필드 추가
- [ ] ProcessDialog에 MVP 섹션 추가
  - [ ] 게임 스키마 드롭다운
  - [ ] 자동 게임 감지 로직
  - [ ] [스키마 편집] 버튼
- [ ] registry.json 로딩 유틸리티
- [ ] 데이터베이스 마이그레이션 (기존 프로세스 호환)

### Phase 2: 스키마 편집기 (Week 6 이전)
- [ ] SchemaEditorDialog 개발
  - [ ] 탭 위젯 (재화/콘텐츠/UI)
  - [ ] SchemaItemsWidget 개발
  - [ ] SchemaItemEditDialog 개발
- [ ] 스키마 로드/저장 로직
- [ ] 한국어 명칭 검증 기능

### Phase 3: MVP 활성화 (Week 6 이후)
- [ ] YOLO 모델 존재 확인
- [ ] mvp_enabled 체크박스 활성화
- [ ] YOLO + OCR 파이프라인 연동
- [ ] 실시간 UI 탐지 및 데이터 추출

---

## 추가 고려사항

### 1. 사용자 정의 게임 추가
향후 사용자가 임의 게임을 추가할 수 있도록:
- SchemaEditorDialog에 "새 게임 추가" 기능
- registry.json에 게임 등록
- 게임별 디렉토리 및 스키마 파일 자동 생성

### 2. 스키마 버전 관리
- metadata.json의 schema_version 추적
- 스키마 업데이트 시 마이그레이션 지원

### 3. 클라우드 동기화 (향후)
- 여러 PC 간 스키마 동기화
- GitHub/Google Drive 연동

---

**작성자**: HomeworkHelper Dev Team
**관련 문서**:
- [schemas/registry.json](../schemas/registry.json)
- [MVP 로드맵](../docs/mvp-roadmap.md)
- [아키텍처 가이드](../docs/architecture.md)
