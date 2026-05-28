"""WiFi CSI + LoRa 救援感知上位机入口。"""

from __future__ import annotations

import queue
from typing import Any

import dearpygui.dearpygui as dpg

try:
    from data_parser import parse_gateway_frame
    from serial_handler import SerialReader
except ImportError:
    # 中文注释：兼容从仓库根目录以模块方式导入 upper_computer.main 的场景。
    from upper_computer.data_parser import parse_gateway_frame
    from upper_computer.serial_handler import SerialReader


class RescueConsoleApp:
    """中文注释：封装 Dear PyGui 界面状态，便于后续扩展可视化、规则和 AI 模块。"""

    def __init__(self) -> None:
        self.reader = SerialReader()
        self.frames: "queue.Queue[str]" = queue.Queue()
        self.rows = 0

    def run(self) -> None:
        dpg.create_context()
        dpg.create_viewport(title="WiFi CSI LoRa Rescue Console", width=980, height=640)
        self._build_ui()
        dpg.setup_dearpygui()
        dpg.show_viewport()

        while dpg.is_dearpygui_running():
            self._drain_serial_frames()
            dpg.render_dearpygui_frame()

        self.reader.stop()
        dpg.destroy_context()

    def _build_ui(self) -> None:
        with dpg.window(label="救援感知上位机", tag="main_window", width=960, height=600):
            dpg.add_text("WiFi CSI + LoRa 应急救援感知系统")

            with dpg.group(horizontal=True):
                dpg.add_input_text(label="串口", tag="port_input", default_value="COM3", width=160)
                dpg.add_input_int(label="波特率", tag="baud_input", default_value=115200, width=120)
                dpg.add_button(label="连接", callback=self._connect_serial)
                dpg.add_button(label="断开", callback=self._disconnect_serial)
                dpg.add_button(label="解析示例帧", callback=self._append_sample_frame)

            dpg.add_separator()
            dpg.add_text("串口状态：未连接", tag="status_text")
            dpg.add_text("最新帧：-", tag="latest_frame")

            with dpg.table(
                header_row=True,
                resizable=True,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True,
                tag="frame_table",
            ):
                for title in ("序号", "类型", "节点", "有效", "字段", "原始数据"):
                    dpg.add_table_column(label=title)

    def _connect_serial(self) -> None:
        port = dpg.get_value("port_input")
        baudrate = int(dpg.get_value("baud_input"))
        try:
            self.reader.start(port=port, baudrate=baudrate, on_line=self.frames.put)
        except Exception as exc:  # noqa: BLE001 - 中文注释：界面层需要展示串口打开失败原因。
            dpg.set_value("status_text", f"串口状态：连接失败 - {exc}")
            return

        dpg.set_value("status_text", f"串口状态：已连接 {port} @ {baudrate}")

    def _disconnect_serial(self) -> None:
        self.reader.stop()
        dpg.set_value("status_text", "串口状态：已断开")

    def _append_sample_frame(self) -> None:
        self.frames.put("NODE,1,CSI,0,RSSI,-55,TEMP,25.3,HUM,60.1")

    def _drain_serial_frames(self) -> None:
        while True:
            try:
                raw_frame = self.frames.get_nowait()
            except queue.Empty:
                break

            parsed = parse_gateway_frame(raw_frame)
            self._append_table_row(parsed)

    def _append_table_row(self, parsed: dict[str, Any]) -> None:
        self.rows += 1
        fields_text = ", ".join(f"{key}={value}" for key, value in parsed["fields"].items())
        dpg.set_value("latest_frame", f"最新帧：{parsed['raw']}")

        with dpg.table_row(parent="frame_table"):
            dpg.add_text(str(self.rows))
            dpg.add_text(str(parsed["type"]))
            dpg.add_text(str(parsed["node_id"]))
            dpg.add_text("是" if parsed["valid"] else "否")
            dpg.add_text(fields_text)
            dpg.add_text(parsed["raw"])


def main() -> None:
    app = RescueConsoleApp()
    app.run()


if __name__ == "__main__":
    main()
