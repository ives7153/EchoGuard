"""RuView-Rescue Dear PyGui 上位机主入口。"""

from __future__ import annotations

import math
import queue
import random
import time
from typing import Any

import dearpygui.dearpygui as dpg

try:
    from data_parser import parse_gateway_frame
    from rules import evaluate_sample
    from serial_handler import SerialReader
    from utils import export_samples_to_csv, take_screenshot
    from viz import RescueDashboard
    from viz.dashboard import WINDOW_TITLE
except ImportError:
    # 兼容从仓库根目录以 `python -m upper_computer.main` 启动。
    from upper_computer.data_parser import parse_gateway_frame
    from upper_computer.rules import evaluate_sample
    from upper_computer.serial_handler import SerialReader
    from upper_computer.utils import export_samples_to_csv, take_screenshot
    from upper_computer.viz import RescueDashboard
    from upper_computer.viz.dashboard import WINDOW_TITLE


BAUDRATE = 115200
NODE_IDS = (1, 2, 3, 4)
MAX_HISTORY_ROWS = 5000


class RescueConsoleApp:
    """上位机应用状态协调层。"""

    def __init__(self) -> None:
        self.reader = SerialReader()
        self.frames: "queue.Queue[str]" = queue.Queue()
        self.serial_errors: "queue.Queue[str]" = queue.Queue()
        self.dashboard = RescueDashboard(
            on_refresh_ports=self._refresh_ports,
            on_connect=self._connect_selected_port,
            on_disconnect=self._disconnect_serial,
            on_export_csv=self._export_csv,
            on_screenshot=self._take_screenshot,
        )

        self.started_at = time.time()
        self.last_port_refresh_at = 0.0
        self.last_connect_attempt_at = 0.0
        self.last_demo_sample_at = 0.0
        self.last_offline_check_at = 0.0
        self.last_ui_update_at = 0.0
        self.auto_reconnect = True
        self.available_ports: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.alarms: list[dict[str, Any]] = []
        self.node_states = self._initial_node_states()

    def run(self) -> None:
        dpg.create_context()
        dpg.create_viewport(title=WINDOW_TITLE, width=1320, height=820, min_width=1100, min_height=720)
        self.dashboard.build()
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._refresh_ports()
        self.dashboard.set_status("串口状态：正在自动探测 Gateway...", ok=True)

        while dpg.is_dearpygui_running():
            now = time.time()
            self._service_serial(now)
            self._drain_serial_frames()
            self._generate_demo_data_if_needed(now)
            self._check_offline_rules(now)
            self._update_node_online_state(now)
            self._update_ui(now)
            dpg.render_dearpygui_frame()

        self.reader.stop()
        dpg.destroy_context()

    def _initial_node_states(self) -> dict[int, dict[str, Any]]:
        return {
            node_id: {
                "node_id": node_id,
                "online": False,
                "rssi": 0.0,
                "battery": 93.0 - node_id,
                "last_received": None,
                "created_at": self.started_at,
                "presence_score": 0.0,
                "motion_score": 0.0,
                "breath_bpm": 0.0,
                "confidence": 0.0,
                "gas": 0.0,
            }
            for node_id in NODE_IDS
        }

    def _service_serial(self, now: float) -> None:
        if now - self.last_port_refresh_at > 3.0:
            self._refresh_ports()

        while True:
            try:
                error = self.serial_errors.get_nowait()
            except queue.Empty:
                break
            self.dashboard.set_status(f"串口状态：连接异常，进入离线演示 - {error}", ok=False)
            self.reader.stop()

        if self.reader.is_running and not self.reader.is_alive:
            message = self.reader.last_error or "读取线程已停止"
            self.reader.stop()
            self.dashboard.set_status(f"串口状态：已断开，进入离线演示 - {message}", ok=False)

        if self.reader.is_running or not self.auto_reconnect:
            return

        if now - self.last_connect_attempt_at < 2.0:
            return

        self.last_connect_attempt_at = now
        port = self._probe_gateway_port()
        if not port:
            self.dashboard.set_status("串口状态：未发现有效 Gateway，离线演示中", ok=False)
            return

        self._start_reader(port, auto=True)

    def _refresh_ports(self) -> None:
        self.last_port_refresh_at = time.time()
        try:
            import serial.tools.list_ports as list_ports

            self.available_ports = [port.device for port in list_ports.comports()]
        except Exception:  # noqa: BLE001 - pyserial 缺失或系统串口查询异常时仍要可演示。
            self.available_ports = []

        selected = self.reader.port if self.reader.is_running else None
        self.dashboard.set_ports(self.available_ports, selected=selected)

    def _probe_gateway_port(self) -> str | None:
        if not self.available_ports:
            return None

        try:
            import serial
        except Exception:
            return None

        for port in self.available_ports:
            try:
                with serial.Serial(port=port, baudrate=BAUDRATE, timeout=0.12) as probe:
                    deadline = time.time() + 0.9
                    while time.time() < deadline:
                        raw = probe.readline()
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="replace").strip()
                        parsed = parse_gateway_frame(line)
                        if parsed["valid"]:
                            return port
            except Exception:
                continue
        return None

    def _connect_selected_port(self) -> None:
        port = self.dashboard.selected_port()
        if not port:
            self.dashboard.set_status("串口状态：没有可连接的串口", ok=False)
            return

        self.auto_reconnect = True
        self.reader.stop()
        self._start_reader(port, auto=False)

    def _start_reader(self, port: str, auto: bool) -> None:
        try:
            self.reader.start(
                port=port,
                baudrate=BAUDRATE,
                on_line=self.frames.put,
                on_error=self.serial_errors.put,
            )
        except Exception as exc:  # noqa: BLE001 - 串口占用、权限或拔插异常都要展示给用户。
            prefix = "自动连接失败" if auto else "连接失败"
            self.dashboard.set_status(f"串口状态：{prefix} {port} - {exc}", ok=False)
            return

        mode = "自动连接" if auto else "手动连接"
        self.dashboard.set_status(f"串口状态：{mode} {port} @ {BAUDRATE}", ok=True)
        self.dashboard.set_ports(self.available_ports, selected=port)

    def _disconnect_serial(self) -> None:
        self.auto_reconnect = False
        self.reader.stop()
        self.dashboard.set_status("串口状态：已手动断开，离线演示中", ok=False)

    def _drain_serial_frames(self) -> None:
        processed = 0
        while processed < 200:
            try:
                raw_frame = self.frames.get_nowait()
            except queue.Empty:
                break

            processed += 1
            parsed = parse_gateway_frame(raw_frame)
            if not parsed["valid"]:
                self.dashboard.set_latest_frame(f"最新帧：忽略非 JSON 数据 - {raw_frame[:120]}")
                continue

            parsed["timestamp"] = time.time()
            parsed["source"] = "serial"
            self._apply_sample(parsed)
            self.dashboard.set_latest_frame(f"最新帧：{parsed['raw']}")

    def _generate_demo_data_if_needed(self, now: float) -> None:
        if self.reader.is_running:
            return
        if now - self.last_demo_sample_at < 0.5:
            return

        self.last_demo_sample_at = now
        elapsed = now - self.started_at
        for node_id in NODE_IDS:
            sample = self._demo_sample(node_id, elapsed, now)
            self._apply_sample(sample)
        self.dashboard.set_latest_frame("最新帧：离线演示数据流")

    def _demo_sample(self, node_id: int, elapsed: float, now: float) -> dict[str, Any]:
        phase = elapsed * 0.85 + node_id * 0.9
        wave = (math.sin(phase) + 1.0) / 2.0
        life_pulse = 0.42 if node_id == 2 and 6.0 < elapsed % 18.0 < 13.5 else 0.0
        presence = min(0.18 + wave * 0.28 + life_pulse, 0.95)
        motion = min(0.15 + ((math.sin(phase * 1.7) + 1.0) / 2.0) * 0.35, 0.9)
        confidence = min(0.62 + presence * 0.35, 0.96)
        breath_bpm = 0.0 if presence < 0.42 else 14.0 + wave * 10.0
        gas = 610.0 + wave * 45.0 if node_id == 4 and elapsed % 24.0 > 14.0 else 360.0 + node_id * 32.0 + wave * 35.0
        rssi = -50.0 - node_id * 4.0 - random.random() * 5.0

        return {
            "valid": True,
            "raw": "offline-demo",
            "node_id": node_id,
            "seq": None,
            "presence_score": presence,
            "motion_score": motion,
            "breath_bpm": breath_bpm,
            "confidence": confidence,
            "gas": gas,
            "temperature": 25.0 + wave * 2.0,
            "humidity": 48.0 + wave * 8.0,
            "rssi": rssi,
            "timestamp": now,
            "source": "demo",
        }

    def _apply_sample(self, sample: dict[str, Any]) -> None:
        node_id = int(sample.get("node_id") or 0)
        if node_id not in self.node_states:
            return

        state = self.node_states[node_id]
        state.update(
            {
                "online": True,
                "rssi": float(sample.get("rssi") or 0.0),
                "last_received": float(sample["timestamp"]),
                "presence_score": float(sample.get("presence_score") or 0.0),
                "motion_score": float(sample.get("motion_score") or 0.0),
                "breath_bpm": float(sample.get("breath_bpm") or 0.0),
                "confidence": float(sample.get("confidence") or 0.0),
                "gas": float(sample.get("gas") or 0.0),
            }
        )

        self.history.append(sample)
        if len(self.history) > MAX_HISTORY_ROWS:
            del self.history[: len(self.history) - MAX_HISTORY_ROWS]

        self._append_alarms(evaluate_sample(sample, self.node_states, float(sample["timestamp"])))

    def _check_offline_rules(self, now: float) -> None:
        if now - self.last_offline_check_at < 1.0:
            return
        self.last_offline_check_at = now
        self._append_alarms(evaluate_sample(None, self.node_states, now))

    def _append_alarms(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        self.alarms.extend(events)
        if len(self.alarms) > 200:
            del self.alarms[: len(self.alarms) - 200]

    def _update_node_online_state(self, now: float) -> None:
        for state in self.node_states.values():
            last_received = state.get("last_received")
            state["online"] = bool(last_received is not None and now - float(last_received) <= 8.0)

    def _update_ui(self, now: float) -> None:
        if now - self.last_ui_update_at < 0.05:
            return
        self.last_ui_update_at = now
        countdown = 30 - int((now - self.started_at) % 31)
        self.dashboard.update(self.node_states, self.history, self.alarms, countdown)

    def _export_csv(self) -> None:
        try:
            path = export_samples_to_csv(self.history)
        except Exception as exc:  # noqa: BLE001 - 导出失败要落在界面上。
            self.dashboard.set_export_message(f"CSV 导出失败：{exc}", ok=False)
            return
        self.dashboard.set_export_message(f"CSV 已导出：{path.name}", ok=True)

    def _take_screenshot(self) -> None:
        try:
            path = take_screenshot()
        except Exception as exc:  # noqa: BLE001 - 截图失败要落在界面上。
            self.dashboard.set_export_message(f"截图失败：{exc}", ok=False)
            return
        self.dashboard.set_export_message(f"截图已保存：{path.name}", ok=True)


def main() -> None:
    app = RescueConsoleApp()
    app.run()


if __name__ == "__main__":
    main()
