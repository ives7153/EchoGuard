"""上位机数据协调层。

中文注释：DataManager 是 UI 与硬件 / 规则 / 导出之间的中间层。UI 不直接读串口、
不直接解析 JSON、不直接跑报警规则，只接收这里发出的 Qt 信号并刷新控件。
这样串口后台读取不会阻塞主线程，同时保持 serial_handler.py / data_parser.py 的兼容性。

本层只驱动真实串口数据：
* 生命体征感知节点（id 1..4）—— 仪表盘页使用，含 presence/motion/bpm/conf 等。
* LoRa 节点矩阵（共 14 个）—— 传感器页使用，前若干个绑定真实固件节点，状态随真实
  数据更新；未绑定真实节点的行保持离线，不再注入任何模拟数据。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget

try:
    from ..config import (
        AUTO_PORT_REFRESH_MS,
        BAUDRATE,
        CONTROL_ID,
        DEFAULT_AFH_ENABLED,
        DEFAULT_MESH_ENABLED,
        GAS_THRESHOLD_PPM,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        HEALTH_EXCELLENT,
        HEALTH_GOOD,
        HEALTH_INACTIVE,
        MAX_EVENT_ROWS,
        MAX_HISTORY_ROWS,
        NODE_IDS,
        NODE_LABELS,
        NODE_MATRIX,
        OFFLINE_SECONDS,
        PRESENCE_THRESHOLD,
        UI_REFRESH_MS,
    )
    from ..data_parser import parse_gateway_frame
    from ..serial_handler import SerialReader
    from .alarm_rules import AlarmEngine
    from .exporter import (
        export_samples_to_csv,
        save_csi_screenshot,
        save_widget_screenshot,
    )
except ImportError:  # 兼容在 upper_computer 目录下直接 python main.py
    from config import (
        AUTO_PORT_REFRESH_MS,
        BAUDRATE,
        CONTROL_ID,
        DEFAULT_AFH_ENABLED,
        DEFAULT_MESH_ENABLED,
        GAS_THRESHOLD_PPM,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        HEALTH_EXCELLENT,
        HEALTH_GOOD,
        HEALTH_INACTIVE,
        MAX_EVENT_ROWS,
        MAX_HISTORY_ROWS,
        NODE_IDS,
        NODE_LABELS,
        NODE_MATRIX,
        OFFLINE_SECONDS,
        PRESENCE_THRESHOLD,
        UI_REFRESH_MS,
    )
    from data_parser import parse_gateway_frame
    from serial_handler import SerialReader
    from core.alarm_rules import AlarmEngine
    from core.exporter import (
        export_samples_to_csv,
        save_csi_screenshot,
        save_widget_screenshot,
    )


@dataclass(slots=True)
class NodeState:
    """单个生命体征感知节点当前状态（id 1..4）。

    中文注释：字段命名沿用 data_parser.py 的规范化结果，UI 与报警规则可直接消费。
    """

    node_id: int
    label: str
    online: bool = False
    rssi: float = 0.0
    wifi_rssi: float = -42.0
    snr: float = 0.0
    packet_loss: float = 0.0
    battery: float = 100.0
    last_received: float | None = None
    created_at: float = field(default_factory=time.time)
    seq: int | None = None
    presence_score: float = 0.0
    motion_score: float = 0.0
    breath_bpm: float = 0.0
    confidence: float = 0.0
    gas: float = 0.0
    temperature: float = 0.0
    humidity: float = 0.0
    source: str = "serial"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MatrixNodeState:
    """LoRa 节点矩阵中的一行（传感器页使用）。"""

    matrix_id: int
    code: str
    mode: str
    bound_node: int | None = None
    online: bool = False
    rssi: float = -110.0
    battery: float | None = None
    health: str = HEALTH_INACTIVE
    last_received: float | None = None
    maintenance: bool = False
    local: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventRecord:
    """右侧事件流记录。"""

    time: float
    title: str
    message: str
    node_id: int = 0
    level: str = "INFO"
    kind: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SerialWorker(QObject):
    """运行在 QThread 中的串口 Worker。

    中文注释：Worker 内部复用 SerialReader；SerialReader 自身创建 Python 后台线程
    读取串口，回调触发 Qt 信号，Qt 会自动把信号投递回主线程。
    """

    line_received = pyqtSignal(str)
    error = pyqtSignal(str)
    opened = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, port: str, baudrate: int) -> None:
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self._reader: SerialReader | None = None

    @pyqtSlot()
    def start_reader(self) -> None:
        try:
            self._reader = SerialReader()
            self._reader.start(
                port=self.port,
                baudrate=self.baudrate,
                on_line=self.line_received.emit,
                on_error=self.error.emit,
            )
        except Exception as exc:  # noqa: BLE001 - 串口占用 / 权限 / 拔插异常需回传 UI。
            self.error.emit(str(exc))
            return

        self.opened.emit(self.port)

    @pyqtSlot()
    def stop_reader(self) -> None:
        if self._reader:
            self._reader.stop()
            self._reader = None
        self.closed.emit()


class DataManager(QObject):
    """应用数据中心：串口、Demo、规则、历史、节点矩阵和导出。"""

    snapshot_changed = pyqtSignal(object)
    status_changed = pyqtSignal(str, bool)
    latest_frame_changed = pyqtSignal(str)
    ports_changed = pyqtSignal(object, object)
    export_message_changed = pyqtSignal(str, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.started_at = time.time()
        self.available_ports: list[str] = []
        self.selected_port = ""
        self.history: list[dict[str, Any]] = []
        self.events: list[EventRecord] = []

        # 报警引擎（阈值可被传感器页热更新）
        self.alarm_engine = AlarmEngine()
        self.presence_threshold = PRESENCE_THRESHOLD
        self.gas_threshold = GAS_THRESHOLD_PPM
        self.afh_enabled = DEFAULT_AFH_ENABLED
        self.mesh_enabled = DEFAULT_MESH_ENABLED
        self.last_sync_at: float | None = None

        # 生命体征节点（id 1..4）
        self.nodes: dict[int, NodeState] = {
            node_id: NodeState(
                node_id=node_id,
                label=NODE_LABELS[node_id],
                battery=max(72.0, 96.0 - node_id * 3.0),
            )
            for node_id in NODE_IDS
        }

        # LoRa 节点矩阵（14 个）
        # 中文注释：矩阵结构来自配置常量，初始全部离线/未激活；只有绑定真实固件
        # 节点的行才会随真实串口数据上线，未绑定的行保持离线占位，不再注入模拟数据。
        self.matrix: dict[int, MatrixNodeState] = {}
        for entry in NODE_MATRIX:
            self.matrix[entry["matrix_id"]] = MatrixNodeState(
                matrix_id=entry["matrix_id"],
                code=entry["code"],
                mode=entry["mode"],
                bound_node=entry.get("bound_node"),
                battery=None,
            )
        self._removed_matrix_nodes: dict[int, MatrixNodeState] = {}

        self._thread: QThread | None = None
        self._worker: SerialWorker | None = None
        self._serial_connected = False
        self._serial_auto_connected = False
        self._serial_started_at = 0.0
        self._last_serial_sample_at = 0.0
        self._dirty = True
        self._active_node = NODE_IDS[0]
        self._paused = False
        self._matrix_filter = "ALL"
        self._diagnostics_report = ""
        self._local_matrix_next_id = max(self.matrix) + 1 if self.matrix else 1
        self._presence_flags = {node_id: False for node_id in NODE_IDS}
        self._breath_lock_flags = {node_id: False for node_id in NODE_IDS}
        self._offline_flags = {node_id: False for node_id in NODE_IDS}
        self._gas_alert_flags = {node_id: False for node_id in NODE_IDS}

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_REFRESH_MS)
        self._ui_timer.timeout.connect(self._publish_snapshot)

        self._offline_timer = QTimer(self)
        self._offline_timer.setInterval(1000)
        self._offline_timer.timeout.connect(self._check_offline_nodes)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_PORT_REFRESH_MS)
        self._auto_timer.timeout.connect(self._auto_service)

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        """启动数据服务：刷新串口列表并自动探测真实 Gateway。"""

        self._ui_timer.start()
        self._offline_timer.start()
        self.refresh_ports()
        self._auto_timer.start()
        self._auto_service()

    def shutdown(self) -> None:
        """程序退出时释放串口线程与定时器。"""

        self._ui_timer.stop()
        self._offline_timer.stop()
        self._auto_timer.stop()
        self.stop_serial()

    # ------------------------------------------------------------------ UI 槽
    @pyqtSlot()
    def refresh_ports(self) -> None:
        """刷新本机串口列表。"""

        try:
            import serial.tools.list_ports as list_ports

            self.available_ports = [port.device for port in list_ports.comports()]
        except Exception:  # noqa: BLE001 - pyserial 缺失或枚举失败时仍可演示。
            self.available_ports = []

        selected = self.selected_port if self.selected_port in self.available_ports else ""
        self.ports_changed.emit(self.available_ports, selected)

    @pyqtSlot(str)
    def connect_to_port(self, port: str) -> None:
        """手动连接指定串口。"""

        if not port or port == "无可用串口":
            self.status_changed.emit("串口状态：没有可连接的串口", False)
            return

        self._connect_serial(port, auto=False)

    @pyqtSlot()
    def disconnect_serial(self) -> None:
        """手动断开串口。"""

        self.stop_serial()
        self.status_changed.emit("串口状态：已手动断开，等待连接", False)

    @pyqtSlot()
    def export_csv(self) -> None:
        """导出当前历史样本为 CSV。"""

        if not self.history:
            self.export_message_changed.emit("暂无历史样本可导出", False)
            return
        try:
            path = export_samples_to_csv(self.history)
        except Exception as exc:  # noqa: BLE001 - 导出失败需落在界面状态上。
            self.export_message_changed.emit(f"CSV 导出失败：{exc}", False)
            return

        self.export_message_changed.emit(f"CSV 已导出：{path.name}", True)
        self._append_event("CSV EXPORTED", f"历史样本已保存到 {path.name}", level="OK", kind="export")

    def save_screenshot(self, widget: QWidget) -> None:
        """保存整窗截图。"""

        try:
            path = save_widget_screenshot(widget)
        except Exception as exc:  # noqa: BLE001
            self.export_message_changed.emit(f"截图失败：{exc}", False)
            return

        self.export_message_changed.emit(f"截图已保存：{path.name}", True)
        self._append_event("SCREENSHOT SAVED", f"控制台截图已保存到 {path.name}", level="OK", kind="export")

    def save_csi_image(self, widget: QWidget) -> None:
        """单独保存 CSI 曲线截图。"""

        try:
            path = save_csi_screenshot(widget)
        except Exception as exc:  # noqa: BLE001
            self.export_message_changed.emit(f"CSI 曲线截图失败：{exc}", False)
            return

        self.export_message_changed.emit(f"CSI 曲线截图已保存：{path.name}", True)
        self._append_event("CSI SNAPSHOT", f"CSI 振幅曲线已保存到 {path.name}", level="OK", kind="export")

    @pyqtSlot(object)
    def save_analysis_image(self, widget: QWidget) -> None:
        """保存分析页当前图表截图。"""

        try:
            path = save_csi_screenshot(widget)
        except Exception as exc:  # noqa: BLE001
            self.export_message_changed.emit(f"分析图表截图失败：{exc}", False)
            return

        self.export_message_changed.emit(f"分析图表截图已保存：{path.name}", True)
        self._append_event("ANALYSIS SNAPSHOT", f"分析图表已保存到 {path.name}", level="OK", kind="export")

    @pyqtSlot(object)
    def export_filtered_csv(self, samples: object) -> None:
        """导出页面传入的过滤后样本。"""

        if not isinstance(samples, list) or not samples:
            self.export_message_changed.emit("当前筛选结果为空，无法导出", False)
            return
        try:
            path = export_samples_to_csv(samples)
        except Exception as exc:  # noqa: BLE001
            self.export_message_changed.emit(f"CSV 导出失败：{exc}", False)
            return

        self.export_message_changed.emit(f"CSV 已导出：{path.name}", True)
        self._append_event("CSV EXPORTED", f"筛选样本已保存到 {path.name}", level="OK", kind="export")

    @pyqtSlot(int)
    def set_active_node(self, node_id: int) -> None:
        """切换当前关注节点。"""

        if int(node_id) not in self.nodes:
            return
        self._active_node = int(node_id)
        self._dirty = True

    @pyqtSlot(bool)
    def set_paused(self, paused: bool) -> None:
        """暂停 / 恢复实时样本应用。"""

        self._paused = bool(paused)
        self._append_event(
            "STREAM PAUSED" if self._paused else "STREAM RESUMED",
            "实时刷新已暂停" if self._paused else "实时刷新已恢复",
            level="WARN" if self._paused else "OK",
            kind="ui",
        )

    @pyqtSlot()
    def clear_events(self) -> None:
        """清空右侧实时事件流。"""

        self.events.clear()
        self._dirty = True

    @pyqtSlot()
    def clear_history(self) -> None:
        """清空本次运行内历史样本缓存。"""

        self.history.clear()
        self._append_event("HISTORY CLEARED", "本地历史样本缓存已清空", level="WARN", kind="history")
        self._dirty = True

    @pyqtSlot(str)
    def set_matrix_filter(self, value: str) -> None:
        self._matrix_filter = str(value or "ALL")
        self._dirty = True

    @pyqtSlot(object)
    def add_local_matrix_node(self, options: object | None = None) -> None:
        """添加一个本次运行内的观察节点，不写入硬件配置。"""

        payload = options if isinstance(options, dict) else {}
        matrix_id = self._local_matrix_next_id
        self._local_matrix_next_id += 1
        code = str(payload.get("code") or f"node{matrix_id}").strip() or f"node{matrix_id}"
        existing_codes = {state.code.lower() for state in self.matrix.values()}
        if code.lower() in existing_codes:
            code = f"node{matrix_id}"
        bound_node = _optional_int(payload.get("bound_node"))
        active_bound_nodes = {state.bound_node for state in self.matrix.values() if state.bound_node is not None}
        if bound_node in active_bound_nodes:
            bound_node = None
        self.matrix[matrix_id] = MatrixNodeState(
            matrix_id=matrix_id,
            code=code,
            mode="NORMAL",
            bound_node=bound_node if bound_node in self.nodes else None,
            online=False,
            rssi=-110.0,
            battery=None,
            local=True,
        )
        bind_text = f"，绑定硬件 ID {bound_node}" if bound_node in self.nodes else ""
        self._append_event("NODE WATCH ADDED", f"已添加观察节点 {code}{bind_text}", level="OK", kind="matrix")
        self._dirty = True

    @pyqtSlot(int)
    def remove_local_matrix_node(self, matrix_id: int) -> None:
        """从当前列表移除节点；不向硬件下发删除命令。"""

        matrix_id = int(matrix_id)
        state = self.matrix.get(matrix_id)
        if state is None:
            return
        del self.matrix[matrix_id]
        if state.bound_node is not None:
            state.online = False
            self._removed_matrix_nodes[matrix_id] = state
        self._append_event("NODE REMOVED", f"已从当前列表移除 {state.code}", level="WARN", kind="matrix")
        self._dirty = True

    @pyqtSlot(int)
    def toggle_matrix_maintenance(self, matrix_id: int) -> None:
        """切换节点维护标记。"""

        state = self.matrix.get(int(matrix_id))
        if state is None:
            return
        state.maintenance = not state.maintenance
        state.health = self._derive_health(state)
        self._append_event(
            "MAINTENANCE MARKED" if state.maintenance else "MAINTENANCE CLEARED",
            f"{state.code} {'已标记维护' if state.maintenance else '已取消维护标记'}",
            level="WARN" if state.maintenance else "OK",
            kind="matrix",
        )
        self._dirty = True

    @pyqtSlot()
    def generate_diagnostics_report(self) -> None:
        """基于当前快照生成本地诊断摘要，不下发硬件命令。"""

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        online_nodes = [node for node in self.nodes.values() if node.online]
        offline_nodes = [node for node in self.nodes.values() if not node.online]
        critical_matrix = [state for state in self.matrix.values() if self._derive_health(state) == HEALTH_CRITICAL]
        report_lines = [
            f"诊断时间：{now}",
            f"串口链路：{'已连接 ' + self.selected_port if self._serial_connected else '未连接'}",
            f"生命体征节点：在线 {len(online_nodes)} / {len(self.nodes)}，离线 {len(offline_nodes)}",
            f"LoRa 矩阵：在线 {sum(1 for s in self.matrix.values() if s.online)} / {len(self.matrix)}，严重项 {len(critical_matrix)}",
            f"历史样本：{len(self.history)} 条；事件：{len(self.events)} 条",
            "建议：优先检查离线节点供电、天线连接与 Gateway 串口输出；本报告未向硬件下发任何指令。",
        ]
        self._diagnostics_report = "\n".join(report_lines)
        self._append_event("DIAGNOSTICS READY", "本地链路自检报告已生成", level="OK", kind="diagnostics")
        self._dirty = True

    @pyqtSlot(float)
    def set_presence_threshold(self, value: float) -> None:
        """传感器页存在感应阈值滑条回调。"""

        self.presence_threshold = max(0.0, min(1.0, float(value)))
        self.alarm_engine.update_thresholds(presence_threshold=self.presence_threshold)
        self._dirty = True

    @pyqtSlot(float)
    def set_gas_threshold(self, value: float) -> None:
        """传感器页气体检测阈值滑条回调。"""

        self.gas_threshold = max(0.0, float(value))
        self._dirty = True

    @pyqtSlot(bool)
    def set_afh_enabled(self, enabled: bool) -> None:
        self.afh_enabled = bool(enabled)
        self._append_event(
            "AFH " + ("ENABLED" if enabled else "DISABLED"),
            f"自动频率跳变已{'开启' if enabled else '关闭'}",
            level="INFO",
            kind="config",
        )

    @pyqtSlot(bool)
    def set_mesh_enabled(self, enabled: bool) -> None:
        self.mesh_enabled = bool(enabled)
        self._append_event(
            "MESH " + ("ENABLED" if enabled else "DISABLED"),
            f"多级网格中继已{'开启' if enabled else '关闭'}",
            level="INFO",
            kind="config",
        )

    @pyqtSlot()
    def sync_global_config(self) -> None:
        """传感器页“同步全局配置”按钮。"""

        self.last_sync_at = time.time()
        self.alarm_engine.update_thresholds(
            presence_threshold=self.presence_threshold,
            gas_alarm_ppm=max(self.gas_threshold, self.alarm_engine.gas_alarm_ppm),
        )
        self._append_event(
            "CONFIG SYNCED",
            f"全局配置已下发：存在阈值 {self.presence_threshold * 100:.0f}% · 气体阈值 {self.gas_threshold:.0f} ppm",
            level="OK",
            kind="config",
        )
        self._dirty = True

    # ------------------------------------------------------------------ 串口
    def stop_serial(self) -> None:
        """停止串口 Worker 与线程。"""

        self._serial_connected = False
        self._last_serial_sample_at = 0.0

        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None

        if worker is not None:
            worker.stop_reader()
            worker.deleteLater()

        if thread is not None:
            thread.quit()
            thread.wait(1500)
            thread.deleteLater()

    def _auto_service(self) -> None:
        """自动探测真实 Gateway 串口；未发现时保持等待，不注入任何模拟数据。"""

        now = time.time()
        if self._serial_connected:
            if (
                self._serial_auto_connected
                and self._last_serial_sample_at <= 0
                and now - self._serial_started_at > 4.0
            ):
                self.status_changed.emit("串口状态：串口无有效 Gateway 帧，断开并重新探测", False)
                self.stop_serial()
            return

        self.refresh_ports()
        port = self._probe_gateway_port()
        if not port:
            self.status_changed.emit("串口状态：未发现有效 Gateway，等待真实串口接入", False)
            return

        self._connect_serial(port, auto=True)

    def _connect_serial(self, port: str, auto: bool) -> None:
        """创建 Qt 串口线程。"""

        self.stop_serial()

        self.selected_port = port
        self._serial_auto_connected = auto
        self._serial_started_at = time.time()
        self.status_changed.emit(f"串口状态：正在连接 {port} @ {BAUDRATE}", True)

        self._thread = QThread(self)
        self._worker = SerialWorker(port, BAUDRATE)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start_reader)
        self._worker.opened.connect(self._handle_serial_opened)
        self._worker.line_received.connect(self._handle_raw_line)
        self._worker.error.connect(self._handle_serial_error)
        self._thread.start()

    def _probe_gateway_port(self) -> str | None:
        """快速探测会输出 Gateway JSON Lines 的串口。"""

        if not self.available_ports:
            return None

        try:
            import serial
        except Exception:
            return None

        for port in self.available_ports:
            try:
                with serial.Serial(port=port, baudrate=BAUDRATE, timeout=0.12) as probe:
                    deadline = time.time() + 0.75
                    while time.time() < deadline:
                        raw = probe.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="replace").strip()
                        if parse_gateway_frame(line).get("valid"):
                            return port
            except Exception:
                continue

        return None

    @pyqtSlot(str)
    def _handle_serial_opened(self, port: str) -> None:
        self._serial_connected = True
        self.selected_port = port
        self.ports_changed.emit(self.available_ports, port)
        self.status_changed.emit(f"串口状态：已连接 {port} @ {BAUDRATE}", True)
        self._append_event(
            "WIFI SYNC ESTABLISHED",
            f"{GATEWAY_ID} 串口链路已建立：{port}",
            level="OK",
            kind="serial",
        )

    @pyqtSlot(str)
    def _handle_serial_error(self, message: str) -> None:
        self.status_changed.emit(f"串口状态：连接异常，等待重新探测 - {message}", False)
        self._append_event("SERIAL LINK LOST", message, level="ALARM", kind="serial")
        self.stop_serial()

    @pyqtSlot(str)
    def _handle_raw_line(self, raw_line: str) -> None:
        parsed = parse_gateway_frame(raw_line)
        if not parsed.get("valid"):
            self.latest_frame_changed.emit(f"最新帧：忽略非 JSON 数据 - {raw_line[:120]}")
            return

        now = time.time()
        parsed["timestamp"] = now
        parsed["source"] = "serial"
        self._last_serial_sample_at = now
        self.latest_frame_changed.emit(f"最新帧：{parsed.get('raw', raw_line)}")
        if self._paused:
            return
        self._restore_matrix_for_node(int(parsed.get("node_id") or 0))
        self._apply_sample(parsed)

    # ------------------------------------------------------------------ LoRa 矩阵
    def _refresh_matrix_node(self, state: MatrixNodeState, now: float) -> None:
        """根据绑定的真实节点刷新一行矩阵状态；未绑定真实节点的行保持离线占位。"""

        if state.bound_node is not None and state.bound_node in self.nodes:
            # 绑定真实固件节点：RSSI 与在线状态来自真实数据管线。
            src = self.nodes[state.bound_node]
            state.online = src.online and state.mode != "SLEEP"
            if src.rssi:
                state.rssi = src.rssi
            if src.last_received is not None:
                state.last_received = src.last_received
        else:
            # 未绑定真实节点：没有真实数据来源，保持离线占位。
            state.online = False

        state.health = self._derive_health(state)

    def _restore_matrix_for_node(self, node_id: int) -> None:
        if node_id <= 0:
            return
        for matrix_id, state in list(self._removed_matrix_nodes.items()):
            if state.bound_node == node_id:
                self.matrix[matrix_id] = state
                del self._removed_matrix_nodes[matrix_id]
                self._append_event("NODE RESTORED", f"{state.code} 收到串口数据，已恢复到列表", level="OK", kind="matrix")

    def _derive_health(self, state: MatrixNodeState) -> str:
        """从运行模式 / RSSI 推导运行健康度；当前固件未上报电池。"""

        if state.maintenance:
            return HEALTH_CRITICAL
        if state.mode == "SLEEP" or not state.online:
            return HEALTH_INACTIVE
        if state.rssi < -118.0:
            return HEALTH_CRITICAL
        if state.rssi < -100.0:
            return HEALTH_GOOD
        return HEALTH_EXCELLENT

    # ------------------------------------------------------------------ 样本应用
    def _apply_sample(self, sample: dict[str, Any]) -> None:
        node_id = int(sample.get("node_id") or 0)
        if node_id not in self.nodes:
            return

        now = float(sample.get("timestamp") or time.time())
        node = self.nodes[node_id]
        was_online = node.online

        node.online = True
        node.rssi = _float(sample.get("rssi"))
        node.wifi_rssi = _float(sample.get("wifi_rssi"), node.rssi)
        node.snr = _float(sample.get("snr"), _snr_from_rssi(node.rssi))
        node.packet_loss = _float(sample.get("packet_loss"), _packet_loss_from_rssi(node.rssi))
        node.last_received = now
        node.seq = _optional_int(sample.get("seq"))
        node.presence_score = _score(sample.get("presence_score", sample.get("presence")))
        node.motion_score = _score(sample.get("motion_score", sample.get("motion")))
        node.breath_bpm = _float(sample.get("breath_bpm", sample.get("bpm")))
        node.confidence = _score(sample.get("confidence", sample.get("conf")))
        node.gas = _float(sample.get("gas"))
        node.temperature = _float(sample.get("temperature", sample.get("temp")))
        node.humidity = _float(sample.get("humidity", sample.get("hum")))
        node.source = str(sample.get("source", "serial"))

        enriched = dict(sample)
        enriched.update(
            {
                "timestamp": now,
                "node_id": node_id,
                "node_code": NODE_LABELS.get(node_id, f"SENS_{node_id:02d}"),
                "wifi_rssi": node.wifi_rssi,
                "snr": node.snr,
                "packet_loss": node.packet_loss,
                "battery": node.battery,
                "mode": "NORMAL",
            }
        )
        self.history.append(enriched)
        if len(self.history) > MAX_HISTORY_ROWS:
            del self.history[: len(self.history) - MAX_HISTORY_ROWS]

        self._active_node = node_id
        self._offline_flags[node_id] = False

        if not was_online:
            self._append_event(
                "WIFI SYNC ESTABLISHED",
                f"CSI 子载波同步完成 ({node.label})",
                node_id=node_id,
                level="OK",
                kind="node",
            )

        self._handle_life_events(node)
        for alarm in self.alarm_engine.evaluate(enriched, None, now):
            alarm_node = int(alarm.get("node_id") or node_id)
            self._append_event(
                str(alarm.get("title", "SYSTEM ALARM")),
                f"{NODE_LABELS.get(alarm_node, f'node{alarm_node}')} {alarm.get('message', '规则报警')}",
                node_id=alarm_node,
                level=str(alarm.get("level", "ALARM")),
                kind=str(alarm.get("kind", "alarm")),
                event_time=float(alarm.get("time", now)),
            )

        self._dirty = True

    def _handle_life_events(self, node: NodeState) -> None:
        """根据状态变化生成右侧实时事件流。"""

        node_id = node.node_id
        has_presence = node.presence_score >= max(0.5, self.presence_threshold) and node.confidence >= 0.62

        if has_presence and not self._presence_flags[node_id]:
            self._append_event(
                "疑似生命微动",
                f"检测到疑似生命微动信号 ({node.label})",
                node_id=node_id,
                level="ALARM",
                kind="presence",
            )
        elif not has_presence and self._presence_flags[node_id]:
            self._append_event(
                "未检测到稳定微动",
                f"微动信号低于阈值或需要继续观察 ({node.label})",
                node_id=node_id,
                level="WARN",
                kind="presence",
            )

        self._presence_flags[node_id] = has_presence

    def _check_offline_nodes(self) -> None:
        now = time.time()

        if self._serial_connected:
            for node in self.nodes.values():
                last = node.last_received
                is_online = bool(last is not None and now - float(last) <= OFFLINE_SECONDS)
                if node.online and not is_online:
                    node.online = False
                    self._dirty = True
                if not is_online and not self._offline_flags[node.node_id]:
                    self._offline_flags[node.node_id] = True
                    self._append_event(
                        "节点离线",
                        f"{node.label} 超过 {OFFLINE_SECONDS:.0f}s 未收到数据",
                        node_id=node.node_id,
                        level="ALARM",
                        kind="offline",
                    )

            for alarm in self.alarm_engine.evaluate(None, self._node_dicts(), now):
                alarm_node = int(alarm.get("node_id") or 0)
                self._append_event(
                    str(alarm.get("title", "节点离线")),
                    f"{NODE_LABELS.get(alarm_node, f'node{alarm_node}')} {alarm.get('message', '节点离线')}",
                    node_id=alarm_node,
                    level=str(alarm.get("level", "ALARM")),
                    kind=str(alarm.get("kind", "offline")),
                    event_time=float(alarm.get("time", now)),
                )

        # 中文注释：矩阵行根据绑定的真实节点刷新在线状态与健康度；未绑定的行保持离线。
        for state in self.matrix.values():
            self._refresh_matrix_node(state, now)

        self._auto_service()

    # ------------------------------------------------------------------ 快照
    def _publish_snapshot(self) -> None:
        if not self._dirty:
            return

        self._dirty = False
        self.snapshot_changed.emit(
            {
                "nodes": self._node_dicts(),
                "matrix": [state.to_dict() for state in self.matrix.values()],
                "history": list(self.history),
                "events": [event.to_dict() for event in self.events],
                "active_node": self._active_node,
                "serial_connected": self._serial_connected,
                "paused": self._paused,
                "diagnostics_report": self._diagnostics_report,
                "config": {
                    "presence_threshold": self.presence_threshold,
                    "gas_threshold": self.gas_threshold,
                    "afh_enabled": self.afh_enabled,
                    "mesh_enabled": self.mesh_enabled,
                    "last_sync_at": self.last_sync_at,
                    "control_id": CONTROL_ID,
                    "online_matrix": sum(1 for s in self.matrix.values() if s.online),
                    "total_matrix": len(self.matrix),
                    "matrix_filter": self._matrix_filter,
                },
            }
        )

    def _append_event(
        self,
        title: str,
        message: str,
        node_id: int = 0,
        level: str = "INFO",
        kind: str = "system",
        event_time: float | None = None,
    ) -> None:
        self.events.append(
            EventRecord(
                time=event_time if event_time is not None else time.time(),
                title=title,
                message=message,
                node_id=node_id,
                level=level,
                kind=kind,
            )
        )
        if len(self.events) > MAX_EVENT_ROWS:
            del self.events[: len(self.events) - MAX_EVENT_ROWS]
        self._dirty = True

    def _node_dicts(self) -> dict[int, dict[str, Any]]:
        return {node_id: node.to_dict() for node_id, node in self.nodes.items()}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _score(value: Any) -> float:
    score = _float(value)
    if score > 1.0:
        score /= 100.0
    return max(0.0, min(score, 1.0))


def _snr_from_rssi(rssi: float) -> float:
    """真实帧暂未提供 SNR 时，根据 RSSI 做保守估算用于 UI 展示。"""

    return max(-8.0, min(14.0, 18.0 - (abs(rssi) - 45.0) * 0.22))


def _packet_loss_from_rssi(rssi: float) -> float:
    """真实帧暂未提供丢包率时，根据 RSSI 估算展示值。"""

    return max(0.0, min(18.0, (abs(rssi) - 50.0) * 0.12))
