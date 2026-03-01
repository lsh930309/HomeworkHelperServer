"""게임별 볼륨 조절 팝오버 패널"""
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QPixmap

from src.data.data_models import ManagedProcess
from src.utils import audio_control

logger = logging.getLogger(__name__)


class VolumePopoverPanel(QWidget):
    """실행 중인 게임의 볼륨을 조절하는 팝오버 패널."""

    def __init__(self, data_manager, parent=None):
        """팝오버 패널을 초기화합니다."""
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._data_manager = data_manager
        self._volume_save_timers: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        """기본 UI 레이아웃을 구성합니다."""
        self.setMinimumWidth(300)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        header = QLabel("🔊 볼륨 조절")
        header.setStyleSheet("font-weight: bold;")
        outer.addWidget(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(line)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(6)
        outer.addLayout(self._list_layout)

        self._empty_label = QLabel("실행 중인 게임이 없습니다.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: gray; padding: 8px;")
        self._list_layout.addWidget(self._empty_label)

    def refresh(self, running_entries: list):
        """실행 중인 (process, pid) 쌍 목록으로 패널을 갱신합니다."""
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not running_entries:
            empty = QLabel("실행 중인 게임이 없습니다.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: gray; padding: 8px;")
            self._list_layout.addWidget(empty)
        else:
            for process, pid in running_entries:
                self._list_layout.addWidget(self._make_row(process, pid))

        self.adjustSize()

    def _make_row(self, process: ManagedProcess, pid: int) -> QWidget:
        """프로세스 한 행(아이콘 / 음소거 버튼 / 슬라이더)을 생성합니다."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 게임 아이콘
        from src.utils.process import get_qicon_for_file
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        qi = get_qicon_for_file(process.monitoring_path)
        if qi and not qi.isNull():
            icon_label.setPixmap(qi.pixmap(20, 20))
        layout.addWidget(icon_label)

        # 게임 이름
        name_label = QLabel(process.name)
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_label)

        # 음소거 버튼
        mute_btn = QPushButton("🔊")
        mute_btn.setFixedSize(28, 28)
        mute_btn.setCheckable(True)

        # 볼륨 슬라이더
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setFixedWidth(110)

        # 초기 볼륨: 실제 시스템 볼륨 → 저장값 → 100 순으로 fallback
        initial_volume = getattr(process, 'default_volume', None)
        if initial_volume is None:
            initial_volume = 100
        actual = audio_control.get_app_volume(pid)
        if actual is not None:
            initial_volume = int(actual * 100)
        if audio_control.is_muted(pid):
            mute_btn.setChecked(True)
            mute_btn.setText("🔇")
        slider.setValue(initial_volume)

        def on_mute_toggled(checked, pid_ref=pid, btn=mute_btn):
            """음소거 버튼 토글 시 시스템 음소거 상태를 변경합니다."""
            btn.setText("🔇" if checked else "🔊")
            if pid_ref:
                audio_control.set_mute(pid_ref, checked)

        mute_btn.toggled.connect(on_mute_toggled)
        slider.valueChanged.connect(
            lambda v, p=process, pid_ref=pid: self._on_volume_changed(v, p, pid_ref)
        )

        layout.addWidget(mute_btn)
        layout.addWidget(slider)
        return row

    def _on_volume_changed(self, value: int, process: ManagedProcess, pid: Optional[int]):
        """슬라이더 값 변경 시 실시간 볼륨 적용 및 DB 저장 예약."""
        if pid:
            audio_control.set_app_volume(pid, value / 100.0)
        process.default_volume = value
        self._schedule_volume_save(process)

    def _schedule_volume_save(self, process: ManagedProcess):
        """볼륨 변경 후 500ms 디바운스로 DB 저장 예약."""
        existing = self._volume_save_timers.get(process.id)
        if existing is not None:
            existing.stop()
            existing.start(500)
        else:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=process: self._save_volume_to_db(p))
            timer.start(500)
            self._volume_save_timers[process.id] = timer

    def _save_volume_to_db(self, process: ManagedProcess):
        """프로세스의 볼륨 설정을 DB에 저장."""
        try:
            self._data_manager.update_process(process)
            logger.debug("볼륨 저장: %s = %s", process.name, process.default_volume)
        except Exception as e:  # noqa: BLE001
            logger.exception("볼륨 저장 실패: %s", e)

    def show_below(self, anchor: QWidget):
        """anchor 위젯의 바로 아래 오른쪽 정렬로 팝오버를 표시합니다."""
        global_pos = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height()))
        self.adjustSize()
        x = global_pos.x() - self.width()
        y = global_pos.y()
        screen = anchor.screen()
        if screen:
            geo = screen.availableGeometry()
            if x < geo.left():
                x = geo.left()
            if y + self.height() > geo.bottom():
                y = global_pos.y() - anchor.height() - self.height()
        self.move(x, y)
        self.show()
