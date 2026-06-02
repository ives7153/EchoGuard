"""上位机数据协调层。

中文注释：DataManager 是 UI 与硬件 / 规则 / 导出之间的中间层。UI 不直接读串口、
不直接解析 JSON、不直接跑报警规则，只接收这里发出的 Qt 信号并刷新控件。
这样串口后台读取不会阻塞主线程，同时保持 serial_handler.py / data_parser.py 的兼容性。

本层只驱动真实串口数据：收到 Gateway JSON 后按节点 id 自动创建节点状态与矩阵行；
未收到真实数据前不预置节点、不注入演示样本。
"""

from __future__ import annotations

import time
import threading
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
        GAS_THRESHOLD_RAW,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        HEALTH_EXCELLENT,
        HEALTH_GOOD,
        HEALTH_INACTIVE,
        MAX_EVENT_ROWS,
        MAX_HISTORY_ROWS,
        NODE_LABELS,
        OFFLINE_SECONDS,
        PRESENCE_THRESHOLD,
        UI_REFRESH_MS,
    )
    from ..data_parser import parse_gateway_frame
    from ..ai import (
        AISettings,
        LocalJinaRuntime,
        create_jina_offline_package,
        deploy_jina_package,
        fetch_llm_models,
        fetch_llm_models_result,
        jina_deployment_status,
        load_ai_settings,
        online_deploy_jina,
        run_ai_judgement,
        save_ai_settings,
        settings_from_dict,
        test_embedding,
        test_llm,
        test_llm_result,
        wait_for_embedding_ready,
    )
    from ..rules.detection_fusion import ai_fallback_text, build_detection_summary
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
        GAS_THRESHOLD_RAW,
        GATEWAY_ID,
        HEALTH_CRITICAL,
        HEALTH_EXCELLENT,
        HEALTH_GOOD,
        HEALTH_INACTIVE,
        MAX_EVENT_ROWS,
        MAX_HISTORY_ROWS,
        NODE_LABELS,
        OFFLINE_SECONDS,
        PRESENCE_THRESHOLD,
        UI_REFRESH_MS,
    )
    from data_parser import parse_gateway_frame
    from ai import (  # type: ignore
        AISettings,
        LocalJinaRuntime,
        create_jina_offline_package,
        deploy_jina_package,
        fetch_llm_models,
        fetch_llm_models_result,
        jina_deployment_status,
        load_ai_settings,
        online_deploy_jina,
        run_ai_judgement,
        save_ai_settings,
        settings_from_dict,
        test_embedding,
        test_llm,
        test_llm_result,
        wait_for_embedding_ready,
    )
    from rules.detection_fusion import ai_fallback_text, build_detection_summary  # type: ignore
    from serial_handler import SerialReader
    from core.alarm_rules import AlarmEngine
    from core.exporter import (
        export_samples_to_csv,
        save_csi_screenshot,
        save_widget_screenshot,
    )


@dataclass(slots=True)
class NodeState:
    """单个生命体征感知节点当前状态。

    中文注释：字段命名沿用 data_parser.py 的规范化结果，UI 与报警规则可直接消费。
    """

    node_id: int
    label: str
    online: bool = False
    rssi: float = 0.0
    wifi_rssi: float = -42.0
    snr: float = 0.0
    packet_loss: float = 0.0
    battery: float | None = None
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
    ai_operation_message_changed = pyqtSignal(str, bool)
    ai_operation_result_changed = pyqtSignal(object)
    ai_models_changed = pyqtSignal(object)
    _ai_analysis_ready = pyqtSignal(int, object)
    _ai_operation_ready = pyqtSignal(str, bool)
    _ai_operation_result_ready = pyqtSignal(object)
    _ai_models_ready = pyqtSignal(object, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.started_at = time.time()
        self.available_ports: list[str] = []
        self.selected_port = ""
        self.history: list[dict[str, Any]] = []
        self.events: list[EventRecord] = []
        self.ai_settings: AISettings = load_ai_settings()
        self.ai_runtime = LocalJinaRuntime()
        self.ai_state: dict[str, Any] = {
            "enabled": self.ai_settings.enabled,
            "running": False,
            "status": "规则回退",
            "text": ai_fallback_text("等待数据"),
            "source": "rule_fallback",
            "window_start": 0.0,
            "window_end": 0.0,
            "updated_at": 0.0,
            "top_matches": [],
            "error": "",
            "config": asdict(self.ai_settings),
        }
        self._ai_busy = False
        self._ai_request_id = 0
        self._ai_last_started_at = 0.0
        self._ai_last_state_key = ""

        # 报警引擎（阈值可被传感器页热更新）
        self.alarm_engine = AlarmEngine()
        self.presence_threshold = PRESENCE_THRESHOLD
        self.gas_threshold = GAS_THRESHOLD_RAW
        self.afh_enabled = DEFAULT_AFH_ENABLED
        self.mesh_enabled = DEFAULT_MESH_ENABLED
        self.last_sync_at: float | None = None

        # 节点由 Gateway 串口帧自动发现；无真实数据时保持空状态。
        self.nodes: dict[int, NodeState] = {}

        # LoRa 节点矩阵由 Gateway 串口帧自动发现；未收到真实数据前保持空表。
        self.matrix: dict[int, MatrixNodeState] = {}

        self._thread: QThread | None = None
        self._worker: SerialWorker | None = None
        self._serial_connected = False
        self._serial_auto_connected = False
        self._serial_started_at = 0.0
        self._last_serial_sample_at = 0.0
        self._dirty = True
        self._active_node = 0
        self._paused = False
        self._matrix_filter = "ALL"
        self._diagnostics_report = ""
        self._presence_flags: dict[int, bool] = {}
        self._breath_lock_flags: dict[int, bool] = {}
        self._offline_flags: dict[int, bool] = {}
        self._gas_alert_flags: dict[int, bool] = {}

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_REFRESH_MS)
        self._ui_timer.timeout.connect(self._publish_snapshot)

        self._offline_timer = QTimer(self)
        self._offline_timer.setInterval(1000)
        self._offline_timer.timeout.connect(self._check_offline_nodes)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_PORT_REFRESH_MS)
        self._auto_timer.timeout.connect(self._auto_service)

        self._ai_timer = QTimer(self)
        self._ai_timer.setInterval(1000)
        self._ai_timer.timeout.connect(self._maybe_schedule_ai_analysis)

        self._ai_analysis_ready.connect(self._handle_ai_analysis_ready)
        self._ai_operation_ready.connect(self._handle_ai_operation_ready)
        self._ai_operation_result_ready.connect(self._handle_ai_operation_result_ready)
        self._ai_models_ready.connect(self._handle_ai_models_ready)

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        """启动数据服务：刷新串口列表并自动探测真实 Gateway。"""

        self._ui_timer.start()
        self._offline_timer.start()
        self._ai_timer.start()
        self.refresh_ports()
        self._auto_timer.start()
        self._auto_service()

    def shutdown(self) -> None:
        """程序退出时释放串口线程与定时器。"""

        self._ui_timer.stop()
        self._offline_timer.stop()
        self._auto_timer.stop()
        self._ai_timer.stop()
        self.stop_serial()
        self.ai_runtime.stop()

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

    @pyqtSlot(object)
    def save_ai_config(self, payload: object) -> None:
        """保存 AI 设置到本机用户配置。"""

        if not isinstance(payload, dict):
            self.ai_operation_message_changed.emit("AI 设置格式无效", False)
            return
        try:
            path = self._apply_ai_settings(payload)
        except Exception as exc:  # noqa: BLE001
            self.ai_operation_message_changed.emit(f"AI 设置保存失败：{exc}", False)
            return
        self.ai_state["enabled"] = self.ai_settings.enabled
        self.ai_state["config"] = asdict(self.ai_settings)
        self.ai_state["status"] = "AI 设置已保存"
        self._ai_last_state_key = ""
        self.ai_operation_message_changed.emit(f"AI 设置已保存：{path}", True)
        self._append_event("AI CONFIG SAVED", "AI 辅助研判设置已保存", level="OK", kind="ai")
        self._dirty = True

    @pyqtSlot(object)
    def handle_ai_action(self, payload: object) -> None:
        """统一处理 AI 设置弹窗动作，动作直接携带当前表单配置。"""

        if not isinstance(payload, dict):
            self._ai_operation_result_ready.emit(
                {"action": "unknown", "ok": False, "message": "AI 操作格式无效"}
            )
            return
        action = str(payload.get("action") or "").strip()
        config = payload.get("config")
        if isinstance(config, dict):
            try:
                self._apply_ai_settings(config)
            except Exception as exc:  # noqa: BLE001
                self._ai_operation_result_ready.emit(
                    {"action": action, "ok": False, "message": f"AI 设置保存失败：{exc}"}
                )
                return

        if action == "save":
            self._ai_operation_result_ready.emit(
                {"action": action, "ok": True, "message": "AI 设置已保存", "config": asdict(self.ai_settings)}
            )
            return
        if action == "stop_jina":
            try:
                message = self.ai_runtime.stop()
            except Exception as exc:  # noqa: BLE001
                self._ai_operation_result_ready.emit({"action": action, "ok": False, "message": str(exc)})
                return
            self._ai_operation_result_ready.emit({"action": action, "ok": True, "message": message})
            return

        settings = self.ai_settings.copy()
        package_path = str(payload.get("package_path") or "").strip()

        def emit_progress(progress: dict[str, Any]) -> None:
            progress_message = str(progress.get("message") or "AI 操作执行中...")
            progress_payload = {
                "action": action,
                "ok": True,
                "running": True,
                "message": progress_message,
            }
            progress_payload.update(progress)
            self._ai_operation_result_ready.emit(progress_payload)

        def worker() -> dict[str, Any]:
            if action == "check_jina_deployment":
                status = jina_deployment_status(settings)
                return {
                    "action": action,
                    "ok": True,
                    "message": status["message"],
                    "deployed": status["deployed"],
                    "port_open": status.get("port_open", False),
                    "server_path": status["server_path"],
                    "model_path": status["model_path"],
                    "endpoint": status["endpoint"],
                    "provider": "local_jina",
                    "real_request": False,
                }
            if action == "deploy_jina_package":
                status = deploy_jina_package(settings, package_path, overwrite=True)
                return {
                    "action": action,
                    "ok": True,
                    "message": status["message"],
                    "deployed": status["deployed"],
                    "port_open": status.get("port_open", False),
                    "server_path": status["server_path"],
                    "model_path": status["model_path"],
                    "endpoint": status["endpoint"],
                    "provider": "local_jina",
                    "real_request": False,
                }
            if action == "online_deploy_jina":
                status = online_deploy_jina(settings, progress=emit_progress, overwrite=False)
                return {
                    "action": action,
                    "ok": True,
                    "message": status["message"],
                    "deployed": status["deployed"],
                    "port_open": status.get("port_open", False),
                    "server_path": status["server_path"],
                    "model_path": status["model_path"],
                    "endpoint": status["endpoint"],
                    "provider": "local_jina",
                    "real_request": True,
                }
            if action == "create_jina_offline_package":
                result = create_jina_offline_package(settings, package_path)
                return {
                    "action": action,
                    "ok": True,
                    "message": result["message"],
                    "deployed": result["deployed"],
                    "package_path": result["package_path"],
                    "server_path": result["server_path"],
                    "model_path": result["model_path"],
                    "provider": "local_jina",
                    "real_request": False,
                }
            if action == "start_jina":
                start_message = self.ai_runtime.start(settings)
                ready = wait_for_embedding_ready(settings)
                endpoint = f"{settings.jina_base_url.rstrip('/')}/v1/embeddings"
                return {
                    "action": action,
                    "ok": True,
                    "message": f"{start_message}；真实请求成功：POST {endpoint} · {ready['dimension']} 维",
                    "dimension": ready["dimension"],
                    "endpoint": endpoint,
                    "provider": "local_jina",
                    "real_request": True,
                }
            if action == "start_and_test_jina":
                self.ai_runtime.start(settings)
                ready = wait_for_embedding_ready(settings)
                endpoint = f"{settings.jina_base_url.rstrip('/')}/v1/embeddings"
                return {
                    "action": action,
                    "ok": True,
                    "message": f"本地 Jina 可用：POST {endpoint} · {ready['dimension']} 维",
                    "deployed": True,
                    "dimension": ready["dimension"],
                    "endpoint": endpoint,
                    "server_path": settings.llama_server_path,
                    "model_path": settings.jina_model_path,
                    "provider": "local_jina",
                    "real_request": True,
                }
            if action == "test_embedding":
                result = test_embedding(settings)
                endpoint = f"{settings.jina_base_url.rstrip('/')}/v1/embeddings"
                return {
                    "action": action,
                    "ok": True,
                    "message": f"真实请求成功：POST {endpoint} · {result['dimension']} 维",
                    "dimension": result["dimension"],
                    "endpoint": endpoint,
                    "provider": "local_jina",
                    "real_request": True,
                }
            if action == "fetch_models":
                model_result = fetch_llm_models_result(settings)
                models = list(model_result.get("models") or [])
                model_source = str(model_result.get("model_source") or "api")
                if model_source == "preset":
                    message = str(model_result.get("message") or "已加载供应商预设模型 ID")
                else:
                    message = f"真实请求成功：GET {model_result.get('endpoint')} · 已获取 {len(models)} 个模型"
                return {
                    "action": action,
                    "ok": True,
                    "message": message,
                    "models": models,
                    "endpoint": model_result.get("endpoint"),
                    "http_status": model_result.get("http_status"),
                    "provider": model_result.get("provider"),
                    "real_request": model_result.get("real_request"),
                    "model_source": model_source,
                }
            if action == "test_llm":
                llm_result = test_llm_result(settings)
                return {
                    "action": action,
                    "ok": True,
                    "message": (
                        f"真实请求成功：POST {llm_result.get('endpoint')} · "
                        f"{llm_result.get('model')} · {llm_result.get('content')}"
                    ),
                    "endpoint": llm_result.get("endpoint"),
                    "http_status": llm_result.get("http_status"),
                    "provider": llm_result.get("provider"),
                    "real_request": True,
                }
            raise RuntimeError("未知 AI 操作")

        self._start_structured_ai_operation(action, worker)

    @pyqtSlot()
    def start_local_jina(self) -> None:
        """按当前配置启动本地 llama-server embedding 服务。"""

        try:
            message = self.ai_runtime.start(self.ai_settings)
        except Exception as exc:  # noqa: BLE001
            self.ai_state["error"] = str(exc)
            self.ai_operation_message_changed.emit(f"本地 Jina 启动失败：{exc}", False)
            self._dirty = True
            return
        self.ai_state["status"] = message
        self.ai_state["running"] = self.ai_runtime.is_running()
        self.ai_operation_message_changed.emit(message, True)
        self._append_event("JINA SERVICE START", message, level="OK", kind="ai")
        self._dirty = True

    @pyqtSlot()
    def stop_local_jina(self) -> None:
        """停止由上位机启动的本地 llama-server。"""

        try:
            message = self.ai_runtime.stop()
        except Exception as exc:  # noqa: BLE001
            self.ai_operation_message_changed.emit(f"本地 Jina 停止失败：{exc}", False)
            return
        self.ai_state["status"] = message
        self.ai_state["running"] = False
        self.ai_operation_message_changed.emit(message, True)
        self._append_event("JINA SERVICE STOP", message, level="WARN", kind="ai")
        self._dirty = True

    @pyqtSlot()
    def test_local_embedding(self) -> None:
        """异步测试本地 Jina embedding 接口。"""

        settings = self.ai_settings.copy()

        def worker() -> tuple[str, bool]:
            result = test_embedding(settings)
            return f"Embedding 测试通过：{result['dimension']} 维", True

        self._start_ai_operation(worker)

    @pyqtSlot()
    def fetch_ai_models(self) -> None:
        """异步获取 OpenAI 兼容大模型列表。"""

        settings = self.ai_settings.copy()

        def worker() -> list[str]:
            return fetch_llm_models(settings)

        def run() -> None:
            try:
                models = worker()
            except Exception as exc:  # noqa: BLE001
                self._ai_models_ready.emit([], False, str(exc))
                return
            self._ai_models_ready.emit(models, True, f"已获取 {len(models)} 个模型")

        threading.Thread(target=run, daemon=True).start()

    @pyqtSlot()
    def test_llm_api(self) -> None:
        """异步测试 OpenAI 兼容大模型接口。"""

        settings = self.ai_settings.copy()

        def worker() -> tuple[str, bool]:
            message = test_llm(settings)
            return f"大模型测试通过：{message}", True

        self._start_ai_operation(worker)

    @pyqtSlot(str)
    def set_matrix_filter(self, value: str) -> None:
        self._matrix_filter = str(value or "ALL")
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
            f"已发现节点：在线 {len(online_nodes)} / {len(self.nodes)}，离线 {len(offline_nodes)}",
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
        """传感器页有害气体原始值阈值滑条回调。"""

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
            gas_alarm_raw=max(self.gas_threshold, self.alarm_engine.gas_alarm_raw),
        )
        self._append_event(
            "CONFIG SYNCED",
            f"本地配置已同步：存在阈值 {self.presence_threshold * 100:.0f}% · 气体原始值阈值 {self.gas_threshold:.0f}",
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
        self._apply_sample(parsed)

    # ------------------------------------------------------------------ LoRa 矩阵
    def _ensure_node_state(self, node_id: int) -> NodeState | None:
        """确保真实上报的节点 ID 可以进入上位机状态表。"""

        if node_id <= 0:
            return None
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeState(
                node_id=node_id,
                label=NODE_LABELS.get(node_id, f"node{node_id}"),
                battery=None,
            )
            self._presence_flags[node_id] = False
            self._breath_lock_flags[node_id] = False
            self._offline_flags[node_id] = False
            self._gas_alert_flags[node_id] = False
        return self.nodes[node_id]

    def _ensure_matrix_node(self, node_id: int) -> MatrixNodeState | None:
        """按真实 Gateway 帧自动创建节点管理表行。"""

        if node_id <= 0:
            return None
        state = self.matrix.get(node_id)
        if state is None:
            state = MatrixNodeState(
                matrix_id=node_id,
                code=NODE_LABELS.get(node_id, f"node{node_id}"),
                mode="NORMAL",
                bound_node=node_id,
                battery=None,
            )
            self.matrix[node_id] = state
            self._append_event("NODE DISCOVERED", f"已发现节点 {state.code}", node_id=node_id, level="OK", kind="matrix")
        return state

    def _refresh_matrix_node(self, state: MatrixNodeState, now: float) -> None:
        """根据绑定的真实节点刷新一行矩阵状态。"""

        if state.bound_node is not None and state.bound_node in self.nodes:
            src = self.nodes[state.bound_node]
            state.online = src.online and state.mode != "SLEEP"
            state.rssi = src.rssi
            state.last_received = src.last_received
        else:
            state.online = False
        state.health = self._derive_health(state)

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
        node = self._ensure_node_state(node_id)
        matrix_state = self._ensure_matrix_node(node_id)
        if node is None:
            return

        now = float(sample.get("timestamp") or time.time())
        was_online = node.online
        label = str(sample.get("node_label") or "").strip()
        if label:
            node.label = label
            if matrix_state is not None:
                matrix_state.code = label

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
        if matrix_state is not None:
            self._refresh_matrix_node(matrix_state, now)

        enriched = dict(sample)
        enriched.update(
            {
                "timestamp": now,
                "node_id": node_id,
                "node_code": node.label,
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

        if self._active_node <= 0 or self._active_node not in self.nodes:
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
                f"{self._node_label(alarm_node)} {alarm.get('message', '规则报警')}",
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
                if last is None:
                    continue
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

            discovered_nodes = {
                node_id: state
                for node_id, state in self._node_dicts().items()
                if state.get("last_received") is not None
            }
            for alarm in self.alarm_engine.evaluate(None, discovered_nodes, now):
                alarm_node = int(alarm.get("node_id") or 0)
                self._append_event(
                    str(alarm.get("title", "节点离线")),
                    f"{self._node_label(alarm_node)} {alarm.get('message', '节点离线')}",
                    node_id=alarm_node,
                    level=str(alarm.get("level", "ALARM")),
                    kind=str(alarm.get("kind", "offline")),
                    event_time=float(alarm.get("time", now)),
                )

        # 中文注释：矩阵行根据绑定的真实节点刷新在线状态与健康度；未绑定的行保持离线。
        for state in self.matrix.values():
            self._refresh_matrix_node(state, now)

        self._auto_service()

    # ------------------------------------------------------------------ AI 辅助研判
    def _apply_ai_settings(self, payload: dict[str, Any]) -> object:
        self.ai_settings = settings_from_dict(payload)
        path = save_ai_settings(self.ai_settings)
        self.ai_state["enabled"] = self.ai_settings.enabled
        self.ai_state["config"] = asdict(self.ai_settings)
        self._ai_last_state_key = ""
        self._dirty = True
        return path

    def _start_structured_ai_operation(self, action: str, worker: object) -> None:
        self.ai_operation_message_changed.emit("AI 操作执行中...", True)
        self._ai_operation_result_ready.emit(
            {"action": action, "ok": True, "running": True, "message": "AI 操作执行中..."}
        )

        def run() -> None:
            try:
                result = worker()  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                self._ai_operation_result_ready.emit(
                    {"action": action, "ok": False, "running": False, "message": str(exc)}
                )
                return
            if isinstance(result, dict):
                result.setdefault("action", action)
                result.setdefault("running", False)
                self._ai_operation_result_ready.emit(result)
            else:
                self._ai_operation_result_ready.emit(
                    {"action": action, "ok": True, "running": False, "message": str(result)}
                )

        threading.Thread(target=run, daemon=True).start()

    def _start_ai_operation(self, worker: object) -> None:
        """在后台线程执行 AI 测试 / 获取模型等短任务。"""

        self.ai_operation_message_changed.emit("AI 操作执行中...", True)

        def run() -> None:
            try:
                message, ok = worker()  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                self._ai_operation_ready.emit(str(exc), False)
                return
            self._ai_operation_ready.emit(str(message), bool(ok))

        threading.Thread(target=run, daemon=True).start()

    def _maybe_schedule_ai_analysis(self) -> None:
        """低频异步生成 AI 辅助解释；实时主判断仍由规则融合负责。"""

        summary = build_detection_summary(self._node_dicts(), self.history)
        self._refresh_ai_fallback(summary)
        if not self.ai_settings.enabled or not self.ai_settings.embedding_enabled:
            return
        if not summary.participant_ids:
            return
        if self._ai_busy:
            return

        now = time.time()
        if now - self._ai_last_started_at < 3.0:
            return
        if summary.state_key == self._ai_last_state_key and now - _float(self.ai_state.get("updated_at")) < 8.0:
            return

        self._ai_busy = True
        self._ai_request_id += 1
        request_id = self._ai_request_id
        self._ai_last_started_at = now
        self._ai_last_state_key = summary.state_key
        self.ai_state.update(
            {
                "running": True,
                "status": "AI 分析中",
                "text": "AI辅助研判：分析中... 规则结论已实时刷新",
                "state_key": summary.state_key,
                "window_start": summary.window_start,
                "window_end": summary.window_end,
                "config": asdict(self.ai_settings),
            }
        )
        self._dirty = True
        settings = self.ai_settings.copy()

        def run() -> None:
            result = run_ai_judgement(settings, summary)
            self._ai_analysis_ready.emit(request_id, result)

        threading.Thread(target=run, daemon=True).start()

    @pyqtSlot(int, object)
    def _handle_ai_analysis_ready(self, request_id: int, result: object) -> None:
        self._ai_busy = False
        if request_id != self._ai_request_id or not isinstance(result, dict):
            return

        current_summary = build_detection_summary(self._node_dicts(), self.history)
        if str(result.get("state_key", "")) != current_summary.state_key:
            self.ai_state.update(
                {
                    "running": False,
                    "status": "上一轮 AI 结果已过期，等待更新",
                    "text": ai_fallback_text(current_summary.status),
                    "source": "rule_fallback",
                    "window_start": current_summary.window_start,
                    "window_end": current_summary.window_end,
                    "updated_at": time.time(),
                    "top_matches": [],
                    "error": "",
                    "state_key": current_summary.state_key,
                    "config": asdict(self.ai_settings),
                }
            )
        else:
            result["running"] = False
            result["config"] = asdict(self.ai_settings)
            result["jina_running"] = self.ai_runtime.is_running()
            self.ai_state.update(result)

        self._dirty = True

    @pyqtSlot(str, bool)
    def _handle_ai_operation_ready(self, message: str, ok: bool) -> None:
        self.ai_operation_message_changed.emit(message, ok)
        self.ai_state["status"] = message
        self.ai_state["error"] = "" if ok else message
        self.ai_state["config"] = asdict(self.ai_settings)
        self._dirty = True

    @pyqtSlot(object)
    def _handle_ai_operation_result_ready(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        ok = bool(result.get("ok", False))
        message = str(result.get("message") or "")
        action = str(result.get("action") or "")
        running = bool(result.get("running", False))
        if ok and action in {"deploy_jina_package", "online_deploy_jina"}:
            server_path = str(result.get("server_path") or "")
            model_path = str(result.get("model_path") or "")
            if server_path:
                self.ai_settings.llama_server_path = server_path
            if model_path:
                self.ai_settings.jina_model_path = model_path
            save_ai_settings(self.ai_settings)
            result["config"] = asdict(self.ai_settings)
        self.ai_operation_result_changed.emit(result)
        self.ai_operation_message_changed.emit(message, ok)
        if "models" in result:
            self.ai_models_changed.emit(result.get("models") or [])
        self.ai_state["running"] = running
        self.ai_state["status"] = message
        self.ai_state["error"] = "" if ok else message
        self.ai_state["jina_running"] = self.ai_runtime.is_running()
        self.ai_state["config"] = asdict(self.ai_settings)
        if action == "stop_jina":
            self.ai_state["jina_running"] = False
        if ok and action in {"test_embedding", "start_jina", "start_and_test_jina"}:
            self.ai_state["source"] = "local_jina"
        self._dirty = True

    @pyqtSlot(object, bool, str)
    def _handle_ai_models_ready(self, models: object, ok: bool, message: str) -> None:
        self.ai_models_changed.emit(models if ok else [])
        self.ai_operation_message_changed.emit(message if ok else f"获取模型失败：{message}", ok)
        self.ai_state["status"] = message if ok else "获取模型失败"
        self.ai_state["error"] = "" if ok else message
        self._dirty = True

    def _refresh_ai_fallback(self, summary: object) -> None:
        if not hasattr(summary, "state_key"):
            return
        current_key = str(summary.state_key)
        if self._ai_busy and self.ai_state.get("state_key") == current_key:
            return
        if self.ai_state.get("source") != "rule_fallback" and self.ai_state.get("state_key") == current_key:
            return
        self.ai_state.update(
            {
                "enabled": self.ai_settings.enabled,
                "running": False,
                "status": "规则回退" if self.ai_settings.enabled else "AI 未启用，使用规则回退",
                "text": ai_fallback_text(summary.status),
                "source": "rule_fallback",
                "window_start": summary.window_start,
                "window_end": summary.window_end,
                "updated_at": _float(self.ai_state.get("updated_at")),
                "top_matches": [],
                "error": "",
                "state_key": current_key,
                "jina_running": self.ai_runtime.is_running(),
                "config": asdict(self.ai_settings),
            }
        )

    # ------------------------------------------------------------------ 快照
    def _publish_snapshot(self) -> None:
        if not self._dirty:
            return

        self._dirty = False
        summary = build_detection_summary(self._node_dicts(), self.history)
        self._refresh_ai_fallback(summary)
        self.ai_state["running"] = self._ai_busy
        self.ai_state["jina_running"] = self.ai_runtime.is_running()
        self.ai_state["config"] = asdict(self.ai_settings)
        self.snapshot_changed.emit(
            {
                "nodes": self._node_dicts(),
                "matrix": [state.to_dict() for state in self.matrix.values()],
                "history": list(self.history),
                "events": [event.to_dict() for event in self.events],
                "ai": dict(self.ai_state),
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

    def _node_label(self, node_id: int) -> str:
        node = self.nodes.get(node_id)
        if node is not None and node.label:
            return node.label
        return NODE_LABELS.get(node_id, f"node{node_id}")


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
