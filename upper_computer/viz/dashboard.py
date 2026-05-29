"""RuView-Rescue Dear PyGui 仪表盘。

中文注释：本文件只负责界面创建和刷新，串口、规则、导出等业务逻辑由
main.py 协调，保持竞赛演示界面足够清晰、稳定、易维护。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import dearpygui.dearpygui as dpg


WINDOW_TITLE = "RuView-Rescue - ESP32-S3 WiFi-CSI LoRa 救援感知系统"


class RescueDashboard:
    """封装上位机所有 Dear PyGui 组件和更新逻辑。"""

    def __init__(
        self,
        on_refresh_ports: Callable[[], None],
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
        on_export_csv: Callable[[], None],
        on_screenshot: Callable[[], None],
    ) -> None:
        self.on_refresh_ports = on_refresh_ports
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_export_csv = on_export_csv
        self.on_screenshot = on_screenshot
        self._font_regular: int | str | None = None
        self._font_big: int | str | None = None
        self._font_huge: int | str | None = None
        self._themes: dict[str, int | str] = {}
        self._last_alarm_count = 0

    def build(self) -> None:
        self._load_fonts()
        self._build_themes()

        with dpg.window(label=WINDOW_TITLE, tag="main_window", no_close=True):
            self._build_header()
            dpg.add_separator()
            with dpg.group(horizontal=True):
                self._build_left_panel()
                self._build_center_panel()
                self._build_right_panel()
            dpg.add_separator()
            self._build_alarm_panel()
            dpg.add_separator()
            self._build_bottom_status_bar()

        dpg.set_primary_window("main_window", True)

    def set_status(self, text: str, ok: bool = True) -> None:
        dpg.set_value("serial_status_text", text)
        dpg.configure_item("serial_status_text", color=(92, 230, 155) if ok else (255, 112, 112))
        dpg.set_value("bottom_status_text", text)
        dpg.configure_item("bottom_status_text", color=(92, 230, 155) if ok else (255, 112, 112))

    def set_ports(self, ports: list[str], selected: str | None = None) -> None:
        values = ports or ["无可用串口"]
        dpg.configure_item("port_combo", items=values)
        if selected and selected in values:
            dpg.set_value("port_combo", selected)
        elif values:
            dpg.set_value("port_combo", values[0])

    def selected_port(self) -> str:
        value = dpg.get_value("port_combo")
        return "" if value == "无可用串口" else str(value)

    def set_latest_frame(self, text: str) -> None:
        dpg.set_value("latest_frame_text", text)
        dpg.set_value("bottom_latest_frame_text", text)

    def set_export_message(self, text: str, ok: bool = True) -> None:
        dpg.set_value("export_message_text", text)
        dpg.configure_item("export_message_text", color=(200, 220, 255) if ok else (255, 112, 112))

    def update(
        self,
        node_states: dict[int, dict[str, Any]],
        history: list[dict[str, Any]],
        alarms: list[dict[str, Any]],
        countdown_seconds: int,
    ) -> None:
        self._update_node_cards(node_states)
        self._update_plot(history)
        self._update_heatmap(node_states)
        self._update_countdown(countdown_seconds)
        self._update_alarm_log(alarms)

    def _load_fonts(self) -> None:
        candidates = [
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        ]
        font_path = next((path for path in candidates if path.exists()), None)
        if not font_path:
            return

        with dpg.font_registry():
            self._font_regular = dpg.add_font(str(font_path), 20)
            self._font_big = dpg.add_font(str(font_path), 30)
            self._font_huge = dpg.add_font(str(font_path), 58)
        dpg.bind_font(self._font_regular)

    def _build_themes(self) -> None:
        line_colors = {
            "motion": (255, 72, 72),
            "presence": (87, 214, 116),
            "breath": (82, 155, 255),
            "gas": (255, 166, 66),
        }
        for name, color in line_colors.items():
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvLineSeries):
                    dpg.add_theme_color(dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 3.0, category=dpg.mvThemeCat_Plots)
            self._themes[name] = theme

    def _build_header(self) -> None:
        # 中文注释：顶部只放操作控件，底部再重复展示运行状态，便于投影时远距离观察。
        with dpg.group(horizontal=True):
            dpg.add_text("RuView-Rescue 救援感知上位机", tag="title_text")
            if self._font_big:
                dpg.bind_item_font("title_text", self._font_big)
            dpg.add_spacer(width=24)
            dpg.add_combo([], label="串口", tag="port_combo", width=180)
            dpg.add_button(label="刷新", callback=lambda: self.on_refresh_ports(), width=72)
            dpg.add_button(label="连接", callback=lambda: self.on_connect(), width=72)
            dpg.add_button(label="断开", callback=lambda: self.on_disconnect(), width=72)
            dpg.add_text("串口状态：初始化中", tag="serial_status_text")
        dpg.add_text("最新帧：-", tag="latest_frame_text", wrap=1260)

    def _build_left_panel(self) -> None:
        # 中文注释：4 个节点固定展示，现场演示时不会因为离线节点消失导致布局跳动。
        with dpg.child_window(label="节点状态", width=270, height=500, border=True):
            dpg.add_text("节点状态")
            if self._font_big:
                dpg.bind_item_font(dpg.last_item(), self._font_big)
            for node_id in range(1, 5):
                with dpg.child_window(tag=f"node_card_{node_id}", height=104, border=True):
                    dpg.add_text(f"Node {node_id}", tag=f"node_title_{node_id}")
                    dpg.add_text("离线", tag=f"node_online_{node_id}", color=(255, 112, 112))
                    dpg.add_text("RSSI: - dBm", tag=f"node_rssi_{node_id}")
                    dpg.add_text("电池: - %", tag=f"node_battery_{node_id}")
                    dpg.add_text("最后收到: -", tag=f"node_last_{node_id}")

    def _build_center_panel(self) -> None:
        # 中文注释：所有曲线共用 60 秒相对时间轴，bpm/gas 做归一化后用于趋势比较。
        with dpg.child_window(label="实时曲线", width=690, height=500, border=True):
            dpg.add_text("60 秒滚动趋势")
            if self._font_big:
                dpg.bind_item_font(dpg.last_item(), self._font_big)
            with dpg.plot(label="", height=405, width=-1):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="最近 60 秒", tag="trend_x_axis")
                dpg.add_plot_axis(dpg.mvYAxis, label="归一化趋势", tag="trend_y_axis")
                dpg.set_axis_limits("trend_x_axis", -60, 0)
                dpg.set_axis_limits("trend_y_axis", 0, 1.2)
                dpg.add_line_series([], [], label="motion_score", parent="trend_y_axis", tag="series_motion")
                dpg.add_line_series([], [], label="presence_score", parent="trend_y_axis", tag="series_presence")
                dpg.add_line_series([], [], label="breath_bpm / 40", parent="trend_y_axis", tag="series_breath")
                dpg.add_line_series([], [], label="gas / 1000", parent="trend_y_axis", tag="series_gas")
            for tag, theme_name in (
                ("series_motion", "motion"),
                ("series_presence", "presence"),
                ("series_breath", "breath"),
                ("series_gas", "gas"),
            ):
                dpg.bind_item_theme(tag, self._themes[theme_name])
            dpg.add_text("最新值：-", tag="latest_values_text")

    def _build_right_panel(self) -> None:
        # 中文注释：热力图按 Node1~4 的 2x2 部署位展示，颜色强度仅随 presence_score 变化。
        with dpg.child_window(label="部署态势", width=300, height=500, border=True):
            dpg.add_text("部署倒计时")
            if self._font_big:
                dpg.bind_item_font(dpg.last_item(), self._font_big)
            dpg.add_text("30", tag="countdown_text", color=(255, 218, 100))
            if self._font_huge:
                dpg.bind_item_font("countdown_text", self._font_huge)
            dpg.add_separator()
            dpg.add_text("节点热力图")
            with dpg.plot(label="", height=245, width=-1):
                dpg.add_plot_axis(dpg.mvXAxis, label="", tag="heat_x_axis", no_tick_labels=True)
                dpg.add_plot_axis(dpg.mvYAxis, label="", tag="heat_y_axis", no_tick_labels=True)
                dpg.set_axis_limits("heat_x_axis", 0, 2)
                dpg.set_axis_limits("heat_y_axis", 0, 2)
                dpg.add_heat_series(
                    [0.0, 0.0, 0.0, 0.0],
                    2,
                    2,
                    parent="heat_y_axis",
                    tag="node_heat_series",
                    scale_min=0.0,
                    scale_max=1.0,
                    bounds_min=(0, 0),
                    bounds_max=(2, 2),
                    format="%.2f",
                )
            dpg.add_text("Node1 0.00 | Node2 0.00", tag="heat_row_1")
            dpg.add_text("Node3 0.00 | Node4 0.00", tag="heat_row_2")

    def _build_alarm_panel(self) -> None:
        # 中文注释：报警日志保留在底部上方，红色高亮用于现场快速定位异常节点。
        with dpg.group(horizontal=True):
            dpg.add_text("报警日志")
            if self._font_big:
                dpg.bind_item_font(dpg.last_item(), self._font_big)
            dpg.add_spacer(width=20)
            dpg.add_button(label="CSV 导出", callback=lambda: self.on_export_csv(), width=110)
            dpg.add_button(label="一键截图", callback=lambda: self.on_screenshot(), width=110)
            dpg.add_text("", tag="export_message_text")
        with dpg.child_window(tag="alarm_log_window", height=160, border=True):
            dpg.add_text("暂无报警", tag="alarm_empty_text", color=(180, 180, 180))

    def _build_bottom_status_bar(self) -> None:
        # 中文注释：底部状态栏承载串口状态与最新帧，满足大屏投影时的总览需求。
        with dpg.group(horizontal=True):
            dpg.add_text("系统状态：", color=(210, 220, 235))
            dpg.add_text("串口状态：初始化中", tag="bottom_status_text", color=(92, 230, 155))
        dpg.add_text("最新帧：-", tag="bottom_latest_frame_text", wrap=1260, color=(210, 220, 235))

    def _update_node_cards(self, node_states: dict[int, dict[str, Any]]) -> None:
        now = time.time()
        for node_id in range(1, 5):
            state = node_states[node_id]
            online = bool(state.get("online"))
            last_received = state.get("last_received")
            age_text = "-" if last_received is None else f"{now - float(last_received):.1f}s 前"
            dpg.set_value(f"node_online_{node_id}", "在线" if online else "离线")
            dpg.configure_item(
                f"node_online_{node_id}",
                color=(92, 230, 155) if online else (255, 112, 112),
            )
            dpg.set_value(f"node_rssi_{node_id}", f"RSSI: {state.get('rssi', 0):.0f} dBm")
            dpg.set_value(f"node_battery_{node_id}", f"电池: {state.get('battery', 0):.0f} %")
            dpg.set_value(f"node_last_{node_id}", f"最后收到: {age_text}")

    def _update_plot(self, history: list[dict[str, Any]]) -> None:
        now = time.time()
        recent = [sample for sample in history if now - float(sample.get("timestamp", now)) <= 60.0]
        xs = [float(sample.get("timestamp", now)) - now for sample in recent]
        dpg.set_value("series_motion", [xs, [float(s.get("motion_score", 0.0)) for s in recent]])
        dpg.set_value("series_presence", [xs, [float(s.get("presence_score", 0.0)) for s in recent]])
        dpg.set_value("series_breath", [xs, [min(float(s.get("breath_bpm", 0.0)) / 40.0, 1.2) for s in recent]])
        dpg.set_value("series_gas", [xs, [min(float(s.get("gas", 0.0)) / 1000.0, 1.2) for s in recent]])
        dpg.set_axis_limits("trend_x_axis", -60, 0)
        dpg.set_axis_limits("trend_y_axis", 0, 1.2)

        if recent:
            latest = recent[-1]
            dpg.set_value(
                "latest_values_text",
                "最新值："
                f"Node {latest.get('node_id')} | "
                f"motion={float(latest.get('motion_score', 0.0)):.2f}  "
                f"presence={float(latest.get('presence_score', 0.0)):.2f}  "
                f"breath={float(latest.get('breath_bpm', 0.0)):.0f} bpm  "
                f"gas={float(latest.get('gas', 0.0)):.0f}",
            )

    def _update_heatmap(self, node_states: dict[int, dict[str, Any]]) -> None:
        values = [_heat_value(node_states[node_id]) for node_id in range(1, 5)]
        dpg.configure_item("node_heat_series", x=values)
        dpg.set_value("heat_row_1", f"Node1 {values[0]:.2f} | Node2 {values[1]:.2f}")
        dpg.set_value("heat_row_2", f"Node3 {values[2]:.2f} | Node4 {values[3]:.2f}")

    def _update_countdown(self, countdown_seconds: int) -> None:
        dpg.set_value("countdown_text", f"{countdown_seconds:02d}")

    def _update_alarm_log(self, alarms: list[dict[str, Any]]) -> None:
        if len(alarms) == self._last_alarm_count:
            return

        self._last_alarm_count = len(alarms)
        children = dpg.get_item_children("alarm_log_window", 1)
        for child in children:
            dpg.delete_item(child)

        if not alarms:
            dpg.add_text("暂无报警", parent="alarm_log_window", color=(180, 180, 180))
            return

        for alarm in list(reversed(alarms[-18:])):
            ts = time.strftime("%H:%M:%S", time.localtime(float(alarm["time"])))
            dpg.add_text(
                f"[{ts}] Node {alarm['node_id']}  {alarm['message']}",
                parent="alarm_log_window",
                color=(255, 78, 78),
            )


def _heat_value(state: dict[str, Any]) -> float:
    if not state.get("online"):
        return 0.0
    # 中文注释：目标要求热力图颜色随 presence_score 渐变，这里不混入 motion/gas。
    presence = float(state.get("presence_score", 0.0))
    return max(0.0, min(presence, 1.0))
