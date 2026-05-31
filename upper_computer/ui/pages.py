"""EchoGuard 上位机页面集合。

中文注释：每个页面都是一个完整的 body 区域（中间内容 + 可选右栏 + 可选底栏），
由 MainWindow 放进 QStackedWidget 切换。页面统一暴露 ``update_snapshot`` 接收
DataManager 快照刷新自身，不可见时会自动跳过重活，降低 CPU 占用。

页面清单：
* DashboardPage   —— 设计稿图 2：CSI 振幅趋势 + 生命体征指标 + 环境/无线 + 事件流 + 拓扑。
* SensorMatrixPage—— 设计稿图 1：活动节点矩阵表 + 右侧系统核心配置 + 底部系统警告条。
* AnalysisPage    —— 数据分析：聚合统计 + 呼吸/运动趋势曲线。
* DiagnosticsPage —— 技术诊断：链路质量表 + 系统信息。
* HistoryPage     —— 历史记录：可滚动样本表 + CSV 导出。
"""

from __future__ import annotations

import time
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from ..config import (
        CONTROL_ID,
        DEFAULT_AFH_ENABLED,
        DEFAULT_MESH_ENABLED,
        GAS_THRESHOLD_PPM,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        NODE_IDS,
        NODE_LABELS,
        PRESENCE_THRESHOLD,
        THEME,
    )
    from .components import (
        BatteryBar,
        CardFrame,
        CsiTrendPlot,
        EventLogPanel,
        HealthBadge,
        MetricCard,
        ModeTag,
        SettingRow,
        SystemWarningBar,
        ThresholdSlider,
        TopologyWidget,
    )
except ImportError:
    from config import (
        CONTROL_ID,
        DEFAULT_AFH_ENABLED,
        DEFAULT_MESH_ENABLED,
        GAS_THRESHOLD_PPM,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        NODE_IDS,
        NODE_LABELS,
        PRESENCE_THRESHOLD,
        THEME,
    )
    from ui.components import (
        BatteryBar,
        CardFrame,
        CsiTrendPlot,
        EventLogPanel,
        HealthBadge,
        MetricCard,
        ModeTag,
        SettingRow,
        SystemWarningBar,
        ThresholdSlider,
        TopologyWidget,
    )


# 矩阵表列宽（首列拉伸，其余固定，保证表头与每行对齐）
_MATRIX_COLUMNS = (
    ("节点 ID", 0),       # 0 = 拉伸
    ("运行模式", 150),
    ("LORA RSSI", 110),
    ("电池电量", 185),
    ("运行健康度", 130),
    ("操作", 56),
)


# ===========================================================================
# 仪表盘页（图 2）
# ===========================================================================
class DashboardPage(QWidget):
    """实时生命体征仪表盘。"""

    export_csv_requested = pyqtSignal()
    screenshot_requested = pyqtSignal(object)
    csi_shot_requested = pyqtSignal(object)
    active_node_changed = pyqtSignal(int)
    pause_toggled = pyqtSignal(bool)
    clear_events_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.metric_cards: dict[str, MetricCard] = {}
        self.group_values: dict[str, QLabel] = {}
        self._last_event_count = -1
        self._paused = False

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_center(), 1)
        body.addWidget(self._build_right_rail())

    # ----- 中间区 -----
    def _build_center(self) -> QWidget:
        center = QWidget()
        center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(center)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.node_combo = QComboBox()
        self.node_combo.setFixedWidth(140)
        for node_id in NODE_IDS:
            self.node_combo.addItem(NODE_LABELS[node_id], node_id)
        self.node_combo.currentIndexChanged.connect(
            lambda: self.active_node_changed.emit(int(self.node_combo.currentData() or NODE_IDS[0]))
        )
        self.pause_btn = QPushButton("暂停刷新")
        self.pause_btn.setObjectName("GhostButton")
        self.pause_btn.clicked.connect(self._toggle_pause)
        detail_btn = QPushButton("节点详情")
        detail_btn.setObjectName("GhostButton")
        detail_btn.clicked.connect(self._show_active_node_detail)
        controls.addWidget(QLabel("关注节点"))
        controls.addWidget(self.node_combo)
        controls.addWidget(self.pause_btn)
        controls.addWidget(detail_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.csi_plot = CsiTrendPlot()
        layout.addWidget(self.csi_plot, 5)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(16)
        metrics.setVerticalSpacing(16)
        self.metric_cards["motion"] = MetricCard("运动分值\n(MOTION SCORE)", "0.00", "等待数据")
        self.metric_cards["presence"] = MetricCard("存在感应\n(PRESENCE)", "CLEAR", "未检测")
        self.metric_cards["breath"] = MetricCard("呼吸频率\n(BREATH BPM)", "-- 次/分", "锁定中")
        self.metric_cards["confidence"] = MetricCard("置信度\n(CONFIDENCE)", "-- %", "模型输出")
        for index, card in enumerate(self.metric_cards.values()):
            metrics.addWidget(card, 0, index)
        layout.addLayout(metrics)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)
        bottom_row.addWidget(
            self._build_value_group(
                "环境状态 (ENVIRONMENT)",
                (
                    ("temp", "温度 TEMP", "-- °C"),
                    ("hum", "湿度 HUM", "-- %"),
                    ("gas", "甲醛 GAS", "-- ppm"),
                ),
            ),
            1,
        )
        bottom_row.addWidget(
            self._build_value_group(
                "无线链路 (WIRELESS)",
                (
                    ("rssi", "LoRa RSSI", "-- dBm"),
                    ("snr", "SNR", "-- dB"),
                    ("loss", "数据包丢弃", "-- %"),
                ),
            ),
            1,
        )
        layout.addLayout(bottom_row)

        export_row = QHBoxLayout()
        export_row.setSpacing(10)
        self.export_message = QLabel("")
        self.export_message.setObjectName("SubtleText")
        export_row.addWidget(self.export_message, 1)

        csv_btn = QPushButton("CSV 导出")
        csv_btn.setObjectName("PrimaryButton")
        csv_btn.clicked.connect(self.export_csv_requested.emit)
        csi_btn = QPushButton("CSI 曲线截图")
        csi_btn.setObjectName("GhostButton")
        csi_btn.clicked.connect(lambda: self.csi_shot_requested.emit(self.csi_plot))
        shot_btn = QPushButton("整窗截图")
        shot_btn.setObjectName("GhostButton")
        shot_btn.clicked.connect(lambda: self.screenshot_requested.emit(self.window()))
        export_row.addWidget(csv_btn)
        export_row.addWidget(csi_btn)
        export_row.addWidget(shot_btn)
        layout.addLayout(export_row)

        return center

    # ----- 右栏 -----
    def _build_right_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("RightRail")
        rail.setFixedWidth(360)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(20, 22, 20, 20)
        layout.setSpacing(16)

        self.event_panel = EventLogPanel()
        layout.addWidget(self.event_panel, 2)

        event_tools = QHBoxLayout()
        event_tools.setSpacing(8)
        self.event_filter = QComboBox()
        self.event_filter.addItems(("全部事件", "ALARM", "WARN", "OK", "INFO"))
        self.event_filter.currentIndexChanged.connect(lambda: setattr(self, "_last_event_count", -1))
        clear_btn = QPushButton("清空事件")
        clear_btn.setObjectName("GhostButton")
        clear_btn.clicked.connect(self.clear_events_requested.emit)
        event_tools.addWidget(self.event_filter, 1)
        event_tools.addWidget(clear_btn)
        layout.addLayout(event_tools)

        topology_card = CardFrame()
        topology_layout = QVBoxLayout(topology_card)
        topology_layout.setContentsMargins(18, 16, 18, 18)
        topology_layout.setSpacing(12)
        title = QLabel("系统拓扑 (TOPOLOGY)")
        title.setObjectName("SectionTitle")
        topology_layout.addWidget(title)
        self.topology_widget = TopologyWidget()
        topology_layout.addWidget(self.topology_widget, 1)
        layout.addWidget(topology_card, 1)

        return rail

    def _build_value_group(self, title: str, items: tuple[tuple[str, str, str], ...]) -> QWidget:
        card = CardFrame()
        card.setMinimumHeight(118)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        row = QHBoxLayout()
        row.setSpacing(12)
        for key, label, value in items:
            box = QVBoxLayout()
            box.setSpacing(6)
            caption = QLabel(label)
            caption.setObjectName("SubtleText")
            value_label = QLabel(value)
            value_label.setObjectName("MetricValue")
            value_label.setStyleSheet("font-size: 19px;")
            self.group_values[key] = value_label
            box.addWidget(caption)
            box.addWidget(value_label)
            row.addLayout(box, 1)
        layout.addLayout(row)
        return card

    # ----- 数据刷新 -----
    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        nodes: dict[int, dict[str, Any]] = snapshot.get("nodes", {})
        history: list[dict[str, Any]] = snapshot.get("history", [])
        events: list[dict[str, Any]] = snapshot.get("events", [])
        active_node = int(snapshot.get("active_node") or NODE_IDS[0])
        active_state = nodes.get(active_node) or nodes.get(NODE_IDS[0], {})
        self._latest_nodes = nodes
        self._latest_active_node = active_node

        self.node_combo.blockSignals(True)
        for index in range(self.node_combo.count()):
            if int(self.node_combo.itemData(index) or 0) == active_node:
                self.node_combo.setCurrentIndex(index)
                break
        self.node_combo.blockSignals(False)
        self._paused = bool(snapshot.get("paused"))
        self.pause_btn.setText("恢复刷新" if self._paused else "暂停刷新")

        # 中文注释：不可见时跳过曲线与拓扑重绘，降低后台 CPU 占用。
        if not self.isVisible():
            return

        self.csi_plot.set_history(history, active_node, active_state)
        self._update_metric_cards(active_state)
        self._update_group_cards(active_state)

        filtered_events = self._filter_events(events)
        event_key = (len(events), self.event_filter.currentText())
        if event_key != self._last_event_count:
            self._last_event_count = event_key
            self.event_panel.set_events(filtered_events)

        self.topology_widget.set_nodes(nodes)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_toggled.emit(self._paused)

    def _filter_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        level = self.event_filter.currentText()
        if level == "全部事件":
            return events
        return [event for event in events if str(event.get("level", "")).upper() == level]

    def _show_active_node_detail(self) -> None:
        nodes = getattr(self, "_latest_nodes", {})
        node_id = int(getattr(self, "_latest_active_node", NODE_IDS[0]))
        state = nodes.get(node_id, {})
        _show_detail_dialog(
            self,
            f"{NODE_LABELS.get(node_id, f'SENS_{node_id:02d}')} 节点详情",
            (
                ("在线状态", "在线" if state.get("online") else "离线"),
                ("Presence", f"{_score(state.get('presence_score')):.2f}"),
                ("Motion", f"{_score(state.get('motion_score')):.2f}"),
                ("Breath BPM", f"{_float(state.get('breath_bpm')):.0f}"),
                ("Confidence", f"{_score(state.get('confidence')) * 100:.0f}%"),
                ("Gas", f"{_float(state.get('gas')):.0f} ppm"),
                ("RSSI", f"{_float(state.get('rssi')):.0f} dBm"),
            ),
        )

    def set_export_message(self, text: str, ok: bool = True) -> None:
        self.export_message.setText(text)
        self.export_message.setStyleSheet(
            f"color: {THEME['blue_soft'] if ok else THEME['red']};"
        )

    def _update_metric_cards(self, state: dict[str, Any]) -> None:
        motion = _score(state.get("motion_score"))
        presence = _score(state.get("presence_score"))
        confidence = _score(state.get("confidence"))
        breath = _float(state.get("breath_bpm"))

        motion_hint = "活跃" if motion >= 0.52 else "平稳"
        presence_text = "DETECT" if presence >= 0.5 else "CLEAR"
        presence_hint = f"{presence * 100:.0f}% 阈值响应"
        breath_hint = "BREATH LOCKED" if breath >= 8 and confidence >= 0.68 else "ACQUIRING"
        conf_hint = "可信" if confidence >= 0.75 else "观测中"

        self.metric_cards["motion"].set_value(
            f"{motion:.2f}", motion_hint, THEME["green"] if motion >= 0.52 else None
        )
        self.metric_cards["presence"].set_value(
            presence_text,
            presence_hint,
            THEME["green"] if presence_text == "DETECT" else THEME["blue_soft"],
        )
        self.metric_cards["breath"].set_value(f"{breath:.0f} 次/分", breath_hint, THEME["text"])
        self.metric_cards["confidence"].set_value(
            f"{confidence * 100:.0f} %", conf_hint, THEME["blue_soft"]
        )

    def _update_group_cards(self, state: dict[str, Any]) -> None:
        temp = _float(state.get("temperature"))
        hum = _float(state.get("humidity"))
        gas = _float(state.get("gas"))
        rssi = _float(state.get("rssi"))
        snr = _float(state.get("snr"))
        loss = _float(state.get("packet_loss"))

        self.group_values["temp"].setText(f"{temp:.1f}°C")
        self.group_values["hum"].setText(f"{hum:.0f}%")
        self.group_values["gas"].setText(f"{gas:.0f} ppm")
        self.group_values["gas"].setStyleSheet(
            f"font-size: 19px; color: {THEME['red'] if gas >= 550 else THEME['text']};"
        )

        self.group_values["rssi"].setText(f"{rssi:.0f} dBm")
        self.group_values["rssi"].setStyleSheet(f"font-size: 19px; color: {THEME['blue_soft']};")
        self.group_values["snr"].setText(f"{snr:.1f} dB")
        self.group_values["loss"].setText(f"{loss:.2f}%")
        self.group_values["loss"].setStyleSheet(
            f"font-size: 19px; color: {THEME['red'] if loss >= 8 else THEME['orange'] if loss >= 2 else THEME['text']};"
        )


# ===========================================================================
# 传感器页 / 活动节点矩阵（图 1）
# ===========================================================================
class _MatrixRow(QFrame):
    """节点矩阵单行，支持原地更新。"""

    menu_requested = pyqtSignal(int)

    def __init__(self, code: str) -> None:
        super().__init__()
        self.matrix_id = 0
        self._state: dict[str, Any] = {}
        self.setObjectName("MatrixRow")
        self.setFixedHeight(78)
        self.setStyleSheet(
            "QFrame#MatrixRow { background: transparent; border: 0;"
            f" border-bottom: 1px solid {THEME['border_soft']}; }}"
            "QFrame#MatrixRow:hover { background: #1A1C22; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 16, 8)
        layout.setSpacing(0)

        # 节点 ID（拉伸列）
        self.code_label = QLabel(code)
        self.code_label.setObjectName("NodeCode")
        self.code_label.setWordWrap(True)
        self.code_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.code_label, 1)

        # 运行模式
        self.mode_tag = ModeTag()
        layout.addWidget(self._fixed(self.mode_tag, _MATRIX_COLUMNS[1][1], align_left=True))

        # RSSI
        self.rssi_label = QLabel("-- dBm")
        self.rssi_label.setStyleSheet(f"color: {THEME['text_soft']}; font-size: 14px;")
        layout.addWidget(self._fixed(self.rssi_label, _MATRIX_COLUMNS[2][1], align_left=True))

        # 电池
        self.battery = BatteryBar()
        layout.addWidget(self._fixed(self.battery, _MATRIX_COLUMNS[3][1], align_left=True))

        # 健康度
        self.health = HealthBadge()
        layout.addWidget(self._fixed(self.health, _MATRIX_COLUMNS[4][1], align_left=True))

        # 操作
        self.menu_btn = QPushButton("⋯")
        self.menu_btn.setObjectName("RowMenu")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.clicked.connect(lambda: self.menu_requested.emit(self.matrix_id))
        layout.addWidget(self._fixed(self.menu_btn, _MATRIX_COLUMNS[5][1], align_left=False))

    @staticmethod
    def _fixed(widget: QWidget, width: int, align_left: bool) -> QWidget:
        holder = QWidget()
        holder.setFixedWidth(width)
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(widget)
        if not align_left:
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            box.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return holder

    def update_state(self, state: dict[str, Any]) -> None:
        self._state = state
        self.matrix_id = int(state.get("matrix_id") or 0)
        self.code_label.setText(str(state.get("code", "")))
        self.mode_tag.set_mode(str(state.get("mode", "NORMAL")))
        rssi = _float(state.get("rssi"))
        online = bool(state.get("online"))
        self.rssi_label.setText(f"{rssi:.0f} dBm")
        self.rssi_label.setStyleSheet(
            f"color: {THEME['text_soft'] if online else THEME['muted_2']}; font-size: 14px;"
        )
        self.battery.set_value(_float(state.get("battery")))
        self.health.set_health(str(state.get("health", "")))


class SensorMatrixPage(QWidget):
    """活动节点矩阵 + 系统核心配置（图 1）。"""

    presence_threshold_changed = pyqtSignal(float)
    gas_threshold_changed = pyqtSignal(float)
    afh_toggled = pyqtSignal(bool)
    mesh_toggled = pyqtSignal(bool)
    sync_requested = pyqtSignal()
    add_node_requested = pyqtSignal()
    matrix_filter_changed = pyqtSignal(str)
    matrix_remove_requested = pyqtSignal(int)
    matrix_maintenance_requested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._rows: dict[int, _MatrixRow] = {}
        self._matrix_filter = "ALL"
        self._latest_matrix: dict[int, dict[str, Any]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_center(), 1)
        body.addWidget(self._build_right_rail())
        outer.addLayout(body, 1)

        self.warning_bar = SystemWarningBar()
        self.warning_bar.hide()
        outer.addWidget(self.warning_bar)

    # ----- 中间区 -----
    def _build_center(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("活动节点矩阵")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        self.subtitle = QLabel("实时监控 0 个连接的 LoRa 节点状态")
        self.subtitle.setObjectName("SectionSub")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self.filter_btn = QPushButton("≡  筛选：全部")
        self.filter_btn.setObjectName("GhostButton")
        self.filter_btn.clicked.connect(self._open_filter_menu)
        add_btn = QPushButton("+  新增节点")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_node_requested.emit)
        header.addWidget(self.filter_btn)
        header.addWidget(add_btn)
        layout.addLayout(header)

        # 表格卡片
        table_card = CardFrame()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        table_layout.addWidget(self._build_table_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows_host)
        table_layout.addWidget(self.scroll, 1)

        layout.addWidget(table_card, 1)
        return center

    def _build_table_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("MatrixHeader")
        header.setFixedHeight(50)
        header.setStyleSheet(
            "QFrame#MatrixHeader { background: #16171C; border: 0;"
            f" border-bottom: 1px solid {THEME['border']};"
            " border-top-left-radius: 12px; border-top-right-radius: 12px; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(0)

        for index, (name, width) in enumerate(_MATRIX_COLUMNS):
            label = QLabel(name)
            label.setObjectName("ColHeader")
            if width == 0:
                label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                layout.addWidget(label, 1)
            else:
                holder = QWidget()
                holder.setFixedWidth(width)
                box = QHBoxLayout(holder)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(label)
                if index == len(_MATRIX_COLUMNS) - 1:
                    box.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    box.setAlignment(Qt.AlignmentFlag.AlignLeft)
                layout.addWidget(holder)
        return header

    # ----- 右栏：系统核心配置 -----
    def _build_right_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("RightRail")
        rail.setFixedWidth(380)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(24, 24, 24, 22)
        layout.setSpacing(22)

        title = QLabel("系统核心")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.presence_slider = ThresholdSlider(
            "存在感应阈值 (Presence)",
            minimum=0.0,
            maximum=1.0,
            value=PRESENCE_THRESHOLD,
            value_fmt=lambda v: f"{v * 100:.0f}%",
            min_label="MIN (0.1s)",
            max_label="MAX (5.0s)",
        )
        self.presence_slider.valueChanged.connect(self.presence_threshold_changed.emit)
        layout.addWidget(self.presence_slider)

        self.gas_slider = ThresholdSlider(
            "气体检测阈值 (Gas)",
            minimum=0.0,
            maximum=1000.0,
            value=GAS_THRESHOLD_PPM,
            value_fmt=lambda v: f"{v:.0f} ppm",
            min_label="0 ppm",
            max_label="1000 ppm",
        )
        self.gas_slider.valueChanged.connect(self.gas_threshold_changed.emit)
        layout.addWidget(self.gas_slider)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {THEME['divider']};")
        layout.addWidget(divider)

        afh_row = SettingRow("自动频率跳变 (AFH)", checked=DEFAULT_AFH_ENABLED)
        afh_row.toggled.connect(self.afh_toggled.emit)
        layout.addWidget(afh_row)

        mesh_row = SettingRow("多级网格中继", checked=DEFAULT_MESH_ENABLED)
        mesh_row.toggled.connect(self.mesh_toggled.emit)
        layout.addWidget(mesh_row)

        layout.addStretch(1)

        sync_btn = QPushButton("↻  同步全局配置")
        sync_btn.setObjectName("SyncButton")
        sync_btn.clicked.connect(self.sync_requested.emit)
        layout.addWidget(sync_btn)

        self.sync_time_label = QLabel("最后同步时间：尚未同步")
        self.sync_time_label.setObjectName("SubtleText")
        self.sync_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.control_id_label = QLabel(f"控制台 ID: {CONTROL_ID}")
        self.control_id_label.setObjectName("SubtleText")
        self.control_id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sync_time_label)
        layout.addWidget(self.control_id_label)

        return rail

    # ----- 数据刷新 -----
    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        matrix: list[dict[str, Any]] = snapshot.get("matrix", [])
        config: dict[str, Any] = snapshot.get("config", {})
        self._latest_matrix = {int(entry.get("matrix_id") or 0): entry for entry in matrix}

        online = config.get("online_matrix", sum(1 for m in matrix if m.get("online")))
        total = config.get("total_matrix", len(matrix))
        self.subtitle.setText(f"实时监控 {total} 个连接的 LoRa 节点状态（在线 {online}）")

        # 原地构建/更新行
        visible_ids: set[int] = set()
        for entry in self._visible_matrix(matrix):
            matrix_id = int(entry.get("matrix_id"))
            visible_ids.add(matrix_id)
            row = self._rows.get(matrix_id)
            if row is None:
                row = _MatrixRow(str(entry.get("code", "")))
                row.menu_requested.connect(self._open_row_menu)
                self._rows[matrix_id] = row
                self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            row.update_state(entry)
            row.show()

        for matrix_id, row in self._rows.items():
            if matrix_id not in visible_ids:
                row.hide()

        last_sync = config.get("last_sync_at")
        if last_sync:
            self.sync_time_label.setText(
                "最后同步时间: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(last_sync)))
            )

        # 严重错误节点 → 底部系统警告条
        critical = next((m for m in matrix if m.get("health") == HEALTH_CRITICAL), None)
        if critical is not None:
            self.warning_bar.show_warning(
                f"节点 {critical.get('code')} 报告严重故障。运行模式 {critical.get('mode')}，"
                f"RSSI {_float(critical.get('rssi')):.0f} dBm，建议进行现场物理检查。"
            )
        else:
            self.warning_bar.hide()

    def _open_filter_menu(self) -> None:
        menu = QMenu(self)
        filters = (
            ("ALL", "全部"),
            ("ONLINE", "在线"),
            ("OFFLINE", "离线"),
            ("CRITICAL", "严重错误"),
            ("MAINTENANCE", "维护标记"),
        )
        for key, label in filters:
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, k=key, text=label: self._set_filter(k, text))
            menu.addAction(action)
        menu.exec(self.filter_btn.mapToGlobal(self.filter_btn.rect().bottomLeft()))

    def _set_filter(self, key: str, label: str) -> None:
        self._matrix_filter = key
        self.filter_btn.setText(f"≡  筛选：{label}")
        self.matrix_filter_changed.emit(key)
        for matrix_id, row in self._rows.items():
            state = self._latest_matrix.get(matrix_id, {})
            row.setVisible(self._matrix_matches(state))

    def _visible_matrix(self, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [entry for entry in matrix if self._matrix_matches(entry)]

    def _matrix_matches(self, entry: dict[str, Any]) -> bool:
        if self._matrix_filter == "ONLINE":
            return bool(entry.get("online"))
        if self._matrix_filter == "OFFLINE":
            return not bool(entry.get("online"))
        if self._matrix_filter == "CRITICAL":
            return entry.get("health") == HEALTH_CRITICAL
        if self._matrix_filter == "MAINTENANCE":
            return bool(entry.get("maintenance"))
        return True

    def _open_row_menu(self, matrix_id: int) -> None:
        state = self._latest_matrix.get(int(matrix_id), {})
        menu = QMenu(self)
        detail_action = QAction("查看详情", self)
        detail_action.triggered.connect(lambda: self._show_matrix_detail(state))
        maintenance_action = QAction("取消维护标记" if state.get("maintenance") else "标记维护", self)
        maintenance_action.triggered.connect(lambda: self.matrix_maintenance_requested.emit(int(matrix_id)))
        remove_action = QAction("移除本地节点", self)
        remove_action.setEnabled(bool(state.get("local")))
        remove_action.triggered.connect(lambda: self.matrix_remove_requested.emit(int(matrix_id)))
        menu.addAction(detail_action)
        menu.addAction(maintenance_action)
        menu.addAction(remove_action)
        row = self._rows.get(int(matrix_id))
        anchor = row.menu_btn if row else self
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _show_matrix_detail(self, state: dict[str, Any]) -> None:
        _show_detail_dialog(
            self,
            f"{state.get('code', 'NODE')} 详情",
            (
                ("节点 ID", state.get("matrix_id", "-")),
                ("运行模式", state.get("mode", "-")),
                ("在线状态", "在线" if state.get("online") else "离线"),
                ("RSSI", f"{_float(state.get('rssi')):.0f} dBm"),
                ("电池", f"{_float(state.get('battery')):.0f}%"),
                ("健康度", state.get("health", "-")),
                ("维护标记", "是" if state.get("maintenance") else "否"),
                ("本地节点", "是" if state.get("local") else "否"),
            ),
        )


# ===========================================================================
# 数据分析页
# ===========================================================================
class AnalysisPage(QWidget):
    """聚合统计 + 呼吸/运动趋势曲线。"""

    active_node_changed = pyqtSignal(int)
    analysis_shot_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._last_plot_at = 0.0
        self._metric_key = "breath_bpm"
        self._window_seconds = 60
        self._selected_node = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("数据分析")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        subtitle = QLabel("基于实时历史样本的聚合统计与趋势")
        subtitle.setObjectName("SectionSub")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.analysis_node_combo = QComboBox()
        self.analysis_node_combo.addItem("全部节点", 0)
        for node_id in NODE_IDS:
            self.analysis_node_combo.addItem(NODE_LABELS[node_id], node_id)
        self.analysis_node_combo.currentIndexChanged.connect(self._on_analysis_control_changed)
        self.metric_combo = QComboBox()
        for label, key in (
            ("呼吸 BPM", "breath_bpm"),
            ("运动分值", "motion_score"),
            ("存在感应", "presence_score"),
            ("气体浓度", "gas"),
            ("LoRa RSSI", "rssi"),
        ):
            self.metric_combo.addItem(label, key)
        self.metric_combo.currentIndexChanged.connect(self._on_analysis_control_changed)
        self.window_combo = QComboBox()
        for label, seconds in (("最近 60 秒", 60), ("最近 5 分钟", 300), ("全部历史", 0)):
            self.window_combo.addItem(label, seconds)
        self.window_combo.currentIndexChanged.connect(self._on_analysis_control_changed)
        shot_btn = QPushButton("图表截图")
        shot_btn.setObjectName("GhostButton")
        shot_btn.clicked.connect(lambda: self.analysis_shot_requested.emit(self.plot))
        controls.addWidget(QLabel("节点"))
        controls.addWidget(self.analysis_node_combo)
        controls.addWidget(QLabel("指标"))
        controls.addWidget(self.metric_combo)
        controls.addWidget(QLabel("窗口"))
        controls.addWidget(self.window_combo)
        controls.addStretch(1)
        controls.addWidget(shot_btn)
        layout.addLayout(controls)

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        stats.setVerticalSpacing(16)
        self.stat_cards: dict[str, MetricCard] = {
            "samples": MetricCard("累计样本\n(SAMPLES)", "0", "历史缓存"),
            "avg_breath": MetricCard("平均呼吸\n(AVG BPM)", "-- 次/分", "全部节点"),
            "max_gas": MetricCard("峰值气体\n(MAX GAS)", "-- ppm", "全部节点"),
            "online": MetricCard("在线节点\n(ONLINE)", "0 / 4", "生命体征节点"),
        }
        for index, card in enumerate(self.stat_cards.values()):
            stats.addWidget(card, 0, index)
        layout.addLayout(stats)

        plot_card = CardFrame()
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(20, 18, 20, 18)
        plot_layout.setSpacing(12)
        self.plot_title = QLabel("呼吸频率趋势 (BREATH BPM Trend)")
        self.plot_title.setObjectName("SectionTitle")
        plot_layout.addWidget(self.plot_title)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(THEME["card"])
        self.plot.showGrid(x=True, y=True, alpha=0.16)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.addLegend(offset=(10, 10))
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#3A3D45"))
            axis.setTextPen(pg.mkPen("#6C7280"))
        self.plot.setLabel("left", "BPM")
        self.plot.setLabel("bottom", "Last 60s")
        self._curves = {}
        palette = [THEME["blue_bright"], THEME["green"], THEME["orange"], THEME["cyan"]]
        for index, node_id in enumerate(NODE_IDS):
            self._curves[node_id] = self.plot.plot(
                [], [], pen=pg.mkPen(palette[index % len(palette)], width=2.0),
                name=NODE_LABELS[node_id],
            )
        plot_layout.addWidget(self.plot)
        layout.addWidget(plot_card, 1)

    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        nodes: dict[int, dict[str, Any]] = snapshot.get("nodes", {})
        history: list[dict[str, Any]] = snapshot.get("history", [])
        self._selected_node = int(self.analysis_node_combo.currentData() or 0)
        self._metric_key = str(self.metric_combo.currentData() or "breath_bpm")
        self._window_seconds = int(self.window_combo.currentData() or 0)
        filtered_history = self._analysis_history(history)

        self.stat_cards["samples"].set_value(f"{len(filtered_history)}", "当前筛选")
        breaths = [_float(s.get("breath_bpm")) for s in filtered_history if _float(s.get("breath_bpm")) > 0]
        avg_breath = sum(breaths) / len(breaths) if breaths else 0.0
        self.stat_cards["avg_breath"].set_value(f"{avg_breath:.0f} 次/分", "当前筛选")
        gases = [_float(s.get("gas")) for s in filtered_history]
        max_gas = max(gases) if gases else 0.0
        self.stat_cards["max_gas"].set_value(
            f"{max_gas:.0f} ppm", "当前筛选", THEME["red"] if max_gas >= 550 else None
        )
        online = sum(1 for n in nodes.values() if n.get("online"))
        self.stat_cards["online"].set_value(
            f"{online} / {len(nodes) or len(NODE_IDS)}", "生命体征节点",
            THEME["green"] if online else None,
        )

        if not self.isVisible():
            return
        now = time.time()
        if now - self._last_plot_at < 0.8:
            return
        self._last_plot_at = now

        for node_id, curve in self._curves.items():
            if self._selected_node and node_id != self._selected_node:
                curve.setData([], [])
                continue
            recent = [s for s in filtered_history if int(s.get("node_id") or 0) == node_id][-240:]
            xs = [_float(s.get("timestamp"), now) - now for s in recent]
            ys = [_score(s.get(self._metric_key)) if self._metric_key in ("motion_score", "presence_score") else _float(s.get(self._metric_key)) for s in recent]
            curve.setData(xs, ys)
        seconds = self._window_seconds or max(60, int(now - min((_float(s.get("timestamp"), now) for s in filtered_history), default=now)))
        self.plot.setXRange(-float(seconds), 0.0, padding=0)
        self.plot_title.setText(f"{self.metric_combo.currentText()} 趋势")

    def _on_analysis_control_changed(self) -> None:
        node_id = int(self.analysis_node_combo.currentData() or 0)
        if node_id:
            self.active_node_changed.emit(node_id)
        self._last_plot_at = 0.0

    def _analysis_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = time.time()
        selected_node = int(self.analysis_node_combo.currentData() or 0)
        seconds = int(self.window_combo.currentData() or 0)
        rows = history
        if selected_node:
            rows = [s for s in rows if int(s.get("node_id") or 0) == selected_node]
        if seconds:
            rows = [s for s in rows if now - _float(s.get("timestamp"), now) <= seconds]
        return rows


# ===========================================================================
# 技术诊断页
# ===========================================================================
class DiagnosticsPage(QWidget):
    """链路质量诊断 + 系统信息。"""

    diagnostics_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._link_labels: dict[int, dict[str, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("技术诊断")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        subtitle = QLabel("生命体征节点链路质量与网关状态")
        subtitle.setObjectName("SectionSub")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        run_btn = QPushButton("本地链路自检")
        run_btn.setObjectName("PrimaryButton")
        run_btn.clicked.connect(self.diagnostics_requested.emit)
        copy_btn = QPushButton("复制报告")
        copy_btn.setObjectName("GhostButton")
        copy_btn.clicked.connect(self._copy_report)
        actions.addWidget(run_btn)
        actions.addWidget(copy_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        link_card = CardFrame()
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(20, 18, 20, 10)
        link_layout.setSpacing(0)

        link_title = QLabel("节点链路质量 (LINK QUALITY)")
        link_title.setObjectName("SectionTitle")
        link_layout.addWidget(link_title)
        link_layout.addSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        headers = ("节点", "状态", "RSSI", "SNR", "丢包率", "电池")
        for col, name in enumerate(headers):
            head = QLabel(name)
            head.setObjectName("ColHeader")
            grid.addWidget(head, 0, col)

        for row_index, node_id in enumerate(NODE_IDS, start=1):
            cells: dict[str, QLabel] = {}
            name = QLabel(NODE_LABELS[node_id])
            name.setObjectName("NodeCode")
            grid.addWidget(name, row_index, 0)
            for col, key in enumerate(("status", "rssi", "snr", "loss", "battery"), start=1):
                lbl = QLabel("--")
                lbl.setStyleSheet(f"color: {THEME['text_soft']}; font-size: 14px;")
                grid.addWidget(lbl, row_index, col)
                cells[key] = lbl
            self._link_labels[node_id] = cells
        link_layout.addLayout(grid)
        layout.addWidget(link_card)

        info_card = CardFrame()
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 18, 20, 18)
        info_layout.setSpacing(10)
        info_title = QLabel("系统信息 (SYSTEM)")
        info_title.setObjectName("SectionTitle")
        info_layout.addWidget(info_title)

        self.info_labels: dict[str, QLabel] = {}
        for key, label in (
            ("gateway", "网关 ID"),
            ("control", "控制台 ID"),
            ("mode", "数据来源"),
            ("afh", "自动频率跳变 (AFH)"),
            ("mesh", "多级网格中继"),
            ("presence", "存在感应阈值"),
            ("gas", "气体检测阈值"),
        ):
            row = QHBoxLayout()
            caption = QLabel(label)
            caption.setObjectName("SubtleText")
            value = QLabel("--")
            value.setStyleSheet(f"color: {THEME['text_soft']}; font-size: 14px; font-weight: 600;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(caption)
            row.addStretch(1)
            row.addWidget(value)
            info_layout.addLayout(row)
            self.info_labels[key] = value
        layout.addWidget(info_card)

        report_card = CardFrame()
        report_layout = QVBoxLayout(report_card)
        report_layout.setContentsMargins(20, 18, 20, 18)
        report_layout.setSpacing(10)
        report_title = QLabel("诊断报告 (LOCAL REPORT)")
        report_title.setObjectName("SectionTitle")
        self.report_box = QTextEdit()
        self.report_box.setReadOnly(True)
        self.report_box.setMinimumHeight(138)
        self.report_box.setText("尚未生成诊断报告。点击“本地链路自检”后会基于当前真实快照生成摘要。")
        self.report_box.setStyleSheet(
            f"background: {THEME['card_alt']}; border: 1px solid {THEME['border']};"
            f" border-radius: 8px; color: {THEME['text_soft']}; padding: 8px;"
        )
        report_layout.addWidget(report_title)
        report_layout.addWidget(self.report_box)
        layout.addWidget(report_card)
        layout.addStretch(1)

    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        nodes: dict[int, dict[str, Any]] = snapshot.get("nodes", {})
        config: dict[str, Any] = snapshot.get("config", {})

        for node_id, cells in self._link_labels.items():
            state = nodes.get(node_id, {})
            online = bool(state.get("online"))
            cells["status"].setText("在线" if online else "离线")
            cells["status"].setStyleSheet(
                f"color: {THEME['green'] if online else THEME['red']}; font-size: 14px; font-weight: 600;"
            )
            cells["rssi"].setText(f"{_float(state.get('rssi')):.0f} dBm")
            cells["snr"].setText(f"{_float(state.get('snr')):.1f} dB")
            loss = _float(state.get("packet_loss"))
            cells["loss"].setText(f"{loss:.2f}%")
            cells["loss"].setStyleSheet(
                f"color: {THEME['red'] if loss >= 8 else THEME['text_soft']}; font-size: 14px;"
            )
            cells["battery"].setText(f"{_float(state.get('battery')):.0f}%")

        self.info_labels["gateway"].setText(GATEWAY_ID)
        self.info_labels["control"].setText(str(config.get("control_id", CONTROL_ID)))
        self.info_labels["mode"].setText(
            "串口实时" if snapshot.get("serial_connected") else "未连接串口"
        )
        self.info_labels["afh"].setText("开启" if config.get("afh_enabled") else "关闭")
        self.info_labels["mesh"].setText("开启" if config.get("mesh_enabled") else "关闭")
        self.info_labels["presence"].setText(f"{_float(config.get('presence_threshold')) * 100:.0f}%")
        self.info_labels["gas"].setText(f"{_float(config.get('gas_threshold')):.0f} ppm")
        report = str(snapshot.get("diagnostics_report") or "")
        if report:
            self.report_box.setText(report)

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self.report_box.toPlainText())


# ===========================================================================
# 历史记录页
# ===========================================================================
class HistoryPage(QWidget):
    """可滚动历史样本表 + CSV 导出。"""

    export_csv_requested = pyqtSignal()
    export_filtered_csv_requested = pyqtSignal(object)
    clear_history_requested = pyqtSignal()

    _COLUMNS = ("时间", "节点", "存在", "运动", "呼吸 BPM", "置信度", "气体", "温度", "湿度", "RSSI")

    def __init__(self) -> None:
        super().__init__()
        self._last_refresh_at = 0.0
        self._latest_filtered: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("历史记录")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        self.subtitle = QLabel("最近 0 条样本")
        self.subtitle.setObjectName("SectionSub")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.history_node_combo = QComboBox()
        self.history_node_combo.addItem("全部节点", 0)
        for node_id in NODE_IDS:
            self.history_node_combo.addItem(NODE_LABELS[node_id], node_id)
        self.history_node_combo.currentIndexChanged.connect(lambda: setattr(self, "_last_refresh_at", 0.0))
        self.history_limit_combo = QComboBox()
        for label, limit in (("最新 200", 200), ("最新 500", 500), ("全部", 0)):
            self.history_limit_combo.addItem(label, limit)
        self.history_limit_combo.currentIndexChanged.connect(lambda: setattr(self, "_last_refresh_at", 0.0))
        export_btn = QPushButton("CSV 导出")
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(self.export_csv_requested.emit)
        export_filter_btn = QPushButton("导出筛选")
        export_filter_btn.setObjectName("GhostButton")
        export_filter_btn.clicked.connect(lambda: self.export_filtered_csv_requested.emit(list(self._latest_filtered)))
        clear_btn = QPushButton("清空历史")
        clear_btn.setObjectName("DangerButton")
        clear_btn.clicked.connect(self.clear_history_requested.emit)
        header.addWidget(self.history_node_combo)
        header.addWidget(self.history_limit_combo)
        header.addWidget(export_btn)
        header.addWidget(export_filter_btn)
        header.addWidget(clear_btn)
        layout.addLayout(header)
        self.export_message = QLabel("")
        self.export_message.setObjectName("SubtleText")
        layout.addWidget(self.export_message)

        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.cellDoubleClicked.connect(self._show_sample_detail)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(self._COLUMNS)):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        history: list[dict[str, Any]] = snapshot.get("history", [])
        filtered = self._filter_history(history)
        self._latest_filtered = filtered
        self.subtitle.setText(f"最近 {len(history)} 条样本（当前筛选 {len(filtered)} 条）")

        if not self.isVisible():
            return
        now = time.time()
        if now - self._last_refresh_at < 1.0:
            return
        self._last_refresh_at = now

        limit = int(self.history_limit_combo.currentData() or 0)
        recent = (filtered[-limit:] if limit else filtered)[::-1]
        self.table.setRowCount(len(recent))
        for row, sample in enumerate(recent):
            ts = _float(sample.get("timestamp"), now)
            values = (
                time.strftime("%H:%M:%S", time.localtime(ts)),
                str(sample.get("node_code", sample.get("node_id", ""))),
                f"{_score(sample.get('presence_score')):.2f}",
                f"{_score(sample.get('motion_score')):.2f}",
                f"{_float(sample.get('breath_bpm')):.0f}",
                f"{_score(sample.get('confidence')) * 100:.0f}%",
                f"{_float(sample.get('gas')):.0f}",
                f"{_float(sample.get('temperature')):.1f}",
                f"{_float(sample.get('humidity')):.0f}",
                f"{_float(sample.get('rssi')):.0f}",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

    def _filter_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        node_id = int(self.history_node_combo.currentData() or 0)
        if not node_id:
            return list(history)
        return [sample for sample in history if int(sample.get("node_id") or 0) == node_id]

    def _show_sample_detail(self, row: int, _col: int) -> None:
        limit = int(self.history_limit_combo.currentData() or 0)
        recent = (self._latest_filtered[-limit:] if limit else self._latest_filtered)[::-1]
        if row < 0 or row >= len(recent):
            return
        sample = recent[row]
        _show_detail_dialog(
            self,
            "历史样本详情",
            (
                ("时间戳", sample.get("timestamp", "-")),
                ("节点", sample.get("node_code", sample.get("node_id", "-"))),
                ("序号", sample.get("seq", "-")),
                ("Presence", f"{_score(sample.get('presence_score')):.2f}"),
                ("Motion", f"{_score(sample.get('motion_score')):.2f}"),
                ("Breath BPM", f"{_float(sample.get('breath_bpm')):.0f}"),
                ("Confidence", f"{_score(sample.get('confidence')) * 100:.0f}%"),
                ("Gas", f"{_float(sample.get('gas')):.0f} ppm"),
                ("Raw", sample.get("raw", "")),
            ),
        )

    def set_export_message(self, text: str, ok: bool = True) -> None:
        self.export_message.setText(text)
        self.export_message.setStyleSheet(
            f"color: {THEME['blue_soft'] if ok else THEME['red']};"
        )


# ---------------------------------------------------------------------------
def _show_detail_dialog(parent: QWidget, title: str, rows: tuple[tuple[str, Any], ...]) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(460)
    dialog.setStyleSheet(
        f"QDialog {{ background: {THEME['bg']}; }}"
        f"QLabel {{ color: {THEME['text_soft']}; }}"
    )

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(14)

    title_label = QLabel(title)
    title_label.setObjectName("SectionTitle")
    title_label.setStyleSheet("font-size: 17px; font-weight: 700;")
    layout.addWidget(title_label)

    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(10)
    for row_index, (name, value) in enumerate(rows):
        key_label = QLabel(str(name))
        key_label.setObjectName("SubtleText")
        value_label = QLabel(str(value))
        value_label.setWordWrap(True)
        value_label.setStyleSheet(f"color: {THEME['text']}; font-size: 14px; font-weight: 600;")
        grid.addWidget(key_label, row_index, 0)
        grid.addWidget(value_label, row_index, 1)
    layout.addLayout(grid)

    close_btn = QPushButton("关闭")
    close_btn.setObjectName("PrimaryButton")
    close_btn.clicked.connect(dialog.accept)
    footer = QHBoxLayout()
    footer.addStretch(1)
    footer.addWidget(close_btn)
    layout.addLayout(footer)
    dialog.exec()


def _score(value: Any) -> float:
    score = _float(value)
    if score > 1.0:
        score /= 100.0
    return max(0.0, min(score, 1.0))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
